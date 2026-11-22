import { useCallback } from 'react';

const API = '';

export function useMeshTerminalMarketsCommand(ctx: any) {
  const { addError, addLines, addOutput, addSystem, nodeIdentity, hasSovereignty, asSearchRecords } = ctx;
  const handleMarketsCommand = async (cmd: string, args: string[], d: any) => {
    switch (cmd) {
            case 'markets': {
              try {
                const query = args.join(' ').trim();
                const res = await fetch(
                  query
                    ? `${API}/api/mesh/oracle/search?q=${encodeURIComponent(query)}&limit=100`
                    : `${API}/api/mesh/oracle/markets`,
                );
                const data = await res.json();
                const markets = query
                  ? asSearchRecords(data.results || data.markets || data.cached || [])
                  : asSearchRecords(
                      Array.isArray(data.markets)
                        ? data.markets
                        : Object.values((data.categories || {}) as Record<string, unknown>).flatMap(
                            (items) => (Array.isArray(items) ? items : []),
                          ),
                    );
                addSystem('');
                if (!markets.length) {
                  addSystem(query ? `  No market matches for '${query}'.` : '  No active prediction markets available.');
                } else {
                  addSystem(
                    query
                      ? `  MARKET SEARCH: ${query} (${markets.length})`
                      : `  PREDICTION MARKETS (${markets.length})`,
                  );
                  for (const m of markets.slice(0, 20)) {
                    const title = pickRecordText(m, ['title', 'question']) || 'untitled market';
                    const pctValue =
                      typeof m.consensus_pct === 'number'
                        ? `${m.consensus_pct}%`
                        : typeof m.probability === 'number'
                          ? `${m.probability}%`
                          : '?%';
                    const category = pickRecordText(m, ['category']);
                    addOutput(`    ${pctValue.padStart(5)}  ${title.slice(0, 60)}`);
                    if (category) {
                      addLines([{ text: `      ${category}`, type: 'dim' }]);
                    }
                  }
                  if (markets.length > 20)
                    addLines([{ text: `    ... and ${markets.length - 20} more`, type: 'dim' }]);
                  addLines([
                    {
                      text: query
                        ? '  Use: predict <market title> yes|no'
                        : "  Tip: markets taiwan | markets bitcoin | markets election",
                      type: 'dim',
                    },
                  ]);
                }
                addSystem('');
              } catch {
                addError('Failed to fetch markets');
              }
              return;
            }
            case 'predict': {
              if (!nodeIdentity || !hasSovereignty()) {
                addError("Not connected. Type 'connect' to activate your Agent identity.");
                return;
              }
              // predict <market title words...> yes|no — last word is side
              if (args.length < 2) {
                addError('Usage: predict <market title> yes|no');
                addLines([{ text: '  Example: predict Will Bitcoin hit 100k? yes', type: 'dim' }]);
                return;
              }
              const pSide = args[args.length - 1].toLowerCase();
              if (!['yes', 'no'].includes(pSide)) {
                addError("Last argument must be 'yes' or 'no'");
                return;
              }
                const pTitle = args.slice(0, -1).join(' ');
                try {
                  const predictionPayload = {
                    market_title: pTitle,
                    side: pSide,
                    stake_amount: 0,
                  };
                  const v = validateEventPayload('prediction', predictionPayload);
                  if (!v.ok) {
                    addError(`Invalid payload: ${v.reason}`);
                    return;
                  }
                  const sequence = nextSequence();
                  const signature = await signEvent(
                    'prediction',
                    nodeIdentity.nodeId,
                    sequence,
                    predictionPayload,
                  );
                  const res = await fetch(`${API}/api/mesh/oracle/predict`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                      node_id: nodeIdentity.nodeId,
                      market_title: pTitle,
                      side: pSide,
                      stake_amount: 0,
                      public_key: nodeIdentity.publicKey,
                      public_key_algo: getPublicKeyAlgo(),
                      signature,
                      sequence,
                      protocol_version: PROTOCOL_VERSION,
                    }),
                  });
                const data = await res.json();
                if (data.ok) {
                  addSystem(`  ${data.detail}`);
                  if (data.probability != null) {
                    const potential =
                      pSide === 'yes'
                        ? (1 - data.probability / 100).toFixed(3)
                        : (data.probability / 100).toFixed(3);
                    addLines([
                      {
                        text: `  Market at ${data.probability}% — potential oracle rep: ${potential}`,
                        type: 'dim',
                      },
                    ]);
                  }
                } else {
                  addError(data.detail);
                }
              } catch {
                addError('Failed to place prediction');
              }
              return;
            }
            case 'oracle': {
              // oracle [node_id] — view oracle profile
              const oTarget = args[0] || (nodeIdentity?.nodeId ?? '');
              if (!oTarget) {
                addError("Usage: oracle <node_id>  (or just 'oracle' for your own)");
                return;
              }
              try {
                const res = await fetch(
                  `${API}/api/mesh/oracle/profile?node_id=${encodeURIComponent(oTarget)}`,
                );
                const data = await res.json();
                if (data.ok === false) {
                  addError(data.detail);
                  return;
                }
                addSystem('');
                addSystem(`  ORACLE: ${data.node_id}`);
                addOutput(
                  `    Oracle Rep:     ${data.oracle_rep} (${data.oracle_rep_locked} locked in stakes)`,
                );
                addOutput(
                  `    Predictions:    ${data.predictions_won}W / ${data.predictions_lost}L (${data.win_rate}% win rate)`,
                );
                addOutput(`    Farming Score:  ${data.farming_pct}% easy bets`);
                const stakes = data.active_stakes || [];
                if (stakes.length > 0) {
                  addSystem('    Active Stakes:');
                  for (const s of stakes) {
                    addOutput(`      ${s.side.toUpperCase()} ${s.amount} rep on msg ${s.message_id}`);
                  }
                }
                const history = data.prediction_history || [];
                if (history.length > 0) {
                  addSystem('    Prediction History:');
                  for (const p of history.slice(0, 10)) {
                    const icon = p.correct ? '+' : '-';
                    addOutput(
                      `      ${icon}${p.rep_earned} ${p.side.toUpperCase()} at ${p.probability}% — ${p.market.slice(0, 40)} (${p.age})`,
                    );
                  }
                }
                addSystem('');
              } catch {
                addError('Failed to fetch oracle profile');
              }
              return;
            }
            case 'stake': {
              // stake <msg_id> truth|false <amount> [days]
              if (!nodeIdentity || !hasSovereignty()) {
                addError("Not connected. Type 'connect' to activate your Agent identity.");
                return;
              }
              const sMsgId = args[0];
              const sSide = args[1]?.toLowerCase();
              const sAmount = parseFloat(args[2]);
              const sDays = parseInt(args[3]) || 1;
              if (
                !sMsgId ||
                !sSide ||
                !['truth', 'false'].includes(sSide) ||
                isNaN(sAmount) ||
                sAmount <= 0
              ) {
                addError('Usage: stake <message_id> truth|false <amount> [days 1-7]');
                addLines([{ text: '  Example: stake a1b2c3d4 truth 0.5 3', type: 'dim' }]);
                return;
                }
                try {
                  const stakePayload = {
                    message_id: sMsgId,
                    poster_id: '',
                    side: sSide,
                    amount: sAmount,
                    duration_days: sDays,
                  };
                  const v = validateEventPayload('stake', stakePayload);
                  if (!v.ok) {
                    addError(`Invalid payload: ${v.reason}`);
                    return;
                  }
                  const sequence = nextSequence();
                  const signature = await signEvent(
                    'stake',
                    nodeIdentity.nodeId,
                    sequence,
                    stakePayload,
                  );
                  const res = await fetch(`${API}/api/mesh/oracle/stake`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                      staker_id: nodeIdentity.nodeId,
                      message_id: sMsgId,
                      poster_id: '',
                      side: sSide,
                      amount: sAmount,
                      duration_days: sDays,
                      public_key: nodeIdentity.publicKey,
                      public_key_algo: getPublicKeyAlgo(),
                      signature,
                      sequence,
                      protocol_version: PROTOCOL_VERSION,
                    }),
                  });
                const data = await res.json();
                if (data.ok) addSystem(`  ${data.detail}`);
                else addError(data.detail);
              } catch {
                addError('Failed to place stake');
              }
              return;
            }
            case 'stakes': {
              // stakes <msg_id> — view stakes on a message
              const stMsgId = args[0];
              if (!stMsgId) {
                addError('Usage: stakes <message_id>');
                return;
              }
              try {
                const res = await fetch(
                  `${API}/api/mesh/oracle/stakes/${encodeURIComponent(stMsgId)}`,
                );
                const data = await res.json();
                addSystem('');
                addSystem(`  ORACLE STAKES: ${stMsgId}`);
                addOutput(`    TRUTH: ${data.truth_total ?? 0} oracle rep`);
                for (const s of data.truth_stakers || []) {
                  addLines([{ text: `      ${s.node_id}: ${s.amount}`, type: 'dim' }]);
                }
                addOutput(`    FALSE: ${data.false_total ?? 0} oracle rep`);
                for (const s of data.false_stakers || []) {
                  addLines([{ text: `      ${s.node_id}: ${s.amount}`, type: 'dim' }]);
                }
                if (data.earliest_expiry) {
                  const expires = new Date(data.earliest_expiry * 1000).toLocaleString();
                  addLines([{ text: `    Earliest resolution: ${expires}`, type: 'dim' }]);
                }
                addSystem('');
              } catch {
                addError('Failed to fetch stakes');
              }
              return;
            }
      default: return;
    }
  };

  return { handleMarketsCommand };
}
