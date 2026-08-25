/**
 * voiceDeterministic — zero-model console loop (voice-agent plan §3.7).
 *
 * Camera intents are matched first by regex and never reach route_query;
 * plain-language layer/time-machine phrases are resolved locally too. All
 * remaining text delegates to the server's `route_query` command through the
 * gated stateless endpoint POST /api/voice/tool — the same validate_and_gate →
 * dispatcher → verbatim-result path the LLM picker uses, with no model and no
 * third-party egress (geocoding rides the backend proxy like LocateBar).
 */
import { API_BASE } from '@/lib/api';
import { executeClientVerb, type ClientToolContext, type ToolResult } from './clientTools';

export interface TurnStep {
  tool: string | null;
  argsSummary: string;
  ok: boolean;
  /** Verbatim detail — static text for failures, real evidence for successes. */
  detail: string;
}

export interface DeterministicOutcome {
  steps: TurnStep[];
  reply: string;
}

export type DeterministicResolution =
  | { kind: 'client_verb'; tool: string; args: Record<string, unknown> }
  | { kind: 'geocode_fly_to'; label: string }
  | { kind: 'local_reply'; reply: string }
  | { kind: 'route_query' };

/** A route_query recommendation the backend gate blocked, awaiting 'confirm'. */
export interface PendingConfirmation {
  tool: string;
  args: Record<string, unknown>;
  kind: 'expensive' | 'destructive';
}

let pendingConfirmation: PendingConfirmation | null = null;

/** The gated recommendation awaiting an operator confirm, if any. */
export function getPendingConfirmation(): PendingConfirmation | null {
  return pendingConfirmation;
}

export function clearPendingConfirmation(): void {
  pendingConfirmation = null;
}

