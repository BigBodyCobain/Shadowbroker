// @ts-nocheck
'use client';
import React from 'react';

export function useMeshTerminalPanels(ctx: any) {
  const {
    Access,
    Agent,
    Begin,
    Browse,
    Build,
    CSSProperties,
    Category,
    Check,
    Checking,
    Commons,
    Consensus,
    Contacts,
    Create,
    Creator,
    Encrypted,
    Epoch,
    Gate,
    Infonet,
    Loading,
    LongFast,
    Look,
    Mesh,
    Meshtastic,
    Messages,
    News,
    No,
    Open,
    Position,
    Prediction,
    Public,
    Pull,
    Question,
    RegExpExecArray,
    Scan,
    Search,
    See,
    Shodan,
    Show,
    Staying,
    Summarize,
    Taiwan,
    Type,
    Use,
    Watch,
    Wormhole,
    access,
    actionCommand,
    actionLabel,
    activatePrivateLane,
    active,
    activity,
    addLines,
    addSystem,
    age,
    aircraft,
    airports,
    alias,
    all,
    amber,
    an,
    and,
    apps,
    around,
    as,
    available,
    aviv,
    based,
    bases,
    between,
    bg,
    bitcoin,
    black,
    block,
    blocked,
    board,
    border,
    brief,
    button,
    by,
    calc,
    cards,
    catalog,
    center,
    channels,
    colors,
    cols,
    commands,
    commons,
    connect,
    consensus_pct,
    contacts,
    counts,
    create,
    creator_node_id,
    current,
    current_epoch,
    cyan,
    datacenters,
    dead,
    denied,
    description,
    detail,
    details,
    dim,
    display_name,
    div,
    dm,
    dossier,
    dossiers,
    down,
    drop,
    elon,
    emerald,
    encrypted,
    entries,
    error,
    event,
    exact,
    exec,
    expandedGateDetail,
    expandedGateId,
    expandedGateKey,
    expandedGateLoading,
    expandedGateMessages,
    expandedMarketIndex,
    experimental,
    exposed,
    face,
    fast,
    filter,
    fixed,
    flags,
    flex,
    flow,
    flows,
    focus,
    font,
    from,
    fuchsia,
    full,
    gap,
    gateCatalog,
    gateCatalogLoading,
    gate_id,
    gates,
    getContacts,
    gi,
    grid,
    group,
    guided,
    has_local_access,
    header,
    headlines,
    help,
    here,
    home,
    hosts,
    hover,
    identity,
    identity_scope,
    ignore,
    inbox,
    infonet,
    input,
    inputRef,
    inset_0_0_0_1px_rgba,
    intercept,
    into,
    is,
    items,
    jet,
    justify,
    lane,
    later,
    latest,
    launch,
    leading,
    ledger,
    left,
    length,
    lineColor,
    linked,
    listen,
    locked,
    map,
    markets,
    mask,
    maxHeight,
    maxWidth,
    md,
    member,
    mesh,
    meshRegion,
    message_count,
    messages,
    min,
    min_overall_rep,
    mono,
    msgs,
    mt,
    musk,
    need,
    news,
    nodeId,
    nodeIdentity,
    nodes,
    not,
    now,
    obfuscated,
    observable,
    of,
    on,
    one,
    openGateCard,
    openSurface,
    operator,
    ops,
    or,
    oracle,
    org,
    pattern,
    pending,
    pendingGateCommand,
    person,
    pickRecordText,
    pl,
    place,
    places,
    pos,
    position,
    post,
    posting,
    power,
    pr,
    pre,
    precision,
    prediction,
    presets,
    previews,
    privateLaneDetail,
    privateLaneLabel,
    probability,
    profile,
    profiles,
    publicAgentReady,
    push,
    px,
    py,
    question,
    quick,
    ramstein,
    records,
    regional,
    remain,
    removeItem,
    rep,
    required,
    restricted,
    root,
    rose,
    route,
    routeToWormholeSetup,
    rules,
    runQuickCommand,
    saved,
    search,
    send,
    sender,
    services,
    sessionStorage,
    setActiveGateComposeId,
    setExpandedMarketIndex,
    setGateAccessGranted,
    setGateAccessPromptOpen,
    setGateReplyTarget,
    setMeshRegion,
    setPendingGateCommand,
    setPrivateLanePromptOpen,
    setPrivateLanePromptStatus,
    setSurfacePanel,
    setTimeout,
    shadow,
    shodan,
    shrink,
    signals,
    size,
    slate,
    slice,
    sm,
    sort,
    source,
    space,
    spacex,
    span,
    splice,
    stakes,
    start,
    stays,
    string,
    surfaceInbox,
    surfaceInboxLoading,
    surfaceMarkets,
    surfaceMarketsLoading,
    surfaceMeshCounts,
    surfaceMeshLoading,
    surfacePanel,
    sweep,
    sync,
    system,
    taiwan,
    tap,
    tel,
    text,
    the,
    then,
    to,
    toUpperCase,
    top,
    topical,
    tracking,
    traffic,
    transition,
    translate,
    trim,
    u00A0,
    unblock,
    unknown,
    unlock,
    up,
    useCallback,
    view,
    views,
    vote,
    voteDirections,
    voteScopeKey,
    want,
    watch,
    welcome,
    when,
    whitespace,
    wider,
    wormholeReadyState,
    wormholeSecureRequired,
    wrap,
    yet,
    you
  } = ctx;
  const renderStyledLine = (line: TermLine, index: number) => {
    const tokenClasses: Array<{ pattern: RegExp; className: string }> = [
      { pattern: /\b(MESHTASTIC|MESH|RADIO)\b/gi, className: 'text-emerald-300' },
      { pattern: /\b(GATES?|COMMONS|INBOX|DM|DEAD DROP)\b/gi, className: 'text-fuchsia-300' },
      { pattern: /\b(MARKETS?|ORACLE|COMMANDS?|OPS|DOSSIER|PREDICT)\b/gi, className: 'text-amber-200' },
      { pattern: /\b(INFONET|SHODAN|STATUS|SIGNALS?)\b/gi, className: 'text-cyan-300' },
      { pattern: /\b(LOCKED|READ ONLY|FAILED|ERROR|DENIED)\b/gi, className: 'text-rose-300' },
      { pattern: /\b(READY|ACTIVE|OPEN|UNLOCK|YES)\b/gi, className: 'text-emerald-300' },
    ];

    const segments: Array<{ text: string; className?: string }> = [{ text: line.text }];
    for (const token of tokenClasses) {
      const nextSegments: Array<{ text: string; className?: string }> = [];
      for (const segment of segments) {
        if (segment.className) {
          nextSegments.push(segment);
          continue;
        }
        let lastIndex = 0;
        const regex = new RegExp(token.pattern.source, token.pattern.flags);
        let match: RegExpExecArray | null;
        while ((match = regex.exec(segment.text)) !== null) {
          if (match.index > lastIndex) {
            nextSegments.push({ text: segment.text.slice(lastIndex, match.index) });
          }
          nextSegments.push({ text: match[0], className: token.className });
          lastIndex = match.index + match[0].length;
        }
        if (lastIndex < segment.text.length) {
          nextSegments.push({ text: segment.text.slice(lastIndex) });
        }
      }
      segments.splice(0, segments.length, ...nextSegments);
    }

    const lineChrome =
      line.type === 'header'
        ? 'border-l-2 border-amber-300/35 pl-3 bg-amber-400/[0.03]'
        : line.type === 'error'
          ? 'border-l-2 border-rose-400/35 pl-3 bg-rose-400/[0.03]'
          : line.type === 'system'
            ? 'border-l border-cyan-400/20 pl-3'
            : line.type === 'input'
              ? 'border-l border-cyan-400/18 pl-3'
              : 'pl-3';

    const content = (
      <>
        {segments.map((segment, segmentIndex) => (
          <span key={`${index}-${segmentIndex}`} className={segment.className}>
            {segment.text || '\u00A0'}
          </span>
        ))}
      </>
    );

    if (line.actionCommand) {
      return (
        <button
          key={index}
          type="button"
          onClick={() => runQuickCommand(line.actionCommand!)}
          className={`group flex w-full items-center justify-between gap-3 text-[12px] leading-[1.8] whitespace-pre-wrap break-all border border-fuchsia-500/15 bg-fuchsia-500/[0.03] pr-3 text-left font-mono transition-all hover:border-fuchsia-400/35 hover:bg-fuchsia-500/[0.08] ${lineColor(line.type)} ${lineChrome}`}
        >
          <span className="min-w-0 flex-1">{content}</span>
          <span className="shrink-0 border border-fuchsia-500/25 px-2 py-0.5 text-[13px] tracking-[0.18em] text-fuchsia-200 transition-colors group-hover:border-fuchsia-400/45 group-hover:text-fuchsia-100">
            {line.actionLabel || 'OPEN'}
          </span>
        </button>
      );
    }

    return (
      <div
        key={index}
        className={`text-[12px] leading-[1.8] whitespace-pre-wrap break-all font-mono ${lineColor(line.type)} ${lineChrome}`}
      >
        {content}
      </div>
    );
  };

  const renderSurfacePanel = () => {
    const cardBase =
      'border bg-black/55 px-4 py-3 text-left font-mono transition-all hover:-translate-y-0.5';

    switch (surfacePanel) {
      case 'help':
        return (
          <div className="grid gap-3 md:grid-cols-3">
            {[
              ['MESH / RADIO', 'Public mesh root watch, signals, and LongFast send.', 'mesh', 'border-emerald-500/25 text-emerald-300', 'help mesh'],
              ['GATES (EXPERIMENTAL ENCRYPTION)', 'Open gate details, unlock a gate face, and post into the commons.', 'gates', 'border-fuchsia-500/25 text-fuchsia-300', 'help gates'],
              ['PRIVATE DM INBOX', 'Contacts, inbox previews, and private message flows.', 'inbox', 'border-cyan-500/25 text-cyan-300', 'help inbox'],
              ['MARKETS / ORACLE', 'Prediction markets, oracle profiles, and stakes.', 'markets', 'border-amber-400/25 text-amber-200', 'help markets'],
              ['INFONET', 'Messages, ledger, sync, and event views.', 'gates', 'border-cyan-500/25 text-cyan-300', 'help infonet'],
              ['OPS / DOSSIER', 'News, dossiers, Shodan, places, and aircraft.', 'apps', 'border-amber-400/25 text-amber-200', 'help ops'],
            ].map(([title, desc, _panel, tone, command]) => (
              <button
                key={title}
                type="button"
                onClick={() => runQuickCommand(String(command))}
                className={`${cardBase} ${tone}`}
              >
                <div className="text-sm tracking-[0.24em]">{title}</div>
                <div className="mt-2 text-[11px] leading-6 text-slate-400">{desc}</div>
                <div className="mt-3 text-[12px] tracking-[0.16em] text-slate-500">
                  {String(command)}
                </div>
              </button>
            ))}
          </div>
        );
      case 'apps':
        return (
          <div className="grid gap-3 md:grid-cols-3">
            {[
              ['MARKETS', 'Browse prediction markets', () => runQuickCommand('markets'), 'border-amber-400/25 text-amber-200'],
              ['DOSSIER PRESETS', 'Open guided dossier presets', () => openSurface('dossier'), 'border-fuchsia-500/25 text-fuchsia-300'],
              ['NEWS', 'Pull latest headlines', () => runQuickCommand('news'), 'border-cyan-500/25 text-cyan-300'],
              ['SHODAN', 'Search exposed hosts and services', () => runQuickCommand('shodan'), 'border-cyan-500/25 text-cyan-300'],
              ['MESH RADIO', 'Open the public mesh command lane', () => openSurface('mesh'), 'border-emerald-500/25 text-emerald-300'],
              ['PRIVATE DM INBOX', 'Check the experimental private dead drop', () => openSurface('inbox'), 'border-fuchsia-500/25 text-fuchsia-300'],
            ].map(([title, desc, action, tone]) => (
              <button key={title as string} type="button" onClick={action as () => void} className={`${cardBase} ${tone}`}>
                <div className="text-sm tracking-[0.24em]">{title as string}</div>
                <div className="mt-2 text-[11px] leading-6 text-slate-400">{desc as string}</div>
              </button>
            ))}
          </div>
        );
      case 'dossier':
        return (
          <div className="grid gap-3 md:grid-cols-3">
            {[
              ['PERSON', 'dossier elon musk', 'Build a quick person brief by name'],
              ['PLACE', 'dossier tel aviv', 'Summarize a place-based brief'],
              ['ORG', 'dossier spacex', 'Scan headlines, signals, and markets around an org'],
              ['JET / PLANE', 'jet musk', 'Look up operator or aircraft-linked records'],
              ['SITE', 'place ramstein', 'Check airports, bases, datacenters, power nodes'],
              ['NEWS FLASH', 'news taiwan', 'Pull a fast topical news sweep'],
            ].map(([title, command, desc]) => (
              <button
                key={title}
                type="button"
                onClick={() => runQuickCommand(String(command))}
                className={`${cardBase} border-fuchsia-500/25 text-fuchsia-300 hover:border-fuchsia-400/45 hover:bg-fuchsia-500/10`}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="text-sm tracking-[0.24em]">{title}</div>
                  <div className="text-[12px] tracking-[0.16em] text-amber-200">{command}</div>
                </div>
                <div className="mt-2 text-[11px] leading-6 text-slate-400">{desc}</div>
              </button>
            ))}
          </div>
        );
      case 'mesh':
        return (
          <div className="space-y-3">
            <div className="grid gap-3 md:grid-cols-2">
              <div className="border border-emerald-500/20 bg-black/45 px-4 py-3 font-mono">
                <div className="text-sm tracking-[0.24em] text-emerald-300">PUBLIC MESH LANE</div>
                <div className="mt-2 text-[11px] leading-6 text-slate-300">
                  {publicAgentReady
                    ? `Public Agent active as ${nodeIdentity?.nodeId || 'unknown'}`
                    : 'No public Agent yet. Type connect to create one for mesh posting.'}
                </div>
                <div className="mt-2 text-sm leading-5 text-emerald-200/75">
                  Meshtastic traffic is public / observable. Wormhole is not required here.
                </div>
              </div>
              <div className="border border-cyan-500/20 bg-black/45 px-4 py-3 font-mono">
                <div className="text-sm tracking-[0.24em] text-cyan-300">WORMHOLE OBFUSCATED LANE</div>
                <div className="mt-2 text-[11px] leading-6 text-slate-300">
                  {privateLaneLabel}
                </div>
                <div className="mt-2 text-sm leading-5 text-cyan-200/75">
                  {privateLaneDetail}
                </div>
              </div>
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              {[
                !publicAgentReady
                  ? ['CONNECT', 'Create a public Agent identity for mesh posting', () => runQuickCommand('connect')]
                  : null,
                ['LISTEN', `Watch ${meshRegion} public mesh traffic`, () => runQuickCommand('mesh listen 12')],
                ['CHANNELS', 'See regional activity counts', () => runQuickCommand('mesh channels')],
                ['SIGNALS', 'Open the wider intercept board', () => runQuickCommand('signals 12')],
              ]
                .filter((x): x is [string, string, () => void] => x !== null)
                .map(([title, desc, action]) => (
                <button
                  key={title}
                  type="button"
                  onClick={action}
                  className={`${cardBase} border-emerald-500/25 text-emerald-300`}
                >
                  <div className="text-sm tracking-[0.24em]">{title}</div>
                  <div className="mt-2 text-[11px] leading-6 text-slate-400">{desc}</div>
                </button>
              ))}
            </div>
            <div className="text-sm tracking-[0.26em] text-emerald-300">MESH ROOT CARDS</div>
            {surfaceMeshLoading ? (
              <div className="border border-emerald-500/20 bg-black/45 px-4 py-5 text-[11px] font-mono text-slate-400">
                Loading mesh channels...
              </div>
            ) : (
              <div className="grid gap-3 md:grid-cols-4">
                {Object.entries(surfaceMeshCounts)
                  .sort((a, b) => b[1] - a[1])
                  .slice(0, 8)
                  .map(([region, count]) => (
                    <div
                      key={region}
                      className={`border px-4 py-3 font-mono transition-all hover:-translate-y-0.5 ${
                        region === meshRegion
                          ? 'border-emerald-400/45 bg-emerald-500/10'
                          : 'border-emerald-500/20 bg-black/50 hover:border-emerald-400/35 hover:bg-emerald-500/6'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div className="text-[11px] tracking-[0.22em] text-emerald-200">{region}</div>
                        <div className="text-sm text-emerald-300">{count}</div>
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => {
                            setMeshRegion(region);
                            runQuickCommand(`mesh listen 12`);
                          }}
                          className="border border-emerald-500/20 bg-emerald-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-emerald-300 hover:bg-emerald-500/14"
                        >
                          LISTEN
                        </button>
                        <button
                          type="button"
                          onClick={() => setMeshRegion(region)}
                          className="border border-cyan-500/20 bg-cyan-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-cyan-300 hover:bg-cyan-500/14"
                        >
                          SELECT
                        </button>
                      </div>
                    </div>
                  ))}
              </div>
            )}
          </div>
        );
      case 'markets':
        return (
          <div className="space-y-3">
            <div className="grid gap-3 md:grid-cols-3">
              {[
                ['ALL MARKETS', 'Open the current market board', () => runQuickCommand('markets')],
                ['TAIWAN', 'Search Taiwan-linked markets', () => runQuickCommand('markets taiwan')],
                ['BITCOIN', 'Search BTC-linked markets', () => runQuickCommand('markets bitcoin')],
              ].map(([title, desc, action]) => (
                <button
                  key={title as string}
                  type="button"
                  onClick={action as () => void}
                  className={`${cardBase} border-amber-400/25 text-amber-200`}
                >
                  <div className="text-sm tracking-[0.24em]">{title as string}</div>
                  <div className="mt-2 text-[11px] leading-6 text-slate-400">{desc as string}</div>
                </button>
              ))}
            </div>
            <div className="text-sm tracking-[0.26em] text-amber-200">LIVE MARKET CARDS</div>
            {surfaceMarketsLoading ? (
              <div className="border border-amber-400/20 bg-black/45 px-4 py-5 text-[11px] font-mono text-slate-400">
                Loading market cards...
              </div>
            ) : (
              <div className="grid gap-3 md:grid-cols-3">
                {surfaceMarkets.map((market, idx) => {
                  const title = pickRecordText(market, ['title', 'question']) || `market-${idx + 1}`;
                  const category = pickRecordText(market, ['category']) || 'market';
                  const pctValue =
                    typeof market.consensus_pct === 'number'
                      ? `${market.consensus_pct}%`
                      : typeof market.probability === 'number'
                        ? `${market.probability}%`
                        : '?%';
                  const expanded = expandedMarketIndex === idx;
                  return (
                    <div
                      key={`${title}-${idx}`}
                      className="border border-amber-400/20 bg-black/50 px-4 py-4 font-mono transition-all hover:-translate-y-0.5 hover:border-amber-300/45 hover:bg-amber-400/6"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="text-[11px] leading-6 text-amber-100">{title}</div>
                        <div className="border border-amber-400/20 bg-amber-400/8 px-2 py-1 text-[13px] text-amber-200">
                          {pctValue}
                        </div>
                      </div>
                      <div className="mt-2 text-[13px] tracking-[0.16em] text-slate-500">{category}</div>
                      <div className="mt-4 flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() =>
                            setExpandedMarketIndex((prev) => (prev === idx ? null : idx))
                          }
                          className="border border-amber-400/20 bg-amber-400/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-amber-200 hover:bg-amber-400/14"
                        >
                          {expanded ? 'HIDE' : 'OPEN'}
                        </button>
                        <button
                          type="button"
                          onClick={() => runQuickCommand(`markets ${title}`)}
                          className="border border-amber-400/20 bg-amber-400/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-amber-200 hover:bg-amber-400/14"
                        >
                          BOARD
                        </button>
                        <button
                          type="button"
                          onClick={() => runQuickCommand(`oracle ${nodeIdentity?.nodeId || ''}`.trim())}
                          className="border border-cyan-500/20 bg-cyan-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-cyan-300 hover:bg-cyan-500/14"
                        >
                          PROFILE
                        </button>
                      </div>
                      {expanded && (
                        <div className="mt-4 border border-amber-400/15 bg-black/35 px-3 py-3 text-sm leading-6 text-slate-300">
                          <div className="text-[13px] tracking-[0.18em] text-amber-200">MARKET DETAIL</div>
                          <div className="mt-2">Question: {title}</div>
                          <div>Category: {category}</div>
                          <div>Consensus: {pctValue}</div>
                          <div className="mt-3 text-slate-500">
                            Use the board view to search for the exact market title, then route into prediction or oracle profile commands from the command line when you need precision.
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      case 'inbox':
        const contactEntries = Object.entries(getContacts());
        return (
          <div className="space-y-3">
            <div className="grid gap-3 md:grid-cols-3">
              {[
                ['CHECK INBOX', 'Pull pending experimental obfuscated DM messages', () => runQuickCommand('inbox')],
                ['CONTACTS', 'Show saved obfuscated contacts', () => runQuickCommand('contacts')],
                ['START DM', 'Begin an encrypted obfuscated message flow', () => runQuickCommand('dm')],
              ].map(([title, desc, action]) => (
                <button
                  key={title as string}
                  type="button"
                  onClick={action as () => void}
                  className={`${cardBase} border-cyan-500/25 text-cyan-300`}
                >
                  <div className="text-sm tracking-[0.24em]">{title as string}</div>
                  <div className="mt-2 text-[11px] leading-6 text-slate-400">{desc as string}</div>
                </button>
              ))}
            </div>
            <div className="text-sm tracking-[0.26em] text-cyan-300">EXPERIMENTAL PRIVATE DM INBOX</div>
            {surfaceInboxLoading ? (
              <div className="border border-cyan-500/20 bg-black/45 px-4 py-5 text-[11px] font-mono text-slate-400">
                Checking inbox...
              </div>
            ) : surfaceInbox.length === 0 ? (
              <div className="border border-cyan-500/20 bg-black/45 px-4 py-5 text-[11px] font-mono text-slate-400">
                No inbox previews available.
              </div>
            ) : (
              <div className="grid gap-3 md:grid-cols-2">
                {surfaceInbox.map((message, idx) => (
                  <div
                    key={`${message.sender}-${idx}`}
                    className="border border-cyan-500/20 bg-black/50 px-4 py-4 font-mono transition-all hover:-translate-y-0.5 hover:border-cyan-400/35 hover:bg-cyan-500/6"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-[11px] tracking-[0.18em] text-cyan-200">{message.sender}</div>
                      <div className="text-[13px] text-slate-500">{message.age}</div>
                    </div>
                    <div className="mt-3 text-[11px] leading-6 text-slate-300">
                      {message.text}
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => runQuickCommand('inbox')}
                        className="border border-cyan-500/20 bg-cyan-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-cyan-300 hover:bg-cyan-500/14"
                      >
                        OPEN
                      </button>
                      <button
                        type="button"
                        onClick={() => runQuickCommand(`dm ${message.sender}`)}
                        className="border border-fuchsia-500/20 bg-fuchsia-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-fuchsia-300 hover:bg-fuchsia-500/14"
                      >
                        REPLY
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div className="text-sm tracking-[0.26em] text-fuchsia-300">CONTACT CARDS</div>
            {contactEntries.length === 0 ? (
              <div className="border border-fuchsia-500/20 bg-black/45 px-4 py-5 text-[11px] font-mono text-slate-400">
                No saved contacts yet.
              </div>
            ) : (
              <div className="grid gap-3 md:grid-cols-2">
                {contactEntries.slice(0, 6).map(([contactId, contact]) => (
                  <div
                    key={contactId}
                    className="border border-fuchsia-500/20 bg-black/50 px-4 py-4 font-mono transition-all hover:-translate-y-0.5 hover:border-fuchsia-400/35 hover:bg-fuchsia-500/6"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-[11px] tracking-[0.18em] text-fuchsia-200">
                        {contact.alias || contactId}
                      </div>
                      <div className="text-[13px] text-slate-500">
                        {contact.blocked ? 'BLOCKED' : 'ACTIVE'}
                      </div>
                    </div>
                    {contact.alias && (
                      <div className="mt-1 text-[13px] tracking-[0.14em] text-slate-500">{contactId}</div>
                    )}
                    <div className="mt-4 flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => runQuickCommand(`dm ${contactId}`)}
                        className="border border-cyan-500/20 bg-cyan-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-cyan-300 hover:bg-cyan-500/14"
                      >
                        MESSAGE
                      </button>
                      <button
                        type="button"
                        onClick={() => runQuickCommand(contact.blocked ? `dm unblock ${contactId}` : `dm block ${contactId}`)}
                        className="border border-fuchsia-500/20 bg-fuchsia-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-fuchsia-300 hover:bg-fuchsia-500/14"
                      >
                        {contact.blocked ? 'UNBLOCK' : 'BLOCK'}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      case 'gates':
        return (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="text-sm tracking-[0.28em] text-fuchsia-300">
                GATES (EXPERIMENTAL ENCRYPTION)
              </div>
              <button
                type="button"
                onClick={() => runQuickCommand('gates')}
                className="border border-fuchsia-500/25 bg-fuchsia-500/8 px-3 py-1.5 text-[13px] font-mono tracking-[0.22em] text-fuchsia-200 hover:bg-fuchsia-500/14"
              >
                OPEN GATE LOG
              </button>
            </div>
            {gateCatalogLoading ? (
              <div className="border border-fuchsia-500/20 bg-black/45 px-4 py-5 text-[11px] font-mono text-slate-400">
                Loading gate catalog...
              </div>
            ) : gateCatalog.length === 0 ? (
              <div className="border border-fuchsia-500/20 bg-black/45 px-4 py-5 text-[11px] font-mono text-slate-400">
                No launch gates available.
              </div>
            ) : (
              <div className="grid gap-3 md:grid-cols-2">
                {gateCatalog.map((gate) => {
                  const minRep = gate.rules?.min_overall_rep;
                  const expanded = expandedGateId === gate.gate_id;
                  return (
                    <div
                      key={gate.gate_id}
                      className="border border-fuchsia-500/20 bg-black/50 px-4 py-4 font-mono shadow-[inset_0_0_0_1px_rgba(217,70,239,0.04)] transition-all hover:-translate-y-0.5 hover:border-fuchsia-400/45 hover:bg-fuchsia-500/6"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-[11px] tracking-[0.22em] text-fuchsia-200">
                            {(gate.display_name || gate.gate_id).toUpperCase()}
                          </div>
                          <div className="mt-1 text-[13px] tracking-[0.16em] text-fuchsia-300/75">
                            {gate.gate_id}
                          </div>
                        </div>
                        <div className="text-[13px] text-slate-500">
                          {typeof gate.message_count === 'number' ? `${gate.message_count} msgs` : 'catalog'}
                        </div>
                      </div>
                      <div className="mt-3 min-h-[40px] text-[11px] leading-6 text-slate-400">
                        {gate.description || 'Encrypted commons lane.'}
                      </div>
                      <div className="mt-3 flex items-center justify-between text-[13px] tracking-[0.16em]">
                        <span className="text-amber-200">{minRep ? `REQ ${minRep} REP` : 'OPEN'}</span>
                        <span className="text-cyan-300">{gate.fixed ? 'FIXED LAUNCH GATE' : 'GATE'}</span>
                      </div>
                      <div className="mt-4 flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => openGateCard(gate.gate_id)}
                          className="border border-cyan-500/25 bg-cyan-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-cyan-300 hover:bg-cyan-500/14"
                        >
                          {expanded ? 'HIDE' : 'OPEN'}
                        </button>
                        <button
                          type="button"
                          onClick={() => runQuickCommand(`messages ${gate.gate_id}`)}
                          className="border border-emerald-500/25 bg-emerald-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-emerald-300 hover:bg-emerald-500/14"
                        >
                          MESSAGES
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setActiveGateComposeId(gate.gate_id);
                            setGateReplyTarget(null);
                            setSurfacePanel('gates');
                            setTimeout(() => inputRef.current?.focus(), 40);
                          }}
                          className="border border-amber-400/25 bg-amber-400/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-amber-200 hover:bg-amber-400/14"
                        >
                          POST
                        </button>
                        <button
                          type="button"
                          onClick={() => runQuickCommand(`gate mask ${gate.gate_id}`)}
                          className="border border-fuchsia-500/25 bg-fuchsia-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-fuchsia-200 hover:bg-fuchsia-500/14"
                        >
                          UNLOCK
                        </button>
                      </div>
                      {expandedGateLoading === gate.gate_id && (
                        <div className="mt-4 border border-fuchsia-500/15 bg-black/35 px-3 py-3 text-sm text-slate-400">
                          Loading gate detail...
                        </div>
                      )}
                      {expanded && expandedGateDetail && (
                        <div className="mt-4 space-y-3 border border-fuchsia-500/15 bg-black/40 px-4 py-4">
                          <div className="grid gap-3 md:grid-cols-2">
                            <div>
                              <div className="text-[13px] tracking-[0.18em] text-fuchsia-300">WELCOME</div>
                              <div className="mt-2 text-[11px] leading-6 text-slate-400">
                                {expandedGateDetail.welcome || expandedGateDetail.description || 'Encrypted commons lane.'}
                              </div>
                            </div>
                            <div className="space-y-2 text-sm">
                              <div className="flex items-center justify-between">
                                <span className="text-slate-500">Creator</span>
                                <span className="text-cyan-300">{expandedGateDetail.creator_node_id || 'unknown'}</span>
                              </div>
                              <div className="flex items-center justify-between">
                                <span className="text-slate-500">Messages</span>
                                <span className="text-cyan-300">{expandedGateDetail.message_count || 0}</span>
                              </div>
                              {expandedGateKey && (
                                <>
                                  <div className="flex items-center justify-between">
                                    <span className="text-slate-500">Epoch</span>
                                    <span className="text-fuchsia-200">{String(expandedGateKey.current_epoch || 0)}</span>
                                  </div>
                                  <div className="flex items-center justify-between">
                                    <span className="text-slate-500">Access</span>
                                    <span className="text-emerald-300">
                                      {expandedGateKey.has_local_access
                                        ? String(expandedGateKey.identity_scope || 'member')
                                        : 'locked'}
                                    </span>
                                  </div>
                                </>
                              )}
                            </div>
                          </div>
                          {expandedGateMessages.length > 0 && (
                            <div>
                              <div className="text-[13px] tracking-[0.18em] text-fuchsia-300">THREAD SNAPSHOT</div>
                              <div className="mt-3 grid gap-3">
                                {expandedGateMessages.map((message, messageIndex) => (
                                  <div
                                    key={`${message.nodeId}-${messageIndex}`}
                                    className="border border-cyan-500/15 bg-black/35 px-3 py-3 text-left transition-all hover:border-cyan-400/30 hover:bg-cyan-500/6"
                                  >
                                    <div className="flex items-center justify-between gap-3">
                                      <div className="text-sm tracking-[0.16em] text-cyan-200">{message.nodeId}</div>
                                      <div className="text-[13px] text-slate-500">{message.age}</div>
                                    </div>
                                    <div className="mt-2 text-[11px] leading-6 text-slate-300">{message.text}</div>
                                    {message.encrypted && (
                                      <div className="mt-2 text-[13px] tracking-[0.16em] text-fuchsia-300">
                                        EXPERIMENTAL ENCRYPTION
                                      </div>
                                    )}
                                    <div className="mt-3 flex flex-wrap gap-2">
                                      <button
                                        type="button"
                                        onClick={() => runQuickCommand(`messages ${gate.gate_id}`)}
                                        className="border border-cyan-500/20 bg-cyan-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-cyan-300 hover:bg-cyan-500/14"
                                      >
                                        THREAD
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() => {
                                          setActiveGateComposeId(gate.gate_id);
                                          setGateReplyTarget(message.nodeId);
                                          setTimeout(() => inputRef.current?.focus(), 40);
                                        }}
                                        className="border border-amber-400/20 bg-amber-400/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-amber-200 hover:bg-amber-400/14"
                                      >
                                        REPLY
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() => runQuickCommand(`rep ${message.nodeId}`)}
                                        className="border border-cyan-500/20 bg-cyan-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-cyan-300 hover:bg-cyan-500/14"
                                      >
                                        REP
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() => runQuickCommand(`vote ${message.nodeId} up ${gate.gate_id}`)}
                                        className={`border px-3 py-1.5 text-[13px] tracking-[0.18em] transition-colors ${
                                          voteDirections[voteScopeKey(message.nodeId, gate.gate_id)] === 1
                                            ? 'border-emerald-400/35 bg-emerald-500/16 text-emerald-100'
                                            : 'border-emerald-500/20 bg-emerald-500/8 text-emerald-300 hover:bg-emerald-500/14'
                                        }`}
                                      >
                                        UP
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() => runQuickCommand(`vote ${message.nodeId} down ${gate.gate_id}`)}
                                        className={`border px-3 py-1.5 text-[13px] tracking-[0.18em] transition-colors ${
                                          voteDirections[voteScopeKey(message.nodeId, gate.gate_id)] === -1
                                            ? 'border-rose-400/35 bg-rose-500/16 text-rose-100'
                                            : 'border-rose-500/20 bg-rose-500/8 text-rose-300 hover:bg-rose-500/14'
                                        }`}
                                      >
                                        DOWN
                                      </button>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      default:
        return null;
    }
  };

  const confirmGateAccess = useCallback(() => {
    if (!wormholeSecureRequired || !wormholeReadyState) {
      routeToWormholeSetup();
      return;
    }
    if (typeof window !== 'undefined') {
      try {
        sessionStorage.removeItem(WORMHOLE_RETURN_KEY);
      } catch {
        /* ignore */
      }
    }
    setGateAccessGranted(true);
    setGateAccessPromptOpen(false);
    const nextCommand = pendingGateCommand;
    setPendingGateCommand(null);
    setSurfacePanel('gates');
    if (nextCommand && nextCommand !== 'gates') {
      setTimeout(() => runQuickCommand(nextCommand), 40);
    } else {
      setTimeout(() => runQuickCommand('gates'), 40);
    }
  }, [
    pendingGateCommand,
    routeToWormholeSetup,
    runQuickCommand,
    wormholeReadyState,
    wormholeSecureRequired,
  ]);

  const confirmPrivateLanePrompt = useCallback(() => {
    void activatePrivateLane('gates');
  }, [activatePrivateLane]);

  const dismissPrivateLanePrompt = useCallback(() => {
    setPrivateLanePromptOpen(false);
    setPrivateLanePromptStatus(null);
    addSystem('  Staying on the public lane for now.');
    addLines([
      {
        text: "  Mesh stays public. Type 'gates' or tap ENTER WORMHOLE later when you want the obfuscated commons.",
        type: 'dim',
      },
    ]);
  }, [addLines, addSystem]);

  const denyGateAccess = useCallback(() => {
    setGateAccessPromptOpen(false);
    setPendingGateCommand(null);
    setSurfacePanel('home');
    if (typeof window !== 'undefined') {
      try {
        sessionStorage.removeItem(WORMHOLE_RETURN_KEY);
      } catch {
        /* ignore */
      }
    }
    addSystem('  Gate access denied. Infonet Commons gates remain restricted.');
  }, [addSystem]);

  // Position + size style
  const sizeStyle: React.CSSProperties = {
    width: size.w,
    height: size.h,
    maxWidth: 'calc(100vw - 4rem)',
    maxHeight: 'calc(100vh - 4rem)',
  };
  const absoluteStyle: React.CSSProperties = {
    position: 'fixed',
    top: pos.y,
    left: pos.x,
    ...sizeStyle,
  };

  return { renderStyledLine, renderSurfacePanel };
}
