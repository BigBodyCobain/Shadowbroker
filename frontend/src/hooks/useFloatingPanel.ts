'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

export interface FloatingPanelPosition {
  x: number;
  y: number;
}

interface StoredFloatingPanelState {
  position?: FloatingPanelPosition;
  isMinimized?: boolean;
}

interface UseFloatingPanelOptions {
  defaultPosition?: FloatingPanelPosition;
  minVisible?: number;
}

export function useFloatingPanel(
  storageKey: string,
  { defaultPosition = { x: 24, y: 380 }, minVisible = 48 }: UseFloatingPanelOptions = {},
) {
  const [position, setPosition] = useState<FloatingPanelPosition>(defaultPosition);
  const [isMinimized, setIsMinimized] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const dragStartRef = useRef({ x: 0, y: 0, posX: 0, posY: 0 });
  const hydratedRef = useRef(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (!raw) return;
      const parsed = JSON.parse(raw) as StoredFloatingPanelState;
      if (
        parsed.position &&
        Number.isFinite(parsed.position.x) &&
        Number.isFinite(parsed.position.y)
      ) {
        setPosition(parsed.position);
      }
      if (typeof parsed.isMinimized === 'boolean') {
        setIsMinimized(parsed.isMinimized);
      }
    } catch {
      /* non-fatal */
    } finally {
      hydratedRef.current = true;
    }
  }, [storageKey]);

  useEffect(() => {
    if (!hydratedRef.current) return;
    try {
      localStorage.setItem(
        storageKey,
        JSON.stringify({ position, isMinimized } satisfies StoredFloatingPanelState),
      );
    } catch {
      /* non-fatal */
    }
  }, [storageKey, position, isMinimized]);

  const clampPosition = useCallback(
    (next: FloatingPanelPosition): FloatingPanelPosition => {
      const maxX = Math.max(0, window.innerWidth - minVisible);
      const maxY = Math.max(0, window.innerHeight - minVisible);
      return {
        x: Math.min(Math.max(0, next.x), maxX),
        y: Math.min(Math.max(0, next.y), maxY),
      };
    },
    [minVisible],
  );

  const onDragStart = useCallback(
    (event: React.MouseEvent) => {
      event.preventDefault();
      setIsDragging(true);
      dragStartRef.current = {
        x: event.clientX,
        y: event.clientY,
        posX: position.x,
        posY: position.y,
      };
    },
    [position.x, position.y],
  );

  useEffect(() => {
    if (!isDragging) return undefined;

    const handleMove = (event: MouseEvent) => {
      const dx = event.clientX - dragStartRef.current.x;
      const dy = event.clientY - dragStartRef.current.y;
      setPosition(
        clampPosition({
          x: dragStartRef.current.posX + dx,
          y: dragStartRef.current.posY + dy,
        }),
      );
    };

    const handleUp = () => setIsDragging(false);

    window.addEventListener('mousemove', handleMove);
    window.addEventListener('mouseup', handleUp);
    return () => {
      window.removeEventListener('mousemove', handleMove);
      window.removeEventListener('mouseup', handleUp);
    };
  }, [isDragging, clampPosition]);

  return {
    position,
    isMinimized,
    setIsMinimized,
    isDragging,
    onDragStart,
  };
}