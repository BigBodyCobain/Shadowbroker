//! Optional localhost/browser companion mode.
//!
//! When explicitly enabled by the user, allows opening the frontend in the
//! system browser on a loopback-only URL. The browser session does **not**
//! receive the native desktop control boundary (`window.__SHADOWBROKER_DESKTOP__`)
//! and therefore cannot invoke any of the 27 native-control commands. It
//! operates at materially reduced trust compared with the native window.
//!
//! **Important honesty note:**
//! The browser companion session in packaged mode does **not** have the same
//! capabilities as standalone browser mode (i.e. `npm run dev` + a real
//! Next.js server). The built-in loopback server is a thin static + API
//! proxy — it does NOT reproduce Next.js middleware, the catch-all `/api/*`
//! route's admin session cookie logic, the wormhole routing logic, or the
//! sensitive-path `X-Admin-Key` injection. Admin-gated backend endpoints
//! (settings, wormhole lifecycle, gate operations, system update) are
//! **not reachable** from the browser companion.
//!
//! **Ownership model (post-P6D-R):**
//! In packaged mode the loopback server is started at app launch by
//! `main.rs` (not by `companion_enable`) so that the Tauri main window also
//! uses it as its HTTP origin. Companion state simply tracks whether the
//! browser opener is enabled and what URL to hand out. Server lifecycle is
//! owned by the app, not by this module.

use serde::Serialize;
use std::path::PathBuf;
use std::sync::Mutex;
use tauri::State;

// ---------------------------------------------------------------------------
// Warning text
// ---------------------------------------------------------------------------

/// Warning shown to users when enabling or querying companion mode.
///
/// Honest about what the browser session cannot do. Does NOT claim parity
/// with standalone browser mode, because the built-in loopback server is a
/// thin proxy and does not reproduce Next.js middleware or admin session
/// handling.
pub const COMPANION_WARNING: &str = "\
Browser companion mode opens the app in your default browser on localhost. \
This is less secure than the native desktop window: browser extensions, \
shared cookies, and local processes can interact with the page. The browser \
session does NOT receive native desktop control privileges and cannot use \
admin-gated APIs (settings, wormhole lifecycle, gate operations, system \
update). In packaged builds, only public data endpoints are reachable from \
the browser session — it is not equivalent to standalone browser mode. \
Use the native window for any sensitive or admin-gated operations.";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

/// Serializable status returned by companion commands.
#[derive(Debug, Clone, Serialize)]
pub struct CompanionStatus {
    pub enabled: bool,
    pub url: Option<String>,
    pub warning: &'static str,
}

/// Companion mode state. Disabled by default.
///
/// This module does NOT own the loopback server lifecycle. In packaged mode
/// the server is started at app launch (see `main.rs`) and its URL is
/// registered here via `set_app_server_url`. Companion mode then uses that
/// shared URL when the user enables the browser opener.
pub struct CompanionState {
    enabled: bool,
    /// Default frontend URL (from `SHADOWBROKER_FRONTEND_URL` or the
    /// `http://127.0.0.1:3000` fallback used in dev mode).
    default_frontend_url: String,
    /// Whether `SHADOWBROKER_FRONTEND_URL` was explicitly set by the user.
    /// When true the default URL is honored even in packaged builds
    /// (explicit override beats built-in server).
    frontend_url_explicit: bool,
    /// URL of the app-level loopback server, set by `main.rs` at startup
    /// when packaged assets are available and no explicit URL override is
    /// active. `None` in dev mode or when no bundled assets were found.
    app_server_url: Option<String>,
    /// Path to bundled frontend assets (informational; server lifecycle
    /// is owned by `main.rs`). Set during setup when the resource
    /// directory contains `companion-www/index.html`.
    www_root: Option<PathBuf>,
}

pub type SharedCompanionState = Mutex<CompanionState>;

/// Create initial companion state. Called from `main()`.
pub fn new_companion_state(
    default_frontend_url: String,
    frontend_url_explicit: bool,
) -> SharedCompanionState {
    Mutex::new(CompanionState {
        enabled: false,
        default_frontend_url,
        frontend_url_explicit,
        app_server_url: None,
        www_root: None,
    })
}

impl CompanionState {
    fn status(&self) -> CompanionStatus {
        CompanionStatus {
            enabled: self.enabled,
            url: if self.enabled {
                Some(self.effective_url())
            } else {
                None
            },
            warning: COMPANION_WARNING,
        }
    }

