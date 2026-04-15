use serde_json::Value;
use tauri::State;

use crate::{handlers::dispatch_control_command, DesktopAppState};

#[tauri::command]
pub async fn invoke_local_control(
    command: String,
    payload: Option<Value>,
    state: State<'_, DesktopAppState>,
) -> Result<Value, String> {
    dispatch_control_command(
        &state.backend_base_url,
        state.admin_key.as_deref(),
        &command,
        payload,
    )
    .await
}
