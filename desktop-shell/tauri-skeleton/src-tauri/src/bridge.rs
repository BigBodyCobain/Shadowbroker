use serde_json::Value;
use tauri::State;

use crate::handlers::dispatch_control_command;
use crate::policy::{self, PolicyOutcome};
use crate::{DesktopAppState, NativeGateCryptoState};

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
