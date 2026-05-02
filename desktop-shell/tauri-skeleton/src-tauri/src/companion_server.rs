//! Loopback-only HTTP server for packaged desktop builds.
//!
//! Serves the bundled frontend static assets on `127.0.0.1` (dynamic port)
//! and proxies `/api/*` requests to the backend. The proxy does **not** inject
//! `X-Admin-Key` and does **not** reproduce the Next.js catch-all route's
//! admin session cookie logic, wormhole routing, or sensitive-path handling.
//! It is intentionally a thin loopback shim, not a Next.js replacement.
//!
//! **Dual role (post-P6D-R):**
//! 1. Origin of the packaged Tauri main window — same-origin `/api/*` gives
//!    the main window a working HTTP path for ordinary non-privileged data
//!    fetches. Privileged (27-command) paths still go through the Rust IPC
//!    control boundary with its own admin key ownership and policy
//!    enforcement — they do NOT traverse this server.
//! 2. Origin for the optional browser companion opener. Browser sessions
//!    have materially reduced trust compared to standalone browser mode:
//!    no admin session cookies, no admin-gated backend endpoints, no
//!    Next.js middleware. Only public data endpoints are reachable.
//!
//! **Not used in dev mode** — when `SHADOWBROKER_FRONTEND_URL` is explicitly
//! set, or when no bundled frontend assets exist, this server is not started.
//! In those cases the main window and companion both fall back to the
//! configured external URL (a running Next.js dev server).

use axum::{
    extract::State,
    http::{HeaderMap, Method, StatusCode, Uri},
    response::IntoResponse,
    routing::any,
    Router,
};
use bytes::Bytes;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;
use tokio::net::TcpListener;
use tower_http::services::{ServeDir, ServeFile};

// ---------------------------------------------------------------------------
// Server state
// ---------------------------------------------------------------------------

struct ServerState {
    backend_url: String,
    client: reqwest::Client,
}

// ---------------------------------------------------------------------------
// Header stripping
// ---------------------------------------------------------------------------

/// Headers stripped from proxied requests (hop-by-hop + security-sensitive).
/// `x-admin-key` is stripped intentionally — browser companion is reduced trust.
const STRIP_REQ: &[&str] = &[
    "host",
    "connection",
    "transfer-encoding",
    "x-admin-key",
    "keep-alive",
    "proxy-authorization",
    "te",
    "trailers",
    "upgrade",
];

/// Headers stripped from proxied responses.
const STRIP_RESP: &[&str] = &[
    "connection",
    "transfer-encoding",
    "content-encoding",
    "content-length",
    "keep-alive",
    "te",
    "trailers",
    "upgrade",
];

// ---------------------------------------------------------------------------
// API proxy handler
// ---------------------------------------------------------------------------

/// Proxy `/api/*` to the backend without `X-Admin-Key` (reduced trust).
///
/// Forwards the request method, safe headers, and body to the backend.
/// The response is returned verbatim (minus hop-by-hop headers).
async fn api_proxy(
    State(state): State<Arc<ServerState>>,
    method: Method,
    uri: Uri,
    headers: HeaderMap,
    body: Bytes,
) -> impl IntoResponse {
    let path_and_query = uri.path_and_query().map(|pq| pq.as_str()).unwrap_or("/");
    let target = format!("{}{}", state.backend_url, path_and_query);

    let req_method =
        reqwest::Method::from_bytes(method.as_str().as_bytes()).unwrap_or(reqwest::Method::GET);

    let mut builder = state.client.request(req_method.clone(), &target);

    // Forward headers, stripping hop-by-hop and security-sensitive ones.
    for (key, value) in &headers {
        let name = key.as_str().to_lowercase();
        if !STRIP_REQ.contains(&name.as_str()) {
            if let Ok(val) = value.to_str() {
                builder = builder.header(key.as_str(), val);
            }
        }
    }

    // Forward body for non-GET/HEAD methods.
    let is_bodyless = req_method == reqwest::Method::GET || req_method == reqwest::Method::HEAD;
    if !is_bodyless && !body.is_empty() {
        builder = builder.body(body);
    }

    match builder.send().await {
        Ok(resp) => {
            let status = StatusCode::from_u16(resp.status().as_u16())
                .unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
            let upstream_headers = resp.headers().clone();
            let resp_bytes = resp.bytes().await.unwrap_or_default();

            let mut response = axum::response::Response::builder().status(status);
            for (key, value) in upstream_headers.iter() {
                let name = key.as_str().to_lowercase();
                if !STRIP_RESP.contains(&name.as_str()) {
                    response = response.header(key, value);
                }
            }
            match response.body(axum::body::Body::from(resp_bytes)) {
                Ok(r) => r.into_response(),
                Err(_) => StatusCode::INTERNAL_SERVER_ERROR.into_response(),
            }
        }
        Err(_) => (
            StatusCode::BAD_GATEWAY,
            [("content-type", "application/json")],
            "{\"error\":\"Backend unavailable\"}",
        )
            .into_response(),
    }
}

