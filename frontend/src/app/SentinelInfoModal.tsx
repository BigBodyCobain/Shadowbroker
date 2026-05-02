'use client';

/* ── SENTINEL HUB — first-time info modal ── */
export function SentinelInfoModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-[10000] flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/90"
        onClick={onClose}
      />
      <div className="relative z-[10001] w-[520px] max-h-[80vh] bg-[var(--bg-secondary)] border border-purple-500/30 shadow-2xl shadow-purple-900/20 overflow-y-auto styled-scrollbar">
        <div className="p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-bold tracking-wider text-purple-300 font-mono">
              SENTINEL HUB IMAGERY
            </h2>
            <button
              onClick={onClose}
              className="text-[var(--text-muted)] hover:text-white transition-colors text-xl leading-none"
            >
              &times;
            </button>
          </div>

          <p className="text-[11px] text-[var(--text-secondary)] font-mono leading-relaxed">
            You now have access to ESA Sentinel-2 satellite imagery directly on the map.
            This uses the Copernicus Data Space Ecosystem with your own credentials.
          </p>

          <div className="space-y-2">
            <h3 className="text-[10px] font-mono text-purple-400 tracking-widest">AVAILABLE LAYERS</h3>
            <div className="grid grid-cols-2 gap-2">
              {[
                { name: 'True Color', desc: 'Natural RGB — see terrain, cities, water' },
                { name: 'False Color IR', desc: 'Near-infrared — vegetation in red' },
                { name: 'NDVI', desc: 'Vegetation health index (green = healthy)' },
                { name: 'Moisture Index', desc: 'Soil & vegetation moisture levels' },
              ].map((l) => (
                <div key={l.name} className="p-2 border border-purple-900/30 bg-purple-950/10">
                  <div className="text-[10px] font-mono text-white">{l.name}</div>
                  <div className="text-[9px] text-[var(--text-muted)]">{l.desc}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <h3 className="text-[10px] font-mono text-purple-400 tracking-widest">USAGE LIMITS (FREE TIER)</h3>
            <div className="p-3 border border-[var(--border-primary)] bg-[var(--bg-primary)]/40 space-y-1.5">
              <div className="flex justify-between text-[10px] font-mono">
                <span className="text-[var(--text-muted)]">Monthly budget</span>
                <span className="text-purple-300">10,000 requests</span>
              </div>
              <div className="flex justify-between text-[10px] font-mono">
                <span className="text-[var(--text-muted)]">Cost per tile</span>
                <span className="text-purple-300">0.25 PU (256&times;256px)</span>
              </div>
              <div className="flex justify-between text-[10px] font-mono">
                <span className="text-[var(--text-muted)]">~Viewport loads/month</span>
                <span className="text-purple-300">~500 (20 tiles each)</span>
              </div>
              <div className="flex justify-between text-[10px] font-mono">
                <span className="text-[var(--text-muted)]">Empty tiles</span>
                <span className="text-green-400">FREE (no data = no charge)</span>
              </div>
            </div>
          </div>

          <div className="space-y-2">
            <h3 className="text-[10px] font-mono text-purple-400 tracking-widest">HOW IT WORKS</h3>
            <ul className="text-[10px] text-[var(--text-secondary)] font-mono leading-relaxed space-y-1 list-disc list-inside">
              <li>Sentinel-2 revisits every ~5 days — not every location has data every day</li>
              <li>The date slider picks the end of a time window; zoomed out uses wider windows</li>
              <li>Black patches = no satellite pass on that date range (normal)</li>
              <li>Best results at zoom 8-14 — closer = sharper imagery (10m resolution)</li>
              <li>Cloud filter auto-skips tiles with {'>'} 30% cloud cover</li>
            </ul>
          </div>

          <button
            onClick={onClose}
            className="w-full py-2.5 bg-purple-500/20 border border-purple-500/40 text-purple-300 hover:bg-purple-500/30 transition-colors text-[11px] font-mono tracking-wider"
          >
            GOT IT
          </button>
        </div>
      </div>
    </div>
  );
}
