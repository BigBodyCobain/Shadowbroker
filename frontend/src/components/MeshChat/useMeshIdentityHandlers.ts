import { useCallback, useEffect } from 'react';
import { setInfonetNodeEnabled } from '@/mesh/controlPlaneStatusClient';
import {
  bootstrapWormholeIdentity,
  fetchWormholeIdentity,
  fetchWormholeStatus,
  prepareWormholeInteractiveLane,
} from '@/mesh/wormholeIdentityClient';
import { purgeBrowserContactGraph, purgeBrowserSigningMaterial, hydrateWormholeContacts, setSecureModeCached } from '@/mesh/meshIdentity';
import { purgeBrowserDmState } from '@/mesh/meshDmWorkerClient';
import { fetchWormholeSettings, joinWormhole, leaveWormhole } from '@/mesh/wormholeClient';
import {
  readStoredPublicMeshAddress,
  writeStoredPublicMeshAddress,
  clearStoredPublicMeshAddress,
  createPublicMeshAddress,
} from './useMeshChatController.helpers';

export interface MeshIdentityHandlersCtx {
  wormholeEnabled: boolean;
  wormholeReadyState: boolean;
  meshSessionActive: boolean;
  activePublicMeshAddress: string | null;
  meshMqttEnabled: boolean;
  publicMeshPrivacyEnforcedRef: React.MutableRefObject<boolean>;
  setMeshQuickStatus: (v: any) => void;
  setWormholeEnabled: (v: boolean) => void;
  setWormholeReadyState: (v: boolean) => void;
  setWormholeRnsReady: (v: boolean) => void;
  setWormholeRnsDirectReady: (v: boolean) => void;
  setWormholeRnsPeers: (v: any) => void;
  setIdentityWizardBusy: (v: boolean) => void;
  setIdentityWizardStatus: (v: any) => void;
  setIdentityWizardOpen: (v: boolean) => void;
  setPublicMeshAddress: (v: string) => void;
  setMeshSessionActive: (v: boolean) => void;
  setMeshMessages: (v: any[]) => void;
  setSendError: (v: string) => void;
  setIdentity: (v: any) => void;
  setContacts: (v: any) => void;
  setActiveTab: (v: any) => void;
  hasStoredPublicLaneIdentity: boolean;
  wormholeDescriptor: any;
  setMeshDirectTarget: (v: string) => void;
  setMeshAddressDraft: (v: string) => void;
  setMeshView: (v: any) => void;
  setSenderPopup: (v: any) => void;
  inputRef: React.RefObject<any>;
  enableMeshMqttBridge: () => Promise<any>;
  errorMessage: (err: any, fallback?: string) => string;
  describeMeshChatControlError: (msg: string) => string;
  [k: string]: any;
}

