use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use base64::Engine as _;
use reqwest::Method;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::http_client::call_backend_json;
use crate::local_custody::{read_or_migrate_json_file, write_protected_json_file};

const GATE_EXPORT_PATH: &str = "/api/wormhole/gate/state/export";
const GATE_SIGN_ENCRYPTED_PATH: &str = "/api/wormhole/gate/message/sign-encrypted";
const GATE_POST_ENCRYPTED_PATH: &str = "/api/wormhole/gate/message/post-encrypted";
const GATE_BUCKETS: [usize; 6] = [192, 384, 768, 1536, 3072, 6144];
const GATE_STATUS_CACHE_TTL: Duration = Duration::from_secs(15);
const GATE_EXPECTED_CHANGE_TTL: Duration = Duration::from_secs(300);

#[derive(Default)]
pub struct GateCryptoRuntime {
    gates: HashMap<String, ImportedGateState>,
    status: HashMap<String, CachedGateStatus>,
    pending_gate_changes: HashMap<String, Instant>,
    cache_root: Option<PathBuf>,
}

impl GateCryptoRuntime {
    pub fn set_cache_root(&mut self, path: PathBuf) {
        self.cache_root = Some(path);
    }
}

impl Drop for GateCryptoRuntime {
    fn drop(&mut self) {
        for (_, state) in self.gates.drain() {
            release_imported_state(state);
        }
    }
}

#[derive(Clone, Debug)]
struct ImportedGateState {
    epoch: i64,
    state_fingerprint: String,
    group_handles: Vec<u64>,
    identity_handles: Vec<u64>,
    active_group_handle: u64,
    members: Vec<GateStateMember>,
    active_identity_scope: String,
    active_persona_id: String,
    active_node_id: String,
}

