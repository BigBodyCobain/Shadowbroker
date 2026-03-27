//! Privacy Core skeleton for the ShadowBroker / Infonet migration.
//!
//! Sprint 1 scope is intentionally narrow:
//! - keep private protocol state opaque to Python
//! - expose only handle-based FFI
//! - prove the repo has a single Rust home for MLS group operations
//! - use in-memory provider/storage only for now
//!
//! This crate follows the architecture docs in `extra/docs-internal/` and keeps
//! group/session state on the Rust side. Persistent storage is deferred to a
//! later sprint.

use std::collections::{hash_map::DefaultHasher, HashMap, VecDeque};
use std::hash::{Hash, Hasher};
use std::panic::{self, AssertUnwindSafe};
use std::slice;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

use mls_rs::client_builder::{BaseConfig, WithCryptoProvider, WithIdentityProvider};
use mls_rs::group::{Group, ReceivedMessage};
use mls_rs::identity::{
    basic::{BasicCredential, BasicIdentityProvider},
    SigningIdentity,
};
use mls_rs::mls_rs_codec::{MlsDecode, MlsEncode};
use mls_rs::{CipherSuite, CipherSuiteProvider, Client, CryptoProvider, ExtensionList, MlsMessage};
use mls_rs_crypto_rustcrypto::RustCryptoProvider;
use serde::Serialize;

type IdentityHandle = u64;
type KeyPackageHandle = u64;
type GroupHandle = u64;
type CommitHandle = u64;
type DMSessionHandle = u64;
type FamilyId = u64;
type MemberRef = u32;

type PrivacyConfig =
    WithIdentityProvider<BasicIdentityProvider, WithCryptoProvider<RustCryptoProvider, BaseConfig>>;
type PrivacyClient = Client<PrivacyConfig>;
type PrivacyGroup = Group<PrivacyConfig>;

const CIPHER_SUITE: CipherSuite = CipherSuite::CURVE25519_AES128;
const VERSION: &str = concat!("privacy-core/", env!("CARGO_PKG_VERSION"));
const MAX_KEY_PACKAGE_SIZE: usize = 65_536;
const MAX_DM_PLAINTEXT_SIZE: usize = 65_536;
const MAX_GROUP_PLAINTEXT_SIZE: usize = 65_536;
const MAX_IDENTITIES: usize = 1_024;
const MAX_GROUPS: usize = 512;
const MAX_DM_SESSIONS: usize = 512;
const MAX_PENDING_DM_OUTPUTS: usize = 256;
const PENDING_DM_OUTPUT_TTL: Duration = Duration::from_secs(10);

#[repr(C)]
pub struct ByteBuffer {
    pub data: *mut u8,
    pub len: usize,
}

impl ByteBuffer {
    fn empty() -> Self {
        Self {
            data: std::ptr::null_mut(),
            len: 0,
        }
    }
}

#[derive(Clone)]
struct IdentityState {
    client: PrivacyClient,
    signing_identity: SigningIdentity,
    label: Vec<u8>,
}

#[derive(Clone)]
struct KeyPackageState {
    message: MlsMessage,
    owner_identity: Option<IdentityHandle>,
}

struct GroupState {
    family_id: FamilyId,
    owner_identity: IdentityHandle,
    group: PrivacyGroup,
}

struct CommitState {
    family_id: FamilyId,
    commit_message: Vec<u8>,
    welcome_messages: Vec<Vec<u8>>,
    joined_group_handles: Vec<GroupHandle>,
}

struct DMSessionState {
    owner_identity: IdentityHandle,
    group: PrivacyGroup,
    welcome_message: Vec<u8>,
}

#[derive(Serialize)]
struct PublicBundle {
    label: String,
    cipher_suite: &'static str,
    signing_public_key: Vec<u8>,
    credential: Vec<u8>,
}

#[derive(Serialize)]
struct HandleStats {
    identities: usize,
    groups: usize,
    dm_sessions: usize,
    max_identities: usize,
    max_groups: usize,
    max_dm_sessions: usize,
}

// Monotonic counter starting at 1. Handle 0 is the FFI error sentinel.
// Wraparound at 2^64 is not handled and is assumed unreachable in practice.
static NEXT_HANDLE: AtomicU64 = AtomicU64::new(1);
static NEXT_FAMILY_ID: AtomicU64 = AtomicU64::new(1);
static LAST_ERROR: OnceLock<Mutex<String>> = OnceLock::new();
static IDENTITIES: OnceLock<Mutex<HashMap<IdentityHandle, IdentityState>>> = OnceLock::new();
static KEY_PACKAGES: OnceLock<Mutex<HashMap<KeyPackageHandle, KeyPackageState>>> = OnceLock::new();
static GROUPS: OnceLock<Mutex<HashMap<GroupHandle, GroupState>>> = OnceLock::new();
static COMMITS: OnceLock<Mutex<HashMap<CommitHandle, CommitState>>> = OnceLock::new();
static DM_SESSIONS: OnceLock<Mutex<HashMap<DMSessionHandle, DMSessionState>>> = OnceLock::new();
static FAMILIES: OnceLock<Mutex<HashMap<FamilyId, Vec<GroupHandle>>>> = OnceLock::new();
static EXPORTED_KEY_PACKAGES: OnceLock<Mutex<HashMap<Vec<u8>, IdentityHandle>>> = OnceLock::new();
static PENDING_DM_OUTPUTS: OnceLock<Mutex<HashMap<(u8, u64, u64), (Vec<u8>, Instant)>>> =
    OnceLock::new();
static PENDING_DM_OUTPUT_LOOKUPS: OnceLock<
    Mutex<HashMap<(u8, u64, u64), VecDeque<(u8, u64, u64)>>>,
> = OnceLock::new();
static PENDING_DM_OUTPUT_COUNTERS: OnceLock<Mutex<HashMap<(u8, u64), u64>>> = OnceLock::new();

fn identities() -> &'static Mutex<HashMap<IdentityHandle, IdentityState>> {
    IDENTITIES.get_or_init(|| Mutex::new(HashMap::new()))
}

fn key_packages() -> &'static Mutex<HashMap<KeyPackageHandle, KeyPackageState>> {
    KEY_PACKAGES.get_or_init(|| Mutex::new(HashMap::new()))
}

fn groups() -> &'static Mutex<HashMap<GroupHandle, GroupState>> {
    GROUPS.get_or_init(|| Mutex::new(HashMap::new()))
}

fn commits() -> &'static Mutex<HashMap<CommitHandle, CommitState>> {
    COMMITS.get_or_init(|| Mutex::new(HashMap::new()))
}

fn dm_sessions() -> &'static Mutex<HashMap<DMSessionHandle, DMSessionState>> {
    DM_SESSIONS.get_or_init(|| Mutex::new(HashMap::new()))
}

fn families() -> &'static Mutex<HashMap<FamilyId, Vec<GroupHandle>>> {
    FAMILIES.get_or_init(|| Mutex::new(HashMap::new()))
}

fn exported_key_packages() -> &'static Mutex<HashMap<Vec<u8>, IdentityHandle>> {
    EXPORTED_KEY_PACKAGES.get_or_init(|| Mutex::new(HashMap::new()))
}

fn pending_dm_outputs() -> &'static Mutex<HashMap<(u8, u64, u64), (Vec<u8>, Instant)>> {
    PENDING_DM_OUTPUTS.get_or_init(|| Mutex::new(HashMap::new()))
}

fn pending_dm_output_lookups() -> &'static Mutex<HashMap<(u8, u64, u64), VecDeque<(u8, u64, u64)>>> {
    PENDING_DM_OUTPUT_LOOKUPS.get_or_init(|| Mutex::new(HashMap::new()))
}

fn pending_dm_output_counters() -> &'static Mutex<HashMap<(u8, u64), u64>> {
    PENDING_DM_OUTPUT_COUNTERS.get_or_init(|| Mutex::new(HashMap::new()))
}

fn last_error() -> &'static Mutex<String> {
    LAST_ERROR.get_or_init(|| Mutex::new(String::new()))
}

fn next_handle() -> u64 {
    NEXT_HANDLE.fetch_add(1, Ordering::Relaxed)
}

fn next_family_id() -> u64 {
    NEXT_FAMILY_ID.fetch_add(1, Ordering::Relaxed)
}

fn set_last_error(message: impl Into<String>) {
    *last_error().lock().expect("last error mutex poisoned") = message.into();
}

fn clear_last_error() {
    set_last_error("");
}

fn wipe_bytes(bytes: &mut [u8]) {
    bytes.fill(0);
}

fn wipe_vec(bytes: &mut Vec<u8>) {
    if !bytes.is_empty() {
        wipe_bytes(bytes.as_mut_slice());
    }
}

fn to_buffer(mut bytes: Vec<u8>) -> ByteBuffer {
    if bytes.is_empty() {
        return ByteBuffer::empty();
    }
    let len = bytes.len();
    let ptr = bytes.as_mut_ptr();
    std::mem::forget(bytes);
    ByteBuffer { data: ptr, len }
}

fn from_buffer(buffer: ByteBuffer) {
    if buffer.data.is_null() || buffer.len == 0 {
        return;
    }
    unsafe {
        let mut bytes = Vec::from_raw_parts(buffer.data, buffer.len, buffer.len);
        wipe_vec(&mut bytes);
    }
}

fn bytes_from_raw<'a>(ptr: *const u8, len: usize) -> Result<&'a [u8], String> {
    // SAFETY: len is checked before ptr is dereferenced. Do not reorder these checks.
    if len == 0 {
        return Ok(&[]);
    }
    if ptr.is_null() {
        return Err("received null pointer for non-empty buffer".to_string());
    }
    Ok(unsafe { slice::from_raw_parts(ptr, len) })
}

fn map_err<E: std::fmt::Display>(err: E) -> String {
    err.to_string()
}

fn make_client(label: &[u8]) -> Result<(PrivacyClient, SigningIdentity), String> {
    let crypto_provider = RustCryptoProvider::default();
    let cipher_suite_provider = crypto_provider
        .cipher_suite_provider(CIPHER_SUITE)
        .ok_or_else(|| "cipher suite is not supported by RustCrypto provider".to_string())?;
    let (secret, public) = cipher_suite_provider
        .signature_key_generate()
        .map_err(map_err)?;
    let credential = BasicCredential::new(label.to_vec());
    let signing_identity = SigningIdentity::new(credential.into_credential(), public);
    let client = Client::builder()
        .identity_provider(BasicIdentityProvider::new())
        .crypto_provider(crypto_provider)
        .signing_identity(signing_identity.clone(), secret, CIPHER_SUITE)
        .build();
    Ok((client, signing_identity))
}

fn family_handles(family_id: FamilyId) -> Vec<GroupHandle> {
    families()
        .lock()
        .expect("families mutex poisoned")
        .get(&family_id)
        .cloned()
        .unwrap_or_default()
}

fn register_group_handle(
    family_id: FamilyId,
    owner_identity: IdentityHandle,
    group: PrivacyGroup,
) -> Result<GroupHandle, String> {
    let handle = next_handle();
    let mut groups_guard = groups().lock().expect("groups mutex poisoned");
    if groups_guard.len() >= MAX_GROUPS && !groups_guard.contains_key(&handle) {
        return Err("maximum group limit reached".to_string());
    }
    groups_guard.insert(
        handle,
        GroupState {
            family_id,
            owner_identity,
            group,
        },
    );
    drop(groups_guard);
    families()
        .lock()
        .expect("families mutex poisoned")
        .entry(family_id)
        .or_default()
        .push(handle);
    Ok(handle)
}

fn process_commit_for_family(
    family_id: FamilyId,
    commit_message: &MlsMessage,
    actor_handle: GroupHandle,
    skip_handles: &[GroupHandle],
) -> Result<(), String> {
    let handles = family_handles(family_id);
    let mut groups_guard = groups().lock().expect("groups mutex poisoned");
    for handle in handles {
        if handle == actor_handle || skip_handles.contains(&handle) {
            continue;
        }
        if let Some(state) = groups_guard.get_mut(&handle) {
            state
                .group
                .process_incoming_message(commit_message.clone())
                .map_err(map_err)?;
        }
    }
    Ok(())
}

fn remove_group_handles(handles_to_remove: &[GroupHandle]) {
    let mut groups_guard = groups().lock().expect("groups mutex poisoned");
    let mut families_guard = families().lock().expect("families mutex poisoned");
    for handle in handles_to_remove {
        if let Some(state) = groups_guard.remove(handle) {
            if let Some(entries) = families_guard.get_mut(&state.family_id) {
                entries.retain(|candidate| candidate != handle);
            }
        }
    }
}

