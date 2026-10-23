//! GET /api/lz4/compat: the community's LZ4 game reports, for Convert Games' My games and
//! Compatibility tabs. Players file them as "[Game report]" issues on the LZ4 Compression
//! project's own site (theghostonline.dev since it left GitHub on 2026-10-17); they are counted
//! here the way that project's `tools/compat_aggregate.py` (and ps5-lz4) counts them: one vote
//! per player per game, their latest. Read at most once a day (or now, with `?refresh=true`);
//! when the site cannot be read, ps5-lz4-nas's copy of compat.json stands in.

use std::collections::{BTreeMap, HashMap};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::Json;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::json_err;

/// The project's site; `PS5UPLOAD_LZ4_ORIGIN` replaces it.
const ORIGIN: &str = "https://theghostonline.dev";
const REPO: &str = "theghostonline/PS5-LZ4-Compression";
/// compat.json as ps5-lz4-nas keeps it, for when the site cannot be read.
const MIRROR: &str = "https://raw.githubusercontent.com/dviree/PS5-LZ4-NAS/main/compat/compat.json";
/// Read again after this long: the daily check.
const EVERY: Duration = Duration::from_secs(24 * 3600);
/// Pages of 50 issues read at most.
const MAX_PAGES: usize = 40;

fn origin() -> String {
    std::env::var("PS5UPLOAD_LZ4_ORIGIN")
        .ok()
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| ORIGIN.into())
        .trim_end_matches('/')
        .to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct Report {
    pub status: String,
    #[serde(default)]
    pub game: String,
    #[serde(default)]
    pub game_version: String,
    #[serde(default)]
    pub level: String,
    #[serde(default)]
    pub source: String,
    #[serde(default)]
    pub firmware: String,
    #[serde(default)]
    pub app_version: String,
    #[serde(default)]
    pub date: String,
    #[serde(default)]
    pub issue: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct Entry {
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub works: u32,
    #[serde(default)]
    pub issues: u32,
    #[serde(default)]
    pub no_start: u32,
    #[serde(default)]
    pub crash: u32,
    #[serde(default)]
    pub reports: u32,
    #[serde(default)]
    pub last_report: Option<Report>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub(crate) struct Compat {
    #[serde(default)]
    pub updated: String,
    /// `live` (the site's issues) or `mirror` (ps5-lz4-nas's compat.json).
    #[serde(default)]
    pub source: String,
    /// The project's page, for links to reports and the report form.
    #[serde(default)]
    pub site: String,
    #[serde(default)]
    pub games: BTreeMap<String, Entry>,
}

/// "How does it run?" as `works`, `issues`, `noStart` or `crash`, as the project's 1.6.3 reads it:
/// the form's answers and their short labels, then free text from reports filed on the web page
/// ("can't start", "Works well, runs better than exFAT"), then the title's ": Works" suffix the
/// app's own report links add.
fn status_of(answer: &str, title: &str) -> Option<&'static str> {
    let s = answer
        .to_lowercase()
        .replace(['\u{2018}', '\u{2019}'], "'")
        .trim()
        .to_string();
    let exact = match s.as_str() {
        "works" => Some("works"),
        "works with issues" => Some("issues"),
        "won't start (black screen or crash on launch)" | "won't start" => Some("noStart"),
        "crashes in game" => Some("crash"),
        _ => None,
    };
    if exact.is_some() {
        return exact;
    }
    let words: Vec<&str> = s
        .split(|c: char| !c.is_alphanumeric() && c != '\'')
        .filter(|w| !w.is_empty())
        .collect();
    let starts = ["start", "boot", "load", "launch"];
    let stopped = [
        "won't", "wont", "can't", "cant", "cannot", "doesn't", "doesnt", "didn't", "didnt", "not",
    ];
    let no_start = words
        .windows(2)
        .any(|w| stopped.contains(&w[0]) && starts.contains(&w[1]))
        || s.contains("black screen")
        || s.contains("freez")
        || s.contains("stuck");
    if s.contains("works with issues") {
        Some("issues")
    } else if matches!(words.first(), Some(&"work") | Some(&"works")) {
        Some("works")
    } else if no_start {
        Some("noStart")
    } else if s.contains("crash") {
        Some("crash")
    } else if ["stutter", "issue", "glitch", "lag"]
        .iter()
        .any(|k| s.contains(k))
    {
        Some("issues")
    } else if words
        .iter()
        .any(|w| matches!(*w, "works" | "runs" | "playable" | "fine"))
    {
        Some("works")
    } else {
        let (_, suffix) = title.rsplit_once(':')?;
        status_of(suffix, "")
    }
}

fn field_of(heading: &str) -> Option<&'static str> {
    match heading.to_ascii_lowercase().as_str() {
        "title id" => Some("titleId"),
        "game" => Some("game"),
        "how does it run?" => Some("status"),
        "game version" => Some("gameVersion"),
        "lz4 level" => Some("level"),
        "packed from" => Some("source"),
        "firmware" => Some("firmware"),
        "lz4 compression version" => Some("appVersion"),
        _ => None,
    }
}

