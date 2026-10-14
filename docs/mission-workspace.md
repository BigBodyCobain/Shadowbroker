# Mission workspace

Open **Missions** next to the voice microphone, or choose **Missions** in the console header. With a text model configured, you can also speak or type **Start a mission: investigate this area and find related stories**. This shortcut saves and starts a mission using the current model for all three default roles.

## Run an investigation

1. Enter an objective, such as “Investigate this area, find related stories, show the strongest source, and propose monitoring.”
2. Choose the saved provider, exact model ID, and model-call limit for each role. Configure keys through **Change model** first. Missions never store provider keys.
3. **Save mission** preserves the plan without running inference. **Run / resume** starts it.
4. Inspect role briefings, the evidence board, and run history. Pin useful sources and open article dossiers directly from evidence cards.
5. Pause or cancel when needed. These controls stop future steps; an already executed action cannot be undone by cancelling its response.

The default sequence is researcher → analyst → reviewer. Researchers gather read-only evidence. Analysts compare evidence and can use the approved dashboard tools. Reviewers independently inspect the actual results and produce a cited briefing. Each role can use a different saved provider/model and has its own call limit (1–8; default 5). A coordinator role is also supported by the API. Roles execute sequentially over the same validated tool layer.

The daily AI budget and two-step outbound opt-in apply to every model step. Call limits also count failed attempts. The backend permits at most two simultaneous mission steps per process. Usage prices remain estimates; provider billing limits remain authoritative.

## Confirmed action chains and approvals

A mission can search → move the map → select an entity → open a source → review the result. Each browser action has an ID, an owning dashboard, a start record, and a receipt. The runner waits for that receipt before asking the model for another step. Article/entity selections are checked against the next dashboard snapshot instead of accepting an optimistic success response.

Only the limited mission tool allowlist is available. Researcher and reviewer roles cannot write or manipulate the display. Analyst/coordinator write proposals stop at **Operator approval required**, showing the exact tool and arguments. The model cannot approve itself. Changes retain the existing full-access requirement; a restricted agent cannot gain full access by proposing an action. Supported proposals include watches, pins, and snapshots. Shell execution, private messages, votes, and arbitrary external communications are not mission tools.

After approval or rejection, review the result and choose **Run / resume** to continue. If a role reaches its configured call limit, the mission pauses; **Continue with next role** is an explicit operator decision, not an automatic increase in budget.

## Persistence and recovery

Records live in `${SB_DATA_DIR:-backend/data}/missions.sqlite3`: objectives, role configuration, bounded context, tool results, reports, evidence pins, and watch definitions. There are limits of 200 saved missions, 512 KiB per mission record, and 100 watches. Old message/history entries may be pruned when a record reaches its storage bound. Provider keys remain in the existing credential store.

Mission inference is driven by the dashboard run loop. Closing the panel keeps an active run going; closing/reloading the dashboard or restarting the backend requires explicit resume. The backend preserves completed work and does not start model calls on restoration. An in-flight step has a two-minute lease; if its outcome is unknown, review the recorded state. A browser action already marked started is never silently replayed. Use **Skip unconfirmed action** only after checking what happened, then resume. This does not reverse a completed action.

A change to a saved provider destination pauses affected missions before stored evidence is sent elsewhere. Each role retains its saved API style. Configure connections first; create a follow-up mission after intentionally changing a destination. Key rotation at the same saved destination does not require a new mission.

**Delete saved mission** removes its workspace record. Existing watches are independent and must be paused/removed separately. Hosted provider retention remains governed by the selected provider.

## Saved monitoring

The workspace exposes the existing watchdog for news keywords, entities, callsigns, registrations, ships, and geographic areas. Watches can be linked to the selected mission. Pause, resume, and remove controls are explicit; changes require full agent access. The panel displays check time, alert count, and the latest trigger evidence.

Saved watches restore on backend startup and continue checking cached telemetry every 15 seconds. Repeated triggers retain the existing debounce; bounded Telegram seen-post state is persisted. Alerts continue through the existing SSE/poll agent channels. Alerts do not automatically trigger paid model inference. The legacy external command/task queues remain process-local; the mission workspace supplies durable investigation state above them.

## Data disclosure

Mission context and tool evidence are sent only to the role's chosen saved provider when the operator runs inference. Current-view snapshots stay bounded to the existing 6 KiB schema; model context and tool results are bounded too. No screenshots, API keys, or automatic shell access are added. Source content and prior role reports are treated as untrusted data. See [outbound data](OUTBOUND_DATA.md).
