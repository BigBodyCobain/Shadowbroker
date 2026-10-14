# Agent framework and mission workspace

Shadowbroker now has a durable mission workspace over the existing command framework. See [operator instructions](mission-workspace.md).

## Delivered capabilities

- **Mission workspace:** saved objectives, role plan, progress, bounded tool history, briefings, and pause/cancel/resume controls. SQLite transactions and revision/lease checks prevent concurrent steps from being accepted twice.
- **Confirmed UI chains:** targeted browser action IDs, start records, selection verification, receipts, and actual tool feedback before the next model step. Interrupted started actions require explicit review and are not automatically replayed.
- **Persistent monitoring:** the existing watchdog's definitions, pause state, latest check/trigger, and bounded Telegram seen-post state survive restarts. The workspace exposes create/pause/resume/remove controls, including area geofences.
- **Evidence board:** stored source cards and tool results, timestamps, pins, article previews, and model-generated role briefings with source context.
- **Specialist roles:** researcher, analyst, reviewer, and API-configurable coordinator roles. Each has a selected saved provider/model, role permissions, and a model-call limit. The default workflow runs three roles sequentially.
- **Operator-origin approvals:** supported writes stop for exact-action review; model-authored confirm flags cannot approve a mission write. Existing full/restricted access gates still apply. Private messaging, voting, shell execution, and arbitrary external communications are excluded from mission tools.

## Existing layers reused

`openclaw_channel.py` remains the authenticated command dispatcher with bounded external command/task queues and batches. `openclaw_routing.py` supplies deterministic routing and playbooks. `openclaw_watchdog.py` evaluates watches and emits alerts over SSE and poll fallback. The shared voice tool registry and `clientTools.ts` remain the validators and browser executors.

`mission_store.py` adds transactional persistence. `mission_engine.py` performs one bounded, leased step per request using the existing text broker and tool layer. `routers/missions.py` exposes operator-authenticated controls under `/api/voice/`. The dashboard run loop waits for browser receipts and advances the current specialist. Ordinary voice/text requests can start a mission with an explicit “start a mission” prefix.

## Operating limits

Inference resumes only when the operator starts it; restoring saved state does not spend model credits. The dashboard drives mission runs, while restored watches run in the existing backend watchdog. The original external command/task queue and best-effort display queue remain process-local; these are not durable worker jobs. Browser receipts currently apply to mission actions, not every legacy external display command.

Role-call limits, the existing daily budget, two simultaneous mission steps per backend process, finite histories, and explicit permission gates bound execution. Stored provider destinations are checked before resuming inference, and credentials are never copied into mission records.

## Further expansion

The useful next stages are named external worker registrations with scoped credentials and acknowledged durable task leases; receipt support for legacy external display commands; richer evidence comparisons; and event-driven mission wakeups with explicit operator-set conditions and budgets. Parallel specialist workers should be added only after those ownership and delivery contracts are in place.

The operator Agent Shell remains separate and depends on POSIX PTY support, so ordinary missions do not depend on it on Windows.
