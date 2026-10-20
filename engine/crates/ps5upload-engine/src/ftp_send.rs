//! POST /api/ftp/send: a game folder or file on this machine sent to the PS5 through the
//! console's own FTP server (etaHEN or another FTP payload, anonymous, :2121 by default),
//! the way ps5-lz4 sends games, for when the PS5Upload payload is not loaded. Runs as a job (GET
//! /api/jobs/{id}): folders are made first, then every file is stored; a file already there
//! with the same size is skipped, so a send that stopped picks up where it was.

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

use axum::extract::State;
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::Json;
use serde::Deserialize;
use suppaftp::tokio::AsyncRustlsFtpStream as Ftp;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use uuid::Uuid;

use crate::fpkg_api::resolve_engine_path;
use crate::{json_err, now_ms, register_transfer_cancel, set_job, AppState, JobState};

/// The port etaHEN and other FTP payloads serve on the PS5.
const DEFAULT_PORT: u16 = 2121;
const CONNECT_TIMEOUT: Duration = Duration::from_secs(15);
const CHUNK: usize = 1 << 20;

#[derive(Deserialize)]
pub(crate) struct FtpSendReq {
    /// The folder or file to send, as the engine sees it (`/lz4/Game-lz4`).
    source: String,
    /// The PS5's address (`192.168.50.90`, a `:port` is ignored).
    addr: String,
    /// The PS5's FTP port; 2121 when left out.
    #[serde(default)]
    port: Option<u16>,
    /// The folder on the PS5 the source goes into (`/data/homebrew`, `/mnt/usb0/homebrew`).
    dest_dir: String,
}

/// What is sent: folders (relative, parents first) and files (relative path, size).
#[derive(Debug, Default, PartialEq, Eq)]
pub(crate) struct Plan {
    pub dirs: Vec<String>,
    pub files: Vec<(String, u64)>,
}

/// The tree under `root` (a folder) or `root` itself (a file, relative path "").
pub(crate) fn plan(root: &Path) -> std::io::Result<Plan> {
    let mut out = Plan::default();
    if root.is_file() {
        out.files
            .push((String::new(), std::fs::metadata(root)?.len()));
        return Ok(out);
    }
    let mut stack = vec![(root.to_path_buf(), String::new())];
    while let Some((dir, rel)) = stack.pop() {
        let mut entries: Vec<_> = std::fs::read_dir(&dir)?.collect::<Result<_, _>>()?;
        entries.sort_by_key(|e| e.file_name());
        for e in entries {
            let name = e.file_name().to_string_lossy().into_owned();
            let ft = e.file_type()?;
            if ft.is_symlink() {
                continue;
            }
            let path = if rel.is_empty() {
                name
            } else {
                format!("{rel}/{name}")
            };
            if ft.is_dir() {
                out.dirs.push(path.clone());
                stack.push((e.path(), path));
            } else {
                out.files.push((path, e.metadata()?.len()));
            }
        }
    }
    out.dirs
        .sort_by_key(|d| (d.matches('/').count(), d.clone()));
    Ok(out)
}

/// A destination folder on the PS5: absolute, no `..`, no trailing slash.
pub(crate) fn clean_dest(dest: &str) -> Result<String, String> {
    let t = dest.trim();
    let d = t.trim_end_matches('/');
    if !t.starts_with('/') || d.split('/').any(|p| p == "..") || d.contains('\0') {
        return Err("the PS5 folder must be an absolute path, like /data/homebrew".into());
    }
    Ok(if d.is_empty() { "/".into() } else { d.into() })
}

fn console_host(addr: &str) -> String {
    let a = addr.trim();
    // `host:port` (not an IPv6 literal): the host only.
    match a.rsplit_once(':') {
        Some((h, p)) if !h.contains(':') && p.chars().all(|c| c.is_ascii_digit()) => h.into(),
        _ => a.into(),
    }
}

