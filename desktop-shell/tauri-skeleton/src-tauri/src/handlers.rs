use reqwest::Method;
use serde_json::Value;

use crate::gate_crypto;
use crate::http_client::call_backend_json;
use crate::NativeGateCryptoState;

fn extract_gate_id(payload: &Option<Value>) -> Result<String, String> {
    payload
        .as_ref()
        .and_then(|v| v.get("gate_id"))
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .map(|s| urlencoding::encode(s).into_owned())
        .ok_or_else(|| "missing_or_empty_gate_id".to_string())
}

fn payload_gate_id(payload: &Option<Value>) -> Option<String> {
    payload
        .as_ref()
        .and_then(|v| v.get("gate_id"))
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .map(ToString::to_string)
}

fn command_expects_gate_authority_change(command: &str) -> bool {
    matches!(
        command,
        "wormhole.gate.enter"
            | "wormhole.gate.leave"
            | "wormhole.gate.persona.create"
            | "wormhole.gate.persona.activate"
            | "wormhole.gate.persona.clear"
            | "wormhole.gate.key.rotate"
    )
}

fn command_requires_gate_state_snapshot(command: &str) -> bool {
    matches!(
        command,
        "wormhole.gate.enter"
            | "wormhole.gate.persona.create"
            | "wormhole.gate.persona.activate"
            | "wormhole.gate.persona.clear"
            | "wormhole.gate.key.rotate"
    )
}

fn payload_prefers_backend_gate_decrypt(command: &str, payload: &Option<Value>) -> bool {
    let Some(value) = payload.as_ref() else {
        return false;
    };
    match command {
        "wormhole.gate.message.decrypt" => {
            let format = value
                .get("format")
                .and_then(|v| v.as_str())
                .unwrap_or("mls1")
                .trim()
                .to_ascii_lowercase();
            let recovery_requested = value
                .get("recovery_envelope")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            recovery_requested || format != "mls1"
        }
        "wormhole.gate.messages.decrypt" => value
            .get("messages")
            .and_then(|v| v.as_array())
            .map(|messages| {
                messages.iter().any(|message| {
                    let format = message
                        .get("format")
                        .and_then(|v| v.as_str())
                        .unwrap_or("mls1")
                        .trim()
                        .to_ascii_lowercase();
                    let recovery_requested = message
                        .get("recovery_envelope")
                        .and_then(|v| v.as_bool())
                        .unwrap_or(false);
                    recovery_requested || format != "mls1"
                })
            })
            .unwrap_or(false),
        _ => false,
    }
}

