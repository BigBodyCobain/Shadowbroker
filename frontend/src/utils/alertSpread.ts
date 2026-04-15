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
  // Title wraps at ~22 chars per line inside 260px maxWidth at 12px font
  const titleLines = Math.max(1, Math.ceil(titleLen / 22));
  const hasFooter = (n.cluster_count || 1) > 1;
  // padding(8+8) + header("!! ALERT LVL X !!" ~20px) + gap(4) + title(lines*17) + footer(18) + padding
  return 16 + 20 + 4 + titleLines * 17 + (hasFooter ? 18 : 0) + 8;
}

/**
 * Resolves alert box collisions using iterative repulsion.
 * Higher-risk alerts get priority (sorted first, pushed less).
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

  // Sort by risk score descending — high-risk alerts stay closer to origin
  items.sort((a, b) => ((b as any).risk_score || 0) - ((a as any).risk_score || 0));

  const BOX_W = ALERT_BOX_WIDTH_PX;
  const GAP = 12; // Increased gap for breathing room
  const MAX_OFFSET = ALERT_MAX_OFFSET_PX;

  // Grid-based Collision Resolution
  const CELL_W = BOX_W + GAP;
  const CELL_H = 80; // Smaller cells = better overlap detection
  const maxIter = 60; // More iterations for dense clusters

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
              const ax = a.x + a.offsetX,
                ay = a.y + a.offsetY;
              const bx = b.x + b.offsetX,
                by = b.y + b.offsetY;
              const adx = Math.abs(ax - bx);
              const ady = Math.abs(ay - by);
              const minDistX = BOX_W + GAP;
              const minDistY = (a.boxH + b.boxH) / 2 + GAP;
              if (adx < minDistX && ady < minDistY) {
                moved = true;
                const overlapX = minDistX - adx;
                const overlapY = minDistY - ady;

                // Higher-index items (lower risk) get pushed more
                // This keeps high-risk alerts closer to their true position
                const weightA = i < j ? 0.35 : 0.65;
                const weightB = 1 - weightA;

                if (overlapY < overlapX) {
                  const push = overlapY + 2;
                  if (ay <= by) {
                    a.offsetY -= push * weightA;
                    b.offsetY += push * weightB;
                  } else {
                    a.offsetY += push * weightA;
                    b.offsetY -= push * weightB;
                  }
                } else {
                  const push = overlapX + 2;
                  if (ax <= bx) {
                    a.offsetX -= push * weightA;
                    b.offsetX += push * weightB;
                  } else {
                    a.offsetX += push * weightA;
                    b.offsetX -= push * weightB;
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
