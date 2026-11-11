//! The vendored NAS converter is private to this container. These routes inherit
//! the engine's normal IP guard; no second public port or arbitrary upstream URL.
use axum::{body::{Body, Bytes}, extract::OriginalUri, http::{HeaderMap, Method, StatusCode}, response::{IntoResponse, Response}};
use std::io::Read;

pub(crate) async fn proxy(OriginalUri(uri): OriginalUri, method: Method, headers: HeaderMap, body: Bytes) -> Response {
    let Some((base, rest)) = uri.path().split_once("/api/nas-zstd") else {
        return StatusCode::NOT_FOUND.into_response();
    };
    let prefix = format!("{base}/api/nas-zstd");
    let path = if rest.is_empty() { "/" } else { rest };
    let url = format!("http://127.0.0.1:19114{path}{}", uri.query().map(|q| format!("?{q}")).unwrap_or_default());
    let (head_tx, head_rx) = tokio::sync::oneshot::channel();
    let (tx, rx) = tokio::sync::mpsc::channel::<Result<Bytes, std::io::Error>>(4);
    tokio::task::spawn_blocking(move || {
        let agent: ureq::Agent = ureq::Agent::config_builder()
            .timeout_global(Some(std::time::Duration::from_secs(300)))
            .http_status_as_error(false).build().into();
        let result = if method == Method::POST {
            agent.post(&url).header("Content-Type", headers.get("content-type").and_then(|v| v.to_str().ok()).unwrap_or("application/json")).send(body.as_ref())
        } else if method == Method::HEAD {
            agent.head(&url).call()
        } else {
            agent.get(&url).call()
        };
        let response = match result {
            Ok(r) => r,
            Err(_) => { let _ = head_tx.send(Err(())); return; }
        };
        let status = response.status();
        let mut out_headers = HeaderMap::new();
        for key in ["content-type", "content-disposition", "cache-control"] {
            if let Some(v) = response.headers().get(key) { out_headers.insert(key, v.clone()); }
        }
        let html = out_headers.get("content-type").is_some_and(|v| v.to_str().unwrap_or("").starts_with("text/html"));
        let _ = head_tx.send(Ok((status, out_headers)));
        let mut reader = response.into_body().into_reader();
        if html {
            let mut text = String::new();
            if let Err(e) = reader.by_ref().take(8 << 20).read_to_string(&mut text) { let _ = tx.blocking_send(Err(e)); return; }
            // Scope the standalone UI's absolute links to this engine path, including
            // deployments with PS5UPLOAD_BASE_URL. JSON and binary data stay untouched.
            for quote in ["'", "\"", "`"] {
                text = text.replace(&format!("{quote}/api/"), &format!("{quote}{prefix}/api/"))
                    .replace(&format!("{quote}/store"), &format!("{quote}{prefix}/store"));
            }
            let _ = tx.blocking_send(Ok(Bytes::from(text)));
        } else {
            loop {
                let mut chunk = vec![0; 64 << 10];
                match reader.read(&mut chunk) {
                    Ok(0) => break,
                    Ok(n) => { chunk.truncate(n); if tx.blocking_send(Ok(Bytes::from(chunk))).is_err() { break; } }
                    Err(e) => { let _ = tx.blocking_send(Err(e)); break; }
                }
            }
        }
    });
    match head_rx.await {
        Ok(Ok((status, headers))) => (status, headers, Body::from_stream(tokio_stream::wrappers::ReceiverStream::new(rx))).into_response(),
        _ => (StatusCode::SERVICE_UNAVAILABLE, "NAS converter unavailable. Update the ps5upload web UI image and mount /ps5 and /zstd.").into_response(),
    }
}
