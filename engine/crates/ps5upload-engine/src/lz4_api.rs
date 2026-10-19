//! POST /api/lz4/status: for each game (a folder or a game image), whether it is packed with
//! AMPR LZ4 asset packs already, can be, or cannot, for Convert Games' My games list. The same
//! check the converter makes (`ampr_pack::image::readiness`), read through the game's own
//! tree, so an image is read in place and never mounted. GET /api/lz4/ffpfsc: the community's
//! .ffpfsc compatibility list, for Convert Games' Compatibility tab.

use std::collections::HashMap;
use std::path::Path;
use std::sync::{Mutex, OnceLock};

use axum::extract::State;
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::Json;
use serde::{Deserialize, Serialize};

use crate::fpkg_api::resolve_engine_path;
use crate::{json_err, AppState};

/// The manifest LZ4 packing writes at the game's root; its presence means the game is packed.
const PACK_INDEX: &str = "ampr_assets.index";
/// Enough for a library page; more is refused so one request cannot hold the engine long.
const MAX_PATHS: usize = 64;

#[derive(Deserialize)]
pub(crate) struct StatusReq {
    paths: Vec<String>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct Lz4Status {
    path: String,
    /// `packed` (already LZ4), `ok` (can be LZ4), `runtime` (can be LZ4 once ampr_emu 0.4.2.1
    /// goes into it, which Convert does), `no_ampr` (the game does not read through AMPR, so
    /// LZ4 packs cannot serve it) or `error` (the game could not be read).
    status: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    reason: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    runtime_version: Option<String>,
}

/// Results by path, kept while the game's size and modified time stay the same.
type Cache = Mutex<HashMap<String, ((u64, i64), Lz4Status)>>;

fn cache() -> &'static Cache {
    static CACHE: OnceLock<Cache> = OnceLock::new();
    CACHE.get_or_init(Default::default)
}

fn stamp(path: &Path) -> (u64, i64) {
    std::fs::metadata(path)
        .map(|m| {
            let mtime = m
                .modified()
                .ok()
                .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
                .map_or(0, |d| d.as_secs() as i64);
            (m.len(), mtime)
        })
        .unwrap_or((0, 0))
}

/// One game's status, read through its tree.
pub(crate) fn status_of(path: &str) -> Lz4Status {
    let resolved = resolve_engine_path(path);
    // An .exfat image is only looked at where the check reads (its root, fakelib/, runtime/):
    // walking every folder of a big game image on a NAS disk can take minutes.
    let is_exfat = resolved
        .extension()
        .is_some_and(|e| e.eq_ignore_ascii_case("exfat"));
    let opened = if is_exfat {
        ps5upload_fpkg::exfat::ExFatSource::open_top(&resolved, &["fakelib", "runtime"])
            .map(|t| Box::new(t) as Box<dyn ps5upload_fpkg::source::SourceTree>)
    } else {
        ps5upload_fpkg::source::open(&resolved)
    };
    let mut tree = match opened {
        Ok(t) => t,
        Err(e) => {
            return Lz4Status {
                path: path.into(),
                status: "error",
                reason: Some(e.to_string()),
                runtime_version: None,
            }
        }
    };
    if tree
        .files()
        .iter()
        .any(|f| f.path.eq_ignore_ascii_case(PACK_INDEX))
    {
        return Lz4Status {
            path: path.into(),
            status: "packed",
            reason: None,
            runtime_version: None,
        };
    }
    match ps5upload_fpkg::ampr_pack::image::readiness(&mut *tree) {
        Some(r) => Lz4Status {
            path: path.into(),
            status: r.kind,
            reason: r.refusal,
            runtime_version: r.runtime_version,
        },
        None => Lz4Status {
            path: path.into(),
            status: "no_ampr",
            reason: None,
            runtime_version: None,
        },
    }
}

