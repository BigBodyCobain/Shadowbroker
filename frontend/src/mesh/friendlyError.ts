/**
 * Turn backend/control-plane error codes into sentences a user can act on.
 *
 * Raw codes such as `wormhole_required_for_gate_compose` or
 * `control_plane_request_failed:403` are useful for debugging but read as
 * hostile in the UI. Unknown machine-style codes keep the code in brackets so
 * support can still identify them.
 */

interface Rule {
  test: (lower: string) => boolean;
  text: string;
}

const has = (...needles: string[]) => (lower: string) => needles.some((n) => lower.includes(n));

const RULES: Rule[] = [
  {
    test: has('failed to fetch', 'networkerror', 'network error', 'backend_unavailable', 'load failed'),
    text: 'Could not reach your ShadowBroker backend. Check that it is running, then try again.',
  },
  {
    test: has('local_control_plane_unavailable'),
    text: 'The local ShadowBroker service is not answering yet. Give it a moment and try again.',
  },
  {
    test: has('control_plane_rate_limited', 'rate limit', 'too many requests', 'cooldown'),
    text: 'That was a lot of requests in a short time. Wait a few seconds and try again.',
  },
  {
    test: has('control_plane_request_failed:401', 'control_plane_request_failed:403', 'access denied', 'forbidden'),
    text: 'This action is only available on the computer running ShadowBroker.',
  },
  {
    test: has(
      'wormhole_required',
      'hidden transport required',
      'wormhole required',
      'transport tier insufficient',
      'requires private transport',
      'private lane',
      'preparing_private_lane',
    ),
    text: 'The private connection is still starting. This usually takes under a minute the first time; your message is kept until it is ready.',
  },
  {
    test: has('privacy_core_attestation', 'privacy-core', 'privacy core'),
    text: 'The private messaging library is not set up on this node. Restart ShadowBroker with the start script so it can build and register it.',
  },
  {
    test: has('gate access still syncing', 'gate_state_stale', 'gate state resynced', 'gate_state_resync'),
    text: 'This room is still syncing. Try again in a moment.',
  },
  {
    test: has('gate_local_runtime_required', 'local gate crypto is unavailable'),
    text: 'This browser cannot run the room encryption locally. Open ShadowBroker in the desktop app or a current Chrome, Edge or Firefox.',
  },
  {
    test: has('gate_envelope_required', 'gate_envelope_encrypt_failed', 'gate secret unavailable', 'gatesecretunavailable'),
    text: 'This room key is not ready on this node yet. Try again in a moment.',
  },
  {
    test: has('no active gate identity', 'not mapped into the mls group'),
    text: 'Join the room first, then post.',
  },
  {
    test: has('gate_mls_compose_failed', 'gate_sign_failed', 'gate post failed', 'replay', 'sequence'),
    text: 'Your post did not go through. Try again.',
  },
  {
    test: has(': mismatch', 'continuity_broken', 'identity changed', 'prekey changed', 'key mismatch'),
    text: "This contact's security keys changed. Compare safety codes with them before sending anything sensitive.",
  },
  {
    test: has('verified first contact required', 'import a signed invite', 'not a dm contact'),
    text: 'Add this person as a contact first: paste the contact address or invite they shared with you.',
  },
  {
    test: has('prekey bundle not found', 'prekey lookup unavailable', 'delivery key has not reached', 'recipient unresolved'),
    text: "That contact isn't reachable yet. Ask them to open ShadowBroker, or to share a fresh contact address.",
  },
  {
    test: has('dm_mls_initiate_failed', 'dm_mls_accept_failed', 'dm session', 'session_expired'),
    text: 'The secure chat session with this contact needs to be re-established. Send the message again; if it keeps failing, re-add the contact.',
  },
  {
    test: has('invite not found or expired'),
    text: 'That invite has expired or was already handled.',
  },
];

const MACHINE_CODE = /^[a-z0-9_.:-]+$/;

export function friendlyInfonetError(raw: unknown, fallback = 'Something went wrong. Try again.'): string {
  const text = String(
    raw instanceof Error ? raw.message : typeof raw === 'string' ? raw : (raw as { message?: string })?.message || '',
  ).trim();
  if (!text) return fallback;
  const lower = text.toLowerCase();
  for (const rule of RULES) {
    if (rule.test(lower)) return rule.text;
  }
  // Snake_case codes are not sentences; keep the code for support.
  if (MACHINE_CODE.test(text) && !text.includes(' ')) {
    return `${fallback} (${text})`;
  }
  return text;
}