pub fn create_identity() -> Result<IdentityHandle, String> {
    let handle = next_handle();
    let label = format!("identity-{handle}").into_bytes();
    let (client, signing_identity) = make_client(&label)?;
    let mut guard = identities().lock().expect("identities mutex poisoned");
    if guard.len() >= MAX_IDENTITIES {
        return Err("identity limit reached".to_string());
    }
    guard.insert(
        handle,
        IdentityState {
            client,
            signing_identity,
            label,
        },
    );
    Ok(handle)
}

pub fn export_key_package(identity: IdentityHandle) -> Result<Vec<u8>, String> {
    let identities_guard = identities().lock().expect("identities mutex poisoned");
    let identity_state = identities_guard
        .get(&identity)
        .ok_or_else(|| format!("unknown identity handle: {identity}"))?;
    let message = identity_state
        .client
        .generate_key_package_message(Default::default(), Default::default(), None)
        .map_err(map_err)?;
    let bytes = message.mls_encode_to_vec().map_err(map_err)?;
    drop(identities_guard);
    exported_key_packages()
        .lock()
        .expect("key package export mutex poisoned")
        .insert(bytes.clone(), identity);
    Ok(bytes)
}

pub fn import_key_package(data: &[u8]) -> Result<KeyPackageHandle, String> {
    if data.len() > MAX_KEY_PACKAGE_SIZE {
        return Err(format!(
            "key package exceeds maximum size: {} > {} bytes",
            data.len(),
            MAX_KEY_PACKAGE_SIZE
        ));
    }
    let mut cursor = data;
    let message = MlsMessage::mls_decode(&mut cursor).map_err(map_err)?;
    let owner_identity = exported_key_packages()
        .lock()
        .expect("key package export mutex poisoned")
        .get(data)
        .copied();
    let handle = next_handle();
    key_packages()
        .lock()
        .expect("key packages mutex poisoned")
        .insert(
            handle,
            KeyPackageState {
                message,
                owner_identity,
            },
        );
    Ok(handle)
}

pub fn create_group(creator: IdentityHandle) -> Result<GroupHandle, String> {
    let identities_guard = identities().lock().expect("identities mutex poisoned");
    let identity_state = identities_guard
        .get(&creator)
        .ok_or_else(|| format!("unknown identity handle: {creator}"))?;
    let group = identity_state
        .client
        .create_group(ExtensionList::default(), Default::default(), None)
        .map_err(map_err)?;
    drop(identities_guard);
    let family_id = next_family_id();
    let handle = next_handle();
    let mut groups_guard = groups().lock().expect("groups mutex poisoned");
    if groups_guard.len() >= MAX_GROUPS {
        return Err("group limit reached".to_string());
    }
    groups_guard.insert(
        handle,
        GroupState {
            family_id,
            owner_identity: creator,
            group,
        },
    );
    drop(groups_guard);
    families()
        .lock()
        .expect("families mutex poisoned")
        .entry(family_id)
        .or_default()
        .push(handle);
    Ok(handle)
}

pub fn add_member(group_handle: GroupHandle, key_package: KeyPackageHandle) -> Result<CommitHandle, String> {
    let package_state = key_packages()
        .lock()
        .expect("key packages mutex poisoned")
        .get(&key_package)
        .cloned()
        .ok_or_else(|| format!("unknown key package handle: {key_package}"))?;

    let family_id = {
        let groups_guard = groups().lock().expect("groups mutex poisoned");
        groups_guard
            .get(&group_handle)
            .map(|state| state.family_id)
            .ok_or_else(|| format!("unknown group handle: {group_handle}"))?
    };

    let commit_output = {
        let mut groups_guard = groups().lock().expect("groups mutex poisoned");
        let group_state = groups_guard
            .get_mut(&group_handle)
            .ok_or_else(|| format!("unknown group handle: {group_handle}"))?;
        let output = group_state
            .group
            .commit_builder()
            .add_member(package_state.message.clone())
            .map_err(map_err)?
            .build()
            .map_err(map_err)?;
        group_state.group.apply_pending_commit().map_err(map_err)?;
        output
    };

    let commit_message = commit_output.commit_message.clone();
    process_commit_for_family(family_id, &commit_message, group_handle, &[])?;

    let welcome = commit_output
        .welcome_messages
        .first()
        .cloned()
        .ok_or_else(|| "add_member did not produce a welcome message".to_string())?;

    let joined_group_handles = if let Some(owner_identity) = package_state.owner_identity {
        let recipient_client = {
            let identities_guard = identities().lock().expect("identities mutex poisoned");
            identities_guard
                .get(&owner_identity)
                .map(|state| state.client.clone())
                .ok_or_else(|| {
                    format!(
                        "missing identity for imported key package owner: {}",
                        owner_identity
                    )
                })?
        };

        let (joined_group, _) = recipient_client
            .join_group(None, &welcome, None)
            .map_err(map_err)?;

        vec![register_group_handle(family_id, owner_identity, joined_group)?]
    } else {
        Vec::new()
    };
    let commit_handle = next_handle();
    commits()
        .lock()
        .expect("commits mutex poisoned")
        .insert(
            commit_handle,
            CommitState {
                family_id,
                commit_message: commit_output.commit_message.mls_encode_to_vec().map_err(map_err)?,
                welcome_messages: commit_output
                    .welcome_messages
                    .iter()
                    .map(|message| message.mls_encode_to_vec().map_err(map_err))
                    .collect::<Result<Vec<_>, _>>()?,
                joined_group_handles,
            },
        );
    Ok(commit_handle)
}

