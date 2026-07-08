'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';

export interface IntelGraphNode {
  id: string;
  label: string;
  type: string;
  score?: number;
  count?: number;
  properties?: Record<string, unknown>;
}

export interface IntelGraphLink {
  source: string;
  target: string;
  label?: string;
  weight?: number;
}

interface SimNode extends IntelGraphNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
  r: number;
}

interface Props {
  nodes: IntelGraphNode[];
  links: IntelGraphLink[];
  height?: number;
  onNodeSelect?: (node: IntelGraphNode) => void;
}

const TYPE_COLOR: Record<string, string> = {
  market: '#22d3ee',
  objective: '#a7f3d0',
  signal: '#fbbf24',
  category: '#60a5fa',
  source: '#c084fc',
  area: '#34d399',
  risk: '#fb7185',
  mobility: '#38bdf8',
  aircraft: '#67e8f9',
  vessel: '#2dd4bf',
  company: '#f59e0b',
  person: '#c084fc',
  country: '#4ade80',
  ip: '#fb923c',
};

function nodeColor(type: string): string {
  return TYPE_COLOR[type] || '#22d3ee';
}

function radiusFor(node: IntelGraphNode): number {
  const score = Number(node.score || node.properties?.score || 0);
  const count = Number(node.count || 1);
  return Math.max(5, Math.min(18, 5 + Math.sqrt(Math.max(score, count)) * 0.9));
}

export default function BusinessIntelGraph({ nodes, links, height = 260, onNodeSelect }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const simRef = useRef<{ nodes: SimNode[]; hover: SimNode | null; selected: SimNode | null }>({
    nodes: [],
    hover: null,
    selected: null,
  });
  const [selected, setSelected] = useState<IntelGraphNode | null>(null);

  const prepared = useMemo(() => {
    const cappedNodes = nodes.slice(0, 90);
    const ids = new Set(cappedNodes.map((n) => n.id));
    return {
      nodes: cappedNodes,
      links: links.filter((l) => ids.has(String(l.source)) && ids.has(String(l.target))).slice(0, 180),
    };
  }, [nodes, links]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(1, Math.floor(rect.width));
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    canvas.style.height = `${height}px`;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const byId = new Map<string, SimNode>();
    const simNodes = prepared.nodes.map((node, i) => {
      const angle = (i / Math.max(1, prepared.nodes.length)) * Math.PI * 2;
      const ring = Math.min(width, height) * (0.22 + (i % 5) * 0.045);
      const sim = {
        ...node,
        x: width / 2 + Math.cos(angle) * ring,
        y: height / 2 + Math.sin(angle) * ring,
        vx: 0,
        vy: 0,
        r: radiusFor(node),
      };
      byId.set(node.id, sim);
      return sim;
    });
    simRef.current.nodes = simNodes;

    let frame = 0;
    let raf = 0;
    const draw = () => {
      frame += 1;
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = 'rgba(2, 6, 12, 0.88)';
      ctx.fillRect(0, 0, width, height);

      for (const node of simNodes) {
        const cx = width / 2;
        const cy = height / 2;
        node.vx += (cx - node.x) * 0.0009;
        node.vy += (cy - node.y) * 0.0009;
      }

      for (const link of prepared.links) {
        const a = byId.get(String(link.source));
        const b = byId.get(String(link.target));
        if (!a || !b) continue;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.max(1, Math.hypot(dx, dy));
        const desired = 56 + Math.min(70, 16 * Number(link.weight || 1));
        const force = (dist - desired) * 0.0009;
        const fx = dx * force;
        const fy = dy * force;
        a.vx += fx;
        a.vy += fy;
        b.vx -= fx;
        b.vy -= fy;
      }

      for (let i = 0; i < simNodes.length; i += 1) {
        for (let j = i + 1; j < simNodes.length; j += 1) {
          const a = simNodes[i];
          const b = simNodes[j];
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const dist = Math.max(1, Math.hypot(dx, dy));
          const repel = Math.min(2.8, 90 / (dist * dist));
          const fx = dx * repel;
          const fy = dy * repel;
          a.vx -= fx;
          a.vy -= fy;
          b.vx += fx;
          b.vy += fy;
        }
      }

      for (const node of simNodes) {
        node.vx *= 0.88;
        node.vy *= 0.88;
        node.x = Math.max(node.r + 4, Math.min(width - node.r - 4, node.x + node.vx));
        node.y = Math.max(node.r + 4, Math.min(height - node.r - 4, node.y + node.vy));
      }

      ctx.lineWidth = 1;
      for (const link of prepared.links) {
        const a = byId.get(String(link.source));
        const b = byId.get(String(link.target));
        if (!a || !b) continue;
        ctx.strokeStyle = `rgba(34, 211, 238, ${Math.min(0.35, 0.08 + Number(link.weight || 1) * 0.035)})`;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }

      for (const node of simNodes) {
        const color = nodeColor(node.type);
        const active = simRef.current.hover?.id === node.id || simRef.current.selected?.id === node.id;
        ctx.shadowBlur = active ? 16 : 8;
        ctx.shadowColor = color;
        ctx.fillStyle = color;
        ctx.globalAlpha = active ? 1 : 0.82;
        ctx.beginPath();
        ctx.arc(node.x, node.y, node.r, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;
        ctx.globalAlpha = 1;

        if (active || node.type === 'market' || node.type === 'objective') {
          ctx.font = '10px var(--font-jetbrains-mono), monospace';
          ctx.fillStyle = 'rgba(207, 250, 254, 0.92)';
          ctx.textAlign = 'center';
          const label = node.label.length > 26 ? `${node.label.slice(0, 25)}...` : node.label;
          ctx.fillText(label, node.x, node.y - node.r - 6);
        }
      }

      if (frame < 520) raf = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(raf);
  }, [prepared, height]);

  const pickNode = (clientX: number, clientY: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    const x = clientX - rect.left;
    const y = clientY - rect.top;
    return [...simRef.current.nodes]
      .sort((a, b) => b.r - a.r)
      .find((node) => Math.hypot(node.x - x, node.y - y) <= node.r + 6) || null;
  };

  return (
    <div className="w-full">
      <canvas
        ref={canvasRef}
        className="w-full border border-cyan-900/40 bg-black/80"
        style={{ height }}
        onMouseMove={(event) => {
          simRef.current.hover = pickNode(event.clientX, event.clientY);
          event.currentTarget.style.cursor = simRef.current.hover ? 'pointer' : 'default';
        }}
        onMouseLeave={() => {
          simRef.current.hover = null;
        }}
        onClick={(event) => {
          const node = pickNode(event.clientX, event.clientY);
          if (!node) return;
          simRef.current.selected = node;
          setSelected(node);
          onNodeSelect?.(node);
        }}
      />
      <div className="mt-2 min-h-[42px] border border-cyan-900/30 bg-black/45 px-2 py-1.5">
        {selected ? (
          <>
            <div className="truncate text-[11px] font-mono font-bold tracking-wider text-cyan-300">
              {selected.type.toUpperCase()} / {selected.label}
            </div>
            <div className="mt-0.5 truncate text-[10px] font-mono text-cyan-600">
              score {Math.round(Number(selected.score || 0))} / links shown {prepared.links.length}
            </div>
          </>
        ) : (
          <div className="text-[10px] font-mono tracking-wider text-cyan-700">
            Select a node to inspect the signal relationship.
          </div>
        )}
      </div>
    </div>
  );
}