pub(crate) async fn lz4_status_handler(
    State(_): State<AppState>,
    Json(req): Json<StatusReq>,
) -> impl IntoResponse {
    if req.paths.len() > MAX_PATHS {
        return json_err(
            StatusCode::BAD_REQUEST,
            format!("at most {MAX_PATHS} games per request"),
        )
        .into_response();
    }
    let result = tokio::task::spawn_blocking(move || {
        req.paths
            .iter()
            .map(|p| {
                let key = stamp(&resolve_engine_path(p));
                if let Some((k, s)) = cache().lock().unwrap_or_else(|e| e.into_inner()).get(p) {
                    if *k == key {
                        return s.clone();
                    }
                }
                let started = std::time::Instant::now();
                let s = status_of(p);
                let took = started.elapsed();
                if took.as_secs() >= 10 || s.status == "error" {
                    crate::log_info!(
                        "lz4 status: {p}: {} in {:.1}s{}",
                        s.status,
                        took.as_secs_f64(),
                        s.reason
                            .as_deref()
                            .map(|r| format!(" ({r})"))
                            .unwrap_or_default()
                    );
                }
                if s.status != "error" {
                    cache()
                        .lock()
                        .unwrap_or_else(|e| e.into_inner())
                        .insert(p.clone(), (key, s.clone()));
                }
                s
            })
            .collect::<Vec<_>>()
    })
    .await;
    match result {
        Ok(results) => (
            StatusCode::OK,
            Json(serde_json::json!({ "results": results })),
        )
            .into_response(),
        Err(join) => json_err(
            StatusCode::INTERNAL_SERVER_ERROR,
            format!("the LZ4 check failed: {join}"),
        )
        .into_response(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmp(tag: &str) -> std::path::PathBuf {
        let d = std::env::temp_dir().join(format!("ps5upload-lz4-{tag}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(d.join("sce_sys")).unwrap();
        std::fs::write(d.join("sce_sys/param.json"), b"{}").unwrap();
        d
    }

    #[test]
    fn a_packed_game_says_so() {
        let d = tmp("packed");
        std::fs::write(d.join("eboot.bin"), b"\x7fELF").unwrap();
        std::fs::write(d.join(PACK_INDEX), b"AMPRPAK4").unwrap();
        assert_eq!(status_of(&d.to_string_lossy()).status, "packed");
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn a_game_without_ampr_cannot_be_lz4() {
        let d = tmp("plain");
        std::fs::write(d.join("eboot.bin"), vec![0u8; 4096]).unwrap();
        assert_eq!(status_of(&d.to_string_lossy()).status, "no_ampr");
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn a_game_that_reads_through_ampr_without_a_runtime_can_be_lz4_with_one() {
        let d = tmp("ampr");
        let mut eboot = vec![0u8; 4096];
        let lib = b"libSceAmpr";
        eboot[1000..1000 + lib.len()].copy_from_slice(lib);
        std::fs::write(d.join("eboot.bin"), eboot).unwrap();
        assert_eq!(status_of(&d.to_string_lossy()).status, "runtime");
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn a_build_is_listed_until_its_guard_goes() {
        let g = building_start("/games/X.exfat");
        g.set_job("j1");
        let listed = |src: &str| {
            building()
                .lock()
                .unwrap()
                .values()
                .any(|b| b.source == src && b.job_id.as_deref() == Some("j1"))
        };
        assert!(listed("/games/X.exfat"));
        drop(g);
        assert!(!listed("/games/X.exfat"));
    }

    #[test]
    fn a_missing_game_is_an_error() {
        let s = status_of("/no/such/game/anywhere");
        assert_eq!(s.status, "error");
        assert!(s.reason.is_some());
    }
}

/// The games being converted to LZ4 game folders right now, so My games can say so on any
/// device: from the moment the build is asked for (reading the source takes minutes for a big
/// image) until its job ends. Keyed by the source path as the request named it.
#[derive(Debug, Clone, Serialize)]
pub(crate) struct Building {
    source: String,
    /// The build's job, once it has one (GET /api/jobs/{id} for its progress).
    job_id: Option<String>,
    started_ms: u64,
}

fn building() -> &'static Mutex<HashMap<u64, Building>> {
    static B: OnceLock<Mutex<HashMap<u64, Building>>> = OnceLock::new();
    B.get_or_init(Default::default)
}

/// A build's place in the list; dropped (the job ended, the request went away), it is gone.
pub(crate) struct BuildingGuard(u64);

impl BuildingGuard {
    pub(crate) fn set_job(&self, job_id: &str) {
        if let Some(b) = building()
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .get_mut(&self.0)
        {
            b.job_id = Some(job_id.to_string());
        }
    }
}

impl Drop for BuildingGuard {
    fn drop(&mut self) {
        building()
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .remove(&self.0);
    }
}

pub(crate) fn building_start(source: &str) -> BuildingGuard {
    static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(1);
    let id = NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    building().lock().unwrap_or_else(|e| e.into_inner()).insert(
        id,
        Building {
            source: source.to_string(),
            job_id: None,
            started_ms: crate::now_ms(),
        },
    );
    BuildingGuard(id)
}

/// GET /api/lz4/building: `{building: [{source, job_id?, started_ms}]}`.
pub(crate) async fn lz4_building_handler() -> impl IntoResponse {
    let list: Vec<Building> = building()
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .values()
        .cloned()
        .collect();
    Json(serde_json::json!({ "building": list }))
}

/// The community's .ffpfsc compatibility list, a Google Sheet ps5-lz4 shows too, read as CSV.
/// `PS5UPLOAD_FFPFSC_SHEET` replaces the sheet's CSV export URL ("" turns it off).
const FFPFSC_SHEET: &str = "https://docs.google.com/spreadsheets/d/1dgu0p7U2yB_mhcUELz-Wkc7Yhs-avoWLY1Gcm0n5XJw/export?format=csv&gid=357033774";
/// Read again after this long.
const FFPFSC_EVERY: std::time::Duration = std::time::Duration::from_secs(6 * 3600);

#[derive(Debug, Clone, Serialize, Default)]
pub(crate) struct FfpfscSheet {
    /// The sheet as people open it.
    url: String,
    /// The sheet's own column names.
    headers: Vec<String>,
    /// One map of column name to cell per game row (empty cells left out).
    rows: Vec<std::collections::BTreeMap<String, String>>,
}

fn sheet_url() -> Option<String> {
    let url = std::env::var("PS5UPLOAD_FFPFSC_SHEET").unwrap_or_else(|_| FFPFSC_SHEET.into());
    (!url.trim().is_empty()).then_some(url)
}

/// The sheet's page for a CSV export URL (`…/export?format=csv&gid=N` → `…/edit#gid=N`).
fn sheet_page(csv_url: &str) -> String {
    match csv_url.split_once("/export?format=csv&gid=") {
        Some((base, gid)) => format!("{base}/edit#gid={gid}"),
        None => csv_url.to_string(),
    }
}

/// RFC 4180 CSV: quoted cells may hold commas, newlines and doubled quotes.
fn parse_csv(text: &str) -> Vec<Vec<String>> {
    let mut rows = Vec::new();
    let mut row = Vec::new();
    let mut cell = String::new();
    let mut quoted = false;
    let mut chars = text.chars().peekable();
    while let Some(c) = chars.next() {
        if quoted {
            match c {
                '"' if chars.peek() == Some(&'"') => {
                    cell.push('"');
                    chars.next();
                }
                '"' => quoted = false,
                _ => cell.push(c),
            }
            continue;
        }
        match c {
            '"' => quoted = true,
            ',' => row.push(std::mem::take(&mut cell)),
            '\r' => {}
            '\n' => {
                row.push(std::mem::take(&mut cell));
                rows.push(std::mem::take(&mut row));
            }
            _ => cell.push(c),
        }
    }
    if !cell.is_empty() || !row.is_empty() {
        row.push(cell);
        rows.push(row);
    }
    rows
}

fn has_title_id(s: &str) -> bool {
    let b = s.as_bytes();
    b.windows(9)
        .any(|w| w[..4].iter().all(u8::is_ascii_uppercase) && w[4..].iter().all(u8::is_ascii_digit))
}

/// The sheet's rows under its own header: the header is the last row with two or more filled
/// cells before the first row naming a Title ID (sheets often open with a title or notes).
fn sheet_from_csv(text: &str, url: String) -> FfpfscSheet {
    let rows: Vec<Vec<String>> = parse_csv(text.trim_start_matches('\u{feff}'))
        .into_iter()
        .map(|r| {
            r.into_iter()
                .map(|c| c.trim().to_string())
                .collect::<Vec<_>>()
        })
        .filter(|r| r.iter().any(|c| !c.is_empty()))
        .collect();
    let first_data = rows
        .iter()
        .position(|r| r.iter().any(|c| has_title_id(c)))
        .unwrap_or(rows.len());
    let head = (0..first_data)
        .rev()
        .find(|&i| rows[i].iter().filter(|c| !c.is_empty()).count() >= 2);
    let width = rows.iter().map(Vec::len).max().unwrap_or(0);
    let name = |i: usize, h: Option<&String>| match h {
        Some(h) if !h.is_empty() => h.clone(),
        _ => format!("Column {}", i + 1),
    };
    let headers: Vec<String> = (0..width)
        .map(|i| name(i, head.and_then(|h| rows[h].get(i))))
        .collect();
    let data = rows
        .iter()
        .skip(head.map_or(0, |h| h + 1))
        .map(|r| {
            r.iter()
                .enumerate()
                .filter(|(_, c)| !c.is_empty())
                .map(|(i, c)| (headers[i].clone(), c.clone()))
                .collect::<std::collections::BTreeMap<_, _>>()
        })
        .filter(|cells| cells.len() >= 2)
        .collect();
    FfpfscSheet {
        url: sheet_page(&url),
        headers,
        rows: data,
    }
}

fn sheet_cache() -> &'static Mutex<Option<(std::time::Instant, FfpfscSheet)>> {
    static SHEET: OnceLock<Mutex<Option<(std::time::Instant, FfpfscSheet)>>> = OnceLock::new();
    SHEET.get_or_init(Default::default)
}

#[derive(Deserialize)]
pub(crate) struct SheetQuery {
    #[serde(default)]
    refresh: bool,
}

/// GET /api/lz4/ffpfsc: the .ffpfsc compatibility list, read at most every six hours (or
/// now, with `?refresh=true`).
pub(crate) async fn lz4_ffpfsc_handler(
    axum::extract::Query(q): axum::extract::Query<SheetQuery>,
) -> impl IntoResponse {
    let Some(url) = sheet_url() else {
        return (StatusCode::OK, Json(FfpfscSheet::default())).into_response();
    };
    if !q.refresh {
        if let Some((at, sheet)) = &*sheet_cache().lock().unwrap_or_else(|e| e.into_inner()) {
            if at.elapsed() < FFPFSC_EVERY {
                return (StatusCode::OK, Json(sheet.clone())).into_response();
            }
        }
    }
    let fetched = tokio::task::spawn_blocking(move || -> Result<FfpfscSheet, String> {
        let text = ureq::get(&url)
            .header("User-Agent", "ps5upload")
            .call()
            .map_err(|e| format!("fetching the .ffpfsc list: {e}"))?
            .body_mut()
            .with_config()
            .limit(20 << 20)
            .read_to_string()
            .map_err(|e| format!("reading the .ffpfsc list: {e}"))?;
        Ok(sheet_from_csv(&text, url))
    })
    .await;
    match fetched {
        Ok(Ok(sheet)) => {
            *sheet_cache().lock().unwrap_or_else(|e| e.into_inner()) =
                Some((std::time::Instant::now(), sheet.clone()));
            (StatusCode::OK, Json(sheet)).into_response()
        }
        Ok(Err(e)) => json_err(StatusCode::BAD_GATEWAY, e).into_response(),
        Err(join) => json_err(
            StatusCode::INTERNAL_SERVER_ERROR,
            format!("the .ffpfsc list task failed: {join}"),
        )
        .into_response(),
    }
}

#[cfg(test)]
mod sheet_tests {
    use super::*;

    #[test]
    fn the_header_is_the_row_above_the_first_game() {
        let csv = "PS5 .ffpfsc compatibility,,\r\nNotes: see below,,\r\nGame,Title ID,Works?\r\n\"Astro Bot, Deluxe\",PPSA01234,Yes\r\nReturnal,PPSA01284,\"No \"\"black\"\" screen\"\r\n,,\r\n";
        let s = sheet_from_csv(csv, FFPFSC_SHEET.into());
        assert_eq!(s.headers, ["Game", "Title ID", "Works?"]);
        assert_eq!(s.rows.len(), 2);
        assert_eq!(s.rows[0]["Game"], "Astro Bot, Deluxe");
        assert_eq!(s.rows[1]["Works?"], "No \"black\" screen");
        assert!(s.url.ends_with("/edit#gid=357033774"), "{}", s.url);
    }

    #[test]
    fn a_sheet_without_a_header_names_its_columns() {
        let s = sheet_from_csv("PPSA01234,Yes\nPPSA05678,No\n", "x".into());
        assert_eq!(s.headers, ["Column 1", "Column 2"]);
        assert_eq!(s.rows[1]["Column 2"], "No");
    }
}