pub fn remove_member(group_handle: GroupHandle, member_ref: MemberRef) -> Result<CommitHandle, String> {
    let (family_id, target_signing_identity) = {
        let groups_guard = groups().lock().expect("groups mutex poisoned");
        let group_state = groups_guard
            .get(&group_handle)
            .ok_or_else(|| format!("unknown group handle: {group_handle}"))?;
        let member = group_state
            .group
            .member_at_index(member_ref)
            .ok_or_else(|| format!("no member at index {member_ref}"))?;
        (group_state.family_id, member.signing_identity)
    };

    let handles_to_remove = {
        let groups_guard = groups().lock().expect("groups mutex poisoned");
        family_handles(family_id)
            .into_iter()
            .filter(|handle| {
                groups_guard
                    .get(handle)
                    .and_then(|state| state.group.current_member_signing_identity().ok())
                    .map(|identity| identity == &target_signing_identity)
                    .unwrap_or(false)
            })
            .collect::<Vec<_>>()
    };

    let commit_output = {
        let mut groups_guard = groups().lock().expect("groups mutex poisoned");
        let group_state = groups_guard
            .get_mut(&group_handle)
            .ok_or_else(|| format!("unknown group handle: {group_handle}"))?;
        let output = group_state
            .group
            .commit_builder()
            .remove_member(member_ref)
            .map_err(map_err)?
            .build()
            .map_err(map_err)?;
        group_state.group.apply_pending_commit().map_err(map_err)?;
        output
    };

    let commit_message = commit_output.commit_message.clone();
    process_commit_for_family(family_id, &commit_message, group_handle, &handles_to_remove)?;
    remove_group_handles(&handles_to_remove);

    let commit_handle = next_handle();
    commits()
        .lock()
        .expect("commits mutex poisoned")
        .insert(
            commit_handle,
            CommitState {
                family_id,
                commit_message: commit_output.commit_message.mls_encode_to_vec().map_err(map_err)?,
                welcome_messages: commit_output
                    .welcome_messages
                    .iter()
                    .map(|message| message.mls_encode_to_vec().map_err(map_err))
                    .collect::<Result<Vec<_>, _>>()?,
                joined_group_handles: Vec::new(),
            },
        );
    Ok(commit_handle)
}

pub fn encrypt_group_message(group_handle: GroupHandle, plaintext: &[u8]) -> Result<Vec<u8>, String> {
    if plaintext.len() > MAX_GROUP_PLAINTEXT_SIZE {
        return Err(format!(
            "group plaintext too large: {} bytes (max {})",
            plaintext.len(),
            MAX_GROUP_PLAINTEXT_SIZE
        ));
    }
    let mut groups_guard = groups().lock().expect("groups mutex poisoned");
    let group_state = groups_guard
        .get_mut(&group_handle)
        .ok_or_else(|| format!("unknown group handle: {group_handle}"))?;
    group_state
        .group
        .encrypt_application_message(plaintext, Vec::new())
        .map_err(map_err)?
        .mls_encode_to_vec()
        .map_err(map_err)
}

pub fn decrypt_group_message(group_handle: GroupHandle, ciphertext: &[u8]) -> Result<Vec<u8>, String> {
    let mut cursor = ciphertext;
    let message = MlsMessage::mls_decode(&mut cursor).map_err(map_err)?;
    let mut groups_guard = groups().lock().expect("groups mutex poisoned");
    let group_state = groups_guard
        .get_mut(&group_handle)
        .ok_or_else(|| format!("unknown group handle: {group_handle}"))?;
    match group_state
        .group
        .process_incoming_message(message)
        .map_err(map_err)?
    {
        ReceivedMessage::ApplicationMessage(description) => Ok(description.data().to_vec()),
        other => Err(format!("expected application message, received {other:?}")),
    }
}

pub fn create_dm_session(
    initiator_identity: IdentityHandle,
    responder_key_package: KeyPackageHandle,
) -> Result<DMSessionHandle, String> {
    let identities_guard = identities().lock().expect("identities mutex poisoned");
    let identity_state = identities_guard
        .get(&initiator_identity)
        .ok_or_else(|| format!("unknown identity handle: {initiator_identity}"))?;
    let initiator_client = identity_state.client.clone();
    drop(identities_guard);

    let package_state = key_packages()
        .lock()
        .expect("key packages mutex poisoned")
        .get(&responder_key_package)
        .cloned()
        .ok_or_else(|| format!("unknown key package handle: {responder_key_package}"))?;

    let mut group = initiator_client
        .create_group(ExtensionList::default(), Default::default(), None)
        .map_err(map_err)?;
    let output = group
        .commit_builder()
        .add_member(package_state.message.clone())
        .map_err(map_err)?
        .build()
        .map_err(map_err)?;
    group.apply_pending_commit().map_err(map_err)?;

    let welcome = output
        .welcome_messages
        .first()
        .cloned()
        .ok_or_else(|| "dm session creation did not produce a welcome message".to_string())?
        .mls_encode_to_vec()
        .map_err(map_err)?;

    let handle = next_handle();
    let mut sessions_guard = dm_sessions().lock().expect("dm sessions mutex poisoned");
    if sessions_guard.len() >= MAX_DM_SESSIONS {
        return Err("dm session limit reached".to_string());
    }
    sessions_guard.insert(
        handle,
        DMSessionState {
            owner_identity: initiator_identity,
            group,
            welcome_message: welcome,
        },
    );
    Ok(handle)
}

pub fn dm_encrypt(session: DMSessionHandle, plaintext: &[u8]) -> Result<Vec<u8>, String> {
    if plaintext.len() > MAX_DM_PLAINTEXT_SIZE {
        return Err("plaintext exceeds maximum size".to_string());
    }
    let mut sessions_guard = dm_sessions().lock().expect("dm sessions mutex poisoned");
    let state = sessions_guard
        .get_mut(&session)
        .ok_or_else(|| format!("unknown dm session handle: {session}"))?;
    state
        .group
        .encrypt_application_message(plaintext, Vec::new())
        .map_err(map_err)?
        .mls_encode_to_vec()
        .map_err(map_err)
}

pub fn dm_decrypt(session: DMSessionHandle, ciphertext: &[u8]) -> Result<Vec<u8>, String> {
    let mut cursor = ciphertext;
    let message = MlsMessage::mls_decode(&mut cursor).map_err(map_err)?;
    let mut sessions_guard = dm_sessions().lock().expect("dm sessions mutex poisoned");
    let state = sessions_guard
        .get_mut(&session)
        .ok_or_else(|| format!("unknown dm session handle: {session}"))?;
    match state
        .group
        .process_incoming_message(message)
        .map_err(map_err)?
    {
        ReceivedMessage::ApplicationMessage(description) => Ok(description.data().to_vec()),
        other => Err(format!("expected application message, received {other:?}")),
    }
}