#[derive(Clone, Debug)]
struct CachedGateStatus {
    checked_at: Instant,
    snapshot: GateStatusSnapshot,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct GateStateSnapshot {
    gate_id: String,
    epoch: i64,
    rust_state_blob_b64: String,
    members: Vec<GateStateMember>,
    active_identity_scope: String,
    active_persona_id: String,
    active_node_id: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct GateStateMember {
    persona_id: String,
    node_id: String,
    identity_scope: String,
    group_handle: u64,
}

#[derive(Debug, Deserialize)]
struct GateStateImportMapping {
    identities: HashMap<String, u64>,
    groups: HashMap<String, u64>,
}

#[derive(Debug, Deserialize)]
struct GateDecryptRequest {
    gate_id: String,
    epoch: Option<i64>,
    ciphertext: String,
}

#[derive(Debug, Deserialize)]
struct GateDecryptBatchRequest {
    messages: Vec<GateDecryptRequest>,
}

#[derive(Debug, Deserialize)]
struct GateComposeRequest {
    gate_id: String,
    plaintext: String,
    reply_to: Option<String>,
}

#[derive(Debug, Deserialize)]
struct GateRequest {
    gate_id: String,
}

#[derive(Clone, Debug, Deserialize)]
struct GateStatusSnapshot {
    current_epoch: i64,
    has_local_access: bool,
    identity_scope: String,
    identity_node_id: String,
    identity_persona_id: String,
}

fn normalize_gate_id(gate_id: &str) -> String {
    gate_id.trim().to_ascii_lowercase()
}

fn decode_gate_ciphertext(ciphertext_b64: &str) -> Result<Vec<u8>, String> {
    let padded = base64::engine::general_purpose::STANDARD
        .decode(ciphertext_b64.trim())
        .map_err(|e| format!("native_gate_ciphertext_b64_invalid:{e}"))?;
    Ok(unpad_gate_ciphertext(&padded))
}

fn unpad_gate_ciphertext(padded: &[u8]) -> Vec<u8> {
    if padded.len() < 2 {
        return padded.to_vec();
    }
    let original_len = u16::from_be_bytes([padded[0], padded[1]]) as usize;
    if original_len == 0 || original_len + 2 > padded.len() {
        return padded.to_vec();
    }
    padded[2..2 + original_len].to_vec()
}

fn decode_plaintext(
    ciphertext_open: &[u8],
    fallback_epoch: i64,
) -> Result<(String, i64, String), String> {
    let raw = std::str::from_utf8(ciphertext_open)
        .map_err(|e| format!("native_gate_plaintext_utf8_invalid:{e}"))?;
    match serde_json::from_str::<Value>(raw) {
        Ok(Value::Object(map)) => {
            let plaintext = map
                .get("m")
                .and_then(Value::as_str)
                .unwrap_or(raw)
                .to_string();
            let epoch = map
                .get("e")
                .and_then(Value::as_i64)
                .unwrap_or(fallback_epoch);
            let reply_to = map
                .get("r")
                .and_then(Value::as_str)
                .unwrap_or("")
                .trim()
                .to_string();
            Ok((plaintext, epoch, reply_to))
        }
        Ok(_) | Err(_) => Ok((raw.to_string(), fallback_epoch, String::new())),
    }
}

fn imported_group_handles(
    snapshot: &GateStateSnapshot,
    mapping: &GateStateImportMapping,
) -> Result<Vec<u64>, String> {
    let mut imported = Vec::new();
    let mut seen = HashSet::new();
    for member in &snapshot.members {
        let key = member.group_handle.to_string();
        let mapped = mapping
            .groups
            .get(&key)
            .copied()
            .ok_or_else(|| format!("native_gate_state_mapping_missing_group:{key}"))?;
        if seen.insert(mapped) {
            imported.push(mapped);
        }
    }
    if imported.is_empty() {
        return Err("native_gate_state_import_empty".to_string());
    }
    Ok(imported)
}

fn gate_member_matches_active(snapshot: &GateStateSnapshot, member: &GateStateMember) -> bool {
    let active_scope = snapshot.active_identity_scope.trim().to_ascii_lowercase();
    if active_scope == "persona" {
        let active_persona_id = snapshot.active_persona_id.trim();
        !active_persona_id.is_empty() && member.persona_id.trim() == active_persona_id
    } else {
        let active_node_id = snapshot.active_node_id.trim();
        !active_node_id.is_empty()
            && member.node_id.trim() == active_node_id
            && member
                .identity_scope
                .trim()
                .eq_ignore_ascii_case("anonymous")
    }
}

fn imported_active_group_handle(
    snapshot: &GateStateSnapshot,
    mapping: &GateStateImportMapping,
) -> Result<u64, String> {
    let member = snapshot
        .members
        .iter()
        .find(|member| gate_member_matches_active(snapshot, member))
        .ok_or_else(|| "native_gate_state_active_member_missing".to_string())?;
    let key = member.group_handle.to_string();
    mapping
        .groups
        .get(&key)
        .copied()
        .ok_or_else(|| format!("native_gate_state_mapping_missing_active_group:{key}"))
}

fn pad_gate_ciphertext(raw_ciphertext: &[u8]) -> Vec<u8> {
    let mut prefixed = Vec::with_capacity(raw_ciphertext.len() + 2);
    let len = raw_ciphertext.len().min(u16::MAX as usize) as u16;
    prefixed.extend_from_slice(&len.to_be_bytes());
    prefixed.extend_from_slice(raw_ciphertext);
    for bucket in GATE_BUCKETS {
        if prefixed.len() <= bucket {
            prefixed.resize(bucket, 0);
            return prefixed;
        }
    }
    let last_bucket = *GATE_BUCKETS.last().unwrap_or(&6144);
    let target = ((prefixed.len() - 1) / last_bucket + 1) * last_bucket;
    prefixed.resize(target, 0);
    prefixed
}

fn encode_gate_ciphertext(raw_ciphertext: &[u8]) -> String {
    base64::engine::general_purpose::STANDARD.encode(pad_gate_ciphertext(raw_ciphertext))
}

fn encode_gate_plaintext(plaintext: &str, epoch: i64, reply_to: &str) -> Result<Vec<u8>, String> {
    let mut payload = serde_json::Map::new();
    payload.insert("m".to_string(), json!(plaintext));
    payload.insert("e".to_string(), json!(epoch));
    let reply_to = reply_to.trim();
    if !reply_to.is_empty() {
        payload.insert("r".to_string(), json!(reply_to));
    }
    serde_json::to_vec(&Value::Object(payload))
        .map_err(|e| format!("native_gate_plaintext_encode_failed:{e}"))
}

fn generate_gate_nonce() -> Result<String, String> {
    let mut bytes = [0u8; 12];
    getrandom::getrandom(&mut bytes).map_err(|e| format!("native_gate_nonce_failed:{e}"))?;
    Ok(base64::engine::general_purpose::STANDARD.encode(bytes))
}

fn gate_cache_filename(gate_id: &str) -> String {
    let normalized = normalize_gate_id(gate_id);
    let mut hex = String::with_capacity(normalized.len() * 2);
    for byte in normalized.as_bytes() {
        hex.push_str(&format!("{byte:02x}"));
    }
    format!("gate-{hex}.json")
}

fn gate_cache_path(cache_root: &Path, gate_id: &str) -> PathBuf {
    cache_root.join(gate_cache_filename(gate_id))
}

fn resync_required_error(gate_id: &str) -> String {
    format!(
        "native_gate_state_resync_required:{}",
        normalize_gate_id(gate_id)
    )
}

fn status_snapshot_from_imported(imported: &ImportedGateState) -> GateStatusSnapshot {
    GateStatusSnapshot {
        current_epoch: imported.epoch,
        has_local_access: true,
        identity_scope: imported.active_identity_scope.clone(),
        identity_node_id: imported.active_node_id.clone(),
        identity_persona_id: imported.active_persona_id.clone(),
    }
}

fn imported_matches_snapshot(imported: &ImportedGateState, snapshot: &GateStateSnapshot) -> bool {
    if !imported
        .active_identity_scope
        .eq_ignore_ascii_case(snapshot.active_identity_scope.trim())
    {
        return false;
    }
    if imported
        .active_identity_scope
        .eq_ignore_ascii_case("persona")
    {
        imported.active_persona_id.trim() == snapshot.active_persona_id.trim()
    } else {
        imported.active_node_id.trim() == snapshot.active_node_id.trim()
    }
}

fn imported_matches_status(imported: &ImportedGateState, status: &GateStatusSnapshot) -> bool {
    if !status.has_local_access || imported.epoch != status.current_epoch {
        return false;
    }
    if !imported
        .active_identity_scope
        .eq_ignore_ascii_case(status.identity_scope.trim())
    {
        return false;
    }
    if imported
        .active_identity_scope
        .eq_ignore_ascii_case("persona")
    {
        imported.active_persona_id.trim() == status.identity_persona_id.trim()
    } else {
        imported.active_node_id.trim() == status.identity_node_id.trim()
    }
}

fn validate_status_transition(
    imported: &ImportedGateState,
    status: &GateStatusSnapshot,
    expected_change: bool,
) -> Result<(), String> {
    if status.current_epoch < imported.epoch {
        return Err("gate_state_regression_detected".to_string());
    }
    if !status.has_local_access {
        if expected_change {
            return Ok(());
        }
        return Err("gate_access_unexpected_change".to_string());
    }
    if status.current_epoch == imported.epoch {
        if imported_matches_status(imported, status) {
            return Ok(());
        }
        if expected_change {
            return Ok(());
        }
        return Err("gate_identity_unexpected_change".to_string());
    }
    if imported_matches_status(imported, status)
        || (imported
            .active_identity_scope
            .eq_ignore_ascii_case(status.identity_scope.trim())
            && ((imported
                .active_identity_scope
                .eq_ignore_ascii_case("persona")
                && imported.active_persona_id.trim() == status.identity_persona_id.trim())
                || (!imported
                    .active_identity_scope
                    .eq_ignore_ascii_case("persona")
                    && imported.active_node_id.trim() == status.identity_node_id.trim())))
    {
        return Ok(());
    }
    if expected_change {
        return Ok(());
    }
    Err("gate_identity_unexpected_change".to_string())
}

fn validate_snapshot_transition(
    imported: &ImportedGateState,
    snapshot: &GateStateSnapshot,
    expected_change: bool,
) -> Result<(), String> {
    if snapshot.epoch < imported.epoch {
        return Err("gate_state_regression_detected".to_string());
    }
    let same_identity = imported_matches_snapshot(imported, snapshot);
    if snapshot.epoch == imported.epoch {
        if !same_identity {
            if expected_change {
                return Ok(());
            }
            return Err("gate_identity_unexpected_change".to_string());
        }
        if imported.state_fingerprint != snapshot.rust_state_blob_b64 {
            return Err("gate_state_unexpected_rewrite".to_string());
        }
        return Ok(());
    }
    if same_identity || expected_change {
        return Ok(());
    }
    Err("gate_identity_unexpected_change".to_string())
}

fn release_imported_state(state: ImportedGateState) {
    for group_handle in state.group_handles {
        let _ = privacy_core::release_group(group_handle);
    }
    for identity_handle in state.identity_handles {
        let _ = privacy_core::release_identity(identity_handle);
    }
}

fn cache_entry(
    gate_state: &Mutex<GateCryptoRuntime>,
    gate_id: &str,
) -> Result<Option<ImportedGateState>, String> {
    let guard = gate_state
        .lock()
        .map_err(|e| format!("native_gate_crypto_lock_failed:{e}"))?;
    Ok(guard.gates.get(gate_id).cloned())
}

fn cache_root(gate_state: &Mutex<GateCryptoRuntime>) -> Result<Option<PathBuf>, String> {
    let guard = gate_state
        .lock()
        .map_err(|e| format!("native_gate_crypto_lock_failed:{e}"))?;
    Ok(guard.cache_root.clone())
}

fn cached_status(
    gate_state: &Mutex<GateCryptoRuntime>,
    gate_id: &str,
) -> Result<Option<GateStatusSnapshot>, String> {
    let guard = gate_state
        .lock()
        .map_err(|e| format!("native_gate_crypto_lock_failed:{e}"))?;
    Ok(guard
        .status
        .get(gate_id)
        .filter(|entry| entry.checked_at.elapsed() <= GATE_STATUS_CACHE_TTL)
        .map(|entry| entry.snapshot.clone()))
}

fn has_expected_gate_change(
    gate_state: &Mutex<GateCryptoRuntime>,
    gate_id: &str,
) -> Result<bool, String> {
    let normalized = normalize_gate_id(gate_id);
    let mut guard = gate_state
        .lock()
        .map_err(|e| format!("native_gate_crypto_lock_failed:{e}"))?;
    guard
        .pending_gate_changes
        .retain(|_, marked_at| marked_at.elapsed() <= GATE_EXPECTED_CHANGE_TTL);
    Ok(guard.pending_gate_changes.contains_key(&normalized))
}

pub fn mark_expected_gate_change(
    gate_state: &Mutex<GateCryptoRuntime>,
    gate_id: &str,
) -> Result<(), String> {
    let normalized = normalize_gate_id(gate_id);
    if normalized.is_empty() {
        return Ok(());
    }
    let mut guard = gate_state
        .lock()
        .map_err(|e| format!("native_gate_crypto_lock_failed:{e}"))?;
    guard.status.remove(&normalized);
    guard
        .pending_gate_changes
        .insert(normalized, Instant::now());
    Ok(())
}

pub fn clear_expected_gate_change(
    gate_state: &Mutex<GateCryptoRuntime>,
    gate_id: &str,
) -> Result<(), String> {
    let normalized = normalize_gate_id(gate_id);
    if normalized.is_empty() {
        return Ok(());
    }
    let mut guard = gate_state
        .lock()
        .map_err(|e| format!("native_gate_crypto_lock_failed:{e}"))?;
    guard.pending_gate_changes.remove(&normalized);
    Ok(())
}

fn replace_status(
    gate_state: &Mutex<GateCryptoRuntime>,
    gate_id: String,
    snapshot: GateStatusSnapshot,
) -> Result<(), String> {
    let mut guard = gate_state
        .lock()
        .map_err(|e| format!("native_gate_crypto_lock_failed:{e}"))?;
    guard.status.insert(
        gate_id,
        CachedGateStatus {
            checked_at: Instant::now(),
            snapshot,
        },
    );
    Ok(())
}

fn invalidate_status(gate_state: &Mutex<GateCryptoRuntime>, gate_id: &str) -> Result<(), String> {
    let mut guard = gate_state
        .lock()
        .map_err(|e| format!("native_gate_crypto_lock_failed:{e}"))?;
    guard.status.remove(gate_id);
    Ok(())
}

fn replace_cache_entry(
    gate_state: &Mutex<GateCryptoRuntime>,
    gate_id: String,
    next: ImportedGateState,
) -> Result<(), String> {
    let old = {
        let mut guard = gate_state
            .lock()
            .map_err(|e| format!("native_gate_crypto_lock_failed:{e}"))?;
        guard.gates.insert(gate_id, next)
    };
    if let Some(previous) = old {
        release_imported_state(previous);
    }
    Ok(())
}

fn drop_cache_entry(
    gate_state: &Mutex<GateCryptoRuntime>,
    gate_id: &str,
) -> Result<Option<ImportedGateState>, String> {
    let normalized = normalize_gate_id(gate_id);
    let mut guard = gate_state
        .lock()
        .map_err(|e| format!("native_gate_crypto_lock_failed:{e}"))?;
    guard.status.remove(&normalized);
    guard.pending_gate_changes.remove(&normalized);
    Ok(guard.gates.remove(&normalized))
}

fn import_snapshot(snapshot: GateStateSnapshot) -> Result<ImportedGateState, String> {
    let blob = base64::engine::general_purpose::STANDARD
        .decode(snapshot.rust_state_blob_b64.trim())
        .map_err(|e| format!("native_gate_state_blob_invalid:{e}"))?;
    let mapping_json = privacy_core::import_gate_state(&blob)
        .map_err(|e| format!("native_gate_state_import_failed:{e}"))?;
    let mapping: GateStateImportMapping = serde_json::from_slice(&mapping_json)
        .map_err(|e| format!("native_gate_state_mapping_invalid:{e}"))?;
    let mut remapped_members = Vec::with_capacity(snapshot.members.len());
    for member in &snapshot.members {
        let key = member.group_handle.to_string();
        let mapped = mapping
            .groups
            .get(&key)
            .copied()
            .ok_or_else(|| format!("native_gate_state_mapping_missing_group:{key}"))?;
        remapped_members.push(GateStateMember {
            persona_id: member.persona_id.clone(),
            node_id: member.node_id.clone(),
            identity_scope: member.identity_scope.clone(),
            group_handle: mapped,
        });
    }
    let remapped_snapshot = GateStateSnapshot {
        rust_state_blob_b64: snapshot.rust_state_blob_b64,
        members: remapped_members.clone(),
        ..snapshot
    };
    Ok(ImportedGateState {
        epoch: remapped_snapshot.epoch,
        state_fingerprint: remapped_snapshot.rust_state_blob_b64.clone(),
        group_handles: imported_group_handles(&remapped_snapshot, &mapping)?,
        identity_handles: mapping.identities.values().copied().collect(),
        active_group_handle: imported_active_group_handle(&remapped_snapshot, &mapping)?,
        members: remapped_members,
        active_identity_scope: remapped_snapshot.active_identity_scope,
        active_persona_id: remapped_snapshot.active_persona_id,
        active_node_id: remapped_snapshot.active_node_id,
    })
}

fn load_persisted_gate_state(
    gate_state: &Mutex<GateCryptoRuntime>,
    gate_id: &str,
) -> Result<Option<ImportedGateState>, String> {
    let Some(cache_root) = cache_root(gate_state)? else {
        return Ok(None);
    };
    let normalized = normalize_gate_id(gate_id);
    let cache_path = gate_cache_path(&cache_root, gate_id);
    if !cache_path.exists() {
        return Ok(None);
    }
    let snapshot = match read_or_migrate_json_file::<GateStateSnapshot>(
        &cache_path,
        &format!("native_gate_state::{}", normalized),
    ) {
        Ok(Some(outcome)) => outcome.value,
        Ok(None) => return Ok(None),
        Err(_) => {
            let _ = fs::remove_file(&cache_path);
            return Ok(None);
        }
    };
    if normalize_gate_id(&snapshot.gate_id) != normalize_gate_id(gate_id) {
        let _ = fs::remove_file(&cache_path);
        return Ok(None);
    }
    match import_snapshot(snapshot) {
        Ok(imported) => {
            replace_cache_entry(gate_state, normalize_gate_id(gate_id), imported.clone())?;
            Ok(Some(imported))
        }
        Err(_) => {
            let _ = fs::remove_file(&cache_path);
            Ok(None)
        }
    }
}

fn persist_gate_state(gate_state: &Mutex<GateCryptoRuntime>, gate_id: &str) -> Result<(), String> {
    let Some(cache_root) = cache_root(gate_state)? else {
        return Ok(());
    };
    let imported = cache_entry(gate_state, gate_id)?
        .ok_or_else(|| format!("native_gate_state_missing:{gate_id}"))?;
    fs::create_dir_all(&cache_root).map_err(|e| format!("native_gate_cache_dir_failed:{e}"))?;
    let blob = privacy_core::export_gate_state(&imported.identity_handles, &imported.group_handles)
        .map_err(|e| format!("native_gate_state_export_failed:{e}"))?;
    let snapshot = GateStateSnapshot {
        gate_id: normalize_gate_id(gate_id),
        epoch: imported.epoch,
        rust_state_blob_b64: base64::engine::general_purpose::STANDARD.encode(blob),
        members: imported.members,
        active_identity_scope: imported.active_identity_scope,
        active_persona_id: imported.active_persona_id,
        active_node_id: imported.active_node_id,
    };
    write_protected_json_file(
        &gate_cache_path(&cache_root, gate_id),
        &format!("native_gate_state::{}", normalize_gate_id(gate_id)),
        &snapshot,
    )
    .map_err(|e| format!("native_gate_cache_write_failed:{e}"))?;
    Ok(())
}

fn import_and_cache_snapshot(
    gate_state: &Mutex<GateCryptoRuntime>,
    snapshot: GateStateSnapshot,
) -> Result<ImportedGateState, String> {
    let normalized = normalize_gate_id(&snapshot.gate_id);
    let current = cache_entry(gate_state, &normalized)?;
    let expected_change = has_expected_gate_change(gate_state, &normalized)?;
    if let Some(current) = current.as_ref() {
        validate_snapshot_transition(current, &snapshot, expected_change)?;
    }
    let imported = import_snapshot(snapshot)?;
    replace_cache_entry(gate_state, normalized.clone(), imported.clone())?;
    replace_status(
        gate_state,
        normalized.clone(),
        status_snapshot_from_imported(&imported),
    )?;
    if expected_change {
        let _ = clear_expected_gate_change(gate_state, &normalized);
    }
    let _ = persist_gate_state(gate_state, &normalized);
    Ok(imported)
}

async fn sync_gate_state(
    gate_state: &Mutex<GateCryptoRuntime>,
    backend_base_url: &str,
    admin_key: Option<&str>,
    gate_id: &str,
) -> Result<ImportedGateState, String> {
    let snapshot_value = call_backend_json(
        backend_base_url,
        admin_key,
        GATE_EXPORT_PATH,
        Method::POST,
        Some(json!({ "gate_id": gate_id })),
    )
    .await?;
    let snapshot: GateStateSnapshot = serde_json::from_value(snapshot_value)
        .map_err(|e| format!("native_gate_state_snapshot_invalid:{e}"))?;
    import_and_cache_snapshot(gate_state, snapshot)
}

pub fn forget_gate_state(
    gate_state: &Mutex<GateCryptoRuntime>,
    gate_id: &str,
) -> Result<(), String> {
    let cache_root = cache_root(gate_state)?;
    if let Some(previous) = drop_cache_entry(gate_state, gate_id)? {
        release_imported_state(previous);
    }
    if let Some(cache_root) = cache_root {
        let _ = fs::remove_file(gate_cache_path(&cache_root, gate_id));
    }
    Ok(())
}

pub fn adopt_gate_state_snapshot_from_result(
    gate_state: &Mutex<GateCryptoRuntime>,
    result: &Value,
) -> Result<String, String> {
    let snapshot_value = result
        .get("gate_state_snapshot")
        .cloned()
        .ok_or_else(|| "native_gate_state_snapshot_missing".to_string())?;
    let snapshot: GateStateSnapshot = serde_json::from_value(snapshot_value)
        .map_err(|e| format!("native_gate_state_snapshot_invalid:{e}"))?;
    let gate_id = normalize_gate_id(&snapshot.gate_id);
    if gate_id.is_empty() {
        return Err("native_gate_state_snapshot_missing_gate_id".to_string());
    }
    let _ = import_and_cache_snapshot(gate_state, snapshot)?;
    Ok(gate_id)
}

pub async fn resync_gate_state(
    gate_state: &Mutex<GateCryptoRuntime>,
    backend_base_url: &str,
    admin_key: Option<&str>,
    payload: Option<Value>,
) -> Result<Value, String> {
    let request: GateRequest = serde_json::from_value(payload.unwrap_or_else(|| json!({})))
        .map_err(|e| format!("native_gate_resync_payload_invalid:{e}"))?;
    let gate_id = normalize_gate_id(&request.gate_id);
    if gate_id.is_empty() {
        return Err("gate_id required".to_string());
    }
    let imported = sync_gate_state(gate_state, backend_base_url, admin_key, &gate_id).await?;
    Ok(json!({
        "ok": true,
        "gate_id": gate_id,
        "epoch": imported.epoch,
        "active_identity_scope": imported.active_identity_scope,
        "active_persona_id": imported.active_persona_id,
        "active_node_id": imported.active_node_id,
        "detail": "native gate state resynced",
    }))
}

async fn fetch_gate_status(
    gate_state: &Mutex<GateCryptoRuntime>,
    backend_base_url: &str,
    admin_key: Option<&str>,
    gate_id: &str,
) -> Result<GateStatusSnapshot, String> {
    let path = format!("/api/wormhole/gate/{}/key", urlencoding::encode(gate_id));
    let status_value =
        call_backend_json(backend_base_url, admin_key, &path, Method::GET, None).await?;
    let snapshot: GateStatusSnapshot = serde_json::from_value(status_value)
        .map_err(|e| format!("native_gate_status_invalid:{e}"))?;
    replace_status(gate_state, normalize_gate_id(gate_id), snapshot.clone())?;
    Ok(snapshot)
}

async fn ensure_gate_status(
    gate_state: &Mutex<GateCryptoRuntime>,
    backend_base_url: &str,
    admin_key: Option<&str>,
    gate_id: &str,
) -> Result<GateStatusSnapshot, String> {
    let normalized = normalize_gate_id(gate_id);
    if let Some(status) = cached_status(gate_state, &normalized)? {
        return Ok(status);
    }
    fetch_gate_status(gate_state, backend_base_url, admin_key, &normalized).await
}

fn decrypt_with_imported_state(
    imported: &ImportedGateState,
    request: &GateDecryptRequest,
) -> Result<Value, String> {
    let gate_id = normalize_gate_id(&request.gate_id);
    let fallback_epoch = request.epoch.unwrap_or(imported.epoch);
    let ciphertext = decode_gate_ciphertext(&request.ciphertext)?;
    for group_handle in &imported.group_handles {
        if let Ok(opened) = privacy_core::decrypt_group_message(*group_handle, &ciphertext) {
            let (plaintext, epoch, reply_to) = decode_plaintext(&opened, fallback_epoch)?;
            let mut result = json!({
                "ok": true,
                "gate_id": gate_id,
                "epoch": epoch,
                "plaintext": plaintext,
                "identity_scope": "native_privacy_core",
            });
            if !reply_to.is_empty() {
                result["reply_to"] = json!(reply_to);
            }
            return Ok(result);
        }
    }
    Err("gate_mls_decrypt_failed".to_string())
}

async fn ensure_gate_state(
    gate_state: &Mutex<GateCryptoRuntime>,
    backend_base_url: &str,
    admin_key: Option<&str>,
    gate_id: &str,
    requested_epoch: i64,
) -> Result<ImportedGateState, String> {
    let normalized = normalize_gate_id(gate_id);
    if let Some(existing) = cache_entry(gate_state, &normalized)? {
        let status =
            ensure_gate_status(gate_state, backend_base_url, admin_key, &normalized).await?;
        let expected_change = has_expected_gate_change(gate_state, &normalized)?;
        validate_status_transition(&existing, &status, expected_change)?;
        if existing.epoch >= requested_epoch && imported_matches_status(&existing, &status) {
            return Ok(existing);
        }
        return Err(resync_required_error(&normalized));
    }
    if let Some(persisted) = load_persisted_gate_state(gate_state, &normalized)? {
        let status =
            ensure_gate_status(gate_state, backend_base_url, admin_key, &normalized).await?;
        let expected_change = has_expected_gate_change(gate_state, &normalized)?;
        validate_status_transition(&persisted, &status, expected_change)?;
        if persisted.epoch >= requested_epoch && imported_matches_status(&persisted, &status) {
            return Ok(persisted);
        }
        return Err(resync_required_error(&normalized));
    }
    sync_gate_state(gate_state, backend_base_url, admin_key, &normalized).await
}

fn encrypt_with_imported_state(
    imported: &ImportedGateState,
    plaintext: &str,
    reply_to: &str,
) -> Result<String, String> {
    let encoded_plaintext = encode_gate_plaintext(plaintext, imported.epoch, reply_to)?;
    let ciphertext =
        privacy_core::encrypt_group_message(imported.active_group_handle, &encoded_plaintext)
            .map_err(|e| format!("native_gate_encrypt_failed:{e}"))?;
    Ok(encode_gate_ciphertext(&ciphertext))
}

async fn sign_native_gate_ciphertext(
    backend_base_url: &str,
    admin_key: Option<&str>,
    gate_id: &str,
    epoch: i64,
    ciphertext: &str,
    nonce: &str,
) -> Result<Value, String> {
    call_backend_json(
        backend_base_url,
        admin_key,
        GATE_SIGN_ENCRYPTED_PATH,
        Method::POST,
        Some(json!({
            "gate_id": gate_id,
            "epoch": epoch,
            "ciphertext": ciphertext,
            "nonce": nonce,
            "format": "mls1",
            "reply_to": "",
        })),
    )
    .await
}

async fn build_native_gate_message(
    gate_state: &Mutex<GateCryptoRuntime>,
    backend_base_url: &str,
    admin_key: Option<&str>,
    payload: Option<Value>,
) -> Result<Value, String> {
    let request: GateComposeRequest = serde_json::from_value(payload.unwrap_or_else(|| json!({})))
        .map_err(|e| format!("native_gate_compose_payload_invalid:{e}"))?;
    let gate_id = normalize_gate_id(&request.gate_id);
    let plaintext = request.plaintext.trim().to_string();
    let reply_to = request.reply_to.unwrap_or_default().trim().to_string();
    if gate_id.is_empty() || plaintext.is_empty() {
        return Err("gate_id and plaintext required".to_string());
    }

    for attempt in 0..2 {
        let imported =
            ensure_gate_state(gate_state, backend_base_url, admin_key, &gate_id, 0).await?;
        let ciphertext = match encrypt_with_imported_state(&imported, &plaintext, &reply_to) {
            Ok(ciphertext) => ciphertext,
            Err(err) => return Err(err),
        };
        let nonce = generate_gate_nonce()?;
        match sign_native_gate_ciphertext(
            backend_base_url,
            admin_key,
            &gate_id,
            imported.epoch,
            &ciphertext,
            &nonce,
        )
        .await
        {
            Ok(mut signed) => {
                if signed.get("epoch").is_none() {
                    signed["epoch"] = json!(imported.epoch);
                }
                return Ok(signed);
            }
            Err(err) if attempt == 0 && err.contains("gate_state_stale") => {
                let _ = invalidate_status(gate_state, &gate_id);
                return Err(resync_required_error(&gate_id));
            }
            Err(err) => return Err(err),
        }
    }

    Err("gate_state_stale".to_string())
}

pub async fn compose_gate_message(
    gate_state: &Mutex<GateCryptoRuntime>,
    backend_base_url: &str,
    admin_key: Option<&str>,
    payload: Option<Value>,
) -> Result<Value, String> {
    let signed =
        build_native_gate_message(gate_state, backend_base_url, admin_key, payload).await?;
    let gate_id = signed
        .get("gate_id")
        .and_then(Value::as_str)
        .map(normalize_gate_id)
        .filter(|gate_id| !gate_id.is_empty())
        .ok_or_else(|| "native_gate_signed_payload_missing_gate_id".to_string())?;
    let _ = persist_gate_state(gate_state, &gate_id);
    Ok(signed)
}

pub async fn post_gate_message(
    gate_state: &Mutex<GateCryptoRuntime>,
    backend_base_url: &str,
    admin_key: Option<&str>,
    payload: Option<Value>,
) -> Result<Value, String> {
    let signed =
        build_native_gate_message(gate_state, backend_base_url, admin_key, payload).await?;
    let gate_id = signed
        .get("gate_id")
        .and_then(Value::as_str)
        .map(normalize_gate_id)
        .filter(|gate_id| !gate_id.is_empty())
        .ok_or_else(|| "native_gate_signed_payload_missing_gate_id".to_string())?;
    let result = call_backend_json(
        backend_base_url,
        admin_key,
        GATE_POST_ENCRYPTED_PATH,
        Method::POST,
        Some(json!({
            "gate_id": signed.get("gate_id").and_then(Value::as_str).unwrap_or(""),
            "sender_id": signed.get("sender_id").and_then(Value::as_str).unwrap_or(""),
            "public_key": signed.get("public_key").and_then(Value::as_str).unwrap_or(""),
            "public_key_algo": signed.get("public_key_algo").and_then(Value::as_str).unwrap_or(""),
            "signature": signed.get("signature").and_then(Value::as_str).unwrap_or(""),
            "sequence": signed.get("sequence").and_then(Value::as_i64).unwrap_or(0),
            "protocol_version": signed.get("protocol_version").and_then(Value::as_str).unwrap_or(""),
            "epoch": signed.get("epoch").and_then(Value::as_i64).unwrap_or(0),
            "ciphertext": signed.get("ciphertext").and_then(Value::as_str).unwrap_or(""),
            "nonce": signed.get("nonce").and_then(Value::as_str).unwrap_or(""),
            "sender_ref": signed.get("sender_ref").and_then(Value::as_str).unwrap_or(""),
            "format": signed.get("format").and_then(Value::as_str).unwrap_or("mls1"),
            "reply_to": "",
            "envelope_hash": signed.get("envelope_hash").and_then(Value::as_str).unwrap_or(""),
        })),
    )
    .await?;
    let _ = persist_gate_state(gate_state, &gate_id);
    Ok(result)
}

pub async fn decrypt_gate_message(
    gate_state: &Mutex<GateCryptoRuntime>,
    backend_base_url: &str,
    admin_key: Option<&str>,
    payload: Option<Value>,
) -> Result<Value, String> {
    let request: GateDecryptRequest = serde_json::from_value(payload.unwrap_or_else(|| json!({})))
        .map_err(|e| format!("native_gate_decrypt_payload_invalid:{e}"))?;
    let gate_id = normalize_gate_id(&request.gate_id);
    if gate_id.is_empty() || request.ciphertext.trim().is_empty() {
        return Err("gate_id and ciphertext required".to_string());
    }
    let requested_epoch = request.epoch.unwrap_or(0);
    let imported = ensure_gate_state(
        gate_state,
        backend_base_url,
        admin_key,
        &gate_id,
        requested_epoch,
    )
    .await?;
    match decrypt_with_imported_state(&imported, &request) {
        Ok(result) => {
            let _ = persist_gate_state(gate_state, &gate_id);
            Ok(result)
        }
        Err(_err) if request.epoch.unwrap_or(0) > imported.epoch => {
            Err(resync_required_error(&gate_id))
        }
        Err(err) => Err(err),
    }
}

pub async fn decrypt_gate_messages(
    gate_state: &Mutex<GateCryptoRuntime>,
    backend_base_url: &str,
    admin_key: Option<&str>,
    payload: Option<Value>,
) -> Result<Value, String> {
    let request: GateDecryptBatchRequest =
        serde_json::from_value(payload.unwrap_or_else(|| json!({})))
            .map_err(|e| format!("native_gate_decrypt_batch_payload_invalid:{e}"))?;
    if request.messages.is_empty() {
        return Err("messages required".to_string());
    }
    if request.messages.len() > 100 {
        return Err("too many messages".to_string());
    }

    let mut gate_epochs: HashMap<String, i64> = HashMap::new();
    for message in &request.messages {
        let gate_id = normalize_gate_id(&message.gate_id);
        if gate_id.is_empty() || message.ciphertext.trim().is_empty() {
            return Err("gate_id and ciphertext required".to_string());
        }
        let epoch = message.epoch.unwrap_or(0);
        gate_epochs
            .entry(gate_id)
            .and_modify(|current| *current = (*current).max(epoch))
            .or_insert(epoch);
    }

    for (gate_id, epoch) in &gate_epochs {
        let _ = ensure_gate_state(gate_state, backend_base_url, admin_key, gate_id, *epoch).await?;
    }

    let mut results = Vec::with_capacity(request.messages.len());
    let mut gates_to_persist = HashSet::new();
    for message in &request.messages {
        let gate_id = normalize_gate_id(&message.gate_id);
        let initial = cache_entry(gate_state, &gate_id)?
            .ok_or_else(|| format!("native_gate_state_missing:{gate_id}"))?;
        match decrypt_with_imported_state(&initial, message) {
            Ok(result) => {
                gates_to_persist.insert(gate_id);
                results.push(result);
            }
            Err(detail) => {
                let detail = if message.epoch.unwrap_or(0) > initial.epoch {
                    resync_required_error(&gate_id)
                } else {
                    detail
                };
                results.push(json!({
                    "ok": false,
                    "gate_id": gate_id,
                    "epoch": message.epoch.unwrap_or(0),
                    "plaintext": "",
                    "detail": detail,
                }));
            }
        }
    }
    for gate_id in gates_to_persist {
        let _ = persist_gate_state(gate_state, &gate_id);
    }
    Ok(json!({ "ok": true, "results": results }))
}

#[cfg(test)]
mod tests {
    use super::{
        decode_plaintext, gate_cache_filename, imported_active_group_handle,
        imported_group_handles, imported_matches_status, pad_gate_ciphertext,
        unpad_gate_ciphertext, validate_snapshot_transition, validate_status_transition,
        GateStateImportMapping, GateStateMember, GateStateSnapshot, GateStatusSnapshot,
        ImportedGateState,
    };
    use std::collections::HashMap;

    #[test]
    fn unpad_gate_ciphertext_respects_length_prefix() {
        let padded = vec![0x00, 0x03, b'a', b'b', b'c', 0x00, 0x00];
        assert_eq!(unpad_gate_ciphertext(&padded), b"abc".to_vec());
    }

    #[test]
    fn decode_plaintext_reads_gate_envelope_shape() {
        let raw = br#"{"m":"hello","e":7,"r":"evt-parent-1"}"#;
        let (plaintext, epoch, reply_to) = decode_plaintext(raw, 0).expect("decode should succeed");
        assert_eq!(plaintext, "hello");
        assert_eq!(epoch, 7);
        assert_eq!(reply_to, "evt-parent-1");
    }

    #[test]
    fn imported_group_handles_follow_mapping() {
        let snapshot = GateStateSnapshot {
            gate_id: "ops".to_string(),
            epoch: 3,
            rust_state_blob_b64: "ZmFrZQ==".to_string(),
            members: vec![
                GateStateMember {
                    persona_id: "persona-a".to_string(),
                    node_id: "!sb_a".to_string(),
                    identity_scope: "persona".to_string(),
                    group_handle: 10,
                },
                GateStateMember {
                    persona_id: String::new(),
                    node_id: "!sb_b".to_string(),
                    identity_scope: "anonymous".to_string(),
                    group_handle: 11,
                },
            ],
            active_identity_scope: "persona".to_string(),
            active_persona_id: "persona-a".to_string(),
            active_node_id: "!sb_a".to_string(),
        };
        let mapping = GateStateImportMapping {
            identities: HashMap::new(),
            groups: HashMap::from([("10".to_string(), 110), ("11".to_string(), 111)]),
        };
        let handles = imported_group_handles(&snapshot, &mapping).expect("handles should map");
        assert_eq!(handles, vec![110, 111]);
    }

    #[test]
    fn imported_active_group_handle_follows_active_member_identity() {
        let snapshot = GateStateSnapshot {
            gate_id: "ops".to_string(),
            epoch: 3,
            rust_state_blob_b64: "ZmFrZQ==".to_string(),
            members: vec![
                GateStateMember {
                    persona_id: "persona-a".to_string(),
                    node_id: "!sb_a".to_string(),
                    identity_scope: "persona".to_string(),
                    group_handle: 10,
                },
                GateStateMember {
                    persona_id: String::new(),
                    node_id: "!sb_b".to_string(),
                    identity_scope: "anonymous".to_string(),
                    group_handle: 11,
                },
            ],
            active_identity_scope: "anonymous".to_string(),
            active_persona_id: String::new(),
            active_node_id: "!sb_b".to_string(),
        };
        let mapping = GateStateImportMapping {
            identities: HashMap::new(),
            groups: HashMap::from([("10".to_string(), 110), ("11".to_string(), 111)]),
        };
        let handle =
            imported_active_group_handle(&snapshot, &mapping).expect("active handle should map");
        assert_eq!(handle, 111);
    }

    #[test]
    fn pad_gate_ciphertext_adds_length_prefix_and_bucket_padding() {
        let padded = pad_gate_ciphertext(b"hello");
        assert_eq!(&padded[..2], &(5u16).to_be_bytes());
        assert_eq!(&padded[2..7], b"hello");
        assert_eq!(padded.len(), 192);
    }

    #[test]
    fn gate_cache_filename_is_stable_and_safe() {
        assert_eq!(
            gate_cache_filename("Ops/Main"),
            "gate-6f70732f6d61696e.json"
        );
    }

    #[test]
    fn imported_matches_status_requires_same_epoch_and_active_persona() {
        let imported = ImportedGateState {
            epoch: 4,
            state_fingerprint: "opaque-a".to_string(),
            group_handles: vec![10],
            identity_handles: vec![20],
            active_group_handle: 10,
            members: vec![],
            active_identity_scope: "persona".to_string(),
            active_persona_id: "persona-a".to_string(),
            active_node_id: "!sb_a".to_string(),
        };
        let good = GateStatusSnapshot {
            current_epoch: 4,
            has_local_access: true,
            identity_scope: "persona".to_string(),
            identity_node_id: "!sb_a".to_string(),
            identity_persona_id: "persona-a".to_string(),
        };
        let bad = GateStatusSnapshot {
            identity_persona_id: "persona-b".to_string(),
            ..good.clone()
        };
        assert!(imported_matches_status(&imported, &good));
        assert!(!imported_matches_status(&imported, &bad));
    }

    fn sample_imported_gate_state() -> ImportedGateState {
        ImportedGateState {
            epoch: 4,
            state_fingerprint: "opaque-a".to_string(),
            group_handles: vec![10],
            identity_handles: vec![20],
            active_group_handle: 10,
            members: vec![],
            active_identity_scope: "persona".to_string(),
            active_persona_id: "persona-a".to_string(),
            active_node_id: "!sb_a".to_string(),
        }
    }

    #[test]
    fn validate_status_transition_rejects_unexpected_identity_change() {
        let imported = sample_imported_gate_state();
        let changed_status = GateStatusSnapshot {
            current_epoch: 5,
            has_local_access: true,
            identity_scope: "persona".to_string(),
            identity_node_id: "!sb_b".to_string(),
            identity_persona_id: "persona-b".to_string(),
        };
        assert_eq!(
            validate_status_transition(&imported, &changed_status, false).unwrap_err(),
            "gate_identity_unexpected_change"
        );
        assert!(validate_status_transition(&imported, &changed_status, true).is_ok());
    }

    #[test]
    fn validate_status_transition_rejects_unexpected_access_loss() {
        let imported = sample_imported_gate_state();
        let revoked_status = GateStatusSnapshot {
            current_epoch: 4,
            has_local_access: false,
            identity_scope: "persona".to_string(),
            identity_node_id: "!sb_a".to_string(),
            identity_persona_id: "persona-a".to_string(),
        };
        assert_eq!(
            validate_status_transition(&imported, &revoked_status, false).unwrap_err(),
            "gate_access_unexpected_change"
        );
        assert!(validate_status_transition(&imported, &revoked_status, true).is_ok());
    }

    #[test]
    fn validate_snapshot_transition_rejects_same_epoch_rewrite() {
        let imported = sample_imported_gate_state();
        let rewritten = GateStateSnapshot {
            gate_id: "ops".to_string(),
            epoch: 4,
            rust_state_blob_b64: "opaque-b".to_string(),
            members: vec![GateStateMember {
                persona_id: "persona-a".to_string(),
                node_id: "!sb_a".to_string(),
                identity_scope: "persona".to_string(),
                group_handle: 10,
            }],
            active_identity_scope: "persona".to_string(),
            active_persona_id: "persona-a".to_string(),
            active_node_id: "!sb_a".to_string(),
        };
        assert_eq!(
            validate_snapshot_transition(&imported, &rewritten, false).unwrap_err(),
            "gate_state_unexpected_rewrite"
        );
    }

    #[test]
    fn validate_snapshot_transition_rejects_regression() {
        let imported = sample_imported_gate_state();
        let regressed = GateStateSnapshot {
            gate_id: "ops".to_string(),
            epoch: 3,
            rust_state_blob_b64: "opaque-a".to_string(),
            members: vec![GateStateMember {
                persona_id: "persona-a".to_string(),
                node_id: "!sb_a".to_string(),
                identity_scope: "persona".to_string(),
                group_handle: 10,
            }],
            active_identity_scope: "persona".to_string(),
            active_persona_id: "persona-a".to_string(),
            active_node_id: "!sb_a".to_string(),
        };
        assert_eq!(
            validate_snapshot_transition(&imported, &regressed, true).unwrap_err(),
            "gate_state_regression_detected"
        );
    }
}
