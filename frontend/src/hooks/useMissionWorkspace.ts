'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  executeMissionAction,
  missionRequest,
  type Mission,
  type MissionRole,
  type MissionSummary,
  type MissionConfiguration,
  type MissionBindings,
} from '@/lib/missionClient';
import { executeClientVerb } from '@/lib/clientTools';
import type { GroundingSnapshot } from '@/lib/voiceGroundingTypes';

export function useMissionWorkspace(
  bindings: () => MissionBindings,
  getSnapshot: () => Promise<GroundingSnapshot>,
) {
  const [open, setOpen] = useState(false);
  const [mission, setMission] = useState<Mission | null>(null);
  const [missions, setMissions] = useState<MissionSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const references = useRef({ bindings, getSnapshot });
  references.current = { bindings, getSnapshot };
  const active = useRef<AbortController | null>(null);
  const dashboardRef = useRef('');
  const dashboard = () => {
    if (!dashboardRef.current) {
      const key = 'shadowbroker-mission-dashboard';
      const fresh = () =>
        crypto.randomUUID?.() ||
        Array.from(crypto.getRandomValues(new Uint8Array(16)), (value) =>
          value.toString(16).padStart(2, '0'),
        ).join('');
      try {
        dashboardRef.current = sessionStorage.getItem(key) || fresh();
        sessionStorage.setItem(key, dashboardRef.current);
      } catch {
        dashboardRef.current = fresh();
      }
    }
    return dashboardRef.current;
  };
  useEffect(() => () => active.current?.abort(), []);

  const refresh = useCallback(async () => {
    const data = await missionRequest<{ missions: MissionSummary[] }>('missions');
    setMissions(data.missions);
  }, []);
  const select = useCallback(async (id: string) => {
    const data = await missionRequest<{ mission: Mission }>(`missions/${id}`);
    setMission(data.mission);
    setError('');
  }, []);
  const create = useCallback(
    async (objective: string, roles: MissionRole[]) => {
      setError('');
      const snapshot = await references.current.getSnapshot();
      const data = await missionRequest<{ mission: Mission }>('missions', {
        objective,
        roles,
        snapshot,
      });
      setMission(data.mission);
      await refresh();
      return data.mission;
    },
    [refresh],
  );

  const run = useCallback(
    async (id: string) => {
      if (active.current) return;
      const request = new AbortController();
      active.current = request;
      setBusy(true);
      setError('');
      const owner = dashboard();
      try {
        let current = (
          await missionRequest<{ mission: Mission }>(
            `missions/${id}/control`,
            { dashboard: owner, action: 'resume' },
            undefined,
            request.signal,
          )
        ).mission;
        setMission(current);
        for (let step = 0; step < 100 && !request.signal.aborted; step++) {
          if (current.status === 'waiting_client') {
            current = await executeMissionAction(
              current,
              owner,
              () => references.current.bindings(),
              () => references.current.getSnapshot(),
              request.signal,
            );
          } else if (current.status === 'running') {
            current = (
              await missionRequest<{ mission: Mission }>(
                `missions/${id}/advance`,
                { dashboard: owner, revision: current.revision },
                undefined,
                request.signal,
              )
            ).mission;
          } else break;
          setMission(current);
        }
        if (!request.signal.aborted && current.status === 'running') {
          current = (
            await missionRequest<{ mission: Mission }>(`missions/${id}/control`, {
              dashboard: owner,
              action: 'pause',
            })
          ).mission;
          setMission(current);
        }
      } catch (exception) {
        if (!request.signal.aborted) {
          setError(exception instanceof Error ? exception.message : 'Mission run failed');
          try {
            await select(id);
          } catch {
            /* Keep the last known state. */
          }
        }
      } finally {
        if (active.current === request) active.current = null;
        setBusy(false);
        void refresh().catch(() => {});
      }
    },
    [refresh, select],
  );

  const startFromText = useCallback(
    async (objective: string, signal: AbortSignal) => {
      setOpen(true);
      setError('');
      try {
        if (active.current) throw new Error('Pause the active mission before starting another');
        signal.throwIfAborted();
        const config = await missionRequest<MissionConfiguration>(
          'missions/config',
          undefined,
          undefined,
          signal,
        );
        if (!config.model) throw new Error('Configure a text model before starting a mission');
        const roles = ['researcher', 'analyst', 'reviewer'].map((role) => ({
          role: role as MissionRole['role'],
          provider: config.provider,
          model: config.model,
          max_calls: 5,
        }));
        const created = await create(objective, roles);
        const stop = () => {
          active.current?.abort();
          void missionRequest<{ mission: Mission }>(`missions/${created.id}/control`, {
            dashboard: dashboard(),
            action: 'pause',
          })
            .then((data) => setMission(data.mission))
            .catch(() => {});
        };
        if (signal.aborted) {
          stop();
          return;
        }
        signal.addEventListener('abort', stop, { once: true });
        try {
          await run(created.id);
        } finally {
          signal.removeEventListener('abort', stop);
        }
      } catch (exception) {
        if (!signal.aborted)
          setError(exception instanceof Error ? exception.message : 'Mission could not start');
        throw exception;
      }
    },
    [create, run],
  );

  const control = useCallback(
    async (action: 'pause' | 'cancel' | 'resolve' | 'next_role') => {
      if (!mission) return;
      active.current?.abort();
      const data = await missionRequest<{ mission: Mission }>(`missions/${mission.id}/control`, {
        dashboard: dashboard(),
        action,
      });
      setMission(data.mission);
      await refresh();
    },
    [mission, refresh],
  );
  const approve = useCallback(
    async (approve: boolean) => {
      if (!mission?.pending) return;
      const data = await missionRequest<{ mission: Mission }>(`missions/${mission.id}/approve`, {
        dashboard: dashboard(),
        action_id: mission.pending.id,
        approve,
      });
      setMission(data.mission);
      await refresh();
    },
    [mission, refresh],
  );
  const pin = useCallback(
    async (id: string, pinned: boolean) => {
      if (!mission) return;
      const data = await missionRequest<{ mission: Mission }>(
        `missions/${mission.id}/evidence/${id}`,
        { pinned },
      );
      setMission(data.mission);
    },
    [mission],
  );
  const showArticle = useCallback(async (url: string, title: string) => {
    const result = await executeClientVerb(
      'open_article',
      url ? { url } : { query: title },
      references.current.bindings(),
    );
    if (!result.ok) throw new Error(String(result.error || 'Article preview unavailable'));
  }, []);
  const remove = useCallback(
    async (id: string) => {
      await missionRequest(`missions/${id}`, undefined, 'DELETE');
      if (mission?.id === id) setMission(null);
      await refresh();
    },
    [mission, refresh],
  );
  return {
    open,
    setOpen,
    mission,
    missions,
    busy,
    error,
    refresh,
    select,
    create,
    run,
    startFromText,
    control,
    approve,
    pin,
    showArticle,
    remove,
  };
}

export type MissionWorkspace = ReturnType<typeof useMissionWorkspace>;