pub fn dm_session_welcome(session: DMSessionHandle) -> Result<Vec<u8>, String> {
    let sessions_guard = dm_sessions().lock().expect("dm sessions mutex poisoned");
    let state = sessions_guard
        .get(&session)
        .ok_or_else(|| format!("unknown dm session handle: {session}"))?;
    if state.welcome_message.is_empty() {
        return Err("dm session does not have a welcome message".to_string());
    }
    Ok(state.welcome_message.clone())
}

pub fn join_dm_session(
    responder_identity: IdentityHandle,
    welcome_bytes: &[u8],
) -> Result<DMSessionHandle, String> {
    let identities_guard = identities().lock().expect("identities mutex poisoned");
    let identity_state = identities_guard
        .get(&responder_identity)
        .ok_or_else(|| format!("unknown identity handle: {responder_identity}"))?;
    let responder_client = identity_state.client.clone();
    drop(identities_guard);

    let mut cursor = welcome_bytes;
    let welcome = MlsMessage::mls_decode(&mut cursor).map_err(map_err)?;
    let (group, _) = responder_client.join_group(None, &welcome, None).map_err(map_err)?;
    let handle = next_handle();
    let mut sessions_guard = dm_sessions().lock().expect("dm sessions mutex poisoned");
    if sessions_guard.len() >= MAX_DM_SESSIONS {
        return Err("dm session limit reached".to_string());
    }
    sessions_guard.insert(
        handle,
        DMSessionState {
            owner_identity: responder_identity,
            group,
            welcome_message: welcome_bytes.to_vec(),
        },
    );
    Ok(handle)
}

pub fn release_dm_session(handle: DMSessionHandle) -> Result<i32, String> {
    let Ok(mut sessions_guard) = dm_sessions().lock() else {
        return Err("dm sessions mutex poisoned".to_string());
    };
    Ok(if sessions_guard.remove(&handle).is_some() { 1 } else { 0 })
}

pub fn export_public_bundle(identity: IdentityHandle) -> Result<Vec<u8>, String> {
    let identities_guard = identities().lock().expect("identities mutex poisoned");
    let state = identities_guard
        .get(&identity)
        .ok_or_else(|| format!("unknown identity handle: {identity}"))?;
    let bundle = PublicBundle {
        label: String::from_utf8_lossy(&state.label).to_string(),
        cipher_suite: "CURVE25519_AES128",
        signing_public_key: state.signing_identity.signature_key.as_bytes().to_vec(),
        credential: state
            .signing_identity
            .credential
            .mls_encode_to_vec()
            .map_err(map_err)?,
    };
    serde_json::to_vec(&bundle).map_err(map_err)
}

fn handle_stats_json() -> Result<Vec<u8>, String> {
    let stats = HandleStats {
        identities: identities().lock().expect("identities mutex poisoned").len(),
        groups: groups().lock().expect("groups mutex poisoned").len(),
        dm_sessions: dm_sessions().lock().expect("dm sessions mutex poisoned").len(),
        max_identities: MAX_IDENTITIES,
        max_groups: MAX_GROUPS,
        max_dm_sessions: MAX_DM_SESSIONS,
    };
    serde_json::to_vec(&stats).map_err(map_err)
}

fn commit_message_bytes(commit: CommitHandle) -> Result<Vec<u8>, String> {
    let commits_guard = commits().lock().expect("commits mutex poisoned");
    let state = commits_guard
        .get(&commit)
        .ok_or_else(|| format!("unknown commit handle: {commit}"))?;
    Ok(state.commit_message.clone())
}

fn commit_welcome_message_bytes(commit: CommitHandle, index: usize) -> Result<Vec<u8>, String> {
    let commits_guard = commits().lock().expect("commits mutex poisoned");
    let state = commits_guard
        .get(&commit)
        .ok_or_else(|| format!("unknown commit handle: {commit}"))?;
    state
        .welcome_messages
        .get(index)
        .cloned()
        .ok_or_else(|| format!("no welcome message at index {index}"))
}

fn commit_joined_group_handle(commit: CommitHandle, index: usize) -> Result<GroupHandle, String> {
    let commits_guard = commits().lock().expect("commits mutex poisoned");
    let state = commits_guard
        .get(&commit)
        .ok_or_else(|| format!("unknown commit handle: {commit}"))?;
    state
        .joined_group_handles
        .get(index)
        .copied()
        .ok_or_else(|| format!("no joined group handle at index {index}"))
}

fn with_handle_result<F>(operation: F) -> u64
where
    F: FnOnce() -> Result<u64, String>,
{
    clear_last_error();
    match panic::catch_unwind(AssertUnwindSafe(operation)) {
        Ok(Ok(handle)) => handle,
        Ok(Err(error)) => {
            set_last_error(error);
            0
        }
        Err(_) => {
            set_last_error("privacy-core panicked across the FFI boundary");
            0
        }
    }
}

fn with_bool_result<F>(operation: F) -> bool
where
    F: FnOnce() -> Result<bool, String>,
{
    clear_last_error();
    match panic::catch_unwind(AssertUnwindSafe(operation)) {
        Ok(Ok(value)) => value,
        Ok(Err(error)) => {
            set_last_error(error);
            false
        }
        Err(_) => {
            set_last_error("privacy-core panicked across the FFI boundary");
            false
        }
    }
}

fn with_bytes_result<F>(operation: F) -> ByteBuffer
where
    F: FnOnce() -> Result<Vec<u8>, String>,
{
    clear_last_error();
    match panic::catch_unwind(AssertUnwindSafe(operation)) {
        Ok(Ok(bytes)) => to_buffer(bytes),
        Ok(Err(error)) => {
            set_last_error(error);
            ByteBuffer::empty()
        }
        Err(_) => {
            set_last_error("privacy-core panicked across the FFI boundary");
            ByteBuffer::empty()
        }
    }
}

fn with_i64_result<F>(operation: F) -> i64
where
    F: FnOnce() -> Result<i64, String>,
{
    clear_last_error();
    match panic::catch_unwind(AssertUnwindSafe(operation)) {
        Ok(Ok(value)) => value,
        Ok(Err(error)) => {
            set_last_error(error);
            -1
        }
        Err(_) => {
            set_last_error("privacy-core panicked across the FFI boundary");
            -1
        }
    }
}