/// Whitespace runs as one space, trimmed, at most `n` characters.
fn clean(s: &str, n: usize) -> String {
    s.split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .chars()
        .take(n)
        .collect()
}

/// The report form's "### Heading" sections of an issue body.
fn sections(body: &str) -> HashMap<&'static str, String> {
    let mut out = HashMap::new();
    let mut current: Option<&'static str> = None;
    let mut text = String::new();
    let mut flush = |key: Option<&'static str>, text: &mut String| {
        let v = text.trim();
        if let Some(k) = key {
            if !v.is_empty() && v != "_No response_" && v != "None" {
                out.insert(k, v.to_string());
            }
        }
        text.clear();
    };
    for line in body.lines() {
        if let Some(h) = line.strip_prefix("### ") {
            flush(current, &mut text);
            current = field_of(h.trim());
        } else {
            text.push_str(line);
            text.push('\n');
        }
    }
    flush(current, &mut text);
    out
}

fn is_title_id(s: &str) -> bool {
    let b = s.as_bytes();
    b.len() == 9
        && b[..4].iter().all(u8::is_ascii_uppercase)
        && b[4..].iter().all(u8::is_ascii_digit)
}

/// "_Moved from GitHub #12, opened by @someone on 2026-01-02" at the start of a moved report:
/// (who, date).
fn moved_from_github(body: &str) -> Option<(String, String)> {
    let rest = body.strip_prefix("_Moved from GitHub #")?;
    let (num, rest) = rest.split_once(", opened ")?;
    let (by, rest) = match rest.strip_prefix("by @") {
        Some(r) => {
            let (who, r) = r.split_once(' ')?;
            (Some(who.to_string()), r)
        }
        None => (None, rest),
    };
    let date: String = rest.strip_prefix("on ")?.chars().take(10).collect();
    (date.len() == 10).then(|| (by.unwrap_or_else(|| format!("github#{num}")), date))
}

/// Report issues (Gitea or GitHub REST) to per-game counts.
pub(crate) fn aggregate(issues: &[Value]) -> BTreeMap<String, Entry> {
    let mut latest: HashMap<(String, String), Report> = HashMap::new();
    for issue in issues {
        if issue.get("pull_request").is_some_and(|p| !p.is_null()) {
            continue;
        }
        let labels: Vec<String> = issue["labels"]
            .as_array()
            .map(|a| {
                a.iter()
                    .filter_map(|l| l["name"].as_str())
                    .map(str::to_ascii_lowercase)
                    .collect()
            })
            .unwrap_or_default();
        if labels
            .iter()
            .any(|l| matches!(l.as_str(), "invalid" | "duplicate" | "spam"))
        {
            continue;
        }
        let title = issue["title"].as_str().unwrap_or_default();
        if !labels.iter().any(|l| l == "compat") && !title.starts_with("[Game report]") {
            continue;
        }
        let body = issue["body"].as_str().unwrap_or_default();
        let f = sections(body);
        let get = |k: &str, n: usize| clean(f.get(k).map(String::as_str).unwrap_or_default(), n);
        let tid = get("titleId", 16).to_ascii_uppercase();
        let Some(status) = status_of(&get("status", 80), title) else {
            continue;
        };
        if !is_title_id(&tid) {
            continue;
        }
        let moved = moved_from_github(body);
        let author = moved
            .as_ref()
            .map(|(who, _)| who.clone())
            .or_else(|| {
                issue["original_author"]
                    .as_str()
                    .filter(|s| !s.is_empty())
                    .map(String::from)
            })
            .or_else(|| issue["user"]["login"].as_str().map(String::from))
            .unwrap_or_else(|| format!("#{}", issue["number"]))
            .to_ascii_lowercase();
        let rep = Report {
            status: status.into(),
            game: get("game", 80),
            game_version: get("gameVersion", 20),
            level: get("level", 4),
            source: get("source", 40),
            firmware: get("firmware", 12),
            app_version: get("appVersion", 12),
            date: moved
                .map(|(_, d)| d)
                .or_else(|| issue["created_at"].as_str().map(String::from))
                .unwrap_or_default(),
            issue: issue["number"].as_u64(),
        };
        let key = (tid, author);
        if latest.get(&key).is_none_or(|old| rep.date >= old.date) {
            latest.insert(key, rep);
        }
    }
    let mut games: BTreeMap<String, Entry> = BTreeMap::new();
    for ((tid, _), rep) in latest {
        let g = games.entry(tid).or_default();
        match rep.status.as_str() {
            "works" => g.works += 1,
            "issues" => g.issues += 1,
            "noStart" => g.no_start += 1,
            _ => g.crash += 1,
        }
        g.reports += 1;
        if g.name.is_empty() && !rep.game.is_empty() {
            g.name = rep.game.clone();
        }
        if g.last_report.as_ref().is_none_or(|l| rep.date > l.date) {
            g.last_report = Some(rep);
        }
    }
    games
}