export function useMeshIdentityHandlers(ctx: MeshIdentityHandlersCtx) {
  const {
    wormholeEnabled, wormholeReadyState, meshSessionActive, activePublicMeshAddress, meshMqttEnabled,
    publicMeshPrivacyEnforcedRef, setMeshQuickStatus, setWormholeEnabled, setWormholeReadyState,
    setWormholeRnsReady, setWormholeRnsDirectReady, setWormholeRnsPeers, setIdentityWizardBusy,
    setIdentityWizardStatus, setIdentityWizardOpen, setPublicMeshAddress, setMeshSessionActive, setMeshMessages,
    setSendError, setIdentity, setContacts, setActiveTab, hasStoredPublicLaneIdentity, wormholeDescriptor,
    setMeshDirectTarget, setMeshAddressDraft, setMeshView, setSenderPopup, inputRef,
    enableMeshMqttBridge, errorMessage, describeMeshChatControlError,
  } = ctx;
  const disablePrivateNodeForPublicMesh = useCallback(async () => {
    try {
      await setInfonetNodeEnabled(false);
    } catch (err) {
      console.warn(
        '[mesh] private node pre-disable failed before public Mesh activation; MQTT enable will retry lane isolation',
        err,
      );
    }
  }, []);

  const disableWormholeForPublicMesh = useCallback(async () => {
    const requireBackendLeave = wormholeEnabled || wormholeReadyState;
    try {
      await leaveWormhole();
    } catch (err) {
      if (requireBackendLeave) {
        throw err;
      }
    }
    setWormholeEnabled(false);
    setWormholeReadyState(false);
    setWormholeRnsReady(false);
    setWormholeRnsDirectReady(false);
    setWormholeRnsPeers({ active: 0, configured: 0 });
    setSecureModeCached(false);
    await disablePrivateNodeForPublicMesh();
  }, [disablePrivateNodeForPublicMesh, wormholeEnabled, wormholeReadyState]);

  useEffect(() => {
    if (!meshSessionActive || !activePublicMeshAddress || !meshMqttEnabled) {
      publicMeshPrivacyEnforcedRef.current = false;
      return;
    }
    if (publicMeshPrivacyEnforcedRef.current) return;
    publicMeshPrivacyEnforcedRef.current = true;
    void disableWormholeForPublicMesh().catch((err) => {
      publicMeshPrivacyEnforcedRef.current = false;
      const message =
        typeof err === 'object' && err !== null && 'message' in err
          ? String((err as { message?: string }).message)
          : 'unknown error';
      setMeshQuickStatus({
        type: 'err',
        text: `Could not isolate public Mesh lane: ${message}`,
      });
    });
  }, [activePublicMeshAddress, disableWormholeForPublicMesh, meshMqttEnabled, meshSessionActive]);

  const createPublicMeshIdentity = useCallback(
    async ({ closeWizardOnSuccess }: { closeWizardOnSuccess: boolean }) => {
      setIdentityWizardBusy(true);
      setIdentityWizardStatus(null);
      try {
        await disableWormholeForPublicMesh();
        const nextAddress = createPublicMeshAddress();
        await enableMeshMqttBridge();
        writeStoredPublicMeshAddress(nextAddress);
        const readyAddress = nextAddress.toUpperCase();
        setPublicMeshAddress(nextAddress);
        setMeshSessionActive(true);
        setMeshMessages([]);
        setSendError('');
        const successText = `Mesh key ready. Address ${readyAddress} is live for this testnet session.`;
        setIdentityWizardStatus({
          type: 'ok',
          text: successText,
        });
        if (closeWizardOnSuccess) {
          window.setTimeout(() => setIdentityWizardOpen(false), 900);
        }
        return { ok: true as const, text: successText };
      } catch (err) {
        const message = describeMeshChatControlError(errorMessage(err));
        const errorText =
          message === 'browser_identity_blocked_secure_mode'
            ? 'Mesh key creation is blocked while Wormhole secure mode is active. Turn Wormhole off first if you want a separate public mesh key.'
            : `Could not create public mesh key: ${message}`;
        setIdentityWizardStatus({
          type: 'err',
          text: errorText,
        });
        return { ok: false as const, text: errorText };
      } finally {
        setIdentityWizardBusy(false);
      }
    },
    [disableWormholeForPublicMesh, enableMeshMqttBridge],
  );

  const handleCreatePublicIdentity = useCallback(async () => {
    await createPublicMeshIdentity({ closeWizardOnSuccess: true });
  }, [createPublicMeshIdentity]);

  const handleQuickCreatePublicIdentity = useCallback(async () => {
    setMeshQuickStatus(null);
    const result = await createPublicMeshIdentity({ closeWizardOnSuccess: false });
    setMeshQuickStatus({ type: result.ok ? 'ok' : 'err', text: result.text });
    if (!result.ok) {
      setIdentityWizardOpen(true);
    }
  }, [createPublicMeshIdentity]);

  const handleActivatePublicMeshSession = useCallback(async () => {
    setIdentityWizardBusy(true);
    setIdentityWizardStatus(null);
    setMeshQuickStatus(null);
    try {
      const savedAddress = readStoredPublicMeshAddress();
      if (!savedAddress) {
        const text = 'No saved public mesh key is available. Create a mesh key first.';
        setMeshSessionActive(false);
        setIdentityWizardStatus({ type: 'err', text });
        setMeshQuickStatus({ type: 'err', text });
        return { ok: false as const, text };
      }
      await disableWormholeForPublicMesh();
      await enableMeshMqttBridge();
      const readyAddress = savedAddress.toUpperCase();
      setPublicMeshAddress(savedAddress);
      setMeshSessionActive(true);
      setMeshMessages([]);
      setSendError('');
      const text = `Meshtastic Chat is on. Address ${readyAddress}.`;
      setIdentityWizardStatus({ type: 'ok', text });
      setMeshQuickStatus(null);
      return { ok: true as const, text };
    } catch (err) {
      const message = describeMeshChatControlError(errorMessage(err));
      const text = `Could not turn Meshtastic Chat on: ${message}`;
      setIdentityWizardStatus({ type: 'err', text });
      setMeshQuickStatus({ type: 'err', text });
      return { ok: false as const, text };
    } finally {
      setIdentityWizardBusy(false);
    }
  }, [disableWormholeForPublicMesh, enableMeshMqttBridge]);

  const handleReplyToMeshAddress = useCallback((address: string) => {
    const target = String(address || '').trim();
    if (!target) return;
    setMeshDirectTarget(target);
    setMeshAddressDraft(target);
    setMeshView('channel');
    setSenderPopup(null);
    setTimeout(() => inputRef.current?.focus(), 0);
  }, []);

  const handleLeaveWormholeForPublicMesh = useCallback(async () => {
    const result = hasStoredPublicLaneIdentity
      ? await handleActivatePublicMeshSession()
      : await createPublicMeshIdentity({ closeWizardOnSuccess: false });
    const status = { type: result.ok ? 'ok' as const : 'err' as const, text: result.text };
    setIdentityWizardStatus(status);
    setMeshQuickStatus(result.ok ? null : status);
    if (result.ok) {
      window.setTimeout(() => setIdentityWizardOpen(false), 900);
    }
  }, [createPublicMeshIdentity, handleActivatePublicMeshSession, hasStoredPublicLaneIdentity]);

  const handleResetPublicIdentity = useCallback(async () => {
    if (wormholeEnabled && wormholeReadyState) {
      setIdentityWizardStatus({
        type: 'err',
        text: 'Reset is blocked while Wormhole secure mode is active. Turn Wormhole off first.',
      });
      return;
    }
    setIdentityWizardBusy(true);
    setIdentityWizardStatus(null);
    try {
      setMeshSessionActive(false);
      setMeshMessages([]);
      clearStoredPublicMeshAddress();
      setPublicMeshAddress('');
      setIdentityWizardStatus({
        type: 'ok',
        text: 'Public mesh identity cleared. Start a fresh one when you are ready.',
      });
    } catch (err) {
      const message =
        typeof err === 'object' && err !== null && 'message' in err
          ? String((err as { message?: string }).message)
          : 'unknown error';
      setIdentityWizardStatus({
        type: 'err',
        text: `Could not clear public identity: ${message}`,
      });
    } finally {
      setIdentityWizardBusy(false);
    }
  }, [wormholeEnabled, wormholeReadyState]);

  const handleBootstrapPrivateIdentity = useCallback(async () => {
    setMeshSessionActive(false);
    setMeshMessages([]);
    if (wormholeEnabled && wormholeReadyState) {
      setIdentityWizardStatus({
        type: 'ok',
        text: wormholeDescriptor?.nodeId
          ? `Wormhole is already active as ${wormholeDescriptor.nodeId}. Gates and Dead Drop are ready now.`
          : 'Wormhole is already active. Gates and Dead Drop are ready now.',
      });
      setActiveTab('infonet');
      window.setTimeout(() => setIdentityWizardOpen(false), 700);
      return;
    }
    setIdentityWizardBusy(true);
    setIdentityWizardStatus(null);
    try {
      if (!wormholeEnabled || !wormholeReadyState) {
        const joined = await joinWormhole();
        const runtime = joined.runtime;
        setWormholeEnabled(Boolean(joined.settings?.enabled ?? runtime?.configured ?? true));
        setWormholeReadyState(Boolean(runtime?.ready));
        setWormholeRnsReady(Boolean(runtime?.rns_ready));
        setWormholeRnsDirectReady(Boolean(runtime?.rns_private_dm_direct_ready));
        setWormholeRnsPeers({
          active: Number(runtime?.rns_active_peers ?? 0),
          configured: Number(runtime?.rns_configured_peers ?? 0),
        });
        if (!runtime?.ready) {
          setIdentityWizardStatus({
            type: 'ok',
            text: 'Wormhole key is provisioning. Give it a moment, then tap ENTER INFONET again.',
          });
          return;
        }
      }
      const wormholeIdentity = await bootstrapWormholeIdentity();
      purgeBrowserSigningMaterial();
      purgeBrowserContactGraph();
      await purgeBrowserDmState();
      const hydratedContacts = await hydrateWormholeContacts(true);
      setContacts(hydratedContacts);
      setIdentity({
        publicKey: wormholeIdentity.public_key,
        privateKey: '',
        nodeId: wormholeIdentity.node_id,
      });
      setIdentityWizardStatus({
        type: 'ok',
        text: `Wormhole private identity ready as ${wormholeIdentity.node_id}. Dead Drop and private signing now use the local Wormhole agent instead of browser-held keys.`,
      });
      setActiveTab('infonet');
      window.setTimeout(() => setIdentityWizardOpen(false), 700);
    } catch (err) {
      const message =
        typeof err === 'object' && err !== null && 'message' in err
          ? String((err as { message?: string }).message)
          : 'unknown error';
      setIdentityWizardStatus({
        type: 'err',
        text: `Could not bootstrap Wormhole identity: ${message}`,
      });
    } finally {
      setIdentityWizardBusy(false);
    }
  }, [wormholeDescriptor?.nodeId, wormholeEnabled, wormholeReadyState]);

  const enterInfonetWormholeLane = useCallback(async () => {
    setMeshSessionActive(false);
    setMeshMessages([]);
    if (wormholeEnabled && wormholeReadyState) {
      try {
        const wormholeIdentity = await fetchWormholeIdentity();
        setIdentity({
          publicKey: wormholeIdentity.public_key,
          privateKey: '',
          nodeId: wormholeIdentity.node_id,
        });
      } catch {
        // Lane is already up; shell can still open.
      }
      return;
    }

    setIdentityWizardBusy(true);
    try {
      const prepared = await prepareWormholeInteractiveLane({ bootstrapIdentity: true });
      const [settings, runtime] = await Promise.all([
        fetchWormholeSettings(true).catch(() => null),
        fetchWormholeStatus().catch(() => null),
      ]);
      const enabled = Boolean(
        settings?.enabled ?? prepared.settingsEnabled ?? runtime?.running ?? runtime?.ready,
      );
      setSecureModeCached(enabled);
      setWormholeEnabled(enabled);
      setWormholeReadyState(Boolean(runtime?.ready ?? prepared.ready));
      setWormholeRnsReady(Boolean(runtime?.rns_ready));
      setWormholeRnsDirectReady(Boolean(runtime?.rns_private_dm_direct_ready));
      setWormholeRnsPeers({
        active: Number(runtime?.rns_active_peers ?? 0),
        configured: Number(runtime?.rns_configured_peers ?? 0),
      });
      if (prepared.identity) {
        purgeBrowserSigningMaterial();
        purgeBrowserContactGraph();
        await purgeBrowserDmState();
        const hydratedContacts = await hydrateWormholeContacts(true);
        setContacts(hydratedContacts);
        setIdentity({
          publicKey: prepared.identity.public_key,
          privateKey: '',
          nodeId: prepared.identity.node_id,
        });
      }
    } finally {
      setIdentityWizardBusy(false);
    }
  }, [wormholeEnabled, wormholeReadyState]);


  return {
    disablePrivateNodeForPublicMesh,
    disableWormholeForPublicMesh,
    createPublicMeshIdentity,
    handleCreatePublicIdentity,
    handleQuickCreatePublicIdentity,
    handleActivatePublicMeshSession,
    handleReplyToMeshAddress,
    handleLeaveWormholeForPublicMesh,
    handleResetPublicIdentity,
    handleBootstrapPrivateIdentity,
    enterInfonetWormholeLane,
  };
}
