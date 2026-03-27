/**
 * Alert spread collision resolution algorithm.
 * Takes news items with coordinates and resolves visual overlaps
 * so alert boxes don't stack on top of each other on the map.
 */

import type { NewsArticle } from '@/types/dashboard';
import { ALERT_BOX_WIDTH_PX, ALERT_MAX_OFFSET_PX } from '@/lib/constants';

export interface SpreadAlertItem extends NewsArticle {
  coords: [number, number];
  originalIdx: number;
  x: number;
  y: number;
  offsetX: number;
  offsetY: number;
  boxH: number;
  alertKey: string;
  showLine: boolean;
  cluster_count?: number;
}

/** Estimate rendered box height based on title length */
function estimateBoxH(n: { title?: string; cluster_count?: number }): number {
  const titleLen = (n.title || '').length;
  const titleLines = Math.max(1, Math.ceil(titleLen / 20)); // ~20 chars per line at 9px in 160px
  const hasFooter = (n.cluster_count || 1) > 1;
  return 10 + 14 + titleLines * 13 + (hasFooter ? 14 : 0) + 10; // padding + header + title + footer + padding
}

/**
 * Resolves alert box collisions using a grid-based spatial algorithm (O(n) per iteration).
 * Returns positioned items with offsets and alert keys.
 */
export function spreadAlertItems(
  news: NewsArticle[],
  zoom: number,
  dismissedAlerts: Set<string>,
): SpreadAlertItem[] {
  const pixelsPerDeg = (256 * Math.pow(2, zoom)) / 360;

  const items = news
    .map((n, idx) => ({ ...n, originalIdx: idx }))
    .filter((n) => n.coords)
    .map((n) => ({
      ...n,
      x: n.coords![1] * pixelsPerDeg,
      y: -n.coords![0] * pixelsPerDeg,
      offsetX: 0,
      offsetY: 0,
      boxH: estimateBoxH(n as { title?: string; cluster_count?: number }),
    }));

  const BOX_W = ALERT_BOX_WIDTH_PX;
  const GAP = 6;
  const MAX_OFFSET = ALERT_MAX_OFFSET_PX;

  // Grid-based Collision Resolution (O(n) per iteration instead of O(n²))
  const CELL_W = BOX_W + GAP;
  const CELL_H = 100;
  const maxIter = 30;

  for (let iter = 0; iter < maxIter; iter++) {
    let moved = false;
    const grid: Record<string, number[]> = {};
    for (let i = 0; i < items.length; i++) {
      const cx = Math.floor((items[i].x + items[i].offsetX) / CELL_W);
      const cy = Math.floor((items[i].y + items[i].offsetY) / CELL_H);
      const key = `${cx},${cy}`;
      (grid[key] ??= []).push(i);
    }
    const checked = new Set<string>();
    for (const key in grid) {
      const [cx, cy] = key.split(',').map(Number);
      for (let dx = -1; dx <= 1; dx++) {
        for (let dy = -1; dy <= 1; dy++) {
          const nk = `${cx + dx},${cy + dy}`;
          if (!grid[nk]) continue;
          const pairKey =
            cx + dx < cx || (cx + dx === cx && cy + dy < cy) ? `${nk}|${key}` : `${key}|${nk}`;
          if (key !== nk && checked.has(pairKey)) continue;
          checked.add(pairKey);
          const cellA = grid[key];
          const cellB = key === nk ? cellA : grid[nk];
          for (const i of cellA) {
            const startJ = key === nk ? cellA.indexOf(i) + 1 : 0;
            for (let jIdx = startJ; jIdx < cellB.length; jIdx++) {
              const j = cellB[jIdx];
              if (i === j) continue;
              const a = items[i],
                b = items[j];
              const adx = Math.abs(a.x + a.offsetX - (b.x + b.offsetX));
              const ady = Math.abs(a.y + a.offsetY - (b.y + b.offsetY));
              const minDistX = BOX_W + GAP;
              const minDistY = (a.boxH + b.boxH) / 2 + GAP;
              if (adx < minDistX && ady < minDistY) {
                moved = true;
                const overlapX = minDistX - adx;
                const overlapY = minDistY - ady;
                if (overlapY < overlapX) {
                  const push = overlapY / 2 + 1;
                  if (a.y + a.offsetY <= b.y + b.offsetY) {
                    a.offsetY -= push;
                    b.offsetY += push;
                  } else {
                    a.offsetY += push;
                    b.offsetY -= push;
                  }
                } else {
                  const push = overlapX / 2 + 1;
                  if (a.x + a.offsetX <= b.x + b.offsetX) {
                    a.offsetX -= push;
                    b.offsetX += push;
                  } else {
                    a.offsetX += push;
                    b.offsetX -= push;
                  }
                }
              }
            }
          }
        }
      }
    }
    if (!moved) break;
  }

  // Clamp offsets so boxes stay near their origin
  for (const item of items) {
    item.offsetX = Math.max(-MAX_OFFSET, Math.min(MAX_OFFSET, item.offsetX));
    item.offsetY = Math.max(-MAX_OFFSET, Math.min(MAX_OFFSET, item.offsetY));
  }

  return items
    .filter((item) => {
      const alertKey = `${item.title}|${item.coords?.[0]},${item.coords?.[1]}`;
      return !dismissedAlerts.has(alertKey);
    })
    .map((item) => ({
      ...item,
      alertKey: `${item.title}|${item.coords?.[0]},${item.coords?.[1]}`,
      showLine: Math.abs(item.offsetX) > 5 || Math.abs(item.offsetY) > 5,
    })) as SpreadAlertItem[];
}