/// Sends `plan` from `local` to `remote` (the source's own folder on the PS5).
async fn send(
    ftp: &mut Ftp,
    local: &Path,
    remote: &str,
    plan: &Plan,
    cancel: &AtomicBool,
    progress: &mut (dyn FnMut(u64, u64) + Send),
) -> Result<(u64, u64), String> {
    let single = plan.files.len() == 1 && plan.files[0].0.is_empty();
    if !single {
        // Each level of the destination, then the source's folders (an existing one is fine).
        let mut at = String::new();
        for part in remote.split('/').filter(|p| !p.is_empty()) {
            at.push('/');
            at.push_str(part);
            let _ = ftp.mkdir(&at).await;
        }
        for d in &plan.dirs {
            let _ = ftp.mkdir(format!("{remote}/{d}")).await;
        }
    }
    let (mut sent, mut skipped) = (0u64, 0u64);
    let mut buf = vec![0u8; CHUNK];
    for (rel, size) in &plan.files {
        if cancel.load(Ordering::Relaxed) {
            return Err("cancelled".into());
        }
        let (src, dst): (PathBuf, String) = if single {
            (local.to_path_buf(), remote.to_string())
        } else {
            (local.join(rel), format!("{remote}/{rel}"))
        };
        if ftp.size(&dst).await.is_ok_and(|n| n as u64 == *size) {
            skipped += size;
            progress(sent + skipped, 0);
            continue;
        }
        let mut file = tokio::fs::File::open(&src)
            .await
            .map_err(|e| format!("{}: {e}", src.display()))?;
        let mut up = ftp
            .put_with_stream(&dst)
            .await
            .map_err(|e| format!("{dst}: {e}"))?;
        loop {
            if cancel.load(Ordering::Relaxed) {
                return Err("cancelled".into());
            }
            let n = file
                .read(&mut buf)
                .await
                .map_err(|e| format!("{}: {e}", src.display()))?;
            if n == 0 {
                break;
            }
            up.write_all(&buf[..n])
                .await
                .map_err(|e| format!("{dst}: {e}"))?;
            sent += n as u64;
            progress(sent + skipped, 0);
        }
        up.finish().await.map_err(|e| format!("{dst}: {e}"))?;
    }
    Ok((sent, skipped))
}

/// POST /api/ftp/send
pub(crate) async fn ftp_send_handler(
    State(state): State<AppState>,
    Json(req): Json<FtpSendReq>,
) -> impl IntoResponse {
    let dest_dir = match clean_dest(&req.dest_dir) {
        Ok(d) => d,
        Err(e) => return json_err(StatusCode::BAD_REQUEST, e).into_response(),
    };
    let local = resolve_engine_path(&req.source);
    let name = match local.file_name() {
        Some(n) => n.to_string_lossy().into_owned(),
        None => return json_err(StatusCode::BAD_REQUEST, "nothing to send").into_response(),
    };
    let scan_root = local.clone();
    let plan = match tokio::task::spawn_blocking(move || plan(&scan_root)).await {
        Ok(Ok(p)) => p,
        Ok(Err(e)) => {
            return json_err(StatusCode::BAD_REQUEST, format!("{}: {e}", local.display()))
                .into_response()
        }
        Err(e) => {
            return json_err(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()).into_response()
        }
    };
    let host = console_host(&req.addr);
    let port = req.port.unwrap_or(DEFAULT_PORT);
    let remote = if dest_dir == "/" {
        format!("/{name}")
    } else {
        format!("{dest_dir}/{name}")
    };
    // Reach the console first, so a wrong address or an FTP server that is not running is an
    // answer here, not a failed job.
    let mut ftp = match connect(&host, port).await {
        Ok(f) => f,
        Err(e) => return json_err(StatusCode::BAD_GATEWAY, e).into_response(),
    };

    let total: u64 = plan.files.iter().map(|(_, s)| s).sum();
    let job_id = Uuid::new_v4();
    let cancel = register_transfer_cancel(job_id);
    let started_at_ms = now_ms();
    set_job(
        &state.jobs,
        &state.events_tx,
        job_id,
        running(started_at_ms, 0, total),
    );
    crate::log_info!(
        "ftp send: {} -> {host}:{port}{remote} ({} files, {total} bytes)",
        local.display(),
        plan.files.len()
    );
    let jobs = state.jobs.clone();
    let events_tx = state.events_tx.clone();
    let answer = serde_json::json!({ "job_id": job_id.to_string(), "dest": remote });
    tokio::spawn(async move {
        let mut last = Instant::now();
        let mut progress = |done: u64, _: u64| {
            if last.elapsed() >= Duration::from_millis(250) {
                last = Instant::now();
                set_job(
                    &jobs,
                    &events_tx,
                    job_id,
                    running(started_at_ms, done, total),
                );
            }
        };
        let outcome = send(&mut ftp, &local, &remote, &plan, &cancel, &mut progress).await;
        let _ = ftp.quit().await;
        let completed_at_ms = now_ms();
        let elapsed_ms = completed_at_ms.saturating_sub(started_at_ms);
        let state = match outcome {
            Ok((sent, skipped)) => {
                crate::log_info!(
                    "ftp send: done, {remote} ({sent} bytes sent, {skipped} already there)"
                );
                JobState::Done {
                    started_at_ms,
                    completed_at_ms,
                    elapsed_ms,
                    tx_id_hex: String::new(),
                    bytes_sent: sent + skipped,
                    dest: remote.clone(),
                    files_sent: plan.files.len() as u64,
                    skipped_files: 0,
                    skipped_bytes: skipped,
                    commit_ack: None,
                }
            }
            Err(error) => {
                crate::log_warn!("ftp send: {remote}: {error}");
                JobState::Failed {
                    started_at_ms,
                    completed_at_ms,
                    elapsed_ms,
                    error,
                    error_reason: None,
                    error_detail: None,
                    error_console: None,
                }
            }
        };
        set_job(&jobs, &events_tx, job_id, state);
    });
    (StatusCode::ACCEPTED, Json(answer)).into_response()
}

