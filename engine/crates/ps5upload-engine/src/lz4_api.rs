//! POST /api/lz4/status: for each game (a folder or a game image), whether it is packed with
//! AMPR LZ4 asset packs already, can be, or cannot, for Convert Games' My games list. The same
//! check the converter makes (`ampr_pack::image::readiness`), read through the game's own
//! tree, so an image is read in place and never mounted.

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
    let mut tree = match ps5upload_fpkg::source::open(&resolve_engine_path(path)) {
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
                let s = status_of(p);
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
    fn a_missing_game_is_an_error() {
        let s = status_of("/no/such/game/anywhere");
        assert_eq!(s.status, "error");
        assert!(s.reason.is_some());
    }
}