fn with_i32_result<F>(operation: F) -> i32
where
    F: FnOnce() -> Result<i32, String>,
{
    clear_last_error();
    match panic::catch_unwind(AssertUnwindSafe(operation)) {
        Ok(Ok(value)) => value,
        Ok(Err(error)) => {
            set_last_error(error);
            0
        }
        Err(_) => {
            set_last_error("privacy-core panicked across the FFI boundary");
            0
        }
    }
}

fn write_to_output_buffer(bytes: &[u8], out_buf: *mut u8, out_cap: usize) -> Result<i64, String> {
    let required = i64::try_from(bytes.len()).map_err(|_| "output too large".to_string())?;
    if out_buf.is_null() || out_cap == 0 {
        return Ok(required);
    }
    if out_cap < bytes.len() {
        return Err(format!(
            "output buffer too small: need {} bytes, got {}",
            bytes.len(),
            out_cap
        ));
    }
    unsafe {
        std::ptr::copy_nonoverlapping(bytes.as_ptr(), out_buf, bytes.len());
    }
    Ok(required)
}

fn input_hash(bytes: &[u8]) -> u64 {
    let mut hasher = DefaultHasher::new();
    bytes.hash(&mut hasher);
    hasher.finish()
}

fn cache_key(session: u64, opcode: u8, counter: u64) -> u64 {
    let mut hasher = DefaultHasher::new();
    session.hash(&mut hasher);
    opcode.hash(&mut hasher);
    counter.hash(&mut hasher);
    hasher.finish()
}

fn next_pending_output_key(opcode: u8, session: u64) -> Result<(u8, u64, u64), String> {
    let mut counters = pending_dm_output_counters()
        .lock()
        .map_err(|_| "pending dm output counters mutex poisoned".to_string())?;
    let counter = counters.entry((opcode, session)).or_insert(0);
    *counter = counter.saturating_add(1);
    Ok((opcode, session, cache_key(session, opcode, *counter)))
}

fn prune_pending_outputs(now: Instant) {
    let mut expired: Vec<(u8, u64, u64)> = Vec::new();
    {
        let mut pending = pending_dm_outputs()
            .lock()
            .expect("pending dm outputs mutex poisoned");
        let expired_keys: Vec<(u8, u64, u64)> = pending
            .iter()
            .filter_map(|(key, (_bytes, inserted_at))| {
                if now.duration_since(*inserted_at) > PENDING_DM_OUTPUT_TTL {
                    Some(*key)
                } else {
                    None
                }
            })
            .collect();
        for key in expired_keys {
            if let Some((mut bytes, _inserted_at)) = pending.remove(&key) {
                wipe_vec(&mut bytes);
            }
            expired.push(key);
        }
    }
    if expired.is_empty() {
        return;
    }
    let mut lookups = pending_dm_output_lookups()
        .lock()
        .expect("pending dm output lookup mutex poisoned");
    lookups.retain(|_, queue| {
        queue.retain(|key| !expired.contains(key));
        !queue.is_empty()
    });
}

fn stage_or_write_output<F>(
    opcode: u8,
    session: u64,
    input_fingerprint: u64,
    out_buf: *mut u8,
    out_cap: usize,
    producer: F,
) -> Result<i64, String>
where
    F: FnOnce() -> Result<Vec<u8>, String>,
{
    let now = Instant::now();
    let lookup_key = (opcode, session, input_fingerprint);
    if out_buf.is_null() || out_cap == 0 {
        let bytes = producer()?;
        let required = i64::try_from(bytes.len()).map_err(|_| "output too large".to_string())?;
        prune_pending_outputs(now);
        let output_key = next_pending_output_key(opcode, session)?;
        let mut pending = pending_dm_outputs()
            .lock()
            .expect("pending dm outputs mutex poisoned");
        if pending.len() >= MAX_PENDING_DM_OUTPUTS {
            return Err("pending output buffer full — cannot enqueue".into());
        }
        pending.insert(output_key, (bytes, now));
        drop(pending);
        pending_dm_output_lookups()
            .lock()
            .expect("pending dm output lookup mutex poisoned")
            .entry(lookup_key)
            .or_default()
            .push_back(output_key);
        return Ok(required);
    }

    prune_pending_outputs(now);
    let output_key = {
        let mut lookups = pending_dm_output_lookups()
            .lock()
            .expect("pending dm output lookup mutex poisoned");
        let mut remove_lookup = false;
        let next = if let Some(queue) = lookups.get_mut(&lookup_key) {
            let next = queue.pop_front();
            remove_lookup = queue.is_empty();
            next
        } else {
            None
        };
        if remove_lookup {
            lookups.remove(&lookup_key);
        }
        next
    };
    let mut bytes = if let Some(output_key) = output_key {
        if let Some((bytes, _inserted_at)) = pending_dm_outputs()
            .lock()
            .expect("pending dm outputs mutex poisoned")
            .remove(&output_key)
        {
            bytes
        } else {
            producer()?
        }
    } else {
        producer()?
    };
    let written = write_to_output_buffer(&bytes, out_buf, out_cap);
    wipe_vec(&mut bytes);
    Ok(written?)
}

#[no_mangle]
pub extern "C" fn privacy_core_version() -> ByteBuffer {
    to_buffer(VERSION.as_bytes().to_vec())
}

#[no_mangle]
pub extern "C" fn privacy_core_last_error_message() -> ByteBuffer {
    let message = last_error().lock().expect("last error mutex poisoned").clone();
    to_buffer(message.into_bytes())
}

#[no_mangle]
pub extern "C" fn privacy_core_free_buffer(buffer: ByteBuffer) {
    from_buffer(buffer);
}

#[no_mangle]
pub extern "C" fn privacy_core_create_identity() -> u64 {
    with_handle_result(create_identity)
}

#[no_mangle]
pub extern "C" fn privacy_core_export_key_package(identity: u64) -> ByteBuffer {
    with_bytes_result(|| export_key_package(identity))
}

#[no_mangle]
pub extern "C" fn privacy_core_import_key_package(data: *const u8, len: usize) -> u64 {
    with_handle_result(|| import_key_package(bytes_from_raw(data, len)?))
}

#[no_mangle]
pub extern "C" fn privacy_core_create_group(identity: u64) -> u64 {
    with_handle_result(|| create_group(identity))
}