async fn connect(host: &str, port: u16) -> Result<Ftp, String> {
    let work = async {
        let mut ftp = Ftp::connect(format!("{host}:{port}"))
            .await
            .map_err(|e| format!("connect: {e}"))?;
        ftp.login("anonymous", "anonymous")
            .await
            .map_err(|e| format!("login: {e}"))?;
        ftp.transfer_type(suppaftp::types::FileType::Binary)
            .await
            .map_err(|e| format!("binary mode: {e}"))?;
        Ok::<_, String>(ftp)
    };
    match tokio::time::timeout(CONNECT_TIMEOUT, work).await {
        Ok(Ok(f)) => Ok(f),
        Ok(Err(e)) => Err(format!(
            "the PS5's FTP server at {host}:{port} did not let us in ({e}); is the FTP server of etaHEN \
             (or another FTP payload) running?"
        )),
        Err(_) => Err(format!(
            "the PS5's FTP server at {host}:{port} did not answer; is the PS5 on and its FTP \
             server running?"
        )),
    }
}

fn running(started_at_ms: u64, bytes_sent: u64, total_bytes: u64) -> JobState {
    JobState::Running {
        stage: None,
        started_at_ms,
        bytes_sent,
        total_bytes,
        files: Default::default(),
        skipped_files: 0,
        skipped_bytes: 0,
        files_processing: 0,
        files_finalized: 0,
        files_finalizing_total: 0,
        bytes_finalized: 0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_folder_is_planned_parents_first_and_a_file_on_its_own() {
        let root = std::env::temp_dir().join(format!("ftp-plan-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        let game = root.join("Game-lz4");
        std::fs::create_dir_all(game.join("sce_sys/about")).unwrap();
        std::fs::write(game.join("eboot.bin"), b"12345").unwrap();
        std::fs::write(game.join("sce_sys/param.json"), b"{}").unwrap();
        let p = plan(&game).unwrap();
        assert_eq!(p.dirs, ["sce_sys", "sce_sys/about"]);
        assert_eq!(
            p.files,
            [
                ("eboot.bin".to_string(), 5),
                ("sce_sys/param.json".to_string(), 2)
            ]
        );
        let one = plan(&game.join("eboot.bin")).unwrap();
        assert_eq!(one.files, [(String::new(), 5)]);
        assert!(one.dirs.is_empty());
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn the_ps5_folder_is_absolute_and_stays_put() {
        assert_eq!(clean_dest("/data/homebrew/").unwrap(), "/data/homebrew");
        assert_eq!(clean_dest("/").unwrap(), "/");
        assert!(clean_dest("data/homebrew").is_err());
        assert!(clean_dest("/data/../etc").is_err());
        assert_eq!(console_host("192.168.50.90:9113"), "192.168.50.90");
        assert_eq!(console_host("ps5.local"), "ps5.local");
    }
}

#[cfg(test)]
mod live {
    use super::*;

    /// Sends a folder to a real FTP server (`PS5UPLOAD_FTP_TEST=host:port`, anonymous, writable)
    /// twice: the second time everything is already there.
    #[tokio::test]
    async fn a_folder_goes_over_and_a_second_send_skips_it() {
        let Ok(addr) = std::env::var("PS5UPLOAD_FTP_TEST") else {
            return;
        };
        let (host, port) = addr.rsplit_once(':').unwrap();
        let root = std::env::temp_dir().join(format!("ftp-live-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        let game = root.join("Game-lz4");
        std::fs::create_dir_all(game.join("sce_sys")).unwrap();
        std::fs::write(game.join("eboot.bin"), vec![7u8; 3 << 20]).unwrap();
        std::fs::write(game.join("sce_sys/param.json"), b"{}").unwrap();
        let p = plan(&game).unwrap();
        let cancel = AtomicBool::new(false);
        let seen = std::sync::atomic::AtomicU64::new(0);
        let mut progress = |d: u64, _: u64| seen.store(d, Ordering::Relaxed);
        let mut ftp = connect(host, port.parse().unwrap()).await.unwrap();
        let (sent, skipped) = send(
            &mut ftp,
            &game,
            "/data/homebrew/Game-lz4",
            &p,
            &cancel,
            &mut progress,
        )
        .await
        .unwrap();
        assert_eq!((sent, skipped), ((3 << 20) + 2, 0));
        assert_eq!(seen.load(Ordering::Relaxed), (3 << 20) + 2);
        let (sent, skipped) = send(
            &mut ftp,
            &game,
            "/data/homebrew/Game-lz4",
            &p,
            &cancel,
            &mut progress,
        )
        .await
        .unwrap();
        assert_eq!((sent, skipped), (0, (3 << 20) + 2));
        let _ = ftp.quit().await;
        let _ = std::fs::remove_dir_all(&root);
    }
}
