/**
 * Infonet economy / governance / gates / bootstrap HTTP client.
 *
 * Pairs with backend/routers/infonet.py. Every function returns the
 * shape declared by the router; if the backend is unavailable, the
 * returned promise rejects with the network error.
 *
 * Cross-cutting design rule (BUILD_LOG.md):
 * - Errors surfaced from validation are diagnostic, not punitive.
 *   The `ok: false, reason: "..."` shape carries a specific failure
 *   so the UI can render "you need 5 more rep" instead of "denied".
 */

const BASE = '/api/infonet';

async function jsonGet<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { credentials: 'include' });
  if (!res.ok && res.status !== 400) {
    throw new Error(`infonet ${path}: HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

async function jsonPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    credentials: 'include',
  });
  // 400 is "ok-shaped error" carrying {ok:false, reason}; let it through.
  if (!res.ok && res.status !== 400) {
    throw new Error(`infonet ${path}: HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

// ─── Status ──────────────────────────────────────────────────────────────

export interface RampFlags {
  node_count: number;
  bootstrap_resolution_active: boolean;
  staked_resolution_active: boolean;
  governance_petitions_active: boolean;
  upgrade_governance_active: boolean;
  commoncoin_active: boolean;
}

export interface InfonetStatus {
  ok: true;
  now: number;
  chain_majority_time: number;
  chain_event_count: number;
  chain_stale: boolean;
  ramp: RampFlags;
  privacy_primitive_status: {
    ringct: string;
    stealth_address: string;
    shielded_balance: string;
    dex: string;
  };
  immutable_principles: Record<string, string | boolean>;
  config_keys_count: number;
  infonet_economy_event_types_count: number;
}

export function fetchInfonetStatus(): Promise<InfonetStatus> {
  return jsonGet<InfonetStatus>('/status');
}

// ─── Petitions ───────────────────────────────────────────────────────────

export type PetitionPayload =
  | { type: 'UPDATE_PARAM'; key: string; value: unknown }
  | { type: 'BATCH_UPDATE_PARAMS'; updates: Array<{ key: string; value: unknown }> }
  | { type: 'ENABLE_FEATURE'; feature: string }
  | { type: 'DISABLE_FEATURE'; feature: string };

export interface PetitionState {
  petition_id: string;
  status: string;
  filer_id: string;
  filed_at: number;
  petition_payload: PetitionPayload | Record<string, unknown>;
  signature_governance_weight: number;
  signature_threshold_at_filing: number;
  votes_for_weight: number;
  votes_against_weight: number;
  voting_deadline: number | null;
  challenge_window_until: number | null;
}

export interface PetitionsList {
  ok: true;
  now: number;
  petitions: PetitionState[];
}

export function fetchPetitions(): Promise<PetitionsList> {
  return jsonGet<PetitionsList>('/petitions');
}

export interface PetitionPreview {
  ok: boolean;
  changed_keys?: string[];
  new_values?: Record<string, unknown>;
  reason?: string;
}

export function previewPetitionPayload(
  payload: PetitionPayload,
): Promise<PetitionPreview> {
  return jsonPost<PetitionPreview>('/petitions/preview', payload);
}

// ─── Event payload validation ────────────────────────────────────────────

export interface EventValidation {
  ok: boolean;
  reason: string | null;
  tier: string;
  would_be_provisional: boolean;
}

export function validateEventPayload(
  event_type: string,
  payload: Record<string, unknown>,
): Promise<EventValidation> {
  return jsonPost<EventValidation>('/events/validate', { event_type, payload });
}

// ─── Upgrades ────────────────────────────────────────────────────────────

export interface UpgradeProposalSummary {
  proposal_id: string;
  status: string;
  proposer_id: string;
  filed_at: number;
  release_hash: string;
  target_protocol_version: string;
  votes_for_weight: number;
  votes_against_weight: number;
  readiness_fraction: number;
  readiness_threshold_met: boolean;
}

export function fetchUpgrades(): Promise<{ ok: true; now: number; upgrades: UpgradeProposalSummary[] }> {
  return jsonGet('/upgrades');
}

export function fetchUpgrade(proposalId: string) {
  return jsonGet<{ ok: true; now: number; upgrade: Record<string, unknown> }>(
    `/upgrades/${encodeURIComponent(proposalId)}`,
  );
}

// ─── Markets ─────────────────────────────────────────────────────────────

export interface EvidenceBundleSummary {
  node_id: string;
  claimed_outcome: 'yes' | 'no';
  evidence_hashes: string[];
  source_description: string;
  bond: number;
  timestamp: number;
  is_first_for_side: boolean;
  submission_hash: string;
}

export interface DisputeSummary {
  dispute_id: string;
  challenger_id: string;
  challenger_stake: number;
  opened_at: number;
  is_resolved: boolean;
  resolved_outcome: string | null;
  confirm_stakes: Array<{ node_id: string; amount: number; rep_type: string }>;
  reverse_stakes: Array<{ node_id: string; amount: number; rep_type: string }>;
}

export interface MarketState {
  ok: true;
  market_id: string;
  status: string;
  snapshot: Record<string, unknown> | null;
  evidence_bundles: EvidenceBundleSummary[];
  excluded_predictor_ids: string[];
  disputes: DisputeSummary[];
  was_reversed: boolean;
  now: number;
}

export function fetchMarketState(marketId: string): Promise<MarketState> {
  return jsonGet<MarketState>(`/markets/${encodeURIComponent(marketId)}`);
}

export interface ResolutionPreview {
  ok: true;
  preview: {
    outcome: 'yes' | 'no' | 'invalid';
    reason: string;
    is_provisional: boolean;
    burned_amount: number;
    stake_returns: Array<{ node_id: string; rep_type: string; amount: number }>;
    stake_winnings: Array<{ node_id: string; rep_type: string; amount: number }>;
    bond_returns: Array<{ node_id: string; amount: number }>;
    bond_forfeits: Array<{ node_id: string; amount: number }>;
    first_submitter_bonuses: Array<{ node_id: string; amount: number }>;
  };
}

export function previewMarketResolution(marketId: string): Promise<ResolutionPreview> {
  return jsonGet<ResolutionPreview>(
    `/markets/${encodeURIComponent(marketId)}/preview-resolution`,
  );
}

// ─── Gates ───────────────────────────────────────────────────────────────

export interface GateMetaSummary {
  creator_node_id: string;
  display_name: string;
  entry_sacrifice: number;
  min_overall_rep: number;
  min_gate_rep: Record<string, number>;
  created_at: number;
}

export interface GateState {
  ok: true;
  gate_id: string;
  meta: GateMetaSummary;
  members: string[];
  ratified: boolean;
  cumulative_member_oracle_rep: number;
  locked: { is_locked: boolean; locked_at: number | null; locked_by: string[] };
  suspension: {
    status: 'active' | 'suspended' | 'shutdown';
    suspended_at: number | null;
    suspended_until: number | null;
    last_shutdown_petition_at: number | null;
  };
  shutdown: {
    has_pending: boolean;
    pending_petition_id: string | null;
    pending_status: string | null;
    execution_at: number | null;
    executed: boolean;
  };
  now: number;
}

export interface GateNotFound {
  ok: false;
  reason: string;
}

export function fetchGateState(gateId: string): Promise<GateState | GateNotFound> {
  return jsonGet<GateState | GateNotFound>(`/gates/${encodeURIComponent(gateId)}`);
}

// ─── Reputation ──────────────────────────────────────────────────────────

export interface NodeReputation {
  ok: true;
  node_id: string;
  oracle_rep: number;
  oracle_rep_active: number;
  oracle_rep_lifetime: number;
  common_rep: number;
  decay_factor: number;
  last_successful_prediction_ts: number | null;
  breakdown: {
    free_prediction_mints: number;
    staked_prediction_returns: number;
    staked_prediction_losses: number;
    total: number;
  };
}

export function fetchNodeReputation(nodeId: string): Promise<NodeReputation> {
  return jsonGet<NodeReputation>(`/nodes/${encodeURIComponent(nodeId)}/reputation`);
}

// ─── Bootstrap ───────────────────────────────────────────────────────────

export interface BootstrapMarketState {
  ok: true;
  market_id: string;
  votes: Array<{
    node_id: string;
    side: string;
    eligible: boolean;
    ineligible_reason: string | null;
  }>;
  tally: {
    yes: number;
    no: number;
    total_eligible: number;
    min_market_participants: number;
    supermajority_threshold: number;
  };
}

export function fetchBootstrapMarketState(marketId: string): Promise<BootstrapMarketState> {
  return jsonGet<BootstrapMarketState>(`/bootstrap/markets/${encodeURIComponent(marketId)}`);
}

// ─── Signed write: append an Infonet economy event ───────────────────────

/**
 * Pre-signed event payload to append to the chain.
 *
 * The CALLER signs the canonical payload using the local node's
 * private key before submitting. ``mesh_hashchain.Infonet.append``
 * (the secure server-side entry point) verifies signature, public-key
 * binding, replay protection, and sequence ordering.
 *
 * Production frontend code uses ``meshIdentity.signEventPayload(...)``
 * (or equivalent) to produce the signature before calling this.
 */
export interface SignedEventBody {
  event_type: string;
  node_id: string;
  payload: Record<string, unknown>;
  signature: string;          // hex
  sequence: number;           // node-monotonic, > 0
  public_key: string;         // base64
  public_key_algo: 'ed25519' | 'ecdsa';
  protocol_version?: string;
}

export interface AppendOk {
  ok: true;
  event: {
    event_id: string;
    event_type: string;
    node_id: string;
    timestamp: number;
    sequence: number;
    payload: Record<string, unknown>;
    [key: string]: unknown;
  };
}

export interface AppendError {
  ok: false;
  reason: string;
}

export type AppendResult = AppendOk | AppendError;

/**
 * Append a signed Infonet economy event to the chain.
 *
 * Cross-cutting non-hostile UX rule: ``reason`` on failure carries
 * the verbatim diagnostic from the secure entry point — surface it
 * directly in the UI so the user can act on it.
 */
export function appendEvent(body: SignedEventBody): Promise<AppendResult> {
  return jsonPost<AppendResult>('/append', body);
}

// Convenience builders. Each builds the structured payload the
// backend validators expect, then the caller wraps with signing
// metadata before calling ``appendEvent``.

export function buildUprepPayload(
  targetNodeId: string,
  targetEventId: string,
): { event_type: 'uprep'; payload: Record<string, unknown> } {
  return {
    event_type: 'uprep',
    payload: { target_node_id: targetNodeId, target_event_id: targetEventId },
  };
}

export function buildPetitionFilePayload(
  petitionId: string,
  petitionPayload: PetitionPayload,
): { event_type: 'petition_file'; payload: Record<string, unknown> } {
  return {
    event_type: 'petition_file',
    payload: { petition_id: petitionId, petition_payload: petitionPayload },
  };
}

export function buildPetitionVotePayload(
  petitionId: string,
  vote: 'for' | 'against',
): { event_type: 'petition_vote'; payload: Record<string, unknown> } {
  return {
    event_type: 'petition_vote',
    payload: { petition_id: petitionId, vote },
  };
}

export function buildPetitionSignPayload(
  petitionId: string,
): { event_type: 'petition_sign'; payload: Record<string, unknown> } {
  return {
    event_type: 'petition_sign',
    payload: { petition_id: petitionId },
  };
}

export function buildChallengeFilePayload(
  petitionId: string,
  reason: string,
): { event_type: 'challenge_file'; payload: Record<string, unknown> } {
  return {
    event_type: 'challenge_file',
    payload: { petition_id: petitionId, reason },
  };
}

export function buildGateSuspendFilePayload(
  petitionId: string,
  gateId: string,
  reason: string,
  evidenceHashes: string[],
): { event_type: 'gate_suspend_file'; payload: Record<string, unknown> } {
  return {
    event_type: 'gate_suspend_file',
    payload: {
      petition_id: petitionId,
      gate_id: gateId,
      reason,
      evidence_hashes: evidenceHashes,
    },
  };
}

export function buildBootstrapResolutionVotePayload(
  marketId: string,
  side: 'yes' | 'no',
  powNonce: number,
): { event_type: 'bootstrap_resolution_vote'; payload: Record<string, unknown> } {
  return {
    event_type: 'bootstrap_resolution_vote',
    payload: { market_id: marketId, side, pow_nonce: powNonce },
  };
}

// ─── End-to-end sign + append helper ────────────────────────────────────

/**
 * Pull the local node identity, advance the sequence counter, sign the
 * canonical payload via the WebCrypto helpers in ``meshIdentity``, and
 * post the signed event to ``/api/infonet/append``.
 *
 * Cross-cutting non-hostile UX rule: every failure mode returns the
 * verbatim diagnostic from the backend so the UI surfaces it directly.
 *
 * Returns the same ``AppendResult`` shape as ``appendEvent`` plus a
 * pre-flight rejection when the local identity isn't loaded yet.
 */
export async function signAndAppend(args: {
  event_type: string;
  payload: Record<string, unknown>;
}): Promise<AppendResult> {
  // Lazy import — keeps the client lightweight for callers that only
  // use the read endpoints. Same module, same browser tab.
  const meshIdentity = await import('@/mesh/meshIdentity');
  const identity = meshIdentity.getNodeIdentity();
  if (!identity || !identity.publicKey) {
    return {
      ok: false,
      reason: 'node_identity_not_loaded — open the InfonetTerminal so the local key materializes, then retry',
    };
  }
  const nodeId = await meshIdentity.deriveNodeIdFromPublicKey(identity.publicKey);
  const sequence = meshIdentity.nextSequence();
  let signature: string;
  try {
    signature = await meshIdentity.signEvent(
      args.event_type,
      nodeId,
      sequence,
      args.payload,
    );
  } catch (err) {
    return {
      ok: false,
      reason: `signing_failed: ${err instanceof Error ? err.message : String(err)}`,
    };
  }
  const algo = meshIdentity.getStoredNodeDescriptor()?.publicKeyAlgo
    ?? 'Ed25519';
  return appendEvent({
    event_type: args.event_type,
    node_id: nodeId,
    payload: args.payload,
    signature,
    sequence,
    public_key: identity.publicKey,
    public_key_algo: algo.toLowerCase() === 'ecdsa' ? 'ecdsa' : 'ed25519',
  });
}

// ─── Additional payload builders (write-action wiring phase) ─────────────

export function buildChallengeVotePayload(
  petitionId: string,
  vote: 'uphold' | 'void',
): { event_type: 'challenge_vote'; payload: Record<string, unknown> } {
  return {
    event_type: 'challenge_vote',
    payload: { petition_id: petitionId, vote },
  };
}

export function buildResolutionStakePayload(
  marketId: string,
  side: 'yes' | 'no' | 'data_unavailable',
  amount: number,
  repType: 'oracle' | 'common',
): { event_type: 'resolution_stake'; payload: Record<string, unknown> } {
  return {
    event_type: 'resolution_stake',
    payload: { market_id: marketId, side, amount, rep_type: repType },
  };
}

export function buildDisputeOpenPayload(
  marketId: string,
  challengerStake: number,
  reason: string,
): { event_type: 'dispute_open'; payload: Record<string, unknown> } {
  return {
    event_type: 'dispute_open',
    payload: { market_id: marketId, challenger_stake: challengerStake, reason },
  };
}

export function buildDisputeStakePayload(
  disputeId: string,
  side: 'confirm' | 'reverse',
  amount: number,
  repType: 'oracle' | 'common',
): { event_type: 'dispute_stake'; payload: Record<string, unknown> } {
  return {
    event_type: 'dispute_stake',
    payload: { dispute_id: disputeId, side, amount, rep_type: repType },
  };
}

export function buildGateShutdownFilePayload(
  petitionId: string,
  gateId: string,
  reason: string,
  evidenceHashes: string[],
): { event_type: 'gate_shutdown_file'; payload: Record<string, unknown> } {
  return {
    event_type: 'gate_shutdown_file',
    payload: {
      petition_id: petitionId,
      gate_id: gateId,
      reason,
      evidence_hashes: evidenceHashes,
    },
  };
}

export function buildGateShutdownAppealFilePayload(
  petitionId: string,
  gateId: string,
  targetPetitionId: string,
  reason: string,
  evidenceHashes: string[],
): { event_type: 'gate_shutdown_appeal_file'; payload: Record<string, unknown> } {
  return {
    event_type: 'gate_shutdown_appeal_file',
    payload: {
      petition_id: petitionId,
      gate_id: gateId,
      target_petition_id: targetPetitionId,
      reason,
      evidence_hashes: evidenceHashes,
    },
  };
}

export function buildUpgradeSignPayload(
  proposalId: string,
): { event_type: 'upgrade_sign'; payload: Record<string, unknown> } {
  return {
    event_type: 'upgrade_sign',
    payload: { proposal_id: proposalId },
  };
}

export function buildUpgradeVotePayload(
  proposalId: string,
  vote: 'for' | 'against',
): { event_type: 'upgrade_vote'; payload: Record<string, unknown> } {
  return {
    event_type: 'upgrade_vote',
    payload: { proposal_id: proposalId, vote },
  };
}

/**
 * Generate a fresh local-side identifier suitable for petition_id /
 * dispute_id / proposal_id. Random + timestamp so refile attempts
 * produce distinct IDs (no replay).
 */
export function freshLocalId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e6).toString(36)}`;
}

// ─── Evidence canonicalization (mirrors services/infonet/markets/evidence.py) ──

function bytesToHex(bytes: ArrayBuffer): string {
  const arr = new Uint8Array(bytes);
  let hex = '';
  for (let i = 0; i < arr.length; i += 1) {
    hex += arr[i].toString(16).padStart(2, '0');
  }
  return hex;
}

async function sha256Hex(input: string): Promise<string> {
  const data = new TextEncoder().encode(input);
  const digest = await crypto.subtle.digest('SHA-256', data);
  return bytesToHex(digest);
}

/**
 * Match Python's ``repr(float)`` — integer-valued floats keep the
 * trailing ``.0``. Required because the backend's ``submission_hash``
 * uses ``repr(float(timestamp))`` and we have to produce the exact
 * same canonical string for the SHA-256 to match.
 */
function pythonReprFloat(x: number): string {
  if (!Number.isFinite(x)) {
    throw new Error(`pythonReprFloat: ${x} is not a finite number`);
  }
  const s = String(x);
  if (Number.isInteger(x) && !s.includes('.') && !s.includes('e')) {
    return `${s}.0`;
  }
  return s;
}

/**
 * SHA-256 of canonical evidence content. Mirrors
 * ``services/infonet/markets/evidence.py:evidence_content_hash``.
 * Excludes node_id — used for cross-author duplicate detection.
 */
export async function evidenceContentHash(args: {
  marketId: string;
  claimedOutcome: 'yes' | 'no';
  evidenceHashes: string[];
  sourceDescription: string;
}): Promise<string> {
  const sorted = [...(args.evidenceHashes || [])].map(String).sort();
  const canonical = [
    'evidence_content',
    args.marketId,
    args.claimedOutcome,
    sorted.join(','),
    String(args.sourceDescription || '').normalize('NFC'),
  ].join('|');
  return sha256Hex(canonical);
}

/**
 * SHA-256 of ``content_hash || node_id || repr(timestamp)``. Mirrors
 * ``services/infonet/markets/evidence.py:submission_hash``. Includes
 * node_id — used for authorship + chain ordering.
 */
export async function submissionHash(args: {
  contentHash: string;
  nodeId: string;
  timestamp: number;
}): Promise<string> {
  const canonical = [
    'evidence_submission',
    args.contentHash,
    args.nodeId,
    pythonReprFloat(args.timestamp),
  ].join('|');
  return sha256Hex(canonical);
}

/**
 * Build a fully-formed ``evidence_submit`` payload with both
 * canonical hashes computed locally. Async because it pulls the
 * local node identity and runs WebCrypto SHA-256.
 *
 * The caller wraps the result with ``signAndAppend``.
 */
export async function buildEvidenceSubmitPayload(args: {
  marketId: string;
  claimedOutcome: 'yes' | 'no';
  evidenceHashes: string[];
  sourceDescription: string;
  bond: number;
}): Promise<{
  event_type: 'evidence_submit';
  payload: Record<string, unknown>;
}> {
  const meshIdentity = await import('@/mesh/meshIdentity');
  const identity = meshIdentity.getNodeIdentity();
  if (!identity?.publicKey) {
    throw new Error(
      'node_identity_not_loaded — open the InfonetTerminal so the local key materializes',
    );
  }
  const nodeId = await meshIdentity.deriveNodeIdFromPublicKey(identity.publicKey);
  const timestamp = Date.now() / 1000;
  const contentHash = await evidenceContentHash({
    marketId: args.marketId,
    claimedOutcome: args.claimedOutcome,
    evidenceHashes: args.evidenceHashes,
    sourceDescription: args.sourceDescription,
  });
  const subHash = await submissionHash({
    contentHash,
    nodeId,
    timestamp,
  });
  return {
    event_type: 'evidence_submit',
    payload: {
      market_id: args.marketId,
      claimed_outcome: args.claimedOutcome,
      evidence_hashes: args.evidenceHashes,
      source_description: args.sourceDescription,
      evidence_content_hash: contentHash,
      submission_hash: subHash,
      bond: args.bond,
    },
  };
}

// ─── Upgrade-hash governance — propose / signal-ready ──────────────────

export function buildUpgradeProposePayload(args: {
  proposalId: string;
  releaseHash: string;
  releaseDescription: string;
  targetProtocolVersion: string;
  releaseUrl?: string;
  compatibilityNotes?: string;
}): { event_type: 'upgrade_propose'; payload: Record<string, unknown> } {
  return {
    event_type: 'upgrade_propose',
    payload: {
      proposal_id: args.proposalId,
      release_hash: args.releaseHash,
      release_description: args.releaseDescription,
      target_protocol_version: args.targetProtocolVersion,
      ...(args.releaseUrl ? { release_url: args.releaseUrl } : {}),
      ...(args.compatibilityNotes ? { compatibility_notes: args.compatibilityNotes } : {}),
    },
  };
}

export function buildUpgradeSignalReadyPayload(
  proposalId: string,
  releaseHash: string,
): { event_type: 'upgrade_signal_ready'; payload: Record<string, unknown> } {
  return {
    event_type: 'upgrade_signal_ready',
    payload: { proposal_id: proposalId, release_hash: releaseHash },
  };
}
