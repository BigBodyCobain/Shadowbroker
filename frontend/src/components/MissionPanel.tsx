'use client';

import { useEffect, useState } from 'react';
import type { MissionWorkspace } from '@/hooks/useMissionWorkspace';
import {
  missionRequest,
  type MissionConfiguration,
  type MissionRole,
  type Watch,
} from '@/lib/missionClient';
import { articleSourceUrl } from '@/lib/newsArticles';

const button =
  'px-2 py-1 border border-cyan-800 rounded text-cyan-200 disabled:opacity-40 hover:bg-cyan-900/30';
const field = 'w-full bg-black/60 border border-slate-700 rounded px-2 py-1 text-slate-100';

export default function MissionPanel({
  workspace,
  onClose,
}: {
  workspace: MissionWorkspace;
  onClose: () => void;
}) {
  const [config, setConfig] = useState<MissionConfiguration | null>(null);
  const [objective, setObjective] = useState('');
  const [roles, setRoles] = useState<MissionRole[]>([]);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [watches, setWatches] = useState<Watch[]>([]);
  const [watchType, setWatchType] = useState('keyword');
  const [watchValue, setWatchValue] = useState('');
  const [radius, setRadius] = useState(50);
  const mission = workspace.mission;
  const refreshMissions = workspace.refresh;
  const perform = async (action: () => Promise<unknown>) => {
    setError('');
    setSaving(true);
    try {
      await action();
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : 'Request failed');
    } finally {
      setSaving(false);
    }
  };
  const refreshWatches = async () =>
    setWatches((await missionRequest<{ watches: Watch[] }>('watches')).watches);
  useEffect(() => {
    let mounted = true;
    void Promise.all([
      missionRequest<MissionConfiguration>('missions/config'),
      refreshMissions(),
      missionRequest<{ watches: Watch[] }>('watches'),
    ])
      .then(([data, , monitoring]) => {
        if (!mounted) return;
        setConfig(data);
        setRoles(
          ['researcher', 'analyst', 'reviewer'].map((role) => ({
            role: role as MissionRole['role'],
            provider: data.provider,
            model: data.model,
            max_calls: 5,
          })),
        );
        setWatches(monitoring.watches);
      })
      .catch((exception) => {
        if (mounted) setError(String(exception.message));
      });
    const interval = setInterval(() => {
      if (!document.hidden)
        void missionRequest<{ watches: Watch[] }>('watches')
          .then((data) => {
            if (mounted) setWatches(data.watches);
          })
          .catch(() => {});
    }, 15000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [refreshMissions]);

  return (
    <section
      aria-label="Mission workspace"
      data-testid="mission-workspace"
      className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 w-[760px] max-w-[95vw] max-h-[80vh] overflow-y-auto styled-scrollbar z-[200] bg-slate-950 border border-cyan-700 shadow-2xl p-3 text-xs font-mono space-y-3"
    >
      <header className="flex items-center gap-2">
        <strong className="text-cyan-300 flex-1">MISSIONS · EVIDENCE · MONITORING</strong>
        <button className={button} onClick={() => workspace.setOpen(false)}>
          Back to console
        </button>
        <button className={button} aria-label="Close mission workspace" onClick={onClose}>
          ×
        </button>
      </header>
      <p className="text-slate-400">
        Missions save objectives, results, and evidence locally. Saved watches resume after a
        backend restart. Model runs resume only when you choose Run. Provider keys are never stored
        in a mission.
      </p>
      {(error || workspace.error) && (
        <p role="alert" className="text-amber-300">
          {error || workspace.error}
        </p>
      )}
      <details open={!mission} className="border border-slate-800 p-2 space-y-2">
        <summary className="cursor-pointer text-cyan-200">New mission</summary>
        <label className="block">
          Objective
          <textarea
            aria-label="Mission objective"
            maxLength={2000}
            rows={3}
            className={field}
            value={objective}
            onChange={(event) => setObjective(event.target.value)}
            placeholder="Investigate this area, find related stories, show the strongest source, and propose monitoring."
          />
        </label>
        <p className="text-slate-400">
          Each role uses a saved provider connection. Configure keys in Change model. Call limits
          are per role; the daily AI budget also applies.
        </p>
        {roles.map((role, index) => (
          <div
            key={role.role}
            className="grid grid-cols-2 sm:grid-cols-4 gap-2"
            title={config?.role_purposes[role.role]}
          >
            <span className="text-violet-300 self-center">{role.role}</span>
            <select
              aria-label={`${role.role} provider`}
              className={field}
              value={role.provider}
              onChange={(event) =>
                setRoles((previous) =>
                  previous.map((item, i) =>
                    i === index ? { ...item, provider: event.target.value, model: '' } : item,
                  ),
                )
              }
            >
              {config?.providers.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.label}
                </option>
              ))}
            </select>
            <input
              aria-label={`${role.role} model`}
              className={field}
              value={role.model}
              placeholder="Exact model ID"
              onChange={(event) =>
                setRoles((previous) =>
                  previous.map((item, i) =>
                    i === index ? { ...item, model: event.target.value } : item,
                  ),
                )
              }
            />
            <label>
              Call limit
              <input
                aria-label={`${role.role} call limit`}
                type="number"
                min={1}
                max={8}
                className={field}
                value={role.max_calls}
                onChange={(event) =>
                  setRoles((previous) =>
                    previous.map((item, i) =>
                      i === index ? { ...item, max_calls: Number(event.target.value) } : item,
                    ),
                  )
                }
              />
            </label>
          </div>
        ))}
        <button
          className={button}
          disabled={
            saving ||
            workspace.busy ||
            objective.trim().length < 3 ||
            !roles.length ||
            roles.some((role) => !role.model.trim())
          }
          onClick={() => void perform(() => workspace.create(objective, roles))}
        >
          Save mission
        </button>
      </details>
      <div className="flex flex-wrap gap-2 items-center">
        <label className="flex-1">
          Saved missions
          <select
            aria-label="Saved missions"
            className={field}
            value={mission?.id || ''}
            disabled={workspace.busy}
            onChange={(event) => {
              if (event.target.value) void perform(() => workspace.select(event.target.value));
            }}
          >
            <option value="">Choose a mission</option>
            {workspace.missions.map((item) => (
              <option key={item.id} value={item.id}>
                {item.status} · {item.objective.slice(0, 75)}
              </option>
            ))}
          </select>
        </label>
        <button
          className={button}
          disabled={saving}
          onClick={() => void perform(workspace.refresh)}
        >
          Refresh
        </button>
      </div>
      {mission && (
        <>
          <div className="border border-slate-700 p-2 space-y-2">
            <h3 className="text-slate-100 font-bold break-words">{mission.objective}</h3>
            <p className="text-cyan-300" role="status">
              {mission.status} · {mission.roles[mission.role_index]?.role || 'finished'} ·{' '}
              {mission.calls}/{mission.max_calls} model calls
            </p>
            {mission.reason && <p className="text-amber-200">{mission.reason}</p>}
            {mission.history_truncated && (
              <p className="text-slate-400">
                Some older history was trimmed; saved evidence remains.
              </p>
            )}
            <ol className="flex flex-wrap gap-3 text-slate-400">
              {mission.roles.map((role, index) => (
                <li
                  key={role.role}
                  className={index === mission.role_index ? 'text-violet-300' : ''}
                >
                  {index + 1}. {role.role} · {role.calls || 0}/{role.max_calls} · {role.provider}/
                  {role.model}
                </li>
              ))}
            </ol>
            <div className="flex flex-wrap gap-2">
              <button
                className={button}
                disabled={
                  saving ||
                  workspace.busy ||
                  ['completed', 'cancelled', 'needs_approval'].includes(mission.status)
                }
                onClick={() => void workspace.run(mission.id)}
              >
                Run / resume
              </button>
              <button
                className={button}
                disabled={saving || ['completed', 'cancelled'].includes(mission.status)}
                onClick={() => void perform(() => workspace.control('pause'))}
              >
                Pause
              </button>
              <button
                className={button}
                disabled={saving || ['completed', 'cancelled'].includes(mission.status)}
                onClick={() => void perform(() => workspace.control('cancel'))}
              >
                Cancel
              </button>
            {mission.pending && (mission.pending.started || mission.pending.kind !== 'approval') && !workspace.busy && (
                <button
                  className={button}
                  disabled={saving}
                  onClick={() => void perform(() => workspace.control('resolve'))}
                >
                  Skip unconfirmed action
                </button>
              )}
              {mission.status === 'paused' && !mission.pending && (
                <button
                  className={button}
                  disabled={saving || workspace.busy}
                  onClick={() => void perform(() => workspace.control('next_role'))}
                >
                  Continue with next role
                </button>
              )}
              <button
                className={button}
                disabled={
                  saving ||
                  workspace.busy ||
                  !['completed', 'cancelled', 'paused'].includes(mission.status)
                }
                onClick={() => void perform(() => workspace.remove(mission.id))}
              >
                Delete saved mission
              </button>
            </div>
            <p className="text-slate-500">
              Closing this panel keeps an active run going. Pause/cancel stops future steps; it
              cannot undo an action already executed.
            </p>
            {mission.status === 'needs_approval' && mission.pending && (
              <div className="border border-amber-700 p-2 space-y-2">
                <strong className="text-amber-200">
                  Operator approval required: {mission.pending.tool}
                </strong>
                <pre className="whitespace-pre-wrap break-words text-slate-200">
                  {JSON.stringify(mission.pending.args, null, 2)}
                </pre>
                <button
                  className={button}
                  disabled={saving}
                  onClick={() => void perform(() => workspace.approve(true))}
                >
                  Approve this exact action
                </button>{' '}
                <button
                  className={button}
                  disabled={saving}
                  onClick={() => void perform(() => workspace.approve(false))}
                >
                  Reject
                </button>
                <p className="text-slate-400">
                  After reviewing the result, choose Run to continue.
                </p>
              </div>
            )}
          </div>
          {!!mission.reports.length && (
            <div className="space-y-2">
              <h3 className="text-violet-300">Role briefings</h3>
              {mission.reports.map((report, index) => (
                <article key={index} className="border border-slate-800 p-2">
                  <strong>{report.role}</strong>
                  <p className="whitespace-pre-wrap text-slate-200">{report.text}</p>
                </article>
              ))}
            </div>
          )}
          <details open className="border border-slate-800 p-2">
            <summary className="text-cyan-200 cursor-pointer">
              Evidence board · {mission.evidence.length}
            </summary>
            {[...mission.evidence]
              .sort((a, b) => Number(b.pinned) - Number(a.pinned))
              .map((item) => (
                <article key={item.id} className="border-b border-slate-800 py-2 space-y-1">
                  <strong className="text-slate-100">
                    {item.pinned ? '★ ' : ''}
                    {item.title}
                  </strong>
                  {item.ok === false && (
                    <span className="text-amber-300"> · failed tool result</span>
                  )}
                  <p className="text-slate-500">
                    {item.tool} · {new Date(item.at * 1000).toLocaleString()}
                  </p>
                  <p className="whitespace-pre-wrap break-words text-slate-300 max-h-32 overflow-auto">
                    {item.summary}
                  </p>
                  <button
                    className={button}
                    disabled={saving}
                    onClick={() => void perform(() => workspace.pin(item.id, !item.pinned))}
                  >
                    {item.pinned ? 'Unpin evidence' : 'Pin evidence'}
                  </button>{' '}
                  {item.url && (
                    <>
                      <button
                        className={button}
                        onClick={() =>
                          void perform(() => workspace.showArticle(item.url, item.title))
                        }
                      >
                        Show article
                      </button>{' '}
                      {articleSourceUrl(item.url) && (
                        <a
                          className="text-cyan-300 underline"
                          href={articleSourceUrl(item.url)!}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          Source ↗
                        </a>
                      )}
                    </>
                  )}
                </article>
              ))}
            {!mission.evidence.length && (
              <p className="text-slate-500 py-2">
                Tool results and source records appear here as the mission runs.
              </p>
            )}
          </details>
          <details className="border border-slate-800 p-2">
            <summary className="cursor-pointer text-cyan-200">
              Run history · {mission.events.length}
            </summary>
            <ol className="space-y-2 mt-2">
              {mission.events.map((event) => (
                <li key={event.id} className="text-slate-300 break-words">
                  <span className="text-slate-500">
                    {new Date(event.at * 1000).toLocaleTimeString()} · {event.role || event.kind}
                  </span>
                  <p className={event.ok === false ? 'text-amber-300' : ''}>{event.text}</p>
                  {event.result && (
                    <pre className="whitespace-pre-wrap max-h-32 overflow-auto text-slate-400">
                      {event.result}
                    </pre>
                  )}
                </li>
              ))}
            </ol>
          </details>
        </>
      )}
      <details className="border border-slate-800 p-2 space-y-2" open>
        <summary className="text-cyan-200 cursor-pointer">
          Saved monitoring · {watches.length}
        </summary>
        <p className="text-slate-400">
          Watches use the existing watchdog and alerts. Changing watches requires full agent access.
          Alerts do not automatically spend model credits.
        </p>
        <div className="flex gap-2">
          <select
            aria-label="Watch type"
            className={field}
            value={watchType}
            onChange={(event) => setWatchType(event.target.value)}
          >
            <option value="keyword">News keyword</option>
            <option value="track_entity">Entity query</option>
            <option value="track_callsign">Aircraft callsign</option>
            <option value="track_registration">Aircraft registration</option>
            <option value="track_ship">Ship name</option>
            <option value="geofence">Area geofence (latitude, longitude)</option>
          </select>
          <input
            aria-label="Watch value"
            maxLength={200}
            className={field}
            value={watchValue}
            onChange={(event) => setWatchValue(event.target.value)}
            placeholder={watchType === 'geofence' ? '39.7, -104.9' : 'Keyword or entity identifier'}
          />
        </div>
        {watchType === 'geofence' && (
          <label>
            Area radius (km)
            <input
              aria-label="Watch radius"
              className={field}
              type="number"
              min={1}
              max={1000}
              value={radius}
              onChange={(event) => setRadius(Number(event.target.value))}
            />
          </label>
        )}
        <button
          className={button}
          disabled={saving || !watchValue.trim()}
          onClick={() =>
            void perform(async () => {
              const key = (
                {
                  keyword: 'keyword',
                  track_entity: 'query',
                  track_callsign: 'callsign',
                  track_registration: 'registration',
                  track_ship: 'name',
                } as Record<string, string>
              )[watchType];
              const coords = watchValue.split(',').map((value) => Number(value.trim()));
              if (
                watchType === 'geofence' &&
                (coords.length !== 2 ||
                  !watchValue.split(',').every((value) => value.trim()) ||
                  !coords.every(Number.isFinite))
              )
                throw new Error('Enter latitude, longitude for the area');
              const params =
                watchType === 'geofence'
                  ? {
                      lat: coords[0],
                      lng: coords[1],
                      radius_km: radius,
                      entity_types: ['aircraft', 'ships'],
                    }
                  : { [key]: watchValue.trim() };
              await missionRequest('watches', {
                type: watchType,
                params,
                ...(mission ? { mission_id: mission.id } : {}),
              });
              setWatchValue('');
              await refreshWatches();
            })
          }
        >
          Save watch
        </button>{' '}
        <button className={button} disabled={saving} onClick={() => void perform(refreshWatches)}>
          Refresh monitoring
        </button>
        {watches.map((watch) => (
          <article
            key={watch.id}
            className="border-t border-slate-800 py-2 space-y-1 text-slate-300"
          >
            <strong>
              {watch.paused ? 'Paused' : 'Active'} · {watch.type}
            </strong>
            <p className="break-words">{JSON.stringify(watch.params)}</p>
            <p className="text-slate-500">
              {watch.fires} alerts · last checked{' '}
              {watch.last_checked
                ? new Date(watch.last_checked * 1000).toLocaleString()
                : 'not yet'}
            </p>
            {watch.last_alert != null && (
              <pre className="whitespace-pre-wrap text-amber-200 max-h-28 overflow-auto">
                {JSON.stringify(watch.last_alert, null, 2)}
              </pre>
            )}
            <button
              className={button}
              disabled={saving}
              onClick={() =>
                void perform(async () => {
                  await missionRequest(`watches/${watch.id}`, { paused: !watch.paused }, 'PATCH');
                  await refreshWatches();
                })
              }
            >
              {watch.paused ? 'Resume watch' : 'Pause watch'}
            </button>{' '}
            <button
              className={button}
              disabled={saving}
              onClick={() =>
                void perform(async () => {
                  await missionRequest(`watches/${watch.id}`, undefined, 'DELETE');
                  await refreshWatches();
                })
              }
            >
              Remove watch
            </button>
          </article>
        ))}
      </details>
    </section>
  );
}
