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
    // Store every file, even one already there with the same size (a patch).
    force: bool,
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
        if !force && ftp.size(&dst).await.is_ok_and(|n| n as u64 == *size) {
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
        let outcome = send(
            &mut ftp,
            &local,
            &remote,
            &plan,
            &cancel,
            &mut progress,
            false,
        )
        .await;
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

#[derive(Deserialize)]
pub(crate) struct FtpPatchReq {
    /// The fix or backport: a .zip/.7z/.rar or a folder, as the engine sees it.
    patch: String,
    addr: String,
    #[serde(default)]
    port: Option<u16>,
    /// The game's folder on the PS5 (`/mnt/usb0/homebrew/Ghost of Yotei-lz4`).
    game_dir: String,
}

/// The folder whose files go into the game: the patch itself, or the one folder an archive
/// wraps them in (`PPSA26344-app0/eboot.bin`).
fn patch_root(dir: &Path) -> PathBuf {
    let mut at = dir.to_path_buf();
    for _ in 0..3 {
        let entries: Vec<_> = match std::fs::read_dir(&at) {
            Ok(r) => r.flatten().collect(),
            Err(_) => return at,
        };
        let game_like = entries.iter().any(|e| {
            let n = e.file_name().to_string_lossy().to_ascii_lowercase();
            n == "eboot.bin" || n == "sce_sys" || n == "sce_module" || n == "fakelib"
        });
        let dirs: Vec<_> = entries.iter().filter(|e| e.path().is_dir()).collect();
        let files = entries.iter().filter(|e| e.path().is_file()).count();
        if game_like || dirs.len() != 1 || files > 0 {
            return at;
        }
        at = dirs[0].path();
    }
    at
}

async fn ftp_read(ftp: &mut Ftp, path: &str) -> Result<Option<Vec<u8>>, String> {
    if ftp.size(path).await.is_err() {
        return Ok(None);
    }
    let mut stream = ftp
        .retr_as_stream(path)
        .await
        .map_err(|e| format!("{path}: {e}"))?;
    let mut buf = Vec::new();
    stream
        .read_to_end(&mut buf)
        .await
        .map_err(|e| format!("{path}: {e}"))?;
    stream.finish().await.map_err(|e| format!("{path}: {e}"))?;
    Ok(Some(buf))
}

async fn ftp_write(ftp: &mut Ftp, path: &str, bytes: &[u8]) -> Result<(), String> {
    let mut up = ftp
        .put_with_stream(path)
        .await
        .map_err(|e| format!("{path}: {e}"))?;
    up.write_all(bytes)
        .await
        .map_err(|e| format!("{path}: {e}"))?;
    up.finish().await.map_err(|e| format!("{path}: {e}"))
}

/// What a patch of a game on the PS5 did, for the job's log and the answer.
#[derive(Debug, Default, serde::Serialize)]
struct PatchDone {
    packed_game: bool,
    replaced: Vec<String>,
    unpacked: Vec<String>,
    added: Vec<String>,
}

/// Puts the patch's files into the game on the PS5. A packed game's manifest and
/// `ampr_emu.index` are read from the console, patched ([`ps5upload_fpkg::ampr_pack::patch`])
/// and written back last; every file and index replaced is kept beside it as
/// `<name>.before-patch` (the first time only, so the original survives repeated patches).
async fn patch_game(
    ftp: &mut Ftp,
    root: &Path,
    game_dir: &str,
    plan: &Plan,
    cancel: &AtomicBool,
    progress: &mut (dyn FnMut(u64, u64) + Send),
) -> Result<PatchDone, String> {
    use ps5upload_fpkg::ampr_pack::patch;
    if ftp.cwd(game_dir).await.is_err() {
        return Err(format!("{game_dir} is not a folder on the PS5"));
    }
    let manifest_path = format!("{game_dir}/{}", patch::MANIFEST);
    let emu_path = format!("{game_dir}/{}", patch::EMU_INDEX);
    let manifest = ftp_read(ftp, &manifest_path).await?;
    let emu = ftp_read(ftp, &emu_path).await?;
    let mut done = PatchDone::default();
    let indexes = match (&manifest, &emu) {
        (Some(m), Some(e)) => {
            let mtime = (now_ms() / 1000) as i64;
            let p = patch::patch(m, e, &plan.files, mtime).map_err(|e| e.to_string())?;
            done.packed_game = true;
            done.replaced = p.replaced.clone();
            done.unpacked = p.unpacked.clone();
            done.added = p.added.clone();
            Some((p.manifest, p.emu_index))
        }
        _ => None,
    };
    // Keep what is replaced, once.
    let keep = |path: &str| format!("{path}.before-patch");
    for (rel, _) in &plan.files {
        let dst = format!("{game_dir}/{rel}");
        if ftp.size(&dst).await.is_ok() && ftp.size(keep(&dst)).await.is_err() {
            ftp.rename(&dst, &keep(&dst))
                .await
                .map_err(|e| format!("keeping {dst}: {e}"))?;
        }
    }
    if let (Some(m), Some(e)) = (&manifest, &emu) {
        for (path, bytes) in [(&manifest_path, m), (&emu_path, e)] {
            if ftp.size(keep(path)).await.is_err() {
                ftp_write(ftp, &keep(path), bytes).await?;
            }
        }
    }
    let sent = send(ftp, root, game_dir, plan, cancel, &mut *progress, true).await?;
    let _ = sent;
    if let Some((m, e)) = indexes {
        ftp_write(ftp, &manifest_path, &m).await?;
        ftp_write(ftp, &emu_path, &e).await?;
    }
    if !done.packed_game {
        done.replaced = plan.files.iter().map(|(r, _)| r.clone()).collect();
    }
    Ok(done)
}

/// POST /api/ftp/patch: a fix or backport (an archive or a folder) put into a game on the PS5
/// over its FTP server, LZ4 packed games included. Returns `{job_id}`.
pub(crate) async fn ftp_patch_handler(
    State(state): State<AppState>,
    Json(req): Json<FtpPatchReq>,
) -> impl IntoResponse {
    let game_dir = match clean_dest(&req.game_dir) {
        Ok(d) if d != "/" => d,
        Ok(_) => {
            return json_err(StatusCode::BAD_REQUEST, "name the game's folder").into_response()
        }
        Err(e) => return json_err(StatusCode::BAD_REQUEST, e).into_response(),
    };
    let source = resolve_engine_path(&req.patch);
    if !source.exists() {
        return json_err(
            StatusCode::BAD_REQUEST,
            format!(
                "{} is not there (is its folder mounted in the container?)",
                source.display()
            ),
        )
        .into_response();
    }
    // An archive is unpacked into a work folder first.
    let work = std::env::temp_dir().join(format!("ps5upload-patch-{}", Uuid::new_v4()));
    let src = source.clone();
    let w = work.clone();
    let prepared = tokio::task::spawn_blocking(move || -> Result<(PathBuf, Plan), String> {
        let root = if src.is_dir() {
            src
        } else if ps5upload_core::archive_extract::archive_kind(&src).is_some() {
            let never = AtomicBool::new(false);
            ps5upload_core::archive_extract::extract(&src, &w, None, &mut |_, _| {}, &never)
                .map_err(|e| format!("unpacking {}: {e:#}", src.display()))?;
            patch_root(&w)
        } else {
            return Err(format!(
                "{} is neither a folder nor a .zip, .7z or .rar",
                src.display()
            ));
        };
        let p = plan(&root).map_err(|e| format!("{}: {e}", root.display()))?;
        if p.files.is_empty() {
            return Err("the patch has no files".into());
        }
        Ok((root, p))
    })
    .await;
    let (root, plan) = match prepared {
        Ok(Ok(x)) => x,
        Ok(Err(e)) => {
            let _ = std::fs::remove_dir_all(&work);
            return json_err(StatusCode::BAD_REQUEST, e).into_response();
        }
        Err(e) => {
            let _ = std::fs::remove_dir_all(&work);
            return json_err(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()).into_response();
        }
    };
    let host = console_host(&req.addr);
    let port = req.port.unwrap_or(DEFAULT_PORT);
    let mut ftp = match connect(&host, port).await {
        Ok(f) => f,
        Err(e) => {
            let _ = std::fs::remove_dir_all(&work);
            return json_err(StatusCode::BAD_GATEWAY, e).into_response();
        }
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
        "ftp patch: {} -> {host}:{port}{game_dir} ({} files)",
        source.display(),
        plan.files.len()
    );
    let jobs = state.jobs.clone();
    let events_tx = state.events_tx.clone();
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
        let outcome = patch_game(&mut ftp, &root, &game_dir, &plan, &cancel, &mut progress).await;
        let _ = ftp.quit().await;
        let _ = std::fs::remove_dir_all(&work);
        let completed_at_ms = now_ms();
        let elapsed_ms = completed_at_ms.saturating_sub(started_at_ms);
        let state = match outcome {
            Ok(done) => {
                crate::log_info!(
                    "ftp patch: done, {game_dir}: {}",
                    serde_json::to_string(&done).unwrap_or_default()
                );
                JobState::Done {
                    started_at_ms,
                    completed_at_ms,
                    elapsed_ms,
                    tx_id_hex: String::new(),
                    bytes_sent: total,
                    dest: game_dir.clone(),
                    files_sent: plan.files.len() as u64,
                    skipped_files: 0,
                    skipped_bytes: 0,
                    commit_ack: None,
                }
            }
            Err(error) => {
                crate::log_warn!("ftp patch: {game_dir}: {error}");
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
    (
        StatusCode::ACCEPTED,
        Json(serde_json::json!({ "job_id": job_id.to_string(), "dest": req.game_dir })),
    )
        .into_response()
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
            false,
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
            false,
        )
        .await
        .unwrap();
        assert_eq!((sent, skipped), (0, (3 << 20) + 2));
        let _ = ftp.quit().await;
        let _ = std::fs::remove_dir_all(&root);
    }
}

#[cfg(test)]
mod live_patch {
    use super::*;
    use ps5upload_fpkg::ampr_pack::{self, format::Manifest, patch, Control, Reader};
    use ps5upload_fpkg::source::{FolderSource, SourceTree};

    /// A packed game on a real FTP server (`PS5UPLOAD_FTP_TEST=host:port`, its root in
    /// `PS5UPLOAD_FTP_ROOT`) patched from a zip that wraps its files in one folder.
    #[tokio::test]
    async fn a_packed_game_on_the_console_is_patched_from_a_zip() {
        let (Ok(addr), Ok(ftp_root)) = (
            std::env::var("PS5UPLOAD_FTP_TEST"),
            std::env::var("PS5UPLOAD_FTP_ROOT"),
        ) else {
            return;
        };
        let (host, port) = addr.rsplit_once(':').unwrap();
        let game = PathBuf::from(&ftp_root).join("mnt/usb0/homebrew/Ghost-lz4");
        let _ = std::fs::remove_dir_all(&game);
        for (p, d) in [
            ("eboot.bin", vec![1u8; 100]),
            ("data/a.bin", vec![b'a'; 70_000]),
            ("psml_package/KPN9_v070.psp", vec![b'k'; 70_000]),
        ] {
            let f = game.join(p);
            std::fs::create_dir_all(f.parent().unwrap()).unwrap();
            std::fs::write(f, d).unwrap();
        }
        let mut tree = FolderSource::open(&game).unwrap();
        let listing: Vec<(String, u64)> = tree
            .files()
            .iter()
            .map(|f| (f.path.clone(), f.size))
            .collect();
        let index = ps5upload_fpkg::ampr_index::build(&listing, 7).unwrap();
        let entries = ps5upload_fpkg::ampr_index::parse(&index).unwrap();
        let config = ampr_pack::default_profile(9, 16);
        let out =
            ampr_pack::build(&entries, &mut tree, &config, &game, &mut Control::default()).unwrap();
        out.write_small_files(&game).unwrap();
        std::fs::write(game.join(patch::EMU_INDEX), &index).unwrap();
        for p in &out.packed {
            std::fs::remove_file(game.join(p)).unwrap();
        }

        // The fix, as a zip with everything under PPSA26344-app0/.
        let work = std::env::temp_dir().join(format!("live-patch-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&work);
        std::fs::create_dir_all(&work).unwrap();
        let zip_path = work.join("BP.zip");
        {
            let mut z = zip::ZipWriter::new(std::fs::File::create(&zip_path).unwrap());
            let o = zip::write::SimpleFileOptions::default();
            for (p, d) in [
                ("PPSA26344-app0/eboot.bin", vec![2u8; 300]),
                (
                    "PPSA26344-app0/psml_package/KPN9_v070.psp",
                    vec![b'n'; 1234],
                ),
                ("PPSA26344-app0/fakelib/libScePsml.sprx", vec![b's'; 77]),
            ] {
                z.start_file(p, o).unwrap();
                std::io::Write::write_all(&mut z, &d).unwrap();
            }
            z.finish().unwrap();
        }
        let x = work.join("x");
        let never = AtomicBool::new(false);
        ps5upload_core::archive_extract::extract(&zip_path, &x, None, &mut |_, _| {}, &never)
            .unwrap();
        let root = patch_root(&x);
        assert!(root.ends_with("PPSA26344-app0"));
        let p = plan(&root).unwrap();

        let mut ftp = connect(host, port.parse().unwrap()).await.unwrap();
        let mut progress = |_: u64, _: u64| {};
        let done = patch_game(
            &mut ftp,
            &root,
            "/mnt/usb0/homebrew/Ghost-lz4",
            &p,
            &never,
            &mut progress,
        )
        .await
        .unwrap();
        let _ = ftp.quit().await;
        assert!(done.packed_game);
        assert_eq!(done.replaced, ["eboot.bin"]);
        assert_eq!(done.unpacked, ["psml_package/KPN9_v070.psp"]);
        assert_eq!(done.added, ["fakelib/libScePsml.sprx"]);

        // On the "console": the new files, the old ones kept, and indexes that agree.
        assert_eq!(
            std::fs::read(game.join("eboot.bin")).unwrap(),
            vec![2u8; 300]
        );
        assert_eq!(
            std::fs::read(game.join("eboot.bin.before-patch")).unwrap(),
            vec![1u8; 100]
        );
        assert_eq!(
            std::fs::read(game.join("psml_package/KPN9_v070.psp")).unwrap(),
            vec![b'n'; 1234]
        );
        assert!(game.join("ampr_assets.index.before-patch").exists());
        let m = Manifest::parse(&std::fs::read(game.join(patch::MANIFEST)).unwrap()).unwrap();
        let e =
            ps5upload_fpkg::ampr_index::parse(&std::fs::read(game.join(patch::EMU_INDEX)).unwrap())
                .unwrap();
        assert_eq!(m.files.len(), e.len());
        let mut folder = FolderSource::open(&game).unwrap();
        let reader = Reader::open(&mut folder, patch::MANIFEST).unwrap();
        let psp = reader.find("psml_package/KPN9_v070.psp").unwrap();
        assert!(!reader.manifest.files[psp].packed());
        let a = reader.find("data/a.bin").unwrap();
        assert_eq!(
            reader.read_file(a, &mut folder, "").unwrap(),
            vec![b'a'; 70_000]
        );
        let _ = std::fs::remove_dir_all(&work);
    }
}
