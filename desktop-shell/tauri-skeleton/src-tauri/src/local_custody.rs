use std::ffi::c_void;
use std::fs;
use std::io::Write;
use std::path::Path;
use std::sync::{Mutex, OnceLock};

use base64::Engine as _;
use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};

const ENVELOPE_KIND: &str = "sb_local_custody";
const ENVELOPE_VERSION: u8 = 1;

#[derive(Clone, Debug, Serialize)]
pub struct LocalCustodyStatus {
    pub code: String,
    pub label: String,
    pub provider: String,
    pub detail: String,
    pub protected_at_rest: bool,
    pub last_error: String,
}

#[derive(Clone, Debug)]
pub struct LoadOutcome<T> {
    pub value: T,
    pub migrated: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct LocalCustodyEnvelope {
    kind: String,
    version: u8,
    scope: String,
    provider: String,
    protected_at_rest: bool,
    #[serde(default)]
    protected_payload: String,
    #[serde(default)]
    payload_b64: String,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum ProviderMode {
    Dpapi,
    Raw,
    #[cfg(test)]
    TestProtected,
    #[cfg(test)]
    TestProtectedAlt,
    #[cfg(test)]
    TestFailWrap,
}

fn status_labels(code: &str) -> &'static str {
    match code {
        "protected_at_rest" => "Protected at rest",
        "degraded_local_custody" => "Degraded local custody",
        "migration_in_progress" => "Migration in progress",
        "migration_failed" => "Migration failed",
        _ => "Degraded local custody",
    }
}

fn default_status() -> LocalCustodyStatus {
    LocalCustodyStatus {
        code: "degraded_local_custody".to_string(),
        label: status_labels("degraded_local_custody").to_string(),
        provider: "unknown".to_string(),
        detail: "Native local custody has not been initialized yet.".to_string(),
        protected_at_rest: false,
        last_error: String::new(),
    }
}

fn status_cell() -> &'static Mutex<LocalCustodyStatus> {
    static STATUS: OnceLock<Mutex<LocalCustodyStatus>> = OnceLock::new();
    STATUS.get_or_init(|| Mutex::new(default_status()))
}

fn set_status(status: LocalCustodyStatus) {
    if let Ok(mut guard) = status_cell().lock() {
        *guard = status;
    }
}

fn provider_status(mode: ProviderMode, detail: &str) -> LocalCustodyStatus {
    let (code, provider, protected_at_rest) = match mode {
        ProviderMode::Dpapi => ("protected_at_rest", "dpapi-machine", true),
        ProviderMode::Raw => ("degraded_local_custody", "raw", false),
        #[cfg(test)]
        ProviderMode::TestProtected => ("protected_at_rest", "test-protected", true),
        #[cfg(test)]
        ProviderMode::TestProtectedAlt => ("protected_at_rest", "test-protected-alt", true),
        #[cfg(test)]
        ProviderMode::TestFailWrap => ("protected_at_rest", "test-protected", true),
    };
    LocalCustodyStatus {
        code: code.to_string(),
        label: status_labels(code).to_string(),
        provider: provider.to_string(),
        detail: detail.to_string(),
        protected_at_rest,
        last_error: String::new(),
    }
}

fn set_migration_status(code: &str, detail: &str, last_error: &str) {
    let (provider, protected_at_rest) = if let Ok(guard) = status_cell().lock() {
        (guard.provider.clone(), guard.protected_at_rest)
    } else {
        ("unknown".to_string(), false)
    };
    set_status(LocalCustodyStatus {
        code: code.to_string(),
        label: status_labels(code).to_string(),
        provider,
        detail: detail.to_string(),
        protected_at_rest,
        last_error: last_error.to_string(),
    });
}

pub fn local_custody_status() -> LocalCustodyStatus {
    status_cell()
        .lock()
        .map(|guard| guard.clone())
        .unwrap_or_else(|_| default_status())
}

fn normalized_scope(scope: &str) -> String {
    scope.trim().to_ascii_lowercase()
}