#[no_mangle]
pub extern "C" fn privacy_core_add_member(group: u64, key_package: u64) -> u64 {
    with_handle_result(|| add_member(group, key_package))
}

#[no_mangle]
pub extern "C" fn privacy_core_remove_member(group: u64, member_ref: u32) -> u64 {
    with_handle_result(|| remove_member(group, member_ref))
}

#[no_mangle]
pub extern "C" fn privacy_core_encrypt_group_message(
    group: u64,
    plaintext: *const u8,
    len: usize,
) -> ByteBuffer {
    with_bytes_result(|| encrypt_group_message(group, bytes_from_raw(plaintext, len)?))
}

#[no_mangle]
pub extern "C" fn privacy_core_decrypt_group_message(
    group: u64,
    ciphertext: *const u8,
    len: usize,
) -> ByteBuffer {
    with_bytes_result(|| decrypt_group_message(group, bytes_from_raw(ciphertext, len)?))
}

#[no_mangle]
pub extern "C" fn privacy_core_export_public_bundle(identity: u64) -> ByteBuffer {
    with_bytes_result(|| export_public_bundle(identity))
}

#[no_mangle]
pub extern "C" fn privacy_core_handle_stats(out_buf: *mut u8, out_cap: usize) -> i64 {
    with_i64_result(|| stage_or_write_output(4, 0, 0, out_buf, out_cap, handle_stats_json))
}

#[no_mangle]
pub extern "C" fn privacy_core_commit_message_bytes(commit: u64) -> ByteBuffer {
    with_bytes_result(|| commit_message_bytes(commit))
}

#[no_mangle]
pub extern "C" fn privacy_core_commit_welcome_message_bytes(commit: u64, index: usize) -> ByteBuffer {
    with_bytes_result(|| commit_welcome_message_bytes(commit, index))
}

#[no_mangle]
pub extern "C" fn privacy_core_commit_joined_group_handle(commit: u64, index: usize) -> u64 {
    with_handle_result(|| commit_joined_group_handle(commit, index))
}

#[no_mangle]
pub extern "C" fn privacy_core_create_dm_session(initiator_identity: u64, responder_key_package: u64) -> i64 {
    with_i64_result(|| create_dm_session(initiator_identity, responder_key_package).map(|handle| handle as i64))
}

#[no_mangle]
pub extern "C" fn privacy_core_dm_encrypt(
    session: u64,
    plaintext: *const u8,
    len: usize,
    out_buf: *mut u8,
    out_cap: usize,
) -> i64 {
    with_i64_result(|| {
        let plaintext = bytes_from_raw(plaintext, len)?;
        stage_or_write_output(1, session, input_hash(plaintext), out_buf, out_cap, || {
            dm_encrypt(session, plaintext)
        })
    })
}

#[no_mangle]
pub extern "C" fn privacy_core_dm_decrypt(
    session: u64,
    ciphertext: *const u8,
    len: usize,
    out_buf: *mut u8,
    out_cap: usize,
) -> i64 {
    with_i64_result(|| {
        let ciphertext = bytes_from_raw(ciphertext, len)?;
        stage_or_write_output(2, session, input_hash(ciphertext), out_buf, out_cap, || {
            dm_decrypt(session, ciphertext)
        })
    })
}

#[no_mangle]
pub extern "C" fn privacy_core_dm_session_welcome(
    session: u64,
    out_buf: *mut u8,
    out_cap: usize,
) -> i64 {
    with_i64_result(|| stage_or_write_output(3, session, 0, out_buf, out_cap, || dm_session_welcome(session)))
}

#[no_mangle]
pub extern "C" fn privacy_core_join_dm_session(
    responder_identity: u64,
    welcome: *const u8,
    len: usize,
) -> i64 {
    with_i64_result(|| join_dm_session(responder_identity, bytes_from_raw(welcome, len)?).map(|handle| handle as i64))
}

#[no_mangle]
pub extern "C" fn privacy_core_release_dm_session(session: u64) -> i32 {
    with_i32_result(|| release_dm_session(session))
}

#[no_mangle]
pub extern "C" fn privacy_core_release_identity(handle: u64) -> bool {
    with_bool_result(|| {
        let Ok(mut guard) = identities().lock() else {
            return Err("identities mutex poisoned".to_string());
        };
        Ok(guard.remove(&handle).is_some())
    })
}

#[no_mangle]
pub extern "C" fn privacy_core_release_key_package(handle: u64) -> bool {
    with_bool_result(|| {
        let Ok(mut guard) = key_packages().lock() else {
            return Err("key packages mutex poisoned".to_string());
        };
        Ok(guard.remove(&handle).is_some())
    })
}

#[no_mangle]
pub extern "C" fn privacy_core_release_group(handle: u64) -> bool {
    with_bool_result(|| {
        let Ok(mut groups_guard) = groups().lock() else {
            return Err("groups mutex poisoned".to_string());
        };
        let removed = groups_guard.remove(&handle);
        drop(groups_guard);

        if let Some(state) = removed {
            let Ok(mut families_guard) = families().lock() else {
                return Err("families mutex poisoned".to_string());
            };
            if let Some(entries) = families_guard.get_mut(&state.family_id) {
                entries.retain(|candidate| candidate != &handle);
            }
            Ok(true)
        } else {
            Ok(false)
        }
    })
}

#[no_mangle]
pub extern "C" fn privacy_core_release_commit(handle: u64) -> bool {
    with_bool_result(|| {
        let Ok(mut guard) = commits().lock() else {
            return Err("commits mutex poisoned".to_string());
        };
        Ok(guard.remove(&handle).is_some())
    })
}