    /// Resolve the URL the browser should open.
    ///
    /// Packaged mode with server running (no explicit URL override): use the
    /// app-level loopback server URL. Otherwise fall back to the configured
    /// default frontend URL (dev mode or explicit override).
    fn effective_url(&self) -> String {
        if !self.frontend_url_explicit {
            if let Some(url) = self.app_server_url.as_deref() {
                return url.to_string();
            }
        }
        self.default_frontend_url.clone()
    }

    /// Whether this companion state will route through the built-in
    /// loopback server (packaged mode without explicit override).
    #[cfg_attr(not(test), allow(dead_code))]
    pub fn uses_builtin_server(&self) -> bool {
        !self.frontend_url_explicit && self.app_server_url.is_some()
    }

    /// Set the URL of the app-level loopback server. Called from `main.rs`
    /// setup once the server has successfully bound.
    pub fn set_app_server_url(&mut self, url: String) {
        self.app_server_url = Some(url);
    }

    /// Record the bundled frontend asset path (packaged build indicator).
    pub fn set_www_root(&mut self, path: PathBuf) {
        self.www_root = Some(path);
    }
}

// ---------------------------------------------------------------------------
// Loopback validation
// ---------------------------------------------------------------------------

/// Check whether a URL string points to a loopback address.
/// Only `127.0.0.1`, `localhost`, and `::1` (including bracketed `[::1]`)
/// are considered loopback. `0.0.0.0`, LAN IPs, and public hosts are rejected.
pub fn is_loopback_origin(url: &str) -> bool {
    let after_scheme = match url.split_once("://") {
        Some((_, rest)) => rest,
        None => return false,
    };
    let host_port = after_scheme.split('/').next().unwrap_or("");
    let host = if host_port.starts_with('[') {
        // IPv6: [::1]:port
        host_port
            .split(']')
            .next()
            .unwrap_or("")
            .trim_start_matches('[')
    } else {
        host_port.split(':').next().unwrap_or("")
    };
    matches!(host, "127.0.0.1" | "localhost" | "::1")
}

// ---------------------------------------------------------------------------
// Tauri commands
// ---------------------------------------------------------------------------

/// Query companion mode status.
#[tauri::command]
pub fn companion_status(state: State<'_, SharedCompanionState>) -> Result<CompanionStatus, String> {
    let cs = state.lock().map_err(|e| format!("companion_lock:{e}"))?;
    Ok(cs.status())
}

/// Enable companion mode.
///
/// In packaged mode, uses the already-running app loopback server URL.
/// In dev mode / explicit override, uses the configured frontend URL.
/// Either way, validates the URL is loopback-only before enabling.
#[tauri::command]
pub fn companion_enable(state: State<'_, SharedCompanionState>) -> Result<CompanionStatus, String> {
    let mut cs = state.lock().map_err(|e| format!("companion_lock:{e}"))?;

    if cs.enabled {
        return Ok(cs.status());
    }

    let url = cs.effective_url();
    if !is_loopback_origin(&url) {
        return Err(format!(
            "companion_not_loopback: frontend origin '{url}' is not a loopback address"
        ));
    }

    cs.enabled = true;
    Ok(cs.status())
}

/// Disable companion mode. Does not affect the app-level loopback server
/// (which remains running for the native main window).
#[tauri::command]
pub fn companion_disable(
    state: State<'_, SharedCompanionState>,
) -> Result<CompanionStatus, String> {
    let mut cs = state.lock().map_err(|e| format!("companion_lock:{e}"))?;
    cs.enabled = false;
    Ok(cs.status())
}

/// Open the frontend in the system browser. Only works when companion mode
/// is enabled and the URL is loopback-only.
#[tauri::command]
pub fn companion_open_browser(
    state: State<'_, SharedCompanionState>,
) -> Result<CompanionStatus, String> {
    let cs = state.lock().map_err(|e| format!("companion_lock:{e}"))?;
    if !cs.enabled {
        return Err(
            "companion_not_enabled: enable companion mode before opening in browser".to_string(),
        );
    }
    let url = cs.effective_url();
    // Defense in depth: re-verify loopback before launching the browser.
    if !is_loopback_origin(&url) {
        return Err(format!(
            "companion_not_loopback: refusing to open non-loopback origin '{url}'"
        ));
    }
    let status = cs.status();
    drop(cs); // release lock before launching browser

    open::that(&url).map_err(|e| format!("companion_open_failed:{e}"))?;
    Ok(status)
}