fn is_custody_envelope(value: &serde_json::Value) -> bool {
    value
        .get("kind")
        .and_then(serde_json::Value::as_str)
        .map(|kind| kind == ENVELOPE_KIND)
        .unwrap_or(false)
        && value
            .get("version")
            .and_then(serde_json::Value::as_u64)
            .map(|version| version == ENVELOPE_VERSION as u64)
            .unwrap_or(false)
}

fn active_provider() -> ProviderMode {
    #[cfg(test)]
    if let Some(mode) = test_provider() {
        return mode;
    }
    if cfg!(target_os = "windows") {
        ProviderMode::Dpapi
    } else {
        ProviderMode::Raw
    }
}

fn provider_for_name(provider: &str) -> Result<ProviderMode, String> {
    match provider.trim().to_ascii_lowercase().as_str() {
        "dpapi-machine" => Ok(ProviderMode::Dpapi),
        "raw" => Ok(ProviderMode::Raw),
        #[cfg(test)]
        "test-protected" => Ok(ProviderMode::TestProtected),
        #[cfg(test)]
        "test-protected-alt" => Ok(ProviderMode::TestProtectedAlt),
        #[cfg(test)]
        "test-fail-wrap" => Ok(ProviderMode::TestFailWrap),
        other if other.is_empty() => Err("local_custody_provider_missing".to_string()),
        other => Err(format!("local_custody_provider_unsupported:{other}")),
    }
}

fn wrap_bytes(scope: &str, plaintext: &[u8]) -> Result<LocalCustodyEnvelope, String> {
    let scope = normalized_scope(scope);
    let provider = active_provider();
    let envelope = match provider {
        ProviderMode::Dpapi => LocalCustodyEnvelope {
            kind: ENVELOPE_KIND.to_string(),
            version: ENVELOPE_VERSION,
            scope,
            provider: "dpapi-machine".to_string(),
            protected_at_rest: true,
            protected_payload: base64::engine::general_purpose::STANDARD
                .encode(dpapi_protect(plaintext)?),
            payload_b64: String::new(),
        },
        ProviderMode::Raw => LocalCustodyEnvelope {
            kind: ENVELOPE_KIND.to_string(),
            version: ENVELOPE_VERSION,
            scope,
            provider: "raw".to_string(),
            protected_at_rest: false,
            protected_payload: String::new(),
            payload_b64: base64::engine::general_purpose::STANDARD.encode(plaintext),
        },
        #[cfg(test)]
        ProviderMode::TestProtected => LocalCustodyEnvelope {
            kind: ENVELOPE_KIND.to_string(),
            version: ENVELOPE_VERSION,
            scope,
            provider: "test-protected".to_string(),
            protected_at_rest: true,
            protected_payload: base64::engine::general_purpose::STANDARD
                .encode(test_protect(plaintext)),
            payload_b64: String::new(),
        },
        #[cfg(test)]
        ProviderMode::TestProtectedAlt => LocalCustodyEnvelope {
            kind: ENVELOPE_KIND.to_string(),
            version: ENVELOPE_VERSION,
            scope,
            provider: "test-protected-alt".to_string(),
            protected_at_rest: true,
            protected_payload: base64::engine::general_purpose::STANDARD
                .encode(test_protect_alt(plaintext)),
            payload_b64: String::new(),
        },
        #[cfg(test)]
        ProviderMode::TestFailWrap => return Err(format!("test_wrap_failed:{scope}")),
    };
    set_status(provider_status(
        provider,
        if envelope.protected_at_rest {
            "Native gate state is wrapped before persistence."
        } else {
            "Native gate state is preserved, but the local custody provider is degraded."
        },
    ));
    Ok(envelope)
}

