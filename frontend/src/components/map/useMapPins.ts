import { useCallback, useEffect, useRef, useState } from 'react';
import { API_BASE } from '@/lib/api';
import type { PinCategory } from '@/types/aiIntel';

type PendingPin = {
  lat: number;
  lng: number;
  entity: { entity_type: string; entity_id: string; entity_label: string } | null;
} | null;

export function useMapPins({ onPinPlaced, aiIntelEnabled }: { onPinPlaced?: () => void; aiIntelEnabled?: boolean }) {
  const [pendingPin, setPendingPin] = useState<PendingPin>(null);
  const [pinLabel, setPinLabel] = useState('');
  const [pinNotes, setPinNotes] = useState('');
  const [pinCategory, setPinCategory] = useState<PinCategory>('custom');
  const [pinSaving, setPinSaving] = useState(false);
  const [aiIntelPins, setAiIntelPins] = useState<any[]>([]);
  const [aiIntelRefreshTick, setAiIntelRefreshTick] = useState(0);
  const [openPinDetailId, setOpenPinDetailId] = useState<string | null>(null);
  const pinLabelInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!pendingPin) return;
    const t = setTimeout(() => pinLabelInputRef.current?.focus(), 50);
    return () => clearTimeout(t);
  }, [pendingPin]);

  useEffect(() => {
    if (!aiIntelEnabled) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const resp = await fetch(`${API_BASE}/api/ai/pins/geojson`);
        if (!resp.ok || cancelled) return;
        const gj = await resp.json();
        const pins = (gj.features || []).map((f: any) => ({
          ...f.properties,
          lat: f.geometry?.coordinates?.[1],
          lng: f.geometry?.coordinates?.[0],
        }));
        if (!cancelled) setAiIntelPins(pins);
      } catch {}
    };
    poll();
    const tid = setInterval(poll, 15_000);
    return () => { cancelled = true; clearInterval(tid); };
  }, [aiIntelEnabled, aiIntelRefreshTick]);

  const handleSavePin = useCallback(async () => {
    if (!pendingPin || !pinLabel.trim()) return;
    setPinSaving(true);
    try {
      const body: Record<string, unknown> = {
        lat: pendingPin.lat,
        lng: pendingPin.lng,
        label: pinLabel.trim(),
        description: pinNotes.trim(),
        source: 'user',
        category: pinCategory,
      };
      if (pendingPin.entity) {
        body.entity_attachment = pendingPin.entity;
      }
      await fetch(`${API_BASE}/api/ai/pins`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      setPendingPin(null);
      setPinLabel('');
      setPinNotes('');
      setPinCategory('custom');
      setAiIntelRefreshTick((t) => t + 1);
      onPinPlaced?.();
    } catch (err) {
      console.error('Failed to save pin:', err);
    }
    setPinSaving(false);
  }, [pendingPin, pinLabel, pinNotes, pinCategory, onPinPlaced]);

  return {
    pendingPin, setPendingPin, pinLabel, setPinLabel, pinNotes, setPinNotes,
    pinCategory, setPinCategory, pinSaving, aiIntelPins, setAiIntelPins,
    aiIntelRefreshTick, setAiIntelRefreshTick, openPinDetailId, setOpenPinDetailId,
    pinLabelInputRef, handleSavePin,
  };
}