// ---------------------------------------------------------------------------
// Unit tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    // -- Loopback validation --

    #[test]
    fn loopback_127_0_0_1() {
        assert!(is_loopback_origin("http://127.0.0.1:3000"));
        assert!(is_loopback_origin("http://127.0.0.1"));
        assert!(is_loopback_origin("https://127.0.0.1:8443/path"));
    }

    #[test]
    fn loopback_localhost() {
        assert!(is_loopback_origin("http://localhost:3000"));
        assert!(is_loopback_origin("http://localhost"));
        assert!(is_loopback_origin("https://localhost:8443/path"));
    }

    #[test]
    fn loopback_ipv6() {
        assert!(is_loopback_origin("http://[::1]:3000"));
        assert!(is_loopback_origin("http://[::1]"));
    }

    #[test]
    fn rejects_non_loopback() {
        assert!(!is_loopback_origin("http://0.0.0.0:3000"));
        assert!(!is_loopback_origin("http://192.168.1.1:3000"));
        assert!(!is_loopback_origin("http://example.com"));
        assert!(!is_loopback_origin("https://10.0.0.1:8443"));
    }

    #[test]
    fn rejects_empty_and_malformed() {
        assert!(!is_loopback_origin(""));
        assert!(!is_loopback_origin("not-a-url"));
        assert!(!is_loopback_origin("://127.0.0.1"));
    }

    // -- Companion state --

    #[test]
    fn disabled_by_default() {
        let state = new_companion_state("http://127.0.0.1:3000".to_string(), false);
        let cs = state.lock().unwrap();
        let status = cs.status();
        assert!(!status.enabled);
        assert!(status.url.is_none());
    }

    #[test]
    fn status_includes_honest_warning() {
        let state = new_companion_state("http://127.0.0.1:3000".to_string(), false);
        let cs = state.lock().unwrap();
        let warning = cs.status().warning;
        assert!(!warning.is_empty());
        assert!(
            warning.contains("less secure"),
            "warning should mention reduced trust"
        );
        assert!(
            warning.contains("native desktop window"),
            "warning should reference the native window"
        );
        assert!(
            warning.contains("admin-gated"),
            "warning must name the specific capabilities browser companion lacks"
        );
        assert!(
            warning.contains("not equivalent to standalone browser mode"),
            "warning must NOT imply standalone browser parity"
        );
    }

    #[test]
    fn url_hidden_when_disabled() {
        let state = new_companion_state("http://127.0.0.1:3000".to_string(), false);
        let cs = state.lock().unwrap();
        assert!(cs.status().url.is_none(), "URL must not leak when disabled");
    }

    // -- Mode detection: effective URL resolution --

    #[test]
    fn dev_mode_uses_default_url() {
        let state = new_companion_state("http://127.0.0.1:3000".to_string(), false);
        let cs = state.lock().unwrap();
        assert_eq!(cs.effective_url(), "http://127.0.0.1:3000");
        assert!(!cs.uses_builtin_server());
    }

    #[test]
    fn packaged_mode_prefers_app_server_url() {
        let state = new_companion_state("http://127.0.0.1:3000".to_string(), false);
        {
            let mut cs = state.lock().unwrap();
            cs.set_app_server_url("http://127.0.0.1:54321".to_string());
        }
        let cs = state.lock().unwrap();
        assert_eq!(cs.effective_url(), "http://127.0.0.1:54321");
        assert!(cs.uses_builtin_server());
    }

    #[test]
    fn explicit_override_beats_app_server() {
        let state = new_companion_state("http://127.0.0.1:4000".to_string(), true);
        {
            let mut cs = state.lock().unwrap();
            cs.set_app_server_url("http://127.0.0.1:54321".to_string());
        }
        let cs = state.lock().unwrap();
        assert_eq!(
            cs.effective_url(),
            "http://127.0.0.1:4000",
            "explicit SHADOWBROKER_FRONTEND_URL must beat the built-in server URL"
        );
        assert!(!cs.uses_builtin_server());
    }

    #[test]
    fn enable_returns_url_reflecting_mode() {
        let state = new_companion_state("http://127.0.0.1:3000".to_string(), false);
        {
            let mut cs = state.lock().unwrap();
            cs.set_app_server_url("http://127.0.0.1:54321".to_string());
            cs.enabled = true;
        }
        let cs = state.lock().unwrap();
        assert_eq!(
            cs.status().url,
            Some("http://127.0.0.1:54321".to_string()),
            "enabled status URL should reflect the app server URL in packaged mode"
        );
    }

    #[test]
    fn set_www_root_records_path() {
        let state = new_companion_state("http://127.0.0.1:3000".to_string(), false);
        let mut cs = state.lock().unwrap();
        cs.set_www_root(PathBuf::from("/tmp/companion-www"));
        assert!(cs.www_root.is_some());
    }
}
