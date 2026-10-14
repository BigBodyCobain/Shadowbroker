# Make the existing agent framework a visible product

## Existing foundation

- `openclaw_channel.py`: authenticated command allowlists, read/full access tiers, bounded command/task queues, concurrent batches and result tracking. Commands use the existing dispatch surface; this is not a durable multi-agent job broker.
- `openclaw_routing.py`: cheap natural-language routing and bounded playbooks (`hot_snapshot`, `status_check`, `monitor_heartbeat`) that avoid full telemetry dumps.
- `openclaw_watchdog.py`: aircraft/ship/entity tracking, geofences, keyword and other monitors. The worker checks every 15 seconds and debounces repeated alerts; events reach agents through SSE with poll fallback.
- `routers/ai_intel.py`: machine-readable tools/capabilities, SSE events for alerts/tasks/layer changes, and the dashboard action queue.
- `voice_tool_registry.py` plus `clientTools.ts`: shared schema validation and existing permission/confirmation gates, with browser-side map, selection, Time Machine, and article actions.
- `useAgentActions.ts`: best-effort dashboard action polling. The current queue is consumed on read, process-local, bounded, and not scoped to a particular dashboard.
- `agent_shell.py`: an operator terminal surface separate from the command API. Its POSIX PTY imports currently prevent loading on native Windows; it should not become a prerequisite for ordinary dashboard agents.

## Delivered in this change

The AI console can open an existing news article dossier automatically with `open_article`. Remote agents can queue the same preview using `show_article`; queued work is distinguished from confirmed display. Unsafe publisher schemes are rejected. The console now forwards the existing bounded map/selection snapshot on ordinary model turns.

## Next implementation priorities

1. **Mission workspace with durable task state.** Give requests a mission ID, objective, chosen model, tool history, evidence, progress, and states such as running, waiting for approval, completed, failed, and cancelled. Persist tasks and watch definitions using the project's existing persistence conventions. Restarting currently loses channel tasks and watches. Add ownership, idempotency, leases, and explicit acknowledgments before distributing work among agents.
2. **Confirmed UI actions and chained work.** Target a dashboard session, record each action ID, and wait for a client receipt or timeout. Feed actual browser results back into the bounded agent loop. Today the text picker returns after a client call, so a search -> zoom -> select -> article sequence is not yet a complete closed loop. Keep step, time, and spend limits plus cancellation.
3. **Monitoring as a first-class UI.** Expose existing track/watch commands as visible, editable subscriptions: which entity/area/topic, why a trigger fired, latest evidence, last check, and pause/remove. Use existing watchdog/SSE events to wake work only when relevant data changes. Make restart behavior explicit until persistence is implemented.
4. **Evidence board and source presentation.** Turn search results into clickable cards tied to stored article/entity references; let operators pin evidence into a mission and generate a cited area brief or before/after comparison. Preserve source timestamps and uncertainty. Treat article content as untrusted data rather than instructions for tools.
5. **Specialist roles over the same tool layer.** Researcher gathers evidence; analyst compares it; reviewer checks support and uncertainty; a coordinator tracks the mission. Give each role explicit tools, provider, budget, and permissions. Operator-approved messages and actions remain under the same policy. Adding model names alone does not create an orchestrator.

A useful first mission is: “Investigate this area, find related stories, show the strongest source, and watch for meaningful changes.” Build that end-to-end path before adding a large role library.

## Safeguards to retain

Operator authentication and access tiers; explicit outbound opt-in and spend limits for hosted inference; range/schema validation; bounded context; no silent shell escalation; operator-origin approval for destructive/external communication; cancellation that suppresses pending work without claiming it undoes completed commands.

## Validation focus

Test missing/stale articles, untrusted source URLs, disconnected dashboards, duplicate delivery, cancellation after search, restart/recovery, and an actual mission against configured providers. Unit or gateway connectivity tests do not establish reliable multi-step visual execution.