fn unwrap_bytes(scope: &str, envelope: &LocalCustodyEnvelope) -> Result<Vec<u8>, String> {
    let scope = normalized_scope(scope);
    if !envelope.scope.is_empty() && normalized_scope(&envelope.scope) != scope {
        return Err(format!(
            "local_custody_scope_mismatch:{}:{}",
            envelope.scope, scope
        ));
    }
    match provider_for_name(&envelope.provider)? {
        ProviderMode::Dpapi => {
            let protected = base64::engine::general_purpose::STANDARD
                .decode(envelope.protected_payload.trim())
                .map_err(|e| format!("local_custody_payload_b64_invalid:{e}"))?;
            dpapi_unprotect(&protected)
        }
        ProviderMode::Raw => base64::engine::general_purpose::STANDARD
            .decode(envelope.payload_b64.trim())
            .map_err(|e| format!("local_custody_payload_b64_invalid:{e}")),
        #[cfg(test)]
        ProviderMode::TestProtected => {
            let protected = base64::engine::general_purpose::STANDARD
                .decode(envelope.protected_payload.trim())
                .map_err(|e| format!("local_custody_payload_b64_invalid:{e}"))?;
            Ok(test_unprotect(&protected))
        }
        #[cfg(test)]
        ProviderMode::TestProtectedAlt => {
            let protected = base64::engine::general_purpose::STANDARD
                .decode(envelope.protected_payload.trim())
                .map_err(|e| format!("local_custody_payload_b64_invalid:{e}"))?;
            Ok(test_unprotect_alt(&protected))
        }
        #[cfg(test)]
        ProviderMode::TestFailWrap => Err("test_wrap_provider_cannot_unwrap".to_string()),
    }
}

fn atomic_write_bytes(target: &Path, bytes: &[u8]) -> Result<(), String> {
    let parent = target
        .parent()
        .ok_or_else(|| "native_local_custody_parent_missing".to_string())?;
    fs::create_dir_all(parent).map_err(|e| format!("native_local_custody_dir_failed:{e}"))?;
    let tmp_path = target.with_extension("tmp");
    {
        let mut file = fs::File::create(&tmp_path)
            .map_err(|e| format!("native_local_custody_tmp_create_failed:{e}"))?;
        file.write_all(bytes)
            .map_err(|e| format!("native_local_custody_tmp_write_failed:{e}"))?;
        file.flush()
            .map_err(|e| format!("native_local_custody_tmp_flush_failed:{e}"))?;
    }
    fs::rename(&tmp_path, target).map_err(|e| format!("native_local_custody_rename_failed:{e}"))
}

pub fn write_protected_json_file<T: Serialize>(
    path: &Path,
    scope: &str,
    value: &T,
) -> Result<(), String> {
    let plaintext = serde_json::to_vec(value)
        .map_err(|e| format!("native_local_custody_serialize_failed:{e}"))?;
    let envelope = wrap_bytes(scope, &plaintext)?;
    let encoded = serde_json::to_vec(&envelope)
        .map_err(|e| format!("native_local_custody_envelope_serialize_failed:{e}"))?;
    atomic_write_bytes(path, &encoded)
}

pub fn read_or_migrate_json_file<T: Serialize + DeserializeOwned>(
    path: &Path,
    scope: &str,
) -> Result<Option<LoadOutcome<T>>, String> {
    if !path.exists() {
        return Ok(None);
    }
    let bytes = fs::read(path).map_err(|e| format!("native_local_custody_read_failed:{e}"))?;
    let raw_value: serde_json::Value = serde_json::from_slice(&bytes)
        .map_err(|e| format!("native_local_custody_json_invalid:{e}"))?;
    if is_custody_envelope(&raw_value) {
        let envelope: LocalCustodyEnvelope = serde_json::from_value(raw_value)
            .map_err(|e| format!("native_local_custody_envelope_invalid:{e}"))?;
        let provider = provider_for_name(&envelope.provider)?;
        let plaintext = unwrap_bytes(scope, &envelope)?;
        let value = serde_json::from_slice(&plaintext)
            .map_err(|e| format!("native_local_custody_decode_failed:{e}"))?;
        set_status(provider_status(
            provider,
            if envelope.protected_at_rest {
                "Native gate state is wrapped before persistence."
            } else {
                "Native gate state is preserved, but the local custody provider is degraded."
            },
        ));
        return Ok(Some(LoadOutcome {
            value,
            migrated: false,
        }));
    }

    let legacy_bytes = bytes;
    let legacy_value: T = serde_json::from_slice(&legacy_bytes)
        .map_err(|e| format!("native_local_custody_legacy_decode_failed:{e}"))?;
    set_migration_status(
        "migration_in_progress",
        "Native gate state is being migrated to wrapped local custody.",
        "",
    );
    match write_protected_json_file(path, scope, &legacy_value) {
        Ok(()) => match read_or_migrate_json_file(path, scope)? {
            Some(LoadOutcome { value, .. }) => Ok(Some(LoadOutcome {
                value,
                migrated: true,
            })),
            None => Err("native_local_custody_migration_missing".to_string()),
        },
        Err(err) => {
            let _ = atomic_write_bytes(path, &legacy_bytes);
            set_migration_status(
                "migration_failed",
                "Native gate state could not be migrated and remains in the legacy readable form.",
                &err,
            );
            Ok(Some(LoadOutcome {
                value: legacy_value,
                migrated: false,
            }))
        }
    }
}

