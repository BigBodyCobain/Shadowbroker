'use client';
import { useEffect, useState } from 'react';
import { getGateCompatTelemetryEventName, getGateCompatTelemetrySnapshot, type GateCompatTelemetrySnapshot } from '@/mesh/gateCompatTelemetry';
import { getBrowserGateLocalRuntimeEventName, getBrowserGateLocalRuntimeStatus, type BrowserGateLocalRuntimeStatus } from '@/mesh/meshGateWorkerClient';

export function useSettingsPanelGateStatus() {
  const [gateCompatTelemetry, setGateCompatTelemetry] = useState<GateCompatTelemetrySnapshot>(() => getGateCompatTelemetrySnapshot());
  const [gateLocalRuntimeStatus, setGateLocalRuntimeStatus] = useState<BrowserGateLocalRuntimeStatus>(() => getBrowserGateLocalRuntimeStatus());
  useEffect(() => {
    const refreshTelemetry = () => setGateCompatTelemetry(getGateCompatTelemetrySnapshot());
    refreshTelemetry();
    if (typeof window === 'undefined') return;
    const eventName = getGateCompatTelemetryEventName();
    window.addEventListener(eventName, refreshTelemetry as EventListener);
    return () => { window.removeEventListener(eventName, refreshTelemetry as EventListener); };
  }, []);
  useEffect(() => {
    const refreshRuntimeStatus = () => setGateLocalRuntimeStatus(getBrowserGateLocalRuntimeStatus());
    refreshRuntimeStatus();
    if (typeof window === 'undefined') return;
    const eventName = getBrowserGateLocalRuntimeEventName();
    window.addEventListener(eventName, refreshRuntimeStatus as EventListener);
    return () => { window.removeEventListener(eventName, refreshRuntimeStatus as EventListener); };
  }, []);
  return { gateCompatTelemetry, gateLocalRuntimeStatus };
}