#[no_mangle]
pub extern "C" fn privacy_core_reset_all_state() -> bool {
    with_bool_result(|| {
        let Ok(mut identities_guard) = identities().lock() else {
            return Err("identities mutex poisoned".to_string());
        };
        identities_guard.clear();
        drop(identities_guard);

        let Ok(mut key_packages_guard) = key_packages().lock() else {
            return Err("key packages mutex poisoned".to_string());
        };
        key_packages_guard.clear();
        drop(key_packages_guard);

        let Ok(mut groups_guard) = groups().lock() else {
            return Err("groups mutex poisoned".to_string());
        };
        groups_guard.clear();
        drop(groups_guard);

        let Ok(mut commits_guard) = commits().lock() else {
            return Err("commits mutex poisoned".to_string());
        };
        commits_guard.clear();
        drop(commits_guard);

        let Ok(mut dm_sessions_guard) = dm_sessions().lock() else {
            return Err("dm sessions mutex poisoned".to_string());
        };
        dm_sessions_guard.clear();
        drop(dm_sessions_guard);

        let Ok(mut families_guard) = families().lock() else {
            return Err("families mutex poisoned".to_string());
        };
        families_guard.clear();
        drop(families_guard);

        let Ok(mut exported_guard) = exported_key_packages().lock() else {
            return Err("exported key packages mutex poisoned".to_string());
        };
        exported_guard.clear();
        drop(exported_guard);

        let Ok(mut pending_outputs_guard) = pending_dm_outputs().lock() else {
            return Err("pending dm outputs mutex poisoned".to_string());
        };
        for (_key, (mut bytes, _inserted_at)) in pending_outputs_guard.drain() {
            wipe_vec(&mut bytes);
        }
        drop(pending_outputs_guard);

        let Ok(mut pending_lookup_guard) = pending_dm_output_lookups().lock() else {
            return Err("pending dm output lookup mutex poisoned".to_string());
        };
        pending_lookup_guard.clear();
        drop(pending_lookup_guard);

        let Ok(mut pending_counter_guard) = pending_dm_output_counters().lock() else {
            return Err("pending dm output counters mutex poisoned".to_string());
        };
        pending_counter_guard.clear();
        drop(pending_counter_guard);

        clear_last_error();
        Ok(true)
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Mutex, OnceLock};

    fn test_lock() -> &'static Mutex<()> {
        static TEST_LOCK: OnceLock<Mutex<()>> = OnceLock::new();
        TEST_LOCK.get_or_init(|| Mutex::new(()))
    }

    #[test]
    fn dm_session_round_trip() {
        let _guard = test_lock().lock().expect("test lock poisoned");
        privacy_core_reset_all_state();

        let alice = create_identity().expect("alice identity");
        let bob = create_identity().expect("bob identity");
        let bob_key_package = export_key_package(bob).expect("bob key package");
        let bob_package_handle = import_key_package(&bob_key_package).expect("import bob key package");

        let alice_session = create_dm_session(alice, bob_package_handle).expect("alice session");
        let welcome = dm_session_welcome(alice_session).expect("welcome");
        let bob_session = join_dm_session(bob, &welcome).expect("bob session");

        let ct1 = dm_encrypt(alice_session, b"hello bob").expect("encrypt alice->bob");
        let pt1 = dm_decrypt(bob_session, &ct1).expect("decrypt alice->bob");
        assert_eq!(pt1, b"hello bob");

        let ct2 = dm_encrypt(bob_session, b"hello alice").expect("encrypt bob->alice");
        let pt2 = dm_decrypt(alice_session, &ct2).expect("decrypt bob->alice");
        assert_eq!(pt2, b"hello alice");

        assert_eq!(release_dm_session(alice_session).expect("release alice"), 1);
        assert_eq!(release_dm_session(bob_session).expect("release bob"), 1);
        assert_eq!(release_dm_session(alice_session).expect("release missing"), 0);
    }

    #[test]
    fn identity_limit_rejects_overflow() {
        let _guard = test_lock().lock().expect("test lock poisoned");
        privacy_core_reset_all_state();

        for _ in 0..MAX_IDENTITIES {
            create_identity().expect("identity within limit");
        }

        assert_eq!(
            create_identity().expect_err("identity overflow"),
            "identity limit reached"
        );
    }

    #[test]
    fn group_encrypt_rejects_oversized_plaintext() {
        let _guard = test_lock().lock().expect("test lock poisoned");
        privacy_core_reset_all_state();

        let owner = create_identity().expect("owner identity");
        let group = create_group(owner).expect("group");

        let ok_plaintext = vec![b'a'; 60 * 1024];
        assert!(encrypt_group_message(group, &ok_plaintext).is_ok());

        let too_large = vec![b'b'; 100 * 1024];
        let err = encrypt_group_message(group, &too_large).expect_err("oversized group plaintext");
        assert!(err.contains("group plaintext too large"));
    }

    #[test]
    fn add_member_respects_group_limit_when_join_registers_new_handle() {
        let _guard = test_lock().lock().expect("test lock poisoned");
        privacy_core_reset_all_state();

        let owner = create_identity().expect("owner identity");
        let recipient = create_identity().expect("recipient identity");
        let recipient_bundle = export_key_package(recipient).expect("recipient bundle");
        let recipient_package = import_key_package(&recipient_bundle).expect("recipient package");

        let mut last_group = 0;
        for _ in 0..MAX_GROUPS {
            last_group = create_group(owner).expect("group within limit");
        }

        let err = add_member(last_group, recipient_package).expect_err("group limit overflow");
        assert_eq!(err, "maximum group limit reached");
    }

    #[test]
    fn staged_outputs_keep_sequential_same_session_requests_distinct() {
        let _guard = test_lock().lock().expect("test lock poisoned");
        privacy_core_reset_all_state();

        let first_required = stage_or_write_output(1, 77, 99, std::ptr::null_mut(), 0, || {
            Ok(b"first-output".to_vec())
        })
        .expect("stage first");
        let second_required = stage_or_write_output(1, 77, 99, std::ptr::null_mut(), 0, || {
            Ok(b"second-output".to_vec())
        })
        .expect("stage second");

        assert_eq!(first_required, 12);
        assert_eq!(second_required, 13);

        let mut first_buf = [0u8; 32];
        let first_written = stage_or_write_output(1, 77, 99, first_buf.as_mut_ptr(), first_buf.len(), || {
            Ok(b"unexpected".to_vec())
        })
        .expect("retrieve first");
        assert_eq!(first_written, 12);
        assert_eq!(&first_buf[..first_written as usize], b"first-output");

        let mut second_buf = [0u8; 32];
        let second_written =
            stage_or_write_output(1, 77, 99, second_buf.as_mut_ptr(), second_buf.len(), || {
                Ok(b"unexpected".to_vec())
            })
            .expect("retrieve second");
        assert_eq!(second_written, 13);
        assert_eq!(&second_buf[..second_written as usize], b"second-output");
    }
}
