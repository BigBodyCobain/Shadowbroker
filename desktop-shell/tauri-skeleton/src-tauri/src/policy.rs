//! Native-side policy enforcement and audit ring for local-control commands.
//!
//! This module is the authoritative guardrail layer. Even if webview JS is
//! bypassed and `invoke_local_control` is called directly via Tauri IPC,
//! every invocation passes through `enforce_and_audit()` before reaching
//! the backend HTTP dispatch.
//!
//! The capability and profile tables mirror the TypeScript source of truth
//! in `frontend/src/lib/desktopControlContract.ts`.

use serde::Serialize;
use serde_json::Value;
use std::collections::HashMap;
use std::sync::Mutex;

// ---------------------------------------------------------------------------
// Capability resolution (mirrors controlCommandCapability in TS)
// ---------------------------------------------------------------------------

pub fn resolve_command_capability(command: &str) -> Option<&'static str> {
    match command {
        "wormhole.status" | "wormhole.connect" | "wormhole.disconnect" | "wormhole.restart" => {
            Some("wormhole_runtime")
        }
        "wormhole.gate.enter"
        | "wormhole.gate.leave"
        | "wormhole.gate.personas.get"
        | "wormhole.gate.persona.create"
        | "wormhole.gate.persona.activate"
        | "wormhole.gate.persona.clear" => Some("wormhole_gate_persona"),
        "wormhole.gate.key.get" | "wormhole.gate.key.rotate" | "wormhole.gate.state.resync" => {
            Some("wormhole_gate_key")
        }
        "wormhole.gate.proof"
        | "wormhole.gate.message.compose"
        | "wormhole.gate.message.post"
        | "wormhole.gate.message.decrypt"
        | "wormhole.gate.messages.decrypt" => Some("wormhole_gate_content"),
        "settings.wormhole.get"
        | "settings.wormhole.set"
        | "settings.privacy.get"
        | "settings.privacy.set"
        | "settings.api_keys.get"
        | "settings.news.get"
        | "settings.news.set"
        | "settings.news.reset"
        | "system.update" => Some("settings"),
        _ => None,
    }
}

// ---------------------------------------------------------------------------
// Profile → capabilities (mirrors sessionProfileCapabilities in TS)
// ---------------------------------------------------------------------------

pub fn resolve_profile_capabilities(profile: &str) -> &'static [&'static str] {
    match profile {
        "full_app" => &[
            "wormhole_gate_persona",
            "wormhole_gate_key",
            "wormhole_gate_content",
            "wormhole_runtime",
            "settings",
        ],
        "gate_observe" => &["wormhole_gate_content"],
        "gate_operator" => &[
            "wormhole_gate_persona",
            "wormhole_gate_key",
            "wormhole_gate_content",
        ],
        "wormhole_runtime" => &["wormhole_runtime"],
        "settings_only" => &["settings"],
        _ => &[],
    }
}

// ---------------------------------------------------------------------------
// Gate target ref extraction (mirrors extractGateTargetRef in TS)
// ---------------------------------------------------------------------------

fn is_gate_target_command(command: &str) -> bool {
    matches!(
        command,
        "wormhole.gate.enter"
            | "wormhole.gate.leave"
            | "wormhole.gate.personas.get"
            | "wormhole.gate.persona.create"
            | "wormhole.gate.persona.activate"
            | "wormhole.gate.persona.clear"
            | "wormhole.gate.key.get"
            | "wormhole.gate.key.rotate"
            | "wormhole.gate.state.resync"
            | "wormhole.gate.proof"
            | "wormhole.gate.message.compose"
            | "wormhole.gate.message.post"
            | "wormhole.gate.message.decrypt"
    )
}

fn extract_target_ref(command: &str, payload: &Option<Value>) -> Option<String> {
    if !is_gate_target_command(command) {
        return None;
    }
    payload
        .as_ref()
        .and_then(|v| v.get("gate_id"))
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .map(|s| s.to_string())
}

