use serde_json::Value;
use tauri::State;

use crate::handlers::dispatch_control_command;
use crate::policy::{self, PolicyOutcome};
use crate::{DesktopAppState, NativeGateCryptoState};
use tauri::Manager;

#[tauri::command]
pub async fn bootstrap_operator_session(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    state: State<'_, DesktopAppState>,
) -> Result<(), String> {
    if window.label() != "main" {
        return Err("native_session_main_window_only".into());
    }
    let url = window
        .url()
        .map_err(|e| format!("native_session_url:{e}"))?;
    let session = {
        app.try_state::<crate::AppServerHandle>()
            .map(|handle| {
                let server = handle.0.lock().map_err(|_| "native_server_lock")?;
                let (name, token) = server.native_session_cookie();
                Ok::<_, &str>((server.url(), name.to_string(), token.to_string()))
            })
            .transpose()
            .map_err(str::to_string)?
    };
    let cookie = if let Some((origin, name, token)) = session {
        if url.origin().ascii_serialization() != origin {
            return Err("native_session_origin_mismatch".into());
        }
        tauri::webview::Cookie::build((name, token))
            .http_only(true)
            .same_site(tauri::webview::cookie::SameSite::Strict)
            .path("/api")
            .domain("127.0.0.1")
            .build()
    } else {
        let expected = std::env::var("SHADOWBROKER_FRONTEND_URL")
            .unwrap_or_else(|_| "http://127.0.0.1:3000".into());
        let expected = url::Url::parse(&expected).map_err(|_| "native_session_invalid_frontend")?;
        if url.origin() != expected.origin() {
            return Err("native_session_origin_mismatch".into());
        }
        let key = state
            .admin_key
            .as_deref()
            .filter(|key| !key.is_empty())
            .ok_or("native_session_admin_key_required")?;
        let response = reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|e| e.to_string())?
            .post(
                expected
                    .join("/api/admin/session")
                    .map_err(|e| e.to_string())?,
            )
            .json(&serde_json::json!({"adminKey": key}))
            .send()
            .await
            .map_err(|e| format!("native_session_login:{e}"))?;
        if !response.status().is_success() {
            return Err("native_session_login_rejected".into());
        }
        let header = response
            .headers()
            .get("set-cookie")
            .and_then(|v| v.to_str().ok())
            .ok_or("native_session_cookie_missing")?;
        let mut cookie = tauri::webview::Cookie::parse(header.to_string())
            .map_err(|_| "native_session_invalid_cookie")?
            .into_owned();
        if cookie.name() != "sb_admin_session" || cookie.http_only() != Some(true) {
            return Err("native_session_invalid_cookie".into());
        }
        cookie.set_domain(
            url.host_str()
                .ok_or("native_session_invalid_host")?
                .to_string(),
        );
        cookie
    };
    window
        .set_cookie(cookie)
        .map_err(|e| format!("native_session_cookie:{e}"))
}

#[tauri::command]
pub async fn invoke_local_control(
    command: String,
    payload: Option<Value>,
    meta: Option<Value>,
    state: State<'_, DesktopAppState>,
    gate_crypto_state: State<'_, NativeGateCryptoState>,
) -> Result<Value, String> {
    // Enforce policy on the Rust side — this runs even if webview JS is
    // bypassed and invoke_local_control is called directly via Tauri IPC.
    match policy::enforce(&command, &payload, &meta) {
        PolicyOutcome::Allowed(entry) => {
            if let Ok(mut ring) = state.audit_ring.lock() {
                ring.record(entry);
            }
        }
        PolicyOutcome::ProfileWarn(entry) => {
            // Profile mismatch but not enforced — log warning, allow dispatch
            eprintln!(
                "native_control_profile_warn: command={} profile={:?} cap={}",
                entry.command, entry.session_profile, entry.expected_capability
            );
            if let Ok(mut ring) = state.audit_ring.lock() {
                ring.record(entry);
            }
        }
        PolicyOutcome::Denied(entry, message) => {
            if let Ok(mut ring) = state.audit_ring.lock() {
                ring.record(entry);
            }
            return Err(message);
        }
    }

    dispatch_control_command(
        &state.backend_base_url,
        state.admin_key.as_deref(),
        &command,
        payload,
        &gate_crypto_state,
    )
    .await
}

#[tauri::command]
pub fn get_native_audit_report(
    limit: Option<usize>,
    state: State<'_, DesktopAppState>,
) -> Result<Value, String> {
    let ring = state
        .audit_ring
        .lock()
        .map_err(|e| format!("audit_lock_failed:{e}"))?;
    let report = ring.snapshot(limit.unwrap_or(25));
    serde_json::to_value(report).map_err(|e| format!("audit_serialize_failed:{e}"))
}

#[tauri::command]
pub fn clear_native_audit_report(state: State<'_, DesktopAppState>) -> Result<(), String> {
    let mut ring = state
        .audit_ring
        .lock()
        .map_err(|e| format!("audit_lock_failed:{e}"))?;
    ring.clear();
    Ok(())
}
