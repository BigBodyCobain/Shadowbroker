//! Loopback-only HTTP server for packaged desktop builds.
//!
//! Serves the bundled frontend static assets on `127.0.0.1` (dynamic port)
//! and proxies `/api/*` requests to the backend. Only the native webview receives
//! an HttpOnly session installed through Rust IPC; browser companions never receive
//! operator credentials. The proxy does **not** reproduce the Next.js catch-all route's
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
    admin_key: Option<String>,
    native_cookie: String,
    native_token: String,
    origin: String,
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
    "cookie",
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

/// Proxy `/api/*`; only a validated native session may receive operator credentials.
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
    let decoded = match urlencoding::decode(uri.path()) {
        Ok(path) => path,
        Err(_) => return StatusCode::BAD_REQUEST.into_response(),
    };
    if decoded.split('/').any(|part| part == "." || part == "..") || decoded.contains('\\') {
        return StatusCode::BAD_REQUEST.into_response();
    }
    let native = has_native_session(&headers, &state.native_cookie, &state.native_token);
    if native && !native_origin_allowed(&headers, &state.origin) {
        return StatusCode::FORBIDDEN.into_response();
    }
    if native && requires_native_control(&decoded, method.as_str()) {
        return (
            StatusCode::FORBIDDEN,
            "Use the native control command for this operation",
        )
            .into_response();
    }
    let path_and_query = uri.path_and_query().map(|pq| pq.as_str()).unwrap_or("/");
    let target = format!("{}{}", state.backend_url, path_and_query);

    let req_method =
        reqwest::Method::from_bytes(method.as_str().as_bytes()).unwrap_or(reqwest::Method::GET);

    let mut builder = state.client.request(req_method.clone(), &target);

    // Forward headers, stripping hop-by-hop and security-sensitive ones.
    for (key, value) in &headers {
        let name = key.as_str().to_lowercase();
        if native
            && matches!(
                name.as_str(),
                "origin" | "sec-fetch-site" | "sec-fetch-mode" | "sec-fetch-dest"
            )
        {
            continue;
        }
        if !STRIP_REQ.contains(&name.as_str()) {
            if let Ok(val) = value.to_str() {
                builder = builder.header(key.as_str(), val);
            }
        }
    }
    if native {
        if let Some(command) = operator_http_command(&decoded) {
            if matches!(
                crate::policy::enforce(command, &None, &None),
                crate::policy::PolicyOutcome::Denied(_, _)
            ) {
                return StatusCode::FORBIDDEN.into_response();
            }
            if let Some(key) = state.admin_key.as_deref() {
                builder = builder.header("X-Admin-Key", key);
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
            let response_body = axum::body::Body::from_stream(resp.bytes_stream());

            let mut response = axum::response::Response::builder().status(status);
            for (key, value) in upstream_headers.iter() {
                let name = key.as_str().to_lowercase();
                if !STRIP_RESP.contains(&name.as_str()) {
                    response = response.header(key, value);
                }
            }
            match response.body(response_body) {
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

fn operator_http_command(path: &str) -> Option<&'static str> {
    if path.starts_with("/api/wormhole/gate/") {
        return Some(if path.contains("/key/") || path.contains("/state/") {
            "wormhole.gate.key.rotate"
        } else if path.contains("/persona") || path.ends_with("/identity") {
            "wormhole.gate.persona.create"
        } else {
            "wormhole.gate.message.post"
        });
    }
    if path.starts_with("/api/wormhole/dm/") || path == "/api/mesh/infonet/session-stream" {
        return Some("wormhole.gate.message.post");
    }
    if path.starts_with("/api/wormhole/") {
        return Some(if path == "/api/wormhole/status" {
            "wormhole.status"
        } else {
            "settings.api_keys.get"
        });
    }
    let prefixes = [
        "/api/settings/",
        "/api/voice/",
        "/api/agent-shell/",
        "/api/ai/",
        "/api/tools/",
        "/api/sentinel/",
        "/api/sentinel2/",
        "/api/radio/openmhz/",
        "/api/thermal/",
        "/api/liveuamap/",
        "/api/prediction-markets/",
        "/api/sar/mode-b",
        "/api/sar/aois",
        "/api/mesh/peers",
        "/api/mesh/oracle/",
    ];
    if prefixes.iter().any(|prefix| path.starts_with(prefix))
        || matches!(
            path,
            "/api/refresh"
                | "/api/debug-latest"
                | "/api/system/update"
                | "/api/layers"
                | "/api/ais/feed"
                | "/api/sigint/transmit"
                | "/api/sigint/meshtastic/scan"
                | "/api/privacy/claims"
                | "/api/mesh/infonet/ingest"
                | "/api/mesh/infonet/peer-registry"
                | "/api/mesh/reputation/all"
                | "/api/mesh/trust/vouches"
                | "/api/mesh/meshtastic/send"
        )
    {
        return Some("settings.api_keys.get");
    }
    None
}

fn has_native_session(headers: &HeaderMap, name: &str, expected: &str) -> bool {
    let cookie = headers
        .get("cookie")
        .and_then(|h| h.to_str().ok())
        .unwrap_or("");
    let value = cookie
        .split(';')
        .filter_map(|entry| entry.trim().split_once('='))
        .find_map(|(key, value)| (key == name).then_some(value))
        .unwrap_or("");
    value.len() == expected.len()
        && !expected.is_empty()
        && value
            .bytes()
            .zip(expected.bytes())
            .fold(0u8, |diff, (a, b)| diff | (a ^ b))
            == 0
}

fn native_origin_allowed(headers: &HeaderMap, origin: &str) -> bool {
    match headers.get("origin").and_then(|h| h.to_str().ok()) {
        Some(value) => value == origin,
        None => matches!(
            headers.get("sec-fetch-site").and_then(|h| h.to_str().ok()),
            None | Some("same-origin")
        ),
    }
}

// These operations must retain Rust policy, gate-state tracking and native custody.
fn requires_native_control(path: &str, method: &str) -> bool {
    (method == "POST"
        && matches!(
            path,
            "/api/wormhole/connect"
                | "/api/wormhole/disconnect"
                | "/api/wormhole/restart"
                | "/api/wormhole/gate/enter"
                | "/api/wormhole/gate/leave"
                | "/api/wormhole/gate/persona/create"
                | "/api/wormhole/gate/persona/activate"
                | "/api/wormhole/gate/persona/clear"
                | "/api/wormhole/gate/key/rotate"
                | "/api/wormhole/gate/state/export"
                | "/api/wormhole/gate/proof"
                | "/api/wormhole/gate/message/compose"
                | "/api/wormhole/gate/message/post"
                | "/api/wormhole/gate/message/decrypt"
                | "/api/wormhole/gate/messages/decrypt"
                | "/api/system/update"
        ))
        || (path.starts_with("/api/wormhole/gate/")
            && method == "GET"
            && (path.ends_with("/key") || path.ends_with("/personas")))
        || matches!(
            path,
            "/api/settings/wormhole" | "/api/settings/privacy-profile"
        )
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
    native_cookie: String,
    native_token: String,
}

impl CompanionServerHandle {
    pub fn native_session_cookie(&self) -> (&str, &str) {
        (&self.native_cookie, &self.native_token)
    }
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
    admin_key: Option<String>,
) -> Result<CompanionServerHandle, String> {
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .map_err(|e| format!("companion_bind_failed:{e}"))?;
    let addr = listener
        .local_addr()
        .map_err(|e| format!("companion_addr_failed:{e}"))?;
    let mut random = [0u8; 32];
    getrandom::getrandom(&mut random).map_err(|e| format!("native_session_random_failed:{e}"))?;
    use base64::Engine;
    let native_token = base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(random);
    let native_cookie = format!("sb_native_{}", addr.port());
    let state = Arc::new(ServerState {
        backend_url,
        client: reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|e| format!("companion_client_failed:{e}"))?,
        admin_key,
        native_cookie: native_cookie.clone(),
        native_token: native_token.clone(),
        origin: format!("http://127.0.0.1:{}", addr.port()),
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
        native_cookie,
        native_token,
    })
}

// ---------------------------------------------------------------------------
// Unit tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn native_cookie_is_required_and_cannot_bypass_origin_or_custody() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let backend_addr = listener.local_addr().unwrap();
        let backend = Router::new().route(
            "/api/voice/status",
            axum::routing::get(|headers: HeaderMap| async move {
                if headers.get("x-admin-key").and_then(|h| h.to_str().ok())
                    == Some("audit-native-key")
                {
                    StatusCode::OK
                } else {
                    StatusCode::FORBIDDEN
                }
            }),
        );
        let task = tokio::spawn(async move {
            axum::serve(listener, backend).await.unwrap();
        });
        let root = std::env::temp_dir().join(format!("sb-native-cookie-{}", backend_addr.port()));
        std::fs::create_dir_all(&root).unwrap();
        std::fs::write(root.join("index.html"), "<html></html>").unwrap();
        let mut server = start_companion_server(
            root.clone(),
            format!("http://{backend_addr}"),
            Some("audit-native-key".into()),
        )
        .await
        .unwrap();
        let client = reqwest::Client::new();
        let url = format!("{}/api/voice/status", server.url());
        assert_eq!(
            client.get(&url).send().await.unwrap().status(),
            StatusCode::FORBIDDEN
        );
        assert_eq!(
            client
                .get(&url)
                .header("X-Admin-Key", "audit-native-key")
                .send()
                .await
                .unwrap()
                .status(),
            StatusCode::FORBIDDEN
        );
        let (name, token) = server.native_session_cookie();
        let cookie = format!("{name}={token}");
        assert_eq!(
            client
                .get(&url)
                .header("Cookie", &cookie)
                .header("Origin", server.url())
                .send()
                .await
                .unwrap()
                .status(),
            StatusCode::OK
        );
        assert_eq!(
            client
                .get(&url)
                .header("Cookie", &cookie)
                .header("Origin", "https://attacker.example")
                .send()
                .await
                .unwrap()
                .status(),
            StatusCode::FORBIDDEN
        );
        assert_eq!(
            client
                .post(format!(
                    "{}/api/wormhole/gate/message/%64ecrypt",
                    server.url()
                ))
                .header("Cookie", &cookie)
                .send()
                .await
                .unwrap()
                .status(),
            StatusCode::FORBIDDEN
        );
        assert!(operator_http_command("/api/flights").is_none());
        server.shutdown();
        task.abort();
        let _ = std::fs::remove_file(root.join("index.html"));
        let _ = std::fs::remove_dir(root);
    }

    #[test]
    fn server_handle_url_format() {
        let handle = CompanionServerHandle {
            addr: "127.0.0.1:12345".parse().unwrap(),
            shutdown_tx: None,
            native_cookie: "test".to_string(),
            native_token: "test".to_string(),
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

        let handle = start_companion_server(tmp.clone(), "http://127.0.0.1:9999".to_string(), None)
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

        let mut handle =
            start_companion_server(tmp.clone(), "http://127.0.0.1:9999".to_string(), None)
                .await
                .expect("server should start");

        // First shutdown
        handle.shutdown();
        // Second shutdown is safe (idempotent)
        handle.shutdown();

        let _ = std::fs::remove_dir_all(&tmp);
    }
}