#[cfg(target_os = "windows")]
#[repr(C)]
struct DataBlob {
    cb_data: u32,
    pb_data: *mut u8,
}

#[cfg(target_os = "windows")]
#[link(name = "Crypt32")]
extern "system" {
    fn CryptProtectData(
        p_data_in: *const DataBlob,
        sz_data_descr: *const u16,
        p_optional_entropy: *const DataBlob,
        pv_reserved: *mut c_void,
        p_prompt_struct: *mut c_void,
        dw_flags: u32,
        p_data_out: *mut DataBlob,
    ) -> i32;
    fn CryptUnprotectData(
        p_data_in: *const DataBlob,
        ppsz_data_descr: *mut *mut u16,
        p_optional_entropy: *const DataBlob,
        pv_reserved: *mut c_void,
        p_prompt_struct: *mut c_void,
        dw_flags: u32,
        p_data_out: *mut DataBlob,
    ) -> i32;
}

#[cfg(target_os = "windows")]
#[link(name = "Kernel32")]
extern "system" {
    fn LocalFree(mem: *mut c_void) -> *mut c_void;
}

#[cfg(target_os = "windows")]
fn dpapi_protect(bytes: &[u8]) -> Result<Vec<u8>, String> {
    const CRYPTPROTECT_UI_FORBIDDEN: u32 = 0x1;
    const CRYPTPROTECT_LOCAL_MACHINE: u32 = 0x4;
    let mut input = bytes.to_vec();
    let in_blob = DataBlob {
        cb_data: input.len() as u32,
        pb_data: input.as_mut_ptr(),
    };
    let mut out_blob = DataBlob {
        cb_data: 0,
        pb_data: std::ptr::null_mut(),
    };
    let ok = unsafe {
        CryptProtectData(
            &in_blob,
            std::ptr::null(),
            std::ptr::null(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            CRYPTPROTECT_UI_FORBIDDEN | CRYPTPROTECT_LOCAL_MACHINE,
            &mut out_blob,
        )
    };
    if ok == 0 {
        return Err("native_local_custody_dpapi_protect_failed".to_string());
    }
    let out =
        unsafe { std::slice::from_raw_parts(out_blob.pb_data, out_blob.cb_data as usize).to_vec() };
    unsafe {
        LocalFree(out_blob.pb_data as *mut c_void);
    }
    Ok(out)
}

#[cfg(target_os = "windows")]
fn dpapi_unprotect(bytes: &[u8]) -> Result<Vec<u8>, String> {
    const CRYPTPROTECT_UI_FORBIDDEN: u32 = 0x1;
    let mut input = bytes.to_vec();
    let in_blob = DataBlob {
        cb_data: input.len() as u32,
        pb_data: input.as_mut_ptr(),
    };
    let mut out_blob = DataBlob {
        cb_data: 0,
        pb_data: std::ptr::null_mut(),
    };
    let ok = unsafe {
        CryptUnprotectData(
            &in_blob,
            std::ptr::null_mut(),
            std::ptr::null(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            CRYPTPROTECT_UI_FORBIDDEN,
            &mut out_blob,
        )
    };
    if ok == 0 {
        return Err("native_local_custody_dpapi_unprotect_failed".to_string());
    }
    let out =
        unsafe { std::slice::from_raw_parts(out_blob.pb_data, out_blob.cb_data as usize).to_vec() };
    unsafe {
        LocalFree(out_blob.pb_data as *mut c_void);
    }
    Ok(out)
}

#[cfg(not(target_os = "windows"))]
fn dpapi_protect(_bytes: &[u8]) -> Result<Vec<u8>, String> {
    Err("native_local_custody_dpapi_unavailable".to_string())
}

#[cfg(not(target_os = "windows"))]
fn dpapi_unprotect(_bytes: &[u8]) -> Result<Vec<u8>, String> {
    Err("native_local_custody_dpapi_unavailable".to_string())
}

#[cfg(test)]
fn test_provider_cell() -> &'static Mutex<Option<ProviderMode>> {
    static TEST_PROVIDER: OnceLock<Mutex<Option<ProviderMode>>> = OnceLock::new();
    TEST_PROVIDER.get_or_init(|| Mutex::new(None))
}

#[cfg(test)]
fn test_provider() -> Option<ProviderMode> {
    test_provider_cell().lock().ok().and_then(|guard| *guard)
}

#[cfg(test)]
pub(crate) fn set_test_provider_for_tests(provider: Option<ProviderMode>) {
    if let Ok(mut guard) = test_provider_cell().lock() {
        *guard = provider;
    }
    reset_local_custody_for_tests();
}

#[cfg(test)]
pub(crate) fn reset_local_custody_for_tests() {
    set_status(default_status());
}

#[cfg(test)]
fn test_protect(bytes: &[u8]) -> Vec<u8> {
    bytes.iter().rev().map(|byte| byte ^ 0x5a).collect()
}

#[cfg(test)]
fn test_unprotect(bytes: &[u8]) -> Vec<u8> {
    bytes.iter().rev().map(|byte| byte ^ 0x5a).collect()
}

#[cfg(test)]
fn test_protect_alt(bytes: &[u8]) -> Vec<u8> {
    bytes.iter().rev().map(|byte| byte ^ 0x33).collect()
}

#[cfg(test)]
fn test_unprotect_alt(bytes: &[u8]) -> Vec<u8> {
    bytes.iter().rev().map(|byte| byte ^ 0x33).collect()
}

#[cfg(test)]
mod tests {
    use super::{
        local_custody_status, read_or_migrate_json_file, reset_local_custody_for_tests,
        set_test_provider_for_tests, write_protected_json_file, ProviderMode,
    };
    use serde_json::json;
    use std::fs;
    use std::sync::{Mutex, OnceLock};

    fn test_lock() -> &'static Mutex<()> {
        static TEST_LOCK: OnceLock<Mutex<()>> = OnceLock::new();
        TEST_LOCK.get_or_init(|| Mutex::new(()))
    }

    fn tmp_file(name: &str) -> std::path::PathBuf {
        let root = std::env::temp_dir().join(format!("shadowbroker-local-custody-{name}"));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).unwrap();
        root.join("state.json")
    }

    #[test]
    fn protected_native_state_is_not_persisted_as_plaintext() {
        let _guard = test_lock().lock().unwrap();
        reset_local_custody_for_tests();
        set_test_provider_for_tests(Some(ProviderMode::TestProtected));
        let path = tmp_file("protected");

        write_protected_json_file(&path, "gate::ops", &json!({"rust_state_blob_b64":"opaque"}))
            .unwrap();
        let raw = fs::read_to_string(&path).unwrap();

        assert!(!raw.contains("opaque"));
        assert!(raw.contains("sb_local_custody"));
        assert_eq!(local_custody_status().code, "protected_at_rest");
        set_test_provider_for_tests(None);
    }

    #[test]
    fn legacy_native_state_auto_migrates() {
        let _guard = test_lock().lock().unwrap();
        reset_local_custody_for_tests();
        set_test_provider_for_tests(Some(ProviderMode::TestProtected));
        let path = tmp_file("migrate");
        fs::write(
            &path,
            serde_json::to_vec(&json!({"gate_id":"ops","epoch":7})).unwrap(),
        )
        .unwrap();

        let loaded = read_or_migrate_json_file::<serde_json::Value>(&path, "gate::ops")
            .unwrap()
            .unwrap();
        let raw = fs::read_to_string(&path).unwrap();

        assert_eq!(loaded.value["gate_id"], "ops");
        assert!(loaded.migrated);
        assert!(raw.contains("sb_local_custody"));
        set_test_provider_for_tests(None);
    }

    #[test]
    fn failed_native_migration_preserves_legacy_readable_state() {
        let _guard = test_lock().lock().unwrap();
        reset_local_custody_for_tests();
        set_test_provider_for_tests(Some(ProviderMode::TestFailWrap));
        let path = tmp_file("fail-migrate");
        let legacy = serde_json::to_vec(&json!({"gate_id":"ops","epoch":7})).unwrap();
        fs::write(&path, &legacy).unwrap();

        let loaded = read_or_migrate_json_file::<serde_json::Value>(&path, "gate::ops")
            .unwrap()
            .unwrap();
        let raw = fs::read(&path).unwrap();

        assert_eq!(loaded.value["gate_id"], "ops");
        assert_eq!(raw, legacy);
        assert_eq!(local_custody_status().code, "migration_failed");
        set_test_provider_for_tests(None);
    }

    #[test]
    fn degraded_status_is_exposed_when_only_raw_provider_is_available() {
        let _guard = test_lock().lock().unwrap();
        reset_local_custody_for_tests();
        set_test_provider_for_tests(Some(ProviderMode::Raw));
        let path = tmp_file("raw");

        write_protected_json_file(&path, "gate::ops", &json!({"gate_id":"ops"})).unwrap();

        assert_eq!(local_custody_status().code, "degraded_local_custody");
        set_test_provider_for_tests(None);
    }

    #[test]
    fn provider_aware_read_handles_raw_to_protected_transition() {
        let _guard = test_lock().lock().unwrap();
        reset_local_custody_for_tests();
        let path = tmp_file("raw-to-protected");
        set_test_provider_for_tests(Some(ProviderMode::Raw));
        write_protected_json_file(&path, "gate::ops", &json!({"gate_id":"ops","epoch":7})).unwrap();

        set_test_provider_for_tests(Some(ProviderMode::TestProtected));
        let loaded = read_or_migrate_json_file::<serde_json::Value>(&path, "gate::ops")
            .unwrap()
            .unwrap();

        assert_eq!(loaded.value["gate_id"], "ops");
        assert_eq!(local_custody_status().provider, "raw");
        assert_eq!(local_custody_status().code, "degraded_local_custody");
        set_test_provider_for_tests(None);
    }

    #[test]
    fn provider_aware_read_handles_protected_to_other_provider_transition() {
        let _guard = test_lock().lock().unwrap();
        reset_local_custody_for_tests();
        let path = tmp_file("protected-transition");
        set_test_provider_for_tests(Some(ProviderMode::TestProtected));
        write_protected_json_file(&path, "gate::ops", &json!({"gate_id":"ops","epoch":9})).unwrap();

        set_test_provider_for_tests(Some(ProviderMode::TestProtectedAlt));
        let loaded = read_or_migrate_json_file::<serde_json::Value>(&path, "gate::ops")
            .unwrap()
            .unwrap();

        assert_eq!(loaded.value["epoch"], 9);
        assert_eq!(local_custody_status().provider, "test-protected");
        assert_eq!(local_custody_status().code, "protected_at_rest");
        set_test_provider_for_tests(None);
    }
}
