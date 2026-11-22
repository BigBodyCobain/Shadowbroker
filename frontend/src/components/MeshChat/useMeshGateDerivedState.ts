// @ts-nocheck
'use client';

import { useCallback, useMemo } from 'react';

export function useMeshGateDerivedState(ctx: any) {
  const {
    selectedGate, gatePersonas, activeGatePersonaId, gates, gateCompatActive, gateKeyStatus,
    gatePersonaPromptGateId, gatePersonaDraftLabel, handleCreateGatePersona, handleSelectGatePersona,
    closeGatePersonaPrompt, nativeAuditReport,
  } = ctx;
  const selectedGateKey = selectedGate.trim().toLowerCase();
  const selectedGatePersonaList = selectedGateKey ? gatePersonas[selectedGateKey] || [] : [];
  const selectedGateActivePersonaId = selectedGateKey ? activeGatePersonaId[selectedGateKey] || '' : '';
  const selectedGateActivePersona = useMemo(
    () =>
      selectedGateActivePersonaId
        ? selectedGatePersonaList.find(
            (persona) => String(persona.persona_id || '') === selectedGateActivePersonaId,
          ) || null
        : null,
    [selectedGateActivePersonaId, selectedGatePersonaList],
  );
  const selectedGateMeta = useMemo(
    () => gates.find((gate) => gate.gate_id === selectedGateKey) || null,
    [gates, selectedGateKey],
  );
  const selectedGateCompatActive = useMemo(
    () => Boolean(selectedGateKey && gateCompatActive[selectedGateKey]),
    [gateCompatActive, selectedGateKey],
  );
  const selectedGateKeyStatus = useMemo(
    () => (selectedGateKey ? gateKeyStatus[selectedGateKey] || null : null),
    [gateKeyStatus, selectedGateKey],
  );
  const selectedGateAccessReady = Boolean(selectedGateKeyStatus?.has_local_access);
  const gatePersonaPromptPersonaList =
    gatePersonaPromptGateId ? gatePersonas[gatePersonaPromptGateId] || [] : [];
  const gatePersonaPromptGateMeta = useMemo(
    () =>
      gates.find(
        (gate) => gate.gate_id === (gatePersonaPromptGateId || '').trim().toLowerCase(),
      ) || null,
    [gatePersonaPromptGateId, gates],
  );
  const gatePersonaPromptTitle =
    gatePersonaPromptGateMeta?.display_name || gatePersonaPromptGateId || selectedGate;
  const submitGatePersonaPrompt = useCallback(async () => {
    const ok = await handleCreateGatePersona(gatePersonaDraftLabel);
    if (ok) {
      closeGatePersonaPrompt();
    }
  }, [closeGatePersonaPrompt, gatePersonaDraftLabel, handleCreateGatePersona]);
  const selectSavedGatePersona = useCallback(
    async (personaId: string) => {
      const ok = await handleSelectGatePersona(personaId);
      if (ok) {
        closeGatePersonaPrompt();
      }
    },
    [closeGatePersonaPrompt, handleSelectGatePersona],
  );
  const remainAnonymousInGate = useCallback(() => {
    closeGatePersonaPrompt();
  }, [closeGatePersonaPrompt]);
  const nativeAuditSummary = useMemo(() => {
    if (!nativeAuditReport?.totalEvents) return null;
    const recent = nativeAuditReport.recent[0] || null;
    const byOutcome = nativeAuditReport.byOutcome || {};
    const mismatchCount = (byOutcome.profile_warn || 0) + (byOutcome.profile_denied || 0);
    const deniedCount =
      (byOutcome.profile_denied || 0) +
      (byOutcome.capability_denied || 0) +
      (byOutcome.shim_refused || 0);
    return {
      recent,
      mismatchCount,
      deniedCount,
    };
  }, [nativeAuditReport]);

  return {
    selectedGateKey, selectedGatePersonaList, selectedGateActivePersonaId, selectedGateActivePersona,
    selectedGateMeta, selectedGateCompatActive, selectedGateKeyStatus, selectedGateAccessReady,
    gatePersonaPromptPersonaList, gatePersonaPromptGateMeta, gatePersonaPromptTitle,
    submitGatePersonaPrompt, selectSavedGatePersona, remainAnonymousInGate, nativeAuditSummary,
  };
}