// Camera-intent regexes (§3.7) — mirrored from services/voice_tool_registry.py.
const RE_ORBIT_STOP = /\b(?:stop|cancel|end)\s+(?:the\s+)?orbit\b/i;
const RE_ORBIT = /\borbit\b/i;
const RE_ZOOM = /\bzoom\s+(in|out)\b/i;
const RE_FLY_TO =
  /\b(?:show|go|fly|jump|take\s+me)\s+(?:me\s+)?(?:to|over|towards)?\s*(?:the\s+)?([a-z0-9\u00c0-\u024f ,.'\-]{2,64})/i;

// Plain-language extensions so common console verbs work without any model.
const RE_LAYER_TOGGLE =
  /\b(?:toggle|enable|disable|turn\s+(?:on|off)|show|hide)\s+(?:the\s+)?([a-z0-9 _-]{2,40}?)\s+(?:layer|layers)\b/i;
const RE_TM_CONTROL =
  /\b(play|resume|pause|stop)\s+(?:the\s+)?time[ -]?machine\b/i;

// §3.7 item 2 — the operator's unlock word for a gated recommendation.
const RE_CONFIRM =
  /^\s*(?:confirm(?:\s+(?:it|the\s+\S+))?|yes|yeah|yep|y|go\s+ahead|do\s+it|run\s+it)\s*[.!]?\s*$/i;

function matchLayerKey(phrase: string, ctx: ClientToolContext): string | null {
  const wanted = phrase.trim().toLowerCase().replace(/\s+/g, '_');
  const keys = Object.keys(ctx.viewSummary().activeLayers);
  if (keys.includes(wanted)) return wanted;
  // Tolerate plural/singular drift ("ships layer" vs ships_military etc. only
  // on an exact normalized hit — never guess a substring layer).
  const singular = wanted.replace(/s$/, '');
  const hit = keys.find((k) => k === singular);
  return hit ?? null;
}

export function resolveDeterministic(text: string, ctx: ClientToolContext): DeterministicResolution {
  const raw = String(text || '').trim();
  if (!raw) return { kind: 'route_query' };

  if (RE_ORBIT_STOP.test(raw)) {
    return { kind: 'client_verb', tool: 'map_orbit', args: { stop: true, lng: 0, lat: 0 } };
  }
  const zoom = RE_ZOOM.exec(raw);
  if (zoom) {
    return { kind: 'client_verb', tool: 'map_zoom', args: { direction: zoom[1].toLowerCase() } };
  }
  if (RE_ORBIT.test(raw)) {
    // "orbit here" — the viewer pins the orbit to its current center.
    return { kind: 'client_verb', tool: 'map_orbit', args: { lng: 0, lat: 0, here: true } };
  }
  const tm = RE_TM_CONTROL.exec(raw);
  if (tm) {
    const verb = tm[1].toLowerCase();
    return {
      kind: 'client_verb',
      tool: 'tm_playback',
      args: { action: verb === 'resume' ? 'play' : verb },
    };
  }
  const toggle = RE_LAYER_TOGGLE.exec(raw);
  if (toggle) {
    const disable = /\b(disable|turn\s+off|hide)\b/i.test(raw);
    const layer = matchLayerKey(toggle[1], ctx);
    if (layer) {
      return { kind: 'client_verb', tool: 'toggle_layer', args: { layer, enabled: !disable } };
    }
    // Unknown layer phrase falls through to route_query rather than guessing.
  }
  const fly = RE_FLY_TO.exec(raw);
  if (fly) {
    const place = fly[1].trim().replace(/[\s.,'-]+$/, '');
    if (place.length >= 2) return { kind: 'geocode_fly_to', label: place };
  }
  return { kind: 'route_query' };
}

interface GeocodeHit {
  label: string;
  lat: number;
  lng: number;
}

async function geocodePlace(label: string): Promise<GeocodeHit | null> {
  const res = await fetch(
    `${API_BASE}/api/geocode/search?q=${encodeURIComponent(label)}&limit=1`,
  );
  if (!res.ok) return null;
  const data = await res.json();
  const first = Array.isArray(data?.results) ? data.results[0] : null;
  const lat = Number(first?.lat);
  const lng = Number(first?.lng);
  if (!first || !Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  return {
    label: String(first.label ?? label).slice(0, 200),
    lat: Math.min(90, Math.max(-90, lat)),
    lng: Math.min(180, Math.max(-180, lng)),
  };
}

async function postVoiceTool(
  tool: string,
  args: Record<string, unknown>,
  flags: { confirmExpensive?: boolean; confirm?: boolean } = {},
): Promise<ToolResult> {
  const res = await fetch(`${API_BASE}/api/voice/tool`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    // Confirm flags ride top-level (§3.6/U3): validate_and_gate consumes them
    // for its gates and strips them from clean_call.args — never rely on them
    // round-tripping inside `args`.
    body: JSON.stringify({
      tool,
      args,
      confirm_expensive: flags.confirmExpensive === true,
      confirm: flags.confirm === true,
    }),
  });
  let payload: Record<string, unknown> = {};
  try {
    payload = await res.json();
  } catch {
    return { ok: false, action: tool, error: `voice tool endpoint returned HTTP ${res.status}` };
  }
  // The endpoint returns the dispatcher envelope verbatim on success and a
  // gated error envelope (400) otherwise — pass either through untouched.
  if (payload.ok === true) {
    return { ...(payload as ToolResult), action: String(payload.action ?? tool) };
  }
  return {
    ok: false,
    action: tool,
    error: String(payload.detail ?? payload.error ?? `voice tool endpoint returned HTTP ${res.status}`),
    ...(typeof payload.code === 'string' ? { code: payload.code } : {}),
  };
}

/** Terse HUD-register templating from envelope leaf fields — never fabricates. */
function templateReply(cmd: string, envelope: ToolResult): string {
  const data = envelope.data;
  if (Array.isArray(data)) return `${cmd}: ${data.length} rows`;
  if (data && typeof data === 'object') {
    const obj = data as Record<string, unknown>;
    for (const key of ['count', 'total']) {
      if (typeof obj[key] === 'number') return `${cmd}: ${obj[key]}`;
    }
    for (const key of ['changed', 'alerts', 'results', 'correlations']) {
      const v = obj[key];
      if (Array.isArray(v)) return `${cmd}: ${v.length} ${key}`;
    }
    if (typeof obj.intent === 'string') return `${cmd}: routed to ${obj.intent}`;
  }
  return `${cmd}: done`;
}

/**
 * Run one deterministic console turn. Never throws — failures become honest
 * steps/replies carrying real error strings.
 */
export async function runDeterministicTurn(
  text: string,
  ctx: ClientToolContext,
): Promise<DeterministicOutcome> {
  const raw = String(text || '').trim();
  const resolution = resolveDeterministic(raw, ctx);
  const steps: TurnStep[] = [];

  const record = (result: ToolResult, tool: string, argsSummary: string): string => {
    steps.push({
      tool,
      argsSummary,
      ok: result.ok === true,
      detail: typeof result.error === 'string' ? result.error : '',
    });
    return result.ok === true ? '' : String(result.error ?? 'command failed');
  };

  // §3.7 item 2 — a gated recommendation awaits confirmation like the LLM
  // path: the bare unlock word re-runs it with the matching confirm flag;
  // any other input abandons it honestly and proceeds with the new text.
  if (pendingConfirmation && RE_CONFIRM.test(raw)) {
    const pending = pendingConfirmation;
    pendingConfirmation = null;
    const flags =
      pending.kind === 'expensive'
        ? { confirmExpensive: true }
        : { confirm: true };
    const confirmed = await postVoiceTool(pending.tool, pending.args, flags);
    const err = record(confirmed, pending.tool, '');
    if (err) return { steps, reply: err };
    return { steps, reply: templateReply(pending.tool, confirmed) };
  }
  if (pendingConfirmation) {
    pendingConfirmation = null;
    steps.push({ tool: null, argsSummary: '', ok: true, detail: 'pending confirmation discarded' });
  }

  if (resolution.kind === 'client_verb') {
    const args = { ...resolution.args };
    // Orbit verbs pin the animation to the viewer's current center.
    let centerMissing = false;
    if (args.here === true) {
      delete args.here;
      const view = await executeClientVerb('get_view_state', {}, ctx);
      const center = (view.view as { center?: { lat: number; lng: number } } | undefined)?.center;
      if (center && Number.isFinite(center.lat) && Number.isFinite(center.lng)) {
        args.lng = center.lng;
        args.lat = center.lat;
      } else {
        centerMissing = true;
      }
    }
    if (centerMissing) {
      steps.push({ tool: resolution.tool, argsSummary: '', ok: false, detail: 'map position unavailable' });
      return { steps, reply: 'Map position unavailable — cannot orbit yet.' };
    }
    const argSummary = Object.entries(args)
      .map(([k, v]) => `${k}=${String(v)}`)
      .join(', ');
    const result = await executeClientVerb(resolution.tool, args, ctx);
    const err = record(result, resolution.tool, argSummary);
    if (err) return { steps, reply: err };
    return {
      steps,
      reply:
        resolution.tool === 'map_orbit'
          ? result.orbiting
            ? 'Orbiting.'
            : 'Orbit stopped.'
          : resolution.tool === 'map_zoom'
            ? `Zoomed ${String(args.direction ?? 'in')}.`
            : resolution.tool === 'tm_playback'
              ? `Time Machine ${(args.action as string) ?? 'updated'}.`
              : `Layer ${(args.layer as string) ?? ''} ${(args.enabled as boolean) ? 'enabled' : 'disabled'}.`,
    };
  }

  if (resolution.kind === 'geocode_fly_to') {
    let hit: GeocodeHit | null = null;
    try {
      hit = await geocodePlace(resolution.label);
    } catch {
      hit = null;
    }
    if (!hit) {
      steps.push({ tool: 'map_fly_to', argsSummary: `label=${resolution.label}`, ok: false, detail: 'place search unavailable' });
      return { steps, reply: 'No place found — check backend connection.' };
    }
    const result = await executeClientVerb(
      'map_fly_to',
      { lat: hit.lat, lng: hit.lng, zoom: 8, label: hit.label },
      ctx,
    );
    const err = record(result, 'map_fly_to', `${hit.lat.toFixed(3)}, ${hit.lng.toFixed(3)}`);
    if (err) return { steps, reply: err };
    return { steps, reply: `Flying to ${hit.label}.` };
  }

  if (resolution.kind === 'local_reply') {
    return { steps, reply: resolution.reply };
  }

  // ── route_query path ────────────────────────────────────────────────────
  const routed = await postVoiceTool('route_query', { text });
  if (!routed.ok) {
    const detail = String(routed.error ?? 'routing unavailable');
    steps.push({ tool: 'route_query', argsSummary: `text=${text.slice(0, 60)}`, ok: false, detail });
    return { steps, reply: detail };
  }
  const data = (routed.data ?? {}) as Record<string, unknown>;
  const intent = typeof data.intent === 'string' ? data.intent : '';
  const recommended = (data.recommended ?? {}) as { cmd?: unknown; args?: Record<string, unknown> };
  const cmd = typeof recommended.cmd === 'string' ? recommended.cmd : '';
  if (!cmd) {
    steps.push({ tool: 'route_query', argsSummary: '', ok: false, detail: 'no recommended command' });
    return {
      steps,
      reply: "No model configured — running deterministic mode. Try: 'fly to Kyiv', 'what changed', 'news on Ukraine'.",
    };
  }
  if (intent === 'discovery') {
    // route_query had no confident mapping (§3.7 item 4) — say so honestly.
    steps.push({ tool: 'route_query', argsSummary: '', ok: true, detail: `intent=${intent}` });
    return {
      steps,
      reply: "No model configured — running deterministic mode. Try: 'fly to Kyiv', 'what changed', 'toggle flights layer'.",
    };
  }

  steps.push({ tool: 'route_query', argsSummary: `intent=${intent}`, ok: true, detail: cmd });
  const executed = await postVoiceTool(cmd, recommended.args ?? {});
  if (!executed.ok) {
    // §3.7 item 2: an expensive/destructive recommendation speaks the gate
    // message verbatim and awaits confirmation instead of dying as a bare
    // error. The unlock word is handled at the top of the next turn.
    const code = typeof executed.code === 'string' ? executed.code : '';
    if (code === 'expensive_command_blocked' || code === 'destructive_confirm_required') {
      pendingConfirmation = {
        tool: cmd,
        args: recommended.args ?? {},
        kind: code === 'expensive_command_blocked' ? 'expensive' : 'destructive',
      };
      steps.push({ tool: cmd, argsSummary: '', ok: false, detail: code });
      return { steps, reply: `${String(executed.error)} Type 'confirm' to run it.` };
    }
  }
  const err = record(executed, cmd, '');
  if (err) return { steps, reply: err };
  return { steps, reply: templateReply(cmd, executed) };
}
