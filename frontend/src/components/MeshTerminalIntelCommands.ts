// @ts-nocheck
import { useCallback } from 'react';

const API = '';

export interface MeshTerminalIntelCommandsCtx {
  addError: (t: string) => void;
  addLines: (lines: any[]) => void;
  addOutput: (t: string) => void;
  addSystem: (t: string) => void;
}
export function useMeshTerminalIntelCommands(ctx: MeshTerminalIntelCommandsCtx) {
  const { addError, addLines, addOutput, addSystem } = ctx;

  const cmdApps = useCallback(() => {
    addSystem('');
    addSystem('  TERMINAL SURFACES');
    addOutput('    INFONET      Gates, messages, sync, ledger, event lookups');
    addOutput('    MESH         Meshtastic region watch + public mesh send');
    addOutput('    DEAD DROP    Encrypted DM lane and contact controls');
    addOutput('    ORACLE       Markets, predicts, stakes, profiles');
    addOutput('    INTEL        News, dossiers, place search, jet search, Shodan');
    addOutput('    UTILITIES    KiwiSDR nearest, routing audit, identity tools');
    addSystem('');
    addLines([
      {
        text: "  Try: gate infonet | messages infonet | news taiwan | dossier musk | jet adelson | shodan nginx",
        type: 'dim',
      },
    ]);
    addSystem('');
  }, [addLines, addOutput, addSystem]);

  const cmdNews = useCallback(
    async (query: string, limit: number = 8) => {
      try {
        const res = await fetch(`${API}/api/live-data/slow`);
        const data = await res.json();
        const news = asSearchRecords(data?.news);
        const hits = news
          .filter((item) =>
            recordMatchesQuery(item, query, ['title', 'summary', 'source', 'description', 'place']),
          )
          .slice(0, Math.max(1, Math.min(limit, 12)));
        addSystem('');
        addSystem(query ? `  NEWS MATCHES: ${query}` : '  LATEST NEWS');
        if (!hits.length) {
          addSystem('    No headline matches.');
        } else {
          for (const item of hits) {
            const title =
              pickRecordText(item, ['title', 'headline', 'name']) || 'Untitled headline';
            const source = pickRecordText(item, ['source', 'publisher']) || 'unknown';
            const place = pickRecordText(item, ['place', 'region', 'country']);
            addOutput(`    ${title.slice(0, 78)}`);
            addLines([
              {
                text: `      ${source}${place ? ` · ${place}` : ''}`,
                type: 'dim',
              },
            ]);
          }
        }
        addSystem('');
      } catch {
        addError('Failed to fetch news');
      }
    },
    [addError, addLines, addOutput, addSystem],
  );

  const cmdJets = useCallback(
    async (query: string) => {
      if (!query.trim()) {
        addError('Usage: jet <name|tail|operator|callsign>');
        return;
      }
      try {
        const res = await fetch(`${API}/api/live-data/fast`);
        const data = await res.json();
        const sources = [
          { label: 'PRIVATE JET', items: asSearchRecords(data?.private_jets) },
          { label: 'PRIVATE FLIGHT', items: asSearchRecords(data?.private_flights) },
          { label: 'TRACKED FLIGHT', items: asSearchRecords(data?.tracked_flights) },
        ];
        const hits = sources.flatMap((source) =>
          source.items
            .filter((item) =>
              recordMatchesQuery(item, query, [
                'owner',
                'operator',
                'registration',
                'tail',
                'callsign',
                'icao24',
                'name',
                'model',
                'aircraft_type',
              ]),
            )
            .slice(0, 6)
            .map((item) => ({ source: source.label, item })),
        );
        addSystem('');
        addSystem(`  FLIGHT / JET MATCHES: ${query}`);
        if (!hits.length) {
          addSystem('    No matching private aviation hits.');
        } else {
          for (const hit of hits.slice(0, 10)) {
            const title =
              pickRecordText(hit.item, ['registration', 'tail', 'callsign', 'icao24', 'name']) ||
              'unknown-airframe';
            const owner = pickRecordText(hit.item, ['owner', 'operator', 'category', 'model']);
            addOutput(`    ${hit.source.padEnd(14)} ${title}`);
            addLines([
              {
                text: `      ${owner || 'owner/operator n/a'} · ${formatLatLng(hit.item)}`,
                type: 'dim',
              },
            ]);
          }
        }
        addSystem('');
      } catch {
        addError('Failed to search flight data');
      }
    },
    [addError, addLines, addOutput, addSystem],
  );

  const cmdPlaces = useCallback(
    async (query: string) => {
      if (!query.trim()) {
        addError('Usage: place <name|city|country|site>');
        return;
      }
      try {
        const res = await fetch(`${API}/api/live-data/slow`);
        const data = await res.json();
        const sources = [
          { label: 'AIRPORT', items: asSearchRecords(data?.airports) },
          { label: 'BASE', items: asSearchRecords(data?.military_bases) },
          { label: 'DC', items: asSearchRecords(data?.datacenters) },
          { label: 'POWER', items: asSearchRecords(data?.power_plants) },
          { label: 'QUAKE', items: asSearchRecords(data?.earthquakes) },
          { label: 'VOLCANO', items: asSearchRecords(data?.volcanoes) },
        ];
        const hits = sources.flatMap((source) =>
          source.items
            .filter((item) =>
              recordMatchesQuery(item, query, [
                'name',
                'title',
                'place',
                'city',
                'country',
                'state',
                'icao',
                'iata',
                'operator',
              ]),
            )
            .slice(0, 5)
            .map((item) => ({ source: source.label, item })),
        );
        addSystem('');
        addSystem(`  PLACE MATCHES: ${query}`);
        if (!hits.length) {
          addSystem('    No matching place records.');
        } else {
          for (const hit of hits.slice(0, 12)) {
            const title =
              pickRecordText(hit.item, ['name', 'title', 'place', 'city']) || 'unknown-site';
            const sub = pickRecordText(hit.item, ['country', 'state', 'icao', 'iata', 'type']);
            addOutput(`    ${hit.source.padEnd(8)} ${title}`);
            addLines([
              {
                text: `      ${sub || 'detail n/a'} · ${formatLatLng(hit.item)}`,
                type: 'dim',
              },
            ]);
          }
        }
        addSystem('');
      } catch {
        addError('Failed to search place data');
      }
    },
    [addError, addLines, addOutput, addSystem],
  );

  const cmdDossier = useCallback(
    async (query: string) => {
      if (!query.trim()) {
        addError('Usage: dossier <name|place|org>');
        return;
      }
      try {
        const [slowRes, fastRes, marketRes, signalRes] = await Promise.all([
          fetch(`${API}/api/live-data/slow`),
          fetch(`${API}/api/live-data/fast`),
          fetch(`${API}/api/mesh/oracle/search?q=${encodeURIComponent(query)}&limit=5`),
          fetch(`${API}/api/mesh/signals?limit=80`),
        ]);
        const [slow, fast, markets, signals] = await Promise.all([
          slowRes.json(),
          fastRes.json(),
          marketRes.json().catch(() => ({})),
          signalRes.json().catch(() => ({})),
        ]);

        const newsHits = asSearchRecords(slow?.news).filter((item) =>
          recordMatchesQuery(item, query, ['title', 'summary', 'source', 'description', 'place']),
        );
        const jetHits = [
          ...asSearchRecords(fast?.private_jets),
          ...asSearchRecords(fast?.private_flights),
          ...asSearchRecords(fast?.tracked_flights),
        ].filter((item) =>
          recordMatchesQuery(item, query, [
            'owner',
            'operator',
            'registration',
            'tail',
            'callsign',
            'icao24',
            'name',
            'model',
          ]),
        );
        const placeHits = [
          ...asSearchRecords(slow?.airports),
          ...asSearchRecords(slow?.military_bases),
          ...asSearchRecords(slow?.datacenters),
          ...asSearchRecords(slow?.power_plants),
          ...asSearchRecords(slow?.earthquakes),
          ...asSearchRecords(slow?.volcanoes),
        ].filter((item) =>
          recordMatchesQuery(item, query, [
            'name',
            'title',
            'place',
            'city',
            'country',
            'state',
            'icao',
            'iata',
          ]),
        );
        const signalHits = asSearchRecords(signals?.signals).filter((item) =>
          recordMatchesQuery(item, query, ['callsign', 'status', 'comment', 'source', 'region']),
        );
        const marketHits = asSearchRecords(markets?.markets || markets?.cached || []);

        addSystem('');
        addSystem(`  DOSSIER: ${query}`);
        addOutput(
          `    hits · news:${newsHits.length} places:${placeHits.length} flights:${jetHits.length} markets:${marketHits.length} signals:${signalHits.length}`,
        );

        if (newsHits[0]) {
          addSystem('    HEADLINE');
          addLines([
            {
              text: `      ${pickRecordText(newsHits[0], ['title', 'headline', 'name'])}`,
              type: 'dim',
            },
          ]);
        }
        if (placeHits[0]) {
          addSystem('    PLACE');
          addLines([
            {
              text: `      ${pickRecordText(placeHits[0], ['name', 'title', 'place', 'city'])} · ${formatLatLng(placeHits[0])}`,
              type: 'dim',
            },
          ]);
        }
        if (jetHits[0]) {
          addSystem('    AVIATION');
          addLines([
            {
              text: `      ${pickRecordText(jetHits[0], ['registration', 'tail', 'callsign', 'icao24'])} · ${pickRecordText(jetHits[0], ['owner', 'operator', 'model']) || 'owner/operator n/a'}`,
              type: 'dim',
            },
          ]);
        }
        if (marketHits[0]) {
          addSystem('    MARKET');
          addLines([
            {
              text: `      ${pickRecordText(marketHits[0], ['title', 'question'])}`,
              type: 'dim',
            },
          ]);
        }
        if (signalHits[0]) {
          addSystem('    SIGNAL');
          addLines([
            {
              text: `      ${pickRecordText(signalHits[0], ['callsign', 'source'])} · ${pickRecordText(signalHits[0], ['status', 'comment', 'region']) || 'recent activity'}`,
              type: 'dim',
            },
          ]);
        }
        addSystem('');
      } catch {
        addError('Failed to build dossier');
      }
    },
    [addError, addLines, addOutput, addSystem],
  );

  const cmdShodan = useCallback(
    async (args: string[]) => {
      try {
        if (!args.length) {
          const res = await fetch(`${API}/api/tools/shodan/status`);
          const data = await res.json();
          addSystem('');
          addSystem('  SHODAN');
          addOutput(`    Ready:       ${data.ready ? 'YES' : 'NO'}`);
          addOutput(`    Configured:  ${data.configured ? 'YES' : 'NO'}`);
          if (data.detail) addLines([{ text: `      ${data.detail}`, type: 'dim' }]);
          addSystem('');
          return;
        }
        if (args[0]?.toLowerCase() === 'host') {
          const ip = args[1];
          if (!ip) {
            addError('Usage: shodan host <ip>');
            return;
          }
          const res = await fetch(`${API}/api/tools/shodan/host`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ip, history: false }),
          });
          const data = await res.json();
          if (!res.ok) {
            addError(data.detail || 'Shodan host lookup failed');
            return;
          }
          addSystem('');
          addSystem(`  SHODAN HOST: ${ip}`);
          addOutput(`    Org:         ${data.org || 'unknown'}`);
          addOutput(`    OS:          ${data.os || 'unknown'}`);
          addOutput(`    Ports:       ${Array.isArray(data.ports) ? data.ports.join(', ') : 'n/a'}`);
          addOutput(`    Hostnames:   ${Array.isArray(data.hostnames) ? data.hostnames.join(', ') : 'n/a'}`);
          addSystem('');
          return;
        }
        const query = args.join(' ');
        const res = await fetch(`${API}/api/tools/shodan/search`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query, page: 1, facets: [] }),
        });
        const data = await res.json();
        if (!res.ok) {
          addError(data.detail || 'Shodan search failed');
          return;
        }
        const matches = asSearchRecords(data.matches);
        addSystem('');
        addSystem(`  SHODAN MATCHES: ${query}`);
        if (!matches.length) {
          addSystem('    No host matches.');
        } else {
          for (const item of matches.slice(0, 8)) {
            addOutput(
              `    ${pickRecordText(item, ['ip_str', 'ip']) || 'unknown-ip'} · ${pickRecordText(item, ['org', 'isp']) || 'unknown org'}`,
            );
            addLines([
              {
                text: `      ${pickRecordText(item, ['product', 'os', 'hostnames']) || 'service detail unavailable'}`,
                type: 'dim',
              },
            ]);
          }
        }
        addSystem('');
      } catch {
        addError('Failed to query Shodan');
      }
    },
    [addError, addLines, addOutput, addSystem],
  );

  return { cmdApps, cmdNews, cmdJets, cmdPlaces, cmdDossier, cmdShodan };
}