fn get_json(url: &str) -> Result<Value, String> {
    ureq::get(url)
        .header("User-Agent", "ps5upload")
        .header("Accept", "application/json")
        .call()
        .map_err(|e| format!("{url}: {e}"))?
        .body_mut()
        .with_config()
        .limit(64 << 20)
        .read_to_string()
        .map_err(|e| format!("{url}: {e}"))
        .and_then(|text| serde_json::from_str(&text).map_err(|e| format!("{url}: {e}")))
}

fn now_utc() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| d.as_secs() as i64);
    crate::collection::iso_utc(secs)
}

/// Every report issue on the site, counted.
fn fetch_live(origin: &str) -> Result<Compat, String> {
    let api = format!("{origin}/api/v1/repos/{REPO}/issues");
    let mut issues = Vec::new();
    for page in 1..=MAX_PAGES {
        let batch = get_json(&format!("{api}?state=all&type=issues&limit=50&page={page}"))?;
        let Some(batch) = batch.as_array() else {
            return Err("unexpected answer from the issues API".into());
        };
        let n = batch.len();
        issues.extend(batch.iter().cloned());
        if n < 50 {
            break;
        }
    }
    Ok(Compat {
        updated: now_utc(),
        source: "live".into(),
        site: format!("{origin}/{REPO}"),
        games: aggregate(&issues),
    })
}

fn fetch(origin: &str) -> Result<Compat, String> {
    match fetch_live(origin) {
        Ok(c) => Ok(c),
        Err(live) => {
            crate::log_warn!("lz4 compat: the site could not be read ({live}); using the mirror");
            let mut c: Compat =
                serde_json::from_value(get_json(MIRROR)?).map_err(|e| format!("{MIRROR}: {e}"))?;
            c.source = "mirror".into();
            c.site = format!("{origin}/{REPO}");
            Ok(c)
        }
    }
}

fn cache() -> &'static Mutex<Option<(Instant, Compat)>> {
    static C: OnceLock<Mutex<Option<(Instant, Compat)>>> = OnceLock::new();
    C.get_or_init(Default::default)
}

#[derive(Deserialize)]
pub(crate) struct CompatQuery {
    #[serde(default)]
    refresh: bool,
}