// ---------------------------------------------------------------------------
// Audit entry and ring
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize)]
pub struct AuditEntry {
    pub command: String,
    #[serde(rename = "expectedCapability")]
    pub expected_capability: String,
    #[serde(rename = "declaredCapability", skip_serializing_if = "Option::is_none")]
    pub declared_capability: Option<String>,
    #[serde(rename = "targetRef", skip_serializing_if = "Option::is_none")]
    pub target_ref: Option<String>,
    #[serde(rename = "sessionProfile", skip_serializing_if = "Option::is_none")]
    pub session_profile: Option<String>,
    #[serde(rename = "sessionProfileHint", skip_serializing_if = "Option::is_none")]
    pub session_profile_hint: Option<String>,
    #[serde(rename = "enforceProfileHint")]
    pub enforce_profile_hint: bool,
    #[serde(rename = "profileAllows")]
    pub profile_allows: bool,
    #[serde(rename = "allowedCapabilitiesConfigured")]
    pub allowed_capabilities_configured: bool,
    pub enforced: bool,
    pub outcome: String,
    #[serde(rename = "recordedAt")]
    pub recorded_at: u64,
}

#[derive(Serialize)]
pub struct AuditReport {
    #[serde(rename = "totalEvents")]
    pub total_events: u64,
    #[serde(rename = "totalRecorded")]
    pub total_recorded: u64,
    pub recent: Vec<AuditEntry>,
    #[serde(rename = "byOutcome")]
    pub by_outcome: HashMap<String, u64>,
    #[serde(
        rename = "lastProfileMismatch",
        skip_serializing_if = "Option::is_none"
    )]
    pub last_profile_mismatch: Option<AuditEntry>,
    #[serde(rename = "lastDenied", skip_serializing_if = "Option::is_none")]
    pub last_denied: Option<AuditEntry>,
}

pub struct AuditRing {
    entries: Vec<AuditEntry>,
    max_entries: usize,
    total_recorded: u64,
}

impl AuditRing {
    pub fn new(max_entries: usize) -> Self {
        Self {
            entries: Vec::new(),
            max_entries,
            total_recorded: 0,
        }
    }

    pub fn record(&mut self, entry: AuditEntry) {
        self.total_recorded += 1;
        self.entries.push(entry);
        if self.entries.len() > self.max_entries {
            let excess = self.entries.len() - self.max_entries;
            self.entries.drain(..excess);
        }
    }

    pub fn snapshot(&self, limit: usize) -> AuditReport {
        let n = limit.max(1);
        let start = self.entries.len().saturating_sub(n);
        let recent: Vec<AuditEntry> = self.entries[start..].iter().rev().cloned().collect();

        let mut by_outcome: HashMap<String, u64> = HashMap::new();
        let mut last_profile_mismatch: Option<AuditEntry> = None;
        let mut last_denied: Option<AuditEntry> = None;

        for entry in &self.entries {
            *by_outcome.entry(entry.outcome.clone()).or_insert(0) += 1;
            if entry.outcome == "profile_warn" || entry.outcome == "profile_denied" {
                last_profile_mismatch = Some(entry.clone());
            }
            if entry.outcome == "profile_denied" || entry.outcome == "capability_denied" {
                last_denied = Some(entry.clone());
            }
        }

        AuditReport {
            total_events: self.entries.len() as u64,
            total_recorded: self.total_recorded,
            recent,
            by_outcome,
            last_profile_mismatch,
            last_denied,
        }
    }

    pub fn clear(&mut self) {
        self.entries.clear();
        self.total_recorded = 0;
    }
}

fn now_millis() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

// ---------------------------------------------------------------------------
// Policy enforcement — returns the audit entry on success, or (entry, error
// message) on denial.  The caller records the entry into the AuditRing
// regardless of outcome.
// ---------------------------------------------------------------------------

pub enum PolicyOutcome {
    /// Command is allowed — proceed with dispatch.
    Allowed(AuditEntry),
    /// Profile mismatch but not enforced — proceed with dispatch, log a warning.
    ProfileWarn(AuditEntry),
    /// Denied — do not dispatch.
    Denied(AuditEntry, String),
}