pub async fn dispatch_control_command(
    backend_base_url: &str,
    admin_key: Option<&str>,
    command: &str,
    payload: Option<Value>,
    gate_crypto_state: &NativeGateCryptoState,
) -> Result<Value, String> {
    let expected_gate_change = if command_expects_gate_authority_change(command) {
        payload_gate_id(&payload)
    } else {
        None
    };
    if let Some(gate_id) = expected_gate_change.as_deref() {
        gate_crypto::mark_expected_gate_change(&gate_crypto_state.0, gate_id)?;
    }

    let result = match command {
        // --- Wormhole lifecycle ---
        "wormhole.status" => {
            call_backend_json(
                backend_base_url,
                admin_key,
                "/api/wormhole/status",
                Method::GET,
                None,
            )
            .await
        }
        "wormhole.connect" => {
            call_backend_json(
                backend_base_url,
                admin_key,
                "/api/wormhole/connect",
                Method::POST,
                None,
            )
            .await
        }
        "wormhole.disconnect" => {
            call_backend_json(
                backend_base_url,
                admin_key,
                "/api/wormhole/disconnect",
                Method::POST,
                None,
            )
            .await
        }
        "wormhole.restart" => {
            call_backend_json(
                backend_base_url,
                admin_key,
                "/api/wormhole/restart",
                Method::POST,
                None,
            )
            .await
        }

        // --- Gate access ---
        "wormhole.gate.enter" => {
            call_backend_json(
                backend_base_url,
                admin_key,
                "/api/wormhole/gate/enter",
                Method::POST,
                payload,
            )
            .await
        }
        "wormhole.gate.leave" => {
            call_backend_json(
                backend_base_url,
                admin_key,
                "/api/wormhole/gate/leave",
                Method::POST,
                payload,
            )
            .await
        }

        // --- Gate personas ---
        "wormhole.gate.personas.get" => {
            let gate_id = extract_gate_id(&payload)?;
            let path = format!("/api/wormhole/gate/{gate_id}/personas");
            call_backend_json(backend_base_url, admin_key, &path, Method::GET, None).await
        }
        "wormhole.gate.persona.create" => {
            call_backend_json(
                backend_base_url,
                admin_key,
                "/api/wormhole/gate/persona/create",
                Method::POST,
                payload,
            )
            .await
        }
        "wormhole.gate.persona.activate" => {
            call_backend_json(
                backend_base_url,
                admin_key,
                "/api/wormhole/gate/persona/activate",
                Method::POST,
                payload,
            )
            .await
        }
        "wormhole.gate.persona.clear" => {
            call_backend_json(
                backend_base_url,
                admin_key,
                "/api/wormhole/gate/persona/clear",
                Method::POST,
                payload,
            )
            .await
        }

        // --- Gate keys ---
        "wormhole.gate.key.get" => {
            let gate_id = extract_gate_id(&payload)?;
            let path = format!("/api/wormhole/gate/{gate_id}/key");
            call_backend_json(backend_base_url, admin_key, &path, Method::GET, None).await
        }
        "wormhole.gate.key.rotate" => {
            call_backend_json(
                backend_base_url,
                admin_key,
                "/api/wormhole/gate/key/rotate",
                Method::POST,
                payload,
            )
            .await
        }
        "wormhole.gate.state.resync" => {
            gate_crypto::resync_gate_state(
                &gate_crypto_state.0,
                backend_base_url,
                admin_key,
                payload,
            )
            .await
        }

        // --- Gate messages ---
        "wormhole.gate.proof" => {
            call_backend_json(
                backend_base_url,
                admin_key,
                "/api/wormhole/gate/proof",
                Method::POST,
                payload,
            )
            .await
        }
        "wormhole.gate.message.compose" => {
            gate_crypto::compose_gate_message(
                &gate_crypto_state.0,
                backend_base_url,
                admin_key,
                payload,
            )
            .await
        }
        "wormhole.gate.message.post" => {
            gate_crypto::post_gate_message(
                &gate_crypto_state.0,
                backend_base_url,
                admin_key,
                payload,
            )
            .await
        }
        "wormhole.gate.message.decrypt" => {
            if payload_prefers_backend_gate_decrypt(command, &payload) {
                return call_backend_json(
                    backend_base_url,
                    admin_key,
                    "/api/wormhole/gate/message/decrypt",
                    Method::POST,
                    payload,
                )
                .await;
            }
            gate_crypto::decrypt_gate_message(
                &gate_crypto_state.0,
                backend_base_url,
                admin_key,
                payload,
            )
            .await
        }
        "wormhole.gate.messages.decrypt" => {
            if payload_prefers_backend_gate_decrypt(command, &payload) {
                return call_backend_json(
                    backend_base_url,
                    admin_key,
                    "/api/wormhole/gate/messages/decrypt",
                    Method::POST,
                    payload,
                )
                .await;
            }
            gate_crypto::decrypt_gate_messages(
                &gate_crypto_state.0,
                backend_base_url,
                admin_key,
                payload,
            )
            .await
        }

        // --- Settings ---
        "settings.wormhole.get" => {
            call_backend_json(
                backend_base_url,
                admin_key,
                "/api/settings/wormhole",
                Method::GET,
                None,
            )
            .await
        }
        "settings.wormhole.set" => {
            call_backend_json(
                backend_base_url,
                admin_key,
                "/api/settings/wormhole",
                Method::PUT,
                payload,
            )
            .await
        }
        "settings.privacy.get" => {
            call_backend_json(
                backend_base_url,
                admin_key,
                "/api/settings/privacy-profile",
                Method::GET,
                None,
            )
            .await
        }
        "settings.privacy.set" => {
            call_backend_json(
                backend_base_url,
                admin_key,
                "/api/settings/privacy-profile",
                Method::PUT,
                payload,
            )
            .await
        }
        "settings.api_keys.get" => {
            call_backend_json(
                backend_base_url,
                admin_key,
                "/api/settings/api-keys",
                Method::GET,
                None,
            )
            .await
        }
        "settings.news.get" => {
            call_backend_json(
                backend_base_url,
                admin_key,
                "/api/settings/news-feeds",
                Method::GET,
                None,
            )
            .await
        }
        "settings.news.set" => {
            call_backend_json(
                backend_base_url,
                admin_key,
                "/api/settings/news-feeds",
                Method::PUT,
                payload,
            )
            .await
        }
        "settings.news.reset" => {
            call_backend_json(
                backend_base_url,
                admin_key,
                "/api/settings/news-feeds/reset",
                Method::POST,
                None,
            )
            .await
        }

        // --- System ---
        "system.update" => {
            call_backend_json(
                backend_base_url,
                admin_key,
                "/api/system/update",
                Method::POST,
                None,
            )
            .await
        }

        _ => Err(format!("unsupported_control_command:{command}")),
    };

    if let Some(gate_id) = expected_gate_change.as_deref() {
        if result.is_err() {
            let _ = gate_crypto::clear_expected_gate_change(&gate_crypto_state.0, gate_id);
        } else if command == "wormhole.gate.leave" {
            let _ = gate_crypto::forget_gate_state(&gate_crypto_state.0, gate_id);
        } else if command_requires_gate_state_snapshot(command) {
            if let Ok(value) = result.as_ref() {
                if let Err(err) =
                    gate_crypto::adopt_gate_state_snapshot_from_result(&gate_crypto_state.0, value)
                {
                    let _ = gate_crypto::clear_expected_gate_change(&gate_crypto_state.0, gate_id);
                    return Err(err);
                }
            }
        }
    }

    result
}