/// GET /api/lz4/compat
pub(crate) async fn lz4_compat_handler(
    axum::extract::Query(q): axum::extract::Query<CompatQuery>,
) -> impl IntoResponse {
    if !q.refresh {
        if let Some((at, c)) = &*cache().lock().unwrap_or_else(|e| e.into_inner()) {
            if at.elapsed() < EVERY {
                return (StatusCode::OK, Json(c.clone())).into_response();
            }
        }
    }
    let origin = origin();
    match tokio::task::spawn_blocking(move || fetch(&origin)).await {
        Ok(Ok(c)) => {
            *cache().lock().unwrap_or_else(|e| e.into_inner()) = Some((Instant::now(), c.clone()));
            (StatusCode::OK, Json(c)).into_response()
        }
        Ok(Err(e)) => {
            // An older copy beats none.
            if let Some((_, c)) = &*cache().lock().unwrap_or_else(|e| e.into_inner()) {
                return (StatusCode::OK, Json(c.clone())).into_response();
            }
            json_err(StatusCode::BAD_GATEWAY, format!("community reports: {e}")).into_response()
        }
        Err(join) => json_err(
            StatusCode::INTERNAL_SERVER_ERROR,
            format!("the community reports task failed: {join}"),
        )
        .into_response(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn report(n: u64, user: &str, tid: &str, how: &str, date: &str) -> Value {
        json!({
            "number": n,
            "title": format!("[Game report] Game: {how}"),
            "user": {"login": user},
            "created_at": date,
            "labels": [],
            "body": format!(
                "### Title ID\n\n{tid}\n\n### Game\n\nGhost of Yotei\n\n### How does it run?\n\n{how}\n\n\
                 ### Game version\n\n02.002.000\n\n### LZ4 level\n\n_No response_\n"
            ),
        })
    }

    #[test]
    fn free_text_answers_and_the_title_suffix_are_read() {
        assert_eq!(status_of("Works", ""), Some("works"));
        assert_eq!(status_of("can\u{2019}t start", ""), Some("noStart"));
        assert_eq!(
            status_of("Works well, runs better than exFAT", ""),
            Some("works")
        );
        assert_eq!(status_of("black screen after logo", ""), Some("noStart"));
        assert_eq!(status_of("crashes at the second boss", ""), Some("crash"));
        assert_eq!(status_of("some stutter in cities", ""), Some("issues"));
        assert_eq!(
            status_of("", "[Game report] Ghost of Yotei: Works with issues"),
            Some("issues")
        );
        assert_eq!(status_of("no idea", "[Game report] Ghost of Yotei"), None);
    }

    #[test]
    fn one_vote_per_player_per_game_their_latest() {
        let issues = vec![
            report(
                1,
                "a",
                "PPSA26344",
                "Crashes in game",
                "2026-10-01T00:00:00Z",
            ),
            report(2, "a", "PPSA26344", "Works", "2026-10-05T00:00:00Z"),
            report(
                3,
                "b",
                "PPSA26344",
                "Won't start (black screen or crash on launch)",
                "2026-10-03T00:00:00Z",
            ),
            report(
                4,
                "c",
                "ppsa26344",
                "Works with issues",
                "2026-10-02T00:00:00Z",
            ),
            // Not a report, a bad Title ID, a spam label: left out.
            json!({"number": 5, "title": "Question", "body": "### Title ID\n\nPPSA26344", "labels": []}),
            report(6, "d", "PPSA2634", "Works", "2026-10-02T00:00:00Z"),
            {
                let mut r = report(7, "e", "PPSA26344", "Works", "2026-10-09T00:00:00Z");
                r["labels"] = json!([{"name": "Spam"}]);
                r
            },
        ];
        let games = aggregate(&issues);
        let g = &games["PPSA26344"];
        assert_eq!(
            (g.works, g.issues, g.no_start, g.crash, g.reports),
            (1, 1, 1, 0, 3)
        );
        assert_eq!(g.name, "Ghost of Yotei");
        let last = g.last_report.as_ref().unwrap();
        assert_eq!((last.issue, last.status.as_str()), (Some(2), "works"));
        assert_eq!(last.game_version, "02.002.000");
        assert_eq!(last.level, "");
        assert_eq!(games.len(), 1);
    }

    #[test]
    fn a_report_moved_from_github_counts_for_its_author_and_date() {
        let mut r = report(
            9,
            "theghostonline",
            "PPSA34547",
            "Works",
            "2026-10-18T00:00:00Z",
        );
        r["body"] = json!(format!(
            "_Moved from GitHub #12, opened by @Jack7277 on 2026-09-30_\n\n{}",
            r["body"].as_str().unwrap()
        ));
        let mine = report(
            10,
            "jack7277",
            "PPSA34547",
            "Crashes in game",
            "2026-10-10T00:00:00Z",
        );
        let games = aggregate(&[r, mine]);
        let g = &games["PPSA34547"];
        // The same player: their later report (the crash) is the one that counts.
        assert_eq!((g.works, g.crash, g.reports), (0, 1, 1));
        assert_eq!(
            moved_from_github("_Moved from GitHub #3, opened on 2026-01-02_"),
            Some(("github#3".into(), "2026-01-02".into()))
        );
    }
}