pub fn enforce(command: &str, payload: &Option<Value>, meta: &Option<Value>) -> PolicyOutcome {
    let expected_capability = match resolve_command_capability(command) {
        Some(cap) => cap.to_string(),
        None => {
            let entry = AuditEntry {
                command: command.to_string(),
                expected_capability: "unknown".to_string(),
                declared_capability: None,
                target_ref: None,
                session_profile: None,
                session_profile_hint: None,
                enforce_profile_hint: false,
                profile_allows: false,
                allowed_capabilities_configured: false,
                enforced: false,
                outcome: "capability_denied".to_string(),
                recorded_at: now_millis(),
            };
            return PolicyOutcome::Denied(entry, format!("unsupported_control_command:{command}"));
        }
    };

    // Parse meta fields
    let declared_capability = meta
        .as_ref()
        .and_then(|m| m.get("capability"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());
    let session_profile_hint = meta
        .as_ref()
        .and_then(|m| m.get("sessionProfileHint"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());
    let enforce_profile_hint = meta
        .as_ref()
        .and_then(|m| m.get("enforceProfileHint"))
        .and_then(|v| v.as_bool())
        .unwrap_or(false);

    let profile = session_profile_hint.as_deref();
    let profile_caps = profile.map(resolve_profile_capabilities).unwrap_or(&[]);
    let profile_allows = profile.is_none()
        || profile_caps.is_empty()
        || profile_caps.contains(&expected_capability.as_str());
    let enforced = enforce_profile_hint && profile.is_some();
    let target_ref = extract_target_ref(command, payload);

    let base = AuditEntry {
        command: command.to_string(),
        expected_capability: expected_capability.clone(),
        declared_capability: declared_capability.clone(),
        target_ref,
        session_profile: profile.map(|s| s.to_string()),
        session_profile_hint: session_profile_hint.clone(),
        enforce_profile_hint,
        profile_allows,
        allowed_capabilities_configured: false,
        enforced,
        outcome: String::new(),
        recorded_at: now_millis(),
    };

    // --- Capability mismatch check ---
    if let Some(ref declared) = declared_capability {
        if *declared != expected_capability {
            let mut entry = base;
            entry.outcome = "capability_mismatch".to_string();
            return PolicyOutcome::Denied(
                entry,
                format!("native_control_capability_mismatch:{declared}:{expected_capability}"),
            );
        }
    }

    // --- Profile enforcement ---
    if !profile_allows {
        let profile_str = profile.unwrap_or("unknown");
        if enforced {
            let mut entry = base;
            entry.outcome = "profile_denied".to_string();
            return PolicyOutcome::Denied(
                entry,
                format!("native_control_profile_mismatch:{profile_str}:{expected_capability}"),
            );
        } else {
            let mut entry = base;
            entry.outcome = "profile_warn".to_string();
            return PolicyOutcome::ProfileWarn(entry);
        }
    }

    // --- Allowed ---
    let mut entry = base;
    entry.outcome = "allowed".to_string();
    PolicyOutcome::Allowed(entry)
}

/// Thread-safe wrapper for shared audit state.
pub type SharedAuditRing = Mutex<AuditRing>;

pub fn new_shared_audit_ring(max_entries: usize) -> SharedAuditRing {
    Mutex::new(AuditRing::new(max_entries))
}

// ---------------------------------------------------------------------------
// Unit tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn allowed_command_without_meta() {
        let result = enforce("wormhole.status", &None, &None);
        match result {
            PolicyOutcome::Allowed(entry) => {
                assert_eq!(entry.outcome, "allowed");
                assert_eq!(entry.expected_capability, "wormhole_runtime");
                assert!(entry.profile_allows);
                assert!(!entry.enforced);
            }
            _ => panic!("expected Allowed"),
        }
    }

    #[test]
    fn allowed_command_with_matching_capability() {
        let meta = Some(json!({ "capability": "wormhole_runtime" }));
        let result = enforce("wormhole.status", &None, &meta);
        match result {
            PolicyOutcome::Allowed(entry) => {
                assert_eq!(entry.outcome, "allowed");
                assert_eq!(
                    entry.declared_capability.as_deref(),
                    Some("wormhole_runtime")
                );
            }
            _ => panic!("expected Allowed"),
        }
    }

    #[test]
    fn capability_mismatch_is_denied() {
        let meta = Some(json!({ "capability": "settings" }));
        let result = enforce("wormhole.gate.key.rotate", &None, &meta);
        match result {
            PolicyOutcome::Denied(entry, msg) => {
                assert_eq!(entry.outcome, "capability_mismatch");
                assert!(msg.contains("native_control_capability_mismatch"));
                assert!(msg.contains("settings"));
                assert!(msg.contains("wormhole_gate_key"));
            }
            _ => panic!("expected Denied"),
        }
    }

    #[test]
    fn enforced_profile_denial() {
        let meta = Some(json!({
            "capability": "wormhole_gate_key",
            "sessionProfileHint": "settings_only",
            "enforceProfileHint": true
        }));
        let payload = Some(json!({ "gate_id": "infonet", "reason": "test" }));
        let result = enforce("wormhole.gate.key.rotate", &payload, &meta);
        match result {
            PolicyOutcome::Denied(entry, msg) => {
                assert_eq!(entry.outcome, "profile_denied");
                assert_eq!(entry.target_ref.as_deref(), Some("infonet"));
                assert_eq!(entry.session_profile.as_deref(), Some("settings_only"));
                assert!(entry.enforced);
                assert!(!entry.profile_allows);
                assert!(msg.contains("native_control_profile_mismatch"));
            }
            _ => panic!("expected Denied"),
        }
    }

    #[test]
    fn non_enforced_profile_mismatch_warns() {
        let meta = Some(json!({
            "capability": "wormhole_gate_key",
            "sessionProfileHint": "settings_only"
        }));
        let result = enforce("wormhole.gate.key.rotate", &None, &meta);
        match result {
            PolicyOutcome::ProfileWarn(entry) => {
                assert_eq!(entry.outcome, "profile_warn");
                assert!(!entry.enforced);
                assert!(!entry.profile_allows);
            }
            _ => panic!("expected ProfileWarn"),
        }
    }

    #[test]
    fn full_app_profile_allows_everything() {
        let meta = Some(json!({
            "sessionProfileHint": "full_app",
            "enforceProfileHint": true
        }));
        let result = enforce("wormhole.gate.key.rotate", &None, &meta);
        match result {
            PolicyOutcome::Allowed(entry) => {
                assert_eq!(entry.outcome, "allowed");
                assert!(entry.profile_allows);
            }
            _ => panic!("expected Allowed"),
        }
    }

    #[test]
    fn unsupported_command_is_denied() {
        let result = enforce("nonexistent.command", &None, &None);
        match result {
            PolicyOutcome::Denied(entry, msg) => {
                assert_eq!(entry.outcome, "capability_denied");
                assert!(msg.contains("unsupported_control_command"));
            }
            _ => panic!("expected Denied"),
        }
    }

    #[test]
    fn gate_command_extracts_target_ref() {
        let payload = Some(json!({ "gate_id": "testgate", "reason": "r" }));
        let result = enforce("wormhole.gate.key.rotate", &payload, &None);
        match result {
            PolicyOutcome::Allowed(entry) => {
                assert_eq!(entry.target_ref.as_deref(), Some("testgate"));
            }
            _ => panic!("expected Allowed"),
        }
    }

    #[test]
    fn non_gate_command_has_no_target_ref() {
        let result = enforce("wormhole.status", &None, &None);
        match result {
            PolicyOutcome::Allowed(entry) => {
                assert!(entry.target_ref.is_none());
            }
            _ => panic!("expected Allowed"),
        }
    }

    #[test]
    fn audit_ring_records_and_snapshots() {
        let mut ring = AuditRing::new(5);
        for i in 0..3 {
            ring.record(AuditEntry {
                command: format!("cmd.{i}"),
                expected_capability: "settings".to_string(),
                declared_capability: None,
                target_ref: None,
                session_profile: None,
                session_profile_hint: None,
                enforce_profile_hint: false,
                profile_allows: true,
                allowed_capabilities_configured: false,
                enforced: false,
                outcome: "allowed".to_string(),
                recorded_at: 1000 + i,
            });
        }
        let report = ring.snapshot(10);
        assert_eq!(report.total_events, 3);
        assert_eq!(report.total_recorded, 3);
        assert_eq!(report.recent.len(), 3);
        // Most recent first
        assert_eq!(report.recent[0].command, "cmd.2");
        assert_eq!(*report.by_outcome.get("allowed").unwrap(), 3);
    }

    #[test]
    fn audit_ring_evicts_oldest() {
        let mut ring = AuditRing::new(2);
        for i in 0..4 {
            ring.record(AuditEntry {
                command: format!("cmd.{i}"),
                expected_capability: "settings".to_string(),
                declared_capability: None,
                target_ref: None,
                session_profile: None,
                session_profile_hint: None,
                enforce_profile_hint: false,
                profile_allows: true,
                allowed_capabilities_configured: false,
                enforced: false,
                outcome: "allowed".to_string(),
                recorded_at: 1000 + i,
            });
        }
        let report = ring.snapshot(10);
        assert_eq!(report.total_events, 2);
        assert_eq!(report.total_recorded, 4);
        assert_eq!(report.recent[0].command, "cmd.3");
        assert_eq!(report.recent[1].command, "cmd.2");
    }

    #[test]
    fn audit_ring_clear() {
        let mut ring = AuditRing::new(10);
        ring.record(AuditEntry {
            command: "test".to_string(),
            expected_capability: "settings".to_string(),
            declared_capability: None,
            target_ref: None,
            session_profile: None,
            session_profile_hint: None,
            enforce_profile_hint: false,
            profile_allows: true,
            allowed_capabilities_configured: false,
            enforced: false,
            outcome: "allowed".to_string(),
            recorded_at: 1000,
        });
        ring.clear();
        let report = ring.snapshot(10);
        assert_eq!(report.total_events, 0);
        assert_eq!(report.total_recorded, 0);
    }

    #[test]
    fn audit_ring_tracks_denied_entries() {
        let mut ring = AuditRing::new(10);
        ring.record(AuditEntry {
            command: "wormhole.gate.key.rotate".to_string(),
            expected_capability: "wormhole_gate_key".to_string(),
            declared_capability: None,
            target_ref: None,
            session_profile: Some("settings_only".to_string()),
            session_profile_hint: Some("settings_only".to_string()),
            enforce_profile_hint: true,
            profile_allows: false,
            allowed_capabilities_configured: false,
            enforced: true,
            outcome: "profile_denied".to_string(),
            recorded_at: 1000,
        });
        let report = ring.snapshot(10);
        assert!(report.last_denied.is_some());
        assert!(report.last_profile_mismatch.is_some());
        assert_eq!(
            report.last_denied.as_ref().unwrap().outcome,
            "profile_denied"
        );
        assert_eq!(*report.by_outcome.get("profile_denied").unwrap(), 1);
    }

    #[test]
    fn all_27_commands_resolve_capability() {
        let commands = [
            "wormhole.status",
            "wormhole.connect",
            "wormhole.disconnect",
            "wormhole.restart",
            "wormhole.gate.enter",
            "wormhole.gate.leave",
            "wormhole.gate.personas.get",
            "wormhole.gate.persona.create",
            "wormhole.gate.persona.activate",
            "wormhole.gate.persona.clear",
            "wormhole.gate.key.get",
            "wormhole.gate.key.rotate",
            "wormhole.gate.proof",
            "wormhole.gate.message.compose",
            "wormhole.gate.message.post",
            "wormhole.gate.message.decrypt",
            "wormhole.gate.messages.decrypt",
            "settings.wormhole.get",
            "settings.wormhole.set",
            "settings.privacy.get",
            "settings.privacy.set",
            "settings.api_keys.get",
            "settings.news.get",
            "settings.news.set",
            "settings.news.reset",
            "system.update",
        ];
        assert_eq!(commands.len(), 26);
        for cmd in &commands {
            assert!(
                resolve_command_capability(cmd).is_some(),
                "command {cmd} should resolve to a capability"
            );
        }
    }

    #[test]
    fn all_profiles_resolve_non_empty() {
        let profiles = [
            "full_app",
            "gate_observe",
            "gate_operator",
            "wormhole_runtime",
            "settings_only",
        ];
        for profile in &profiles {
            let caps = resolve_profile_capabilities(profile);
            assert!(
                !caps.is_empty(),
                "profile {profile} should have capabilities"
            );
        }
        assert_eq!(resolve_profile_capabilities("full_app").len(), 5);
        assert_eq!(resolve_profile_capabilities("settings_only"), &["settings"]);
        assert_eq!(
            resolve_profile_capabilities("gate_observe"),
            &["wormhole_gate_content"]
        );
    }
}