// ---------------------------------------------------------------------------
// Server handle
// ---------------------------------------------------------------------------

/// Handle to a running companion server.
///
/// Dropping the handle gracefully shuts down the server.
pub struct CompanionServerHandle {
    addr: SocketAddr,
    shutdown_tx: Option<tokio::sync::oneshot::Sender<()>>,
}

impl CompanionServerHandle {
    /// The loopback URL browsers should open.
    pub fn url(&self) -> String {
        format!("http://127.0.0.1:{}", self.addr.port())
    }

    /// Gracefully stop the server.
    pub fn shutdown(&mut self) {
        if let Some(tx) = self.shutdown_tx.take() {
            let _ = tx.send(());
        }
    }
}

impl Drop for CompanionServerHandle {
    fn drop(&mut self) {
        self.shutdown();
    }
}

// ---------------------------------------------------------------------------
// Server startup
// ---------------------------------------------------------------------------

/// Start the companion loopback server.
///
/// Binds to `127.0.0.1:0` (OS-assigned port), serves static frontend files
/// from `www_root`, and proxies `/api/*` to `backend_url` without admin key.
///
/// Static file serving uses an index.html SPA fallback: requests that don't
/// match a static file are served the root `index.html`, letting Next.js
/// client-side routing handle the path.
pub async fn start_companion_server(
    www_root: PathBuf,
    backend_url: String,
) -> Result<CompanionServerHandle, String> {
    let state = Arc::new(ServerState {
        backend_url,
        client: reqwest::Client::new(),
    });

    // Static file serving with SPA fallback to index.html.
    let index_fallback = www_root.join("index.html");
    let serve = ServeDir::new(&www_root)
        .append_index_html_on_directories(true)
        .not_found_service(ServeFile::new(index_fallback));

    let app = Router::new()
        .route("/api/*rest", any(api_proxy))
        .with_state(state)
        .fallback_service(serve);

    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .map_err(|e| format!("companion_bind_failed:{e}"))?;
    let addr = listener
        .local_addr()
        .map_err(|e| format!("companion_addr_failed:{e}"))?;

    let (shutdown_tx, shutdown_rx) = tokio::sync::oneshot::channel::<()>();

    tokio::spawn(async move {
        axum::serve(listener, app)
            .with_graceful_shutdown(async {
                let _ = shutdown_rx.await;
            })
            .await
            .ok();
    });

    Ok(CompanionServerHandle {
        addr,
        shutdown_tx: Some(shutdown_tx),
    })
}

// ---------------------------------------------------------------------------
// Unit tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn server_handle_url_format() {
        let handle = CompanionServerHandle {
            addr: "127.0.0.1:12345".parse().unwrap(),
            shutdown_tx: None,
        };
        assert_eq!(handle.url(), "http://127.0.0.1:12345");
    }

    #[test]
    fn strip_lists_include_admin_key() {
        assert!(
            STRIP_REQ.contains(&"x-admin-key"),
            "proxy must strip X-Admin-Key from requests (reduced trust)"
        );
    }

    #[test]
    fn strip_lists_include_hop_by_hop() {
        for header in &["connection", "transfer-encoding", "keep-alive"] {
            assert!(
                STRIP_REQ.contains(header),
                "should strip {header} from requests"
            );
            assert!(
                STRIP_RESP.contains(header),
                "should strip {header} from responses"
            );
        }
    }

    #[tokio::test]
    async fn binds_to_loopback() {
        let tmp = std::env::temp_dir().join("sb_companion_server_test");
        let _ = std::fs::create_dir_all(&tmp);
        std::fs::write(tmp.join("index.html"), "<html></html>").unwrap();

        let handle = start_companion_server(tmp.clone(), "http://127.0.0.1:9999".to_string())
            .await
            .expect("server should start");

        assert!(handle.addr.ip().is_loopback(), "must bind to loopback");
        assert_ne!(handle.addr.port(), 0, "port should be assigned");
        assert!(handle.url().starts_with("http://127.0.0.1:"));

        let _ = std::fs::remove_dir_all(&tmp);
    }

    #[tokio::test]
    async fn shutdown_is_idempotent() {
        let tmp = std::env::temp_dir().join("sb_companion_shutdown_test");
        let _ = std::fs::create_dir_all(&tmp);
        std::fs::write(tmp.join("index.html"), "<html></html>").unwrap();

        let mut handle = start_companion_server(tmp.clone(), "http://127.0.0.1:9999".to_string())
            .await
            .expect("server should start");

        // First shutdown
        handle.shutdown();
        // Second shutdown is safe (idempotent)
        handle.shutdown();

        let _ = std::fs::remove_dir_all(&tmp);
    }
}
