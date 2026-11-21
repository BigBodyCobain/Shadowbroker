'use client';

import React from 'react';
import { Marker, Popup } from 'react-map-gl/maplibre';
import { PIN_CATEGORY_LABELS, PIN_CATEGORY_COLORS, type PinCategory } from '@/types/aiIntel';

export interface MapEntityPopupsProps {
  AIIntelPinDetail?: any;
  Active?: any;
  Activity?: any;
  Address?: any;
  Air?: any;
  Alert?: any;
  AlertTriangle?: any;
  Altitude?: any;
  Antenna?: any;
  Arrow?: any;
  Article?: any;
  Bands?: any;
  Below?: any;
  Callsign?: any;
  Capacity?: any;
  Category?: any;
  CctvFullscreenModal?: any;
  Center?: any;
  Change?: any;
  Check?: any;
  Classification?: any;
  Close?: any;
  Confidence?: any;
  Connecting?: any;
  Contradiction?: any;
  Coords?: any;
  Core?: any;
  Correlation?: any;
  CorrelationPopup?: any;
  Country?: any;
  Course?: any;
  Cross?: any;
  CrowdThreat?: any;
  Data?: any;
  Destination?: any;
  Detail?: any;
  Dialog?: any;
  Duration?: any;
  Earthquake?: any;
  Elevation?: any;
  Enriched?: any;
  Enter?: any;
  Eruption?: any;
  Escape?: any;
  Event?: any;
  Expires?: any;
  Explain?: any;
  ExternalLink?: any;
  Extreme?: any;
  Fishing?: any;
  FishingDestinationRoute?: any;
  Flag?: any;
  Force?: any;
  Frequency?: any;
  Fuel?: any;
  Goldstein?: any;
  Good?: any;
  Ground?: any;
  GtRiskPopup?: any;
  HTMLTextAreaElement?: any;
  Hazardous?: any;
  Info?: any;
  Intel?: any;
  It?: any;
  Kalshi?: any;
  Kind?: any;
  KiwiProps?: any;
  KiwiSDR?: any;
  Label?: any;
  Last?: any;
  Level?: any;
  Listeners?: any;
  LoRa?: any;
  Location?: any;
  MHz?: any;
  Magnitude?: any;
  MilitaryBasePopup?: any;
  Minor?: any;
  Model?: any;
  Moderate?: any;
  Modulation?: any;
  MultiPolygon?: any;
  Negative?: any;
  No?: any;
  Node?: any;
  Notes?: any;
  Oblast?: any;
  Observations?: any;
  Occurred?: any;
  Open?: any;
  Operator?: any;
  Oracle?: any;
  Pin?: any;
  PinCategory?: any;
  Placement?: any;
  Plant?: any;
  Play?: any;
  Police?: any;
  Polygon?: any;
  Polymarket?: any;
  Portalled?: any;
  Power?: any;
  Prevent?: any;
  Progress?: any;
  Provenance?: any;
  Proxy?: any;
  Pulsing?: any;
  Quality?: any;
  Radio?: any;
  Radius?: any;
  Raid?: any;
  Receivers?: any;
  Record?: any;
  Region?: any;
  RegionDossierPanel?: any;
  Registration?: any;
  Report?: any;
  Reported?: any;
  Risk?: any;
  Route?: any;
  Same?: any;
  SatNOGS?: any;
  Satellite?: any;
  SatellitePopup?: any;
  Scanner?: any;
  ScannerProps?: any;
  Score?: any;
  Sensitive?: any;
  Sentiment?: any;
  Severe?: any;
  Severity?: any;
  Shape?: any;
  Ship?: any;
  ShipPopup?: any;
  Sighting?: any;
  Sightings?: any;
  SigintPopup?: any;
  SigintProps?: any;
  Since?: any;
  Solver?: any;
  Source?: any;
  Speed?: any;
  Squawk?: any;
  Start?: any;
  Station?: any;
  Status?: any;
  Subcategory?: any;
  TelegramOsintPopup?: any;
  Threat?: any;
  TinyGS?: any;
  Tracking?: any;
  Train?: any;
  Type?: any;
  URLs?: any;
  Ukraine?: any;
  Unhealthy?: any;
  Unknown?: any;
  Users?: any;
  Very?: any;
  Vessel?: any;
  View?: any;
  Volcano?: any;
  Wastewater?: any;
  WastewaterPopup?: any;
  Weather?: any;
  WikiImage?: any;
  Witness?: any;
  _blank?: any;
  _build_assessment?: any;
  _headlines_list?: any;
  _snippets_list?: any;
  _urls_list?: any;
  a855f7?: any;
  a855f733?: any;
  a855f766?: any;
  a855f799?: any;
  above?: any;
  absolute?: any;
  actors?: any;
  actual?: any;
  address?: any;
  adverse?: any;
  air_quality?: any;
  air_raid?: any;
  aircraft_model?: any;
  alertKey?: any;
  alert_type?: any;
  alerts?: any;
  align?: any;
  alignItems?: any;
  all?: any;
  already?: any;
  alt_km?: any;
  always?: any;
  amber?: any;
  amtrak?: any;
  an?: any;
  and?: any;
  animate?: any;
  anomaly_id?: any;
  antenna?: any;
  aoi_id?: any;
  aoi_name?: any;
  approved?: any;
  aq?: any;
  aqi?: any;
  article?: any;
  articleSourceUrl?: any;
  artillery_shelling?: any;
  as?: any;
  assessment?: any;
  async?: any;
  at?: any;
  auto?: any;
  available?: any;
  avg_sentiment?: any;
  back?: any;
  backdrop?: any;
  backdropFilter?: any;
  backend?: any;
  background?: any;
  bands?: any;
  bar?: any;
  based?: any;
  between?: any;
  bg?: any;
  black?: any;
  block?: any;
  blur?: any;
  body?: any;
  bold?: any;
  border?: any;
  borderBottom?: any;
  borderLeft?: any;
  borderLeftColor?: any;
  borderRight?: any;
  borderStyle?: any;
  borderTop?: any;
  borderWidth?: any;
  bottom?: any;
  box?: any;
  boxShadow?: any;
  break?: any;
  breaking?: any;
  btn?: any;
  buildCctvProxyUrl?: any;
  buildPolymarketUrl?: any;
  button?: any;
  by?: any;
  bypass?: any;
  c084fc?: any;
  c4b5fd?: any;
  calc?: any;
  callsign?: any;
  camera?: any;
  cameraId?: any;
  canvas?: any;
  capacity_mw?: any;
  capitalize?: any;
  carrier?: any;
  catch?: any;
  category_colour?: any;
  cctv?: any;
  center?: any;
  center_lat?: any;
  center_lon?: any;
  checkbox?: any;
  checked?: any;
  chemical?: any;
  circle?: any;
  city?: any;
  clamp?: any;
  clear?: any;
  click?: any;
  clientCount?: any;
  closeButton?: any;
  closeOnClick?: any;
  cluster?: any;
  cog?: any;
  col?: any;
  colors?: any;
  cols?: any;
  columns?: any;
  combining?: any;
  company?: any;
  conflict?: any;
  connecting?: any;
  consensus_pct?: any;
  const?: any;
  constructive?: any;
  contagion?: any;
  context?: any;
  coordinates?: any;
  corr?: any;
  corr_index?: any;
  correlation?: any;
  correlations?: any;
  corroboration?: any;
  country?: any;
  country_name?: any;
  createPortal?: any;
  critical?: any;
  cross?: any;
  crowdthreat?: any;
  currentTarget?: any;
  cursor?: any;
  custom?: any;
  cyan?: any;
  d8b4fe?: any;
  data?: any;
  database?: any;
  datacenter?: any;
  datacenters?: any;
  date?: any;
  date_time?: any;
  delay?: any;
  destination?: any;
  details?: any;
  detected?: any;
  dialog?: any;
  display?: any;
  div?: any;
  dossier?: any;
  dot?: any;
  down?: any;
  drones?: any;
  drop?: any;
  duration?: any;
  duration_hrs?: any;
  e9d5ff?: any;
  eab308?: any;
  earthquake?: any;
  earthquakes?: any;
  ef4444?: any;
  elevated?: any;
  elevation?: any;
  else?: any;
  emerald?: any;
  entity?: any;
  entity_id?: any;
  entity_label?: any;
  entity_type?: any;
  estimate?: any;
  event_date?: any;
  events?: any;
  expires?: any;
  external?: any;
  f97316?: any;
  fade?: any;
  fallback?: any;
  family?: any;
  fbbf24?: any;
  fde68a?: any;
  feed?: any;
  ff4444?: any;
  ff6b6b?: any;
  ff8800?: any;
  ff8844?: any;
  ffcc00?: any;
  fields?: any;
  filter?: any;
  financial?: any;
  find?: any;
  fire?: any;
  firing?: any;
  fishing_activity?: any;
  fishing_event?: any;
  fixed?: any;
  flex?: any;
  floor?: any;
  focus?: any;
  font?: any;
  fontSize?: any;
  fontWeight?: any;
  formatDossierTime?: any;
  found?: any;
  frequency?: any;
  from?: any;
  fuel_type?: any;
  full?: any;
  fullscreen?: any;
  gap?: any;
  gdelt?: any;
  geometry?: any;
  getFullYear?: any;
  getTime?: any;
  gets?: any;
  global?: any;
  goldstein?: any;
  gradient?: any;
  gray?: any;
  green?: any;
  grid?: any;
  group?: any;
  gt_risk?: any;
  h2?: any;
  handleSavePin?: any;
  handled?: any;
  has?: any;
  here?: any;
  hidden?: any;
  high?: any;
  hls?: any;
  hostname?: any;
  hotkeys?: any;
  hover?: any;
  iLat?: any;
  iLng?: any;
  icao24?: any;
  if?: any;
  image?: any;
  imo?: any;
  in?: any;
  includes?: any;
  inline?: any;
  input?: any;
  inset?: any;
  intel?: any;
  intelligence?: any;
  internet?: any;
  internet_outages?: any;
  interpShip?: any;
  interpretation?: any;
  is?: any;
  it?: any;
  items?: any;
  its?: any;
  itself?: any;
  join?: any;
  justify?: any;
  justifyContent?: any;
  kalshi_pct?: any;
  keys?: any;
  keywords?: any;
  kiwisdr?: any;
  kiwisdrs?: any;
  km?: any;
  kn?: any;
  kts?: any;
  last?: any;
  last_eruption_year?: any;
  last_seen?: any;
  late?: any;
  latitude?: any;
  ldquo?: any;
  lead?: any;
  leading?: any;
  left?: any;
  length?: any;
  let?: any;
  level?: any;
  lg?: any;
  line?: any;
  lineHeight?: any;
  link?: any;
  list?: any;
  listeners?: any;
  live?: any;
  liveuamap?: any;
  location_title?: any;
  lon?: any;
  longitude?: any;
  low?: any;
  m3u8?: any;
  machine?: any;
  magnitude_unit?: any;
  maneuver?: any;
  maneuvers?: any;
  map?: any;
  maplibre?: any;
  marginLeft?: any;
  marker?: any;
  market?: any;
  match?: any;
  match_score?: any;
  max?: any;
  maxH?: any;
  maxHeight?: any;
  mb?: any;
  md?: any;
  mean_change_pct?: any;
  measures?: any;
  mediaType?: any;
  media_type?: any;
  media_url?: any;
  medium?: any;
  middle?: any;
  milbase?: any;
  military_base?: any;
  military_bases?: any;
  min?: any;
  minWidth?: any;
  mjpeg?: any;
  mjpg?: any;
  ml?: any;
  mmsi?: any;
  modal?: any;
  moderate?: any;
  modulation?: any;
  mono?: any;
  more?: any;
  mp4?: any;
  muted?: any;
  name_en?: any;
  nativeEvent?: any;
  negative?: any;
  neutral?: any;
  new?: any;
  news?: any;
  none?: any;
  noopener?: any;
  norad_id?: any;
  noreferrer?: any;
  not?: any;
  nowrap?: any;
  nuclear?: any;
  num_articles?: any;
  num_sources?: any;
  observations?: any;
  occurred?: any;
  omitted?: any;
  on?: any;
  onClose?: any;
  onDeleted?: any;
  onEntityClick?: any;
  onKeyUp?: any;
  onMouseEnter?: any;
  onMouseLeave?: any;
  onPinPlaced?: any;
  onUpdated?: any;
  only?: any;
  open?: any;
  openPinDetailId?: any;
  operational?: any;
  operator?: any;
  option?: any;
  optional?: any;
  oracle?: any;
  oracleIntel?: any;
  oracle_score?: any;
  oracle_service?: any;
  orange?: any;
  others?: any;
  otherwise?: any;
  outage?: any;
  outline?: any;
  outside?: any;
  overflow?: any;
  overlay?: any;
  own?: any;
  owner?: any;
  padding?: any;
  panel?: any;
  pb?: any;
  peer?: any;
  pendingPin?: any;
  pin?: any;
  pinCategory?: any;
  pinId?: any;
  pinLabel?: any;
  pinLabelInputRef?: any;
  pinLat?: any;
  pinLng?: any;
  pinNotes?: any;
  pinSaving?: any;
  ping?: any;
  pm25?: any;
  pointer?: any;
  pointerEvents?: any;
  pointing?: any;
  polymarket_pct?: any;
  popup?: any;
  position?: any;
  positive?: any;
  posts?: any;
  power_plant?: any;
  power_plants?: any;
  prediction_odds?: any;
  pretty?: any;
  preventDefault?: any;
  primary?: any;
  properties?: any;
  prose?: any;
  provenance_url?: any;
  pt?: any;
  published?: any;
  pulse?: any;
  purple?: any;
  push?: any;
  px?: any;
  py?: any;
  quot?: any;
  radius_km?: any;
  rdquo?: any;
  reads?: any;
  real?: any;
  red?: any;
  reference?: any;
  references?: any;
  region?: any;
  regionDossier?: any;
  regionDossierLoading?: any;
  region_dossier?: any;
  region_name?: any;
  rel?: any;
  relative?: any;
  relaxed?: any;
  removed?: any;
  replace?: any;
  reported?: any;
  resize?: any;
  return?: any;
  rgba?: any;
  right?: any;
  ring?: any;
  risk?: any;
  risk_score?: any;
  round?: any;
  rounded?: any;
  route?: any;
  routine?: any;
  row?: any;
  same?: any;
  sameEntityId?: any;
  sar_anomalies?: any;
  sar_anomaly?: any;
  sar_aoi?: any;
  satellite?: any;
  satellite_analysis?: any;
  satellites?: any;
  satnogs_station?: any;
  sb?: any;
  scanner?: any;
  score?: any;
  scroll?: any;
  scrollbar?: any;
  scroller?: any;
  secondary?: any;
  seen?: any;
  select?: any;
  selectedEntity?: any;
  selector?: any;
  semibold?: any;
  sentiment?: any;
  sentinel2?: any;
  setAiIntelRefreshTick?: any;
  setOpenPinDetailId?: any;
  setPendingPin?: any;
  setPinCategory?: any;
  setPinLabel?: any;
  setPinNotes?: any;
  setTrackedScanner?: any;
  setTrackedSdr?: any;
  severity?: any;
  sgp4_propagated?: any;
  shadow?: any;
  shape?: any;
  shape_raw?: any;
  ships?: any;
  shortName?: any;
  show?: any;
  shown?: any;
  shrink?: any;
  sigint?: any;
  signal?: any;
  sits?: any;
  size?: any;
  slice?: any;
  sm?: any;
  snug?: any;
  so?: any;
  sog?: any;
  solid?: any;
  source?: any;
  source_agency?: any;
  source_constellation?: any;
  source_label?: any;
  source_url?: any;
  space?: any;
  span?: any;
  speed_kmh?: any;
  speed_knots?: any;
  split?: any;
  squawk?: any;
  sr?: any;
  stacking?: any;
  start?: any;
  started_at?: any;
  state?: any;
  status?: any;
  steals?: any;
  still?: any;
  stopImmediatePropagation?: any;
  stopPropagation?: any;
  story?: any;
  street?: any;
  strokeDasharray?: any;
  styled?: any;
  subcategory?: any;
  subtitle?: any;
  svg?: any;
  swallowed?: any;
  target?: any;
  teal?: any;
  telegramClusterKey?: any;
  telegramClusterNearNewsAlert?: any;
  telegramMapPinCoords?: any;
  telegram_osint?: any;
  text?: any;
  textarea?: any;
  the?: any;
  this?: any;
  threat?: any;
  threat_type?: any;
  through?: any;
  tier?: any;
  tiers?: any;
  tight?: any;
  tiles?: any;
  timeago?: any;
  times?: any;
  timestamp?: any;
  tinygs_confirmed?: any;
  tinygs_satellite?: any;
  to?: any;
  toFixed?: any;
  toISOString?: any;
  toLocaleDateString?: any;
  toLocaleString?: any;
  toLocaleTimeString?: any;
  toLowerCase?: any;
  toUpperCase?: any;
  tone?: any;
  top?: any;
  top_headline?: any;
  topic?: any;
  tracking?: any;
  trains?: any;
  transition?: any;
  translateX?: any;
  transparent?: any;
  triangle?: any;
  trim?: any;
  truncate?: any;
  truth?: any;
  try?: any;
  typeof?: any;
  typing?: any;
  uap_sighting?: any;
  uap_sightings?: any;
  uav_type?: any;
  uavs?: any;
  ukraine_alert?: any;
  ukraine_alerts?: any;
  underline?: any;
  unknown?: any;
  unrest?: any;
  uppercase?: any;
  urban_fights?: any;
  use?: any;
  users?: any;
  users_max?: any;
  var?: any;
  verification?: any;
  vessel?: any;
  vesselLat?: any;
  vesselLng?: any;
  vessel_flag?: any;
  vessel_name?: any;
  video?: any;
  viirs?: any;
  viirs_change_node?: any;
  viirs_change_nodes?: any;
  violet?: any;
  visible?: any;
  volcanoes?: any;
  vs?: any;
  wastewater?: any;
  watchbox?: any;
  watchlist?: any;
  weather_alert?: any;
  weather_alerts?: any;
  webm?: any;
  weighted?: any;
  when?: any;
  while?: any;
  white?: any;
  whitespace?: any;
  wider?: any;
  widest?: any;
  wiki?: any;
  wikiUrl?: any;
  with?: any;
  words?: any;
  wrap?: any;
  www?: any;
  xl?: any;
  yellow?: any;
  zIndex?: any;
  zinc?: any;
  zip?: any;
}

export function MapEntityPopups({ p }: { p: MapEntityPopupsProps }) {
  const {
    AIIntelPinDetail,
    Active,
    Activity,
    Address,
    Air,
    Alert,
    AlertTriangle,
    Altitude,
    Antenna,
    Arrow,
    Article,
    Bands,
    Below,
    Callsign,
    Capacity,
    Category,
    CctvFullscreenModal,
    Center,
    Change,
    Check,
    Classification,
    Close,
    Confidence,
    Connecting,
    Contradiction,
    Coords,
    Core,
    Correlation,
    CorrelationPopup,
    Country,
    Course,
    Cross,
    CrowdThreat,
    Data,
    Destination,
    Detail,
    Dialog,
    Duration,
    Earthquake,
    Elevation,
    Enriched,
    Enter,
    Eruption,
    Escape,
    Event,
    Expires,
    Explain,
    ExternalLink,
    Extreme,
    Fishing,
    FishingDestinationRoute,
    Flag,
    Force,
    Frequency,
    Fuel,
    Goldstein,
    Good,
    Ground,
    GtRiskPopup,
    HTMLTextAreaElement,
    Hazardous,
    Info,
    Intel,
    It,
    Kalshi,
    Kind,
    KiwiProps,
    KiwiSDR,
    Label,
    Last,
    Level,
    Listeners,
    LoRa,
    Location,
    MHz,
    Magnitude,
    MilitaryBasePopup,
    Minor,
    Model,
    Moderate,
    Modulation,
    MultiPolygon,
    Negative,
    No,
    Node,
    Notes,
    Oblast,
    Observations,
    Occurred,
    Open,
    Operator,
    Oracle,
    Pin,
    PinCategory,
    Placement,
    Plant,
    Play,
    Police,
    Polygon,
    Polymarket,
    Portalled,
    Power,
    Prevent,
    Progress,
    Provenance,
    Proxy,
    Pulsing,
    Quality,
    Radio,
    Radius,
    Raid,
    Receivers,
    Record,
    Region,
    RegionDossierPanel,
    Registration,
    Report,
    Reported,
    Risk,
    Route,
    Same,
    SatNOGS,
    Satellite,
    SatellitePopup,
    Scanner,
    ScannerProps,
    Score,
    Sensitive,
    Sentiment,
    Severe,
    Severity,
    Shape,
    Ship,
    ShipPopup,
    Sighting,
    Sightings,
    SigintPopup,
    SigintProps,
    Since,
    Solver,
    Source,
    Speed,
    Squawk,
    Start,
    Station,
    Status,
    Subcategory,
    TelegramOsintPopup,
    Threat,
    TinyGS,
    Tracking,
    Train,
    Type,
    URLs,
    Ukraine,
    Unhealthy,
    Unknown,
    Users,
    Very,
    Vessel,
    View,
    Volcano,
    Wastewater,
    WastewaterPopup,
    Weather,
    WikiImage,
    Witness,
    _blank,
    _build_assessment,
    _headlines_list,
    _snippets_list,
    _urls_list,
    a855f7,
    a855f733,
    a855f766,
    a855f799,
    above,
    absolute,
    actors,
    actual,
    address,
    adverse,
    air_quality,
    air_raid,
    aircraft_model,
    alertKey,
    alert_type,
    alerts,
    align,
    alignItems,
    all,
    already,
    alt_km,
    always,
    amber,
    amtrak,
    an,
    and,
    animate,
    anomaly_id,
    antenna,
    aoi_id,
    aoi_name,
    approved,
    aq,
    aqi,
    article,
    articleSourceUrl,
    artillery_shelling,
    as,
    assessment,
    async,
    at,
    auto,
    available,
    avg_sentiment,
    back,
    backdrop,
    backdropFilter,
    backend,
    background,
    bands,
    bar,
    based,
    between,
    bg,
    black,
    block,
    blur,
    body,
    bold,
    border,
    borderBottom,
    borderLeft,
    borderLeftColor,
    borderRight,
    borderStyle,
    borderTop,
    borderWidth,
    bottom,
    box,
    boxShadow,
    break,
    breaking,
    btn,
    buildCctvProxyUrl,
    buildPolymarketUrl,
    button,
    by,
    bypass,
    c084fc,
    c4b5fd,
    calc,
    callsign,
    camera,
    cameraId,
    canvas,
    capacity_mw,
    capitalize,
    carrier,
    catch,
    category_colour,
    cctv,
    center,
    center_lat,
    center_lon,
    checkbox,
    checked,
    chemical,
    circle,
    city,
    clamp,
    clear,
    click,
    clientCount,
    closeButton,
    closeOnClick,
    cluster,
    cog,
    col,
    colors,
    cols,
    columns,
    combining,
    company,
    conflict,
    connecting,
    consensus_pct,
    const,
    constructive,
    contagion,
    context,
    coordinates,
    corr,
    corr_index,
    correlation,
    correlations,
    corroboration,
    country,
    country_name,
    createPortal,
    critical,
    cross,
    crowdthreat,
    currentTarget,
    cursor,
    custom,
    cyan,
    d8b4fe,
    data,
    database,
    datacenter,
    datacenters,
    date,
    date_time,
    delay,
    destination,
    details,
    detected,
    dialog,
    display,
    div,
    dossier,
    dot,
    down,
    drones,
    drop,
    duration,
    duration_hrs,
    e9d5ff,
    eab308,
    earthquake,
    earthquakes,
    ef4444,
    elevated,
    elevation,
    else,
    emerald,
    entity,
    entity_id,
    entity_label,
    entity_type,
    estimate,
    event_date,
    events,
    expires,
    external,
    f97316,
    fade,
    fallback,
    family,
    fbbf24,
    fde68a,
    feed,
    ff4444,
    ff6b6b,
    ff8800,
    ff8844,
    ffcc00,
    fields,
    filter,
    financial,
    find,
    fire,
    firing,
    fishing_activity,
    fishing_event,
    fixed,
    flex,
    floor,
    focus,
    font,
    fontSize,
    fontWeight,
    formatDossierTime,
    found,
    frequency,
    from,
    fuel_type,
    full,
    fullscreen,
    gap,
    gdelt,
    geometry,
    getFullYear,
    getTime,
    gets,
    global,
    goldstein,
    gradient,
    gray,
    green,
    grid,
    group,
    gt_risk,
    h2,
    handleSavePin,
    handled,
    has,
    here,
    hidden,
    high,
    hls,
    hostname,
    hotkeys,
    hover,
    iLat,
    iLng,
    icao24,
    if,
    image,
    imo,
    in,
    includes,
    inline,
    input,
    inset,
    intel,
    intelligence,
    internet,
    internet_outages,
    interpShip,
    interpretation,
    is,
    it,
    items,
    its,
    itself,
    join,
    justify,
    justifyContent,
    kalshi_pct,
    keys,
    keywords,
    kiwisdr,
    kiwisdrs,
    km,
    kn,
    kts,
    last,
    last_eruption_year,
    last_seen,
    late,
    latitude,
    ldquo,
    lead,
    leading,
    left,
    length,
    let,
    level,
    lg,
    line,
    lineHeight,
    link,
    list,
    listeners,
    live,
    liveuamap,
    location_title,
    lon,
    longitude,
    low,
    m3u8,
    machine,
    magnitude_unit,
    maneuver,
    maneuvers,
    map,
    maplibre,
    marginLeft,
    marker,
    market,
    match,
    match_score,
    max,
    maxH,
    maxHeight,
    mb,
    md,
    mean_change_pct,
    measures,
    mediaType,
    media_type,
    media_url,
    medium,
    middle,
    milbase,
    military_base,
    military_bases,
    min,
    minWidth,
    mjpeg,
    mjpg,
    ml,
    mmsi,
    modal,
    moderate,
    modulation,
    mono,
    more,
    mp4,
    muted,
    name_en,
    nativeEvent,
    negative,
    neutral,
    new,
    news,
    none,
    noopener,
    norad_id,
    noreferrer,
    not,
    nowrap,
    nuclear,
    num_articles,
    num_sources,
    observations,
    occurred,
    omitted,
    on,
    onClose,
    onDeleted,
    onEntityClick,
    onKeyUp,
    onMouseEnter,
    onMouseLeave,
    onPinPlaced,
    onUpdated,
    only,
    open,
    openPinDetailId,
    operational,
    operator,
    option,
    optional,
    oracle,
    oracleIntel,
    oracle_score,
    oracle_service,
    orange,
    others,
    otherwise,
    outage,
    outline,
    outside,
    overflow,
    overlay,
    own,
    owner,
    padding,
    panel,
    pb,
    peer,
    pendingPin,
    pin,
    pinCategory,
    pinId,
    pinLabel,
    pinLabelInputRef,
    pinLat,
    pinLng,
    pinNotes,
    pinSaving,
    ping,
    pm25,
    pointer,
    pointerEvents,
    pointing,
    polymarket_pct,
    popup,
    position,
    positive,
    posts,
    power_plant,
    power_plants,
    prediction_odds,
    pretty,
    preventDefault,
    primary,
    properties,
    prose,
    provenance_url,
    pt,
    published,
    pulse,
    purple,
    push,
    px,
    py,
    quot,
    radius_km,
    rdquo,
    reads,
    real,
    red,
    reference,
    references,
    region,
    regionDossier,
    regionDossierLoading,
    region_dossier,
    region_name,
    rel,
    relative,
    relaxed,
    removed,
    replace,
    reported,
    resize,
    return,
    rgba,
    right,
    ring,
    risk,
    risk_score,
    round,
    rounded,
    route,
    routine,
    row,
    same,
    sameEntityId,
    sar_anomalies,
    sar_anomaly,
    sar_aoi,
    satellite,
    satellite_analysis,
    satellites,
    satnogs_station,
    sb,
    scanner,
    score,
    scroll,
    scrollbar,
    scroller,
    secondary,
    seen,
    select,
    selectedEntity,
    selector,
    semibold,
    sentiment,
    sentinel2,
    setAiIntelRefreshTick,
    setOpenPinDetailId,
    setPendingPin,
    setPinCategory,
    setPinLabel,
    setPinNotes,
    setTrackedScanner,
    setTrackedSdr,
    severity,
    sgp4_propagated,
    shadow,
    shape,
    shape_raw,
    ships,
    shortName,
    show,
    shown,
    shrink,
    sigint,
    signal,
    sits,
    size,
    slice,
    sm,
    snug,
    so,
    sog,
    solid,
    source,
    source_agency,
    source_constellation,
    source_label,
    source_url,
    space,
    span,
    speed_kmh,
    speed_knots,
    split,
    squawk,
    sr,
    stacking,
    start,
    started_at,
    state,
    status,
    steals,
    still,
    stopImmediatePropagation,
    stopPropagation,
    story,
    street,
    strokeDasharray,
    styled,
    subcategory,
    subtitle,
    svg,
    swallowed,
    target,
    teal,
    telegramClusterKey,
    telegramClusterNearNewsAlert,
    telegramMapPinCoords,
    telegram_osint,
    text,
    textarea,
    the,
    this,
    threat,
    threat_type,
    through,
    tier,
    tiers,
    tight,
    tiles,
    timeago,
    times,
    timestamp,
    tinygs_confirmed,
    tinygs_satellite,
    to,
    toFixed,
    toISOString,
    toLocaleDateString,
    toLocaleString,
    toLocaleTimeString,
    toLowerCase,
    toUpperCase,
    tone,
    top,
    top_headline,
    topic,
    tracking,
    trains,
    transition,
    translateX,
    transparent,
    triangle,
    trim,
    truncate,
    truth,
    try,
    typeof,
    typing,
    uap_sighting,
    uap_sightings,
    uav_type,
    uavs,
    ukraine_alert,
    ukraine_alerts,
    underline,
    unknown,
    unrest,
    uppercase,
    urban_fights,
    use,
    users,
    users_max,
    var,
    verification,
    vessel,
    vesselLat,
    vesselLng,
    vessel_flag,
    vessel_name,
    video,
    viirs,
    viirs_change_node,
    viirs_change_nodes,
    violet,
    visible,
    volcanoes,
    vs,
    wastewater,
    watchbox,
    watchlist,
    weather_alert,
    weather_alerts,
    webm,
    weighted,
    when,
    while,
    white,
    whitespace,
    wider,
    widest,
    wiki,
    wikiUrl,
    with,
    words,
    wrap,
    www,
    xl,
    yellow,
    zIndex,
    zinc,
    zip
  } = p as any; // typed via MapEntityPopupsProps

  return (
    <>
        {/* Satellite click popup (with ISS live feed + maneuver alerts) */}
        {selectedEntity?.type === 'satellite' &&
          (() => {
            const sat = data?.satellites?.find((s) => sameEntityId(s.id, selectedEntity.id));
            if (!sat) return null;
            const maneuverAlert = data?.satellite_analysis?.maneuvers?.find(
              (m) => m.norad_id === sat.id
            );
            return (
              <SatellitePopup
                sat={sat}
                maneuverAlert={maneuverAlert}
                onClose={() => onEntityClick?.(null)}
              />
            );
          })()}

        {/* Correlation / Contradiction click popup */}
        {selectedEntity?.type === 'correlation' &&
          (() => {
            const corrIndex = typeof selectedEntity.extra?.corr_index === 'number'
              ? selectedEntity.extra.corr_index
              : parseInt(String(selectedEntity.id).replace('corr-', ''), 10);
            const alert = data?.correlations?.[corrIndex];
            if (!alert) return null;
            return (
              <CorrelationPopup
                alert={alert}
                onClose={() => onEntityClick?.(null)}
              />
            );
          })()}

        {/* UAP Sighting popup */}
        {selectedEntity?.type === 'uap_sighting' &&
          (() => {
            const props = selectedEntity.extra || {};
            const sighting = data?.uap_sightings?.find((s) => sameEntityId(s.id, selectedEntity.id));
            const lat = sighting?.lat ?? props.lat;
            const lng = sighting?.lng ?? props.lng;
            if (lat == null || lng == null) return null;
            const location = [props.city, props.state, props.country].filter(Boolean).join(', ') || 'Unknown location';
            const count = props.count ?? 1;
            const hasShape = props.shape && props.shape !== 'unknown';
            const hasSummary = props.summary && props.summary !== 'Sighting reported' && !props.summary?.match(/^\d+ sighting\(s\) reported$/);
            return (
              <Popup longitude={lng} latitude={lat} closeButton={false} closeOnClick={false} onClose={() => onEntityClick?.(null)} className="threat-popup" maxWidth="320px">
                <div className="map-popup bg-[#1a0a30] min-w-[220px]" style={{ borderColor: '#a855f766' }}>
                  <div className="map-popup-title pb-1 flex items-center gap-2" style={{ color: '#c084fc', borderBottom: '1px solid #a855f733' }}>
                    <span style={{ fontSize: 16 }}>👽</span>
                    <span>UAP Sighting</span>
                    <button onClick={() => onEntityClick?.(null)} className="ml-auto text-[var(--text-secondary)] hover:text-[var(--text-primary)]">✕</button>
                  </div>

                  {/* Core details */}
                  <div className="map-popup-row">Location: <span className="text-white">{location}</span></div>
                  {props.date_time && <div className="map-popup-row">Date: <span className="text-white">{props.date_time}</span></div>}
                  {count > 1 && <div className="map-popup-row">Sightings: <span className="text-purple-300 font-bold">{count}</span></div>}

                  {/* Enriched details from NUFORC database */}
                  {(hasShape || props.duration) && (
                    <div className="mt-1.5 pt-1.5 border-t border-purple-500/20">
                      {hasShape && (
                        <div className="map-popup-row">Shape: <span className="text-purple-200 font-semibold">{props.shape_raw || props.shape}</span></div>
                      )}
                      {props.duration && (
                        <div className="map-popup-row">Duration: <span className="text-white">{props.duration}</span></div>
                      )}
                    </div>
                  )}

                  {/* Witness summary */}
                  {hasSummary && (
                    <div className="mt-1.5 pt-1.5 border-t border-purple-500/20">
                      <div className="text-[11px] font-mono tracking-widest text-purple-400/50 mb-1">WITNESS REPORT</div>
                      <div className="text-[10px] leading-relaxed" style={{ color: '#d8b4fe' }}>
                        &ldquo;{props.summary}&rdquo;
                      </div>
                    </div>
                  )}

                  <div className="mt-2 pt-1 border-t border-purple-500/10 text-[11px] tracking-wider" style={{ color: '#a855f799' }}>
                    {props.source || 'NUFORC'} — UAP SIGHTING REPORT
                  </div>
                </div>
              </Popup>
            );
          })()}

        {/* Wastewater plant popup */}
        {selectedEntity?.type === 'wastewater' &&
          (() => {
            const plant = data?.wastewater?.find((w) => sameEntityId(w.id, selectedEntity.id));
            if (!plant) return null;
            return (
              <WastewaterPopup
                plant={plant}
                onClose={() => onEntityClick?.(null)}
              />
            );
          })()}

        {/* CrowdThreat popup */}
        {selectedEntity?.type === 'crowdthreat' &&
          (() => {
            const props = selectedEntity.extra || {};
            const ct = data?.crowdthreat?.find((c) => `ct-${c.id}` === selectedEntity.id);
            const lat = ct?.lat ?? props.lat;
            const lng = ct?.lng ?? props.lng;
            if (lat == null || lng == null) return null;
            const accent = props.category_colour || '#6b7280';
            const location = [props.address || props.city, props.country].filter(Boolean).join(', ') || 'Unknown';
            return (
              <Popup longitude={lng} latitude={lat} closeButton={false} closeOnClick={false} onClose={() => onEntityClick?.(null)} className="threat-popup" maxWidth="320px">
                <div className="map-popup min-w-[220px]" style={{ borderColor: `${accent}66`, background: 'var(--bg-secondary)' }}>
                  <div className="map-popup-title pb-1 flex items-center gap-2" style={{ color: accent, borderBottom: `1px solid ${accent}33` }}>
                    <span className="font-bold text-[11px] leading-tight flex-1">{props.title}</span>
                    <button onClick={() => onEntityClick?.(null)} className="ml-auto text-[var(--text-secondary)] hover:text-[var(--text-primary)] shrink-0">✕</button>
                  </div>
                  {props.summary && (
                    <div className="text-[10px] text-white/80 leading-relaxed mt-1 mb-1.5">{props.summary}</div>
                  )}
                  <div className="map-popup-row">Category: <span className="font-semibold" style={{ color: accent }}>{props.category}</span></div>
                  {props.subcategory && <div className="map-popup-row">Subcategory: <span className="text-white">{props.subcategory}</span></div>}
                  {props.threat_type && <div className="map-popup-row">Type: <span className="text-white">{props.threat_type}</span></div>}
                  <div className="map-popup-row">Location: <span className="text-white">{location}</span></div>
                  {props.occurred && <div className="map-popup-row">Occurred: <span className="text-white">{props.occurred}</span></div>}
                  {props.timeago && <div className="map-popup-row">Reported: <span className="text-white">{props.timeago}</span></div>}
                  {props.verification && (
                    <div className="map-popup-row">Status: <span className={props.verification === 'approved' ? 'text-green-400 font-bold' : 'text-yellow-400'}>{props.verification.toUpperCase()}</span></div>
                  )}
                  {props.severity && (
                    <div className="map-popup-row">Severity: <span className="text-red-400 font-bold">{props.severity}</span></div>
                  )}
                  {props.source_url && (
                    <div className="mt-1.5 pt-1.5 border-t border-[var(--border-primary)]">
                      <a href={props.source_url} target="_blank" rel="noreferrer" className="text-[10px] font-bold underline" style={{ color: accent }}>View Source</a>
                    </div>
                  )}
                  <div className="mt-1.5 text-[11px] tracking-wider" style={{ color: `${accent}88` }}>
                    CROWDTHREAT — VERIFIED THREAT INTELLIGENCE
                  </div>
                </div>
              </Popup>
            );
          })()}

        {/* Train click popup */}
        {selectedEntity?.type === 'train' &&
          (() => {
            const train = data?.trains?.find((t) => sameEntityId(t.id, selectedEntity.id));
            if (!train) return null;
            const isAmtrak = train.source === 'amtrak';
            const sourceLabel = train.source_label || train.source.toUpperCase();
            const subtitleParts = [sourceLabel];
            if (train.operator && train.operator !== sourceLabel) subtitleParts.push(train.operator);
            return (
              <Popup
                longitude={train.lng}
                latitude={train.lat}
                closeButton={false}
                closeOnClick={false}
                onClose={() => onEntityClick?.(null)}
                anchor="bottom"
                offset={12}
              >
                <div className="map-popup border border-orange-500/30">
                  <div className="flex justify-between items-start mb-0.5">
                  <div className={`map-popup-title ${isAmtrak ? 'text-[#ff8800]' : 'text-[#00aaff]'}`}>
                      {train.name}
                    </div>
                    <button onClick={() => onEntityClick?.(null)}
                      className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] ml-2">✕</button>
                  </div>
                  <div className="map-popup-subtitle text-[#8899aa] border-b border-gray-700/50 pb-1">
                    {subtitleParts.join(' / ')}{train.number ? ` — #${train.number}` : ''}
                  </div>
                  {train.country && (
                    <div className="map-popup-row">
                      Country: <span className="text-white">{train.country}</span>
                    </div>
                  )}
                  {train.route && (
                    <div className="map-popup-row">
                      Route: <span className="text-white">{train.route}</span>
                    </div>
                  )}
                  {train.speed_kmh != null && (
                    <div className="map-popup-row">
                      Speed: <span className="text-[#44ff88]">{train.speed_kmh} km/h</span>
                    </div>
                  )}
                  <div className="map-popup-row">
                    Status: <span className={train.status?.toLowerCase().includes('late') || train.status?.toLowerCase().includes('delay')
                      ? 'text-red-400' : 'text-green-400'}>{train.status || 'Active'}</span>
                  </div>
                </div>
              </Popup>
            );
          })()}

        {/* UAV click popup — real ADS-B detected drones */}
        {selectedEntity?.type === 'uav' &&
          (() => {
            const uav = data?.uavs?.find((u) => sameEntityId(u.id, selectedEntity.id));
            if (!uav) return null;
            return (
              <Popup
                longitude={uav.lng}
                latitude={uav.lat}
                closeButton={false}
                closeOnClick={false}
                onClose={() => onEntityClick?.(null)}
                anchor="bottom"
                offset={12}
              >
                <div className="map-popup border border-red-500/40">
                  <div className="map-popup-title text-[#ff4444]">{uav.callsign}</div>
                  <div className="map-popup-subtitle text-[#ff8844]">LIVE ADS-B TRANSPONDER</div>
                  {uav.aircraft_model && (
                    <div className="map-popup-row">
                      Model: <span className="text-white">{uav.aircraft_model}</span>
                    </div>
                  )}
                  {uav.uav_type && (
                    <div className="map-popup-row">
                      Classification: <span className="text-[#ffcc00]">{uav.uav_type}</span>
                    </div>
                  )}
                  {uav.country && (
                    <div className="map-popup-row">
                      Registration: <span className="text-white">{uav.country}</span>
                    </div>
                  )}
                  {uav.icao24 && (
                    <div className="map-popup-row">
                      ICAO: <span className="text-[#888]">{uav.icao24}</span>
                    </div>
                  )}
                  <div className="map-popup-row">
                    Altitude: <span className="text-[#44ff88]">{uav.alt?.toLocaleString()} m</span>
                  </div>
                  {(uav.speed_knots ?? 0) > 0 && (
                    <div className="map-popup-row">
                      Speed: <span className="text-[#00e5ff]">{uav.speed_knots} kn</span>
                    </div>
                  )}
                  {uav.squawk && (
                    <div className="map-popup-row">
                      Squawk: <span className="text-[#888]">{uav.squawk}</span>
                    </div>
                  )}
                  {uav.wiki && (
                    <div className="mt-2 border-t border-[var(--border-primary)]/50 pt-2">
                      <WikiImage
                        wikiUrl={uav.wiki}
                        label={uav.callsign}
                        maxH="max-h-28"
                        accent="hover:border-red-500/50"
                      />
                    </div>
                  )}
                </div>
              </Popup>
            );
          })()}

        {/* KiwiSDR Receivers Popup */}
        {selectedEntity?.type === 'kiwisdr' &&
          (() => {
            const receiver = data?.kiwisdr?.find(
              (k) => k.name === selectedEntity.name || k.name === String(selectedEntity.id),
            );
            // use extra if available from the click event, otherwise fallback
            const props = (selectedEntity.extra || receiver || {}) as KiwiProps;
            const lat =
              props.lat ??
              selectedEntity.extra?.lat ??
              selectedEntity.extra?.geometry?.coordinates?.[1];
            const lng =
              props.lon ??
              props.lng ??
              selectedEntity.extra?.lon ??
              selectedEntity.extra?.geometry?.coordinates?.[0];
            if (lat == null || lng == null) return null;
            return (
              <Popup
                longitude={lng}
                latitude={lat}
                closeButton={false}
                closeOnClick={false}
                onClose={() => onEntityClick?.(null)}
                anchor="bottom"
                offset={12}
              >
                <div
                  className="map-popup !border-amber-500/40"
                  style={{ borderWidth: 1, borderStyle: 'solid' }}
                >
                  <div className="flex justify-between items-start mb-1">
                    <div className="map-popup-title text-amber-400">
                      {(props.name || 'UNKNOWN SDR RECEIVER').toUpperCase()}
                    </div>
                    <button
                      onClick={() => onEntityClick?.(null)}
                      className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] ml-2"
                    >
                      ✕
                    </button>
                  </div>
                  <div className="map-popup-subtitle text-amber-600/80 border-b border-amber-900/30 pb-1 flex items-center gap-1.5">
                    <Radio size={10} /> PUBLIC NETWORK RECEIVER
                  </div>

                  {props.location && (
                    <div className="map-popup-row mt-1">
                      Location: <span className="text-white">{props.location}</span>
                    </div>
                  )}
                  {props.users !== undefined && (
                    <div className="map-popup-row">
                      Active Users:{' '}
                      <span
                        className={
                          props.users >= (props.users_max || 4) ? 'text-red-400' : 'text-amber-400'
                        }
                      >
                        {props.users} / {props.users_max || '?'}
                      </span>
                    </div>
                  )}
                  {props.antenna && (
                    <div className="map-popup-row">
                      Antenna: <span className="text-[#888]">{props.antenna}</span>
                    </div>
                  )}
                  {props.bands && (
                    <div className="map-popup-row">
                      Bands:{' '}
                      <span className="text-cyan-400">
                        {(Number(props.bands.split('-')[0]) / 1e6).toFixed(0)}-
                        {(Number(props.bands.split('-')[1]) / 1e6).toFixed(0)} MHz
                      </span>
                    </div>
                  )}

                  <div className="flex items-center gap-2 mt-3 pt-2 border-t border-[var(--border-primary)]">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        if (setTrackedSdr) {
                          setTrackedSdr({
                            lat,
                            lon: lng,
                            name: props.name || 'Unknown',
                            url: props.url,
                            users: props.users,
                            users_max: props.users_max,
                            bands: props.bands,
                            antenna: props.antenna,
                            location: props.location,
                          });
                        }
                        onEntityClick?.(null);
                      }}
                      className="flex-1 text-center px-2 py-1.5 rounded bg-amber-950/40 border border-amber-500/30 hover:bg-amber-900/60 hover:border-amber-400 text-amber-400 text-[10px] font-mono tracking-widest transition-colors flex justify-center items-center gap-1.5"
                    >
                      <Activity size={10} /> TRACK
                    </button>
                    {props.url && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          if (setTrackedSdr) {
                            setTrackedSdr({
                              lat,
                              lon: lng,
                              name: props.name || 'Unknown',
                              url: props.url,
                              users: props.users,
                              users_max: props.users_max,
                              bands: props.bands,
                              antenna: props.antenna,
                              location: props.location,
                            });
                          }
                          onEntityClick?.(null);
                        }}
                        className="flex-1 text-center px-2 py-1.5 rounded bg-amber-500/20 border border-amber-500/50 hover:bg-amber-500/30 hover:border-amber-400 text-amber-300 text-[10px] font-mono tracking-widest transition-colors flex justify-center items-center gap-1.5"
                      >
                        <Play size={10} /> TUNE IN
                      </button>
                    )}
                  </div>
                </div>
              </Popup>
            );
          })()}

        {/* SatNOGS Ground Station Popup */}
        {selectedEntity?.type === 'satnogs_station' &&
          (() => {
            const props = (selectedEntity.extra || {}) as Record<string, unknown>;
            const lat = (props.lat as number) ?? selectedEntity.extra?.geometry?.coordinates?.[1];
            const lng = (props.lng as number) ?? selectedEntity.extra?.geometry?.coordinates?.[0];
            if (lat == null || lng == null) return null;
            return (
              <Popup
                longitude={lng}
                latitude={lat}
                closeButton={false}
                closeOnClick={false}
                onClose={() => onEntityClick?.(null)}
                anchor="bottom"
                offset={12}
              >
                <div
                  className="map-popup !border-teal-500/40"
                  style={{ borderWidth: 1, borderStyle: 'solid' }}
                >
                  <div className="flex justify-between items-start mb-1">
                    <div className="map-popup-title text-teal-400">
                      {((props.name as string) || 'UNKNOWN STATION').toUpperCase()}
                    </div>
                    <button
                      onClick={() => onEntityClick?.(null)}
                      className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] ml-2"
                    >
                      ✕
                    </button>
                  </div>
                  <div className="map-popup-subtitle text-teal-600/80 border-b border-teal-900/30 pb-1 flex items-center gap-1.5">
                    <Satellite size={10} /> SATNOGS GROUND STATION
                  </div>
                  {String(props.antenna || '') !== '' && (
                    <div className="map-popup-row mt-1">
                      Antenna: <span className="text-[#888]">{String(props.antenna)}</span>
                    </div>
                  )}
                  {Number(props.observations || 0) > 0 && (
                    <div className="map-popup-row">
                      Observations: <span className="text-teal-400">{Number(props.observations).toLocaleString()}</span>
                    </div>
                  )}
                  {String(props.last_seen || '') !== '' && (
                    <div className="map-popup-row">
                      Last seen: <span className="text-[#888]">{new Date(String(props.last_seen)).toLocaleString()}</span>
                    </div>
                  )}
                  <div className="map-popup-row text-[10px] text-[#555] mt-1">
                    {lat.toFixed(4)}°, {lng.toFixed(4)}°
                  </div>
                </div>
              </Popup>
            );
          })()}

        {/* TinyGS LoRa Satellite Popup */}
        {selectedEntity?.type === 'tinygs_satellite' &&
          (() => {
            const props = (selectedEntity.extra || {}) as Record<string, unknown>;
            const lat = (props.lat as number) ?? selectedEntity.extra?.geometry?.coordinates?.[1];
            const lng = (props.lng as number) ?? selectedEntity.extra?.geometry?.coordinates?.[0];
            if (lat == null || lng == null) return null;
            return (
              <Popup
                longitude={lng}
                latitude={lat}
                closeButton={false}
                closeOnClick={false}
                onClose={() => onEntityClick?.(null)}
                anchor="bottom"
                offset={12}
              >
                <div
                  className="map-popup !border-purple-500/40"
                  style={{ borderWidth: 1, borderStyle: 'solid' }}
                >
                  <div className="flex justify-between items-start mb-1">
                    <div className="map-popup-title text-purple-400">
                      {String(props.name || 'UNKNOWN SATELLITE').toUpperCase()}
                    </div>
                    <button
                      onClick={() => onEntityClick?.(null)}
                      className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] ml-2"
                    >
                      ✕
                    </button>
                  </div>
                  <div className="map-popup-subtitle text-purple-600/80 border-b border-purple-900/30 pb-1 flex items-center gap-1.5">
                    <Satellite size={10} /> LORA SATELLITE
                    {props.tinygs_confirmed ? (
                      <span className="text-green-400 text-[11px] ml-1">TINYGS LIVE</span>
                    ) : props.sgp4_propagated ? (
                      <span className="text-purple-400 text-[11px] ml-1">SGP4 ORBIT</span>
                    ) : null}
                  </div>
                  {Number(props.alt_km || 0) > 0 && (
                    <div className="map-popup-row mt-1">
                      Altitude: <span className="text-purple-400">{Number(props.alt_km).toFixed(0)} km</span>
                    </div>
                  )}
                  {String(props.modulation || '') !== '' && (
                    <div className="map-popup-row">
                      Modulation: <span className="text-purple-400">{String(props.modulation)}</span>
                    </div>
                  )}
                  {String(props.frequency || '') !== '' && (
                    <div className="map-popup-row">
                      Frequency: <span className="text-purple-400">{String(props.frequency)} MHz</span>
                    </div>
                  )}
                  {String(props.status || '') !== '' && (
                    <div className="map-popup-row">
                      Status: <span className="text-[#888]">{String(props.status)}</span>
                    </div>
                  )}
                  <div className="map-popup-row text-[10px] text-[#555] mt-1">
                    {lat.toFixed(4)}°, {lng.toFixed(4)}°
                  </div>
                </div>
              </Popup>
            );
          })()}

        {/* CCTV popup removed — now handled by fullscreen OPTIC INTERCEPT modal */}

        {/* Police Scanner click popup */}
        {selectedEntity?.type === 'scanner' &&
          (() => {
            const props = (selectedEntity.extra || {}) as ScannerProps;
            const lat = props.lat ?? selectedEntity.extra?.geometry?.coordinates?.[1];
            const lng = props.lng ?? selectedEntity.extra?.geometry?.coordinates?.[0];
            if (lat == null || lng == null) return null;
            return (
              <Popup
                longitude={lng}
                latitude={lat}
                closeButton={false}
                closeOnClick={false}
                onClose={() => onEntityClick?.(null)}
                anchor="bottom"
                offset={12}
              >
                <div
                  className="map-popup !border-red-500/40"
                  style={{ borderWidth: 1, borderStyle: 'solid' }}
                >
                  <div className="flex justify-between items-start mb-1">
                    <div className="map-popup-title text-red-400">
                      {(props.name || 'UNKNOWN SYSTEM').toUpperCase()}
                    </div>
                    <button
                      onClick={() => onEntityClick?.(null)}
                      className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] ml-2"
                    >
                      ✕
                    </button>
                  </div>
                  <div className="map-popup-subtitle text-red-600/80 border-b border-red-900/30 pb-1 flex items-center gap-1.5">
                    <Radio size={10} /> TRUNKED RADIO SYSTEM
                  </div>

                  {(props.city || props.state) && (
                    <div className="map-popup-row mt-1">
                      Location:{' '}
                      <span className="text-white">
                        {[props.city, props.state].filter(Boolean).join(', ')}
                      </span>
                    </div>
                  )}
                  <div className="map-popup-row">
                    Active Listeners: <span className="text-red-400">{props.clientCount || 0}</span>
                  </div>
                  {props.description && (
                    <div className="map-popup-row">
                      <span className="text-[#888]">{String(props.description).slice(0, 120)}</span>
                    </div>
                  )}

                  <div className="flex items-center gap-2 mt-3 pt-2 border-t border-[var(--border-primary)]">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        if (setTrackedScanner) {
                          setTrackedScanner({
                            shortName: props.shortName || '',
                            name: props.name || '',
                            lat,
                            lng,
                            city: props.city || '',
                            state: props.state || '',
                            clientCount: props.clientCount || 0,
                            description: props.description || '',
                          });
                        }
                        onEntityClick?.(null);
                      }}
                      className="flex-1 text-center px-2 py-1.5 rounded bg-red-950/40 border border-red-500/30 hover:bg-red-900/60 hover:border-red-400 text-red-400 text-[10px] font-mono tracking-widest transition-colors flex justify-center items-center gap-1.5"
                    >
                      <Activity size={10} /> TRACK
                    </button>
                    <button
                      onClick={async (e) => {
                        e.stopPropagation();
                        const sn = props.shortName || '';
                        if (setTrackedScanner) {
                          setTrackedScanner({
                            shortName: sn,
                            name: props.name || '',
                            lat,
                            lng,
                            city: props.city || '',
                            state: props.state || '',
                            clientCount: props.clientCount || 0,
                            description: props.description || '',
                          });
                        }
                        onEntityClick?.(null);
                      }}
                      className="flex-1 text-center px-2 py-1.5 rounded bg-red-500/20 border border-red-500/50 hover:bg-red-500/30 hover:border-red-400 text-red-300 text-[10px] font-mono tracking-widest transition-colors flex justify-center items-center gap-1.5"
                    >
                      <Play size={10} /> OPEN PLAYER
                    </button>
                  </div>
                </div>
              </Popup>
            );
          })()}

        {/* SIGINT signal click popup */}
        {selectedEntity?.type === 'sigint' &&
          (() => {
            const props = (selectedEntity.extra || {}) as SigintProps;
            const sig = data?.sigint?.find(
              (s) => `${s.source}:${s.callsign}` === selectedEntity.id,
            );
            const d = sig || props;
            const lat = sig?.lat ?? props.geometry?.coordinates?.[1];
            const lng = sig?.lng ?? props.geometry?.coordinates?.[0];
            if (lat == null || lng == null) return null;
            return (
              <SigintPopup
                data={d}
                lat={lat}
                lng={lng}
                kiwisdrs={data?.kiwisdr || []}
                setTrackedSdr={setTrackedSdr}
                onClose={() => onEntityClick?.(null)}
              />
            );
          })()}

        {/* Ship / carrier click popup */}
        {selectedEntity?.type === 'ship' &&
          (() => {
            const ship = data?.ships?.find((s, i: number) => {
              return (
                sameEntityId(s.mmsi || s.name || `ship-${i}`, selectedEntity.id) ||
                sameEntityId(s.mmsi || s.name || `carrier-${i}`, selectedEntity.id)
              );
            });
            if (!ship) return null;
            const [iLng, iLat] = interpShip(ship);
            return (
              <ShipPopup
                ship={ship}
                longitude={iLng}
                latitude={iLat}
                onClose={() => onEntityClick?.(null)}
              />
            );
          })()}

        {/* SAR anomaly click popup */}
        {selectedEntity?.type === 'sar_anomaly' &&
          (() => {
            const extra = (selectedEntity.extra || {}) as Record<string, unknown>;
            const anomaly = data?.sar_anomalies?.find(
              (a) => a.anomaly_id === selectedEntity.id,
            );
            const a = anomaly || extra;
            const lat = typeof a.lat === 'number' ? a.lat : Number(extra.center_lat);
            const lng =
              typeof (a as { lon?: number }).lon === 'number'
                ? (a as { lon: number }).lon
                : Number(extra.center_lon);
            if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
            const kind = String(a.kind || extra.kind || 'anomaly');
            const title = String(a.title || extra.title || `SAR ${kind}`);
            const summary = String(a.summary || extra.summary || '');
            const solver = String(a.solver || extra.solver || '');
            const constellation = String(
              (a as { source_constellation?: string }).source_constellation ||
                extra.source_constellation ||
                '',
            );
            const magnitude = Number(a.magnitude ?? extra.magnitude ?? 0);
            const unit = String(a.magnitude_unit || extra.magnitude_unit || '');
            const confidence = Number(a.confidence ?? extra.confidence ?? 0);
            const lastSeen = Number(a.last_seen ?? extra.last_seen ?? 0);
            const provenance = String(a.provenance_url || extra.provenance_url || '');
            const aoiId = String(a.aoi_id || extra.aoi_id || '');
            const color = String(extra.color || '#eab308');
            return (
              <Popup
                longitude={lng}
                latitude={lat}
                closeButton={false}
                closeOnClick={false}
                onClose={() => onEntityClick?.(null)}
                className="threat-popup"
                maxWidth="320px"
              >
                <div
                  className="map-popup bg-zinc-950/95 text-amber-100 min-w-[240px]"
                  style={{ border: `1px solid ${color}66` }}
                >
                  <div
                    className="map-popup-title flex items-center justify-between gap-2 border-b pb-1"
                    style={{ borderColor: `${color}33`, color }}
                  >
                    <span className="font-semibold">{title}</span>
                    <button
                      type="button"
                      onClick={() => onEntityClick?.(null)}
                      className="text-amber-200/60 hover:text-amber-100"
                      aria-label="Close"
                    >
                      ✕
                    </button>
                  </div>
                  {summary && (
                    <div className="map-popup-row text-[11px] text-amber-100/80 leading-snug">
                      {summary}
                    </div>
                  )}
                  <div className="map-popup-row text-[11px]">
                    Kind:{' '}
                    <span className="text-amber-200 font-mono">
                      {kind.replace(/_/g, ' ')}
                    </span>
                  </div>
                  {solver && (
                    <div className="map-popup-row text-[11px]">
                      Solver: <span className="text-amber-200">{solver}</span>
                    </div>
                  )}
                  {constellation && (
                    <div className="map-popup-row text-[11px]">
                      Source: <span className="text-amber-200">{constellation}</span>
                    </div>
                  )}
                  {magnitude !== 0 && (
                    <div className="map-popup-row text-[11px]">
                      Magnitude:{' '}
                      <span className="text-amber-200">
                        {magnitude.toFixed(3)} {unit}
                      </span>
                    </div>
                  )}
                  <div className="map-popup-row text-[11px]">
                    Confidence:{' '}
                    <span className="text-amber-200">{(confidence * 100).toFixed(0)}%</span>
                  </div>
                  {lastSeen > 0 && (
                    <div className="map-popup-row text-[11px]">
                      Last seen:{' '}
                      <span className="text-amber-200">
                        {new Date(lastSeen * 1000).toISOString().replace('T', ' ').slice(0, 19)}Z
                      </span>
                    </div>
                  )}
                  {aoiId && (
                    <div className="map-popup-row text-[11px]">
                      AOI: <span className="text-amber-200 font-mono">{aoiId}</span>
                    </div>
                  )}
                  {provenance && (
                    <div className="map-popup-row text-[11px]">
                      <a
                        href={provenance}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-cyan-300 hover:text-cyan-200 underline"
                      >
                        Provenance ↗
                      </a>
                    </div>
                  )}
                </div>
              </Popup>
            );
          })()}

        {/* SAR AOI click popup — operator watchbox details */}
        {selectedEntity?.type === 'sar_aoi' &&
          (() => {
            const extra = (selectedEntity.extra || {}) as Record<string, unknown>;
            const lat = Number(extra.center_lat);
            const lng = Number(extra.center_lon);
            if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
            const name = String(extra.name || selectedEntity.id);
            const description = String(extra.description || '');
            const category = String(extra.category || 'watchlist');
            const radius = Number(extra.radius_km || 0);
            return (
              <Popup
                longitude={lng}
                latitude={lat}
                closeButton={false}
                closeOnClick={false}
                onClose={() => onEntityClick?.(null)}
                className="threat-popup"
                maxWidth="300px"
              >
                <div className="map-popup bg-zinc-950/95 border border-amber-400/40 text-amber-100 min-w-[220px]">
                  <div className="map-popup-title flex items-center justify-between gap-2 text-amber-300 border-b border-amber-400/20 pb-1">
                    <span>AOI · {name}</span>
                    <button
                      type="button"
                      onClick={() => onEntityClick?.(null)}
                      className="text-amber-200/60 hover:text-amber-100"
                      aria-label="Close"
                    >
                      ✕
                    </button>
                  </div>
                  {description && (
                    <div className="map-popup-row text-[11px] text-amber-100/80 leading-snug">
                      {description}
                    </div>
                  )}
                  <div className="map-popup-row text-[11px]">
                    Category:{' '}
                    <span className="text-amber-200 font-mono">{category}</span>
                  </div>
                  <div className="map-popup-row text-[11px]">
                    Radius: <span className="text-amber-200">{radius.toFixed(0)} km</span>
                  </div>
                  <div className="map-popup-row text-[11px]">
                    Center:{' '}
                    <span className="text-amber-200 font-mono">
                      {lat.toFixed(3)}, {lng.toFixed(3)}
                    </span>
                  </div>
                </div>
              </Popup>
            );
          })()}

        {/* Data Center click popup */}
        {selectedEntity?.type === 'datacenter' &&
          (() => {
            const dc = data?.datacenters?.find((_, i: number) => `dc-${i}` === selectedEntity.id);
            if (!dc) return null;
            // Check if any internet outage is in the same country
            const outagesInCountry = (data?.internet_outages || []).filter(
              (o) =>
                o.country_name &&
                dc.country &&
                o.country_name.toLowerCase() === dc.country.toLowerCase(),
            );
            return (
              <Popup
                longitude={dc.lng}
                latitude={dc.lat}
                closeButton={false}
                closeOnClick={false}
                onClose={() => onEntityClick?.(null)}
                className="threat-popup"
                maxWidth="280px"
              >
                <div className="map-popup bg-[#1a1035] border border-violet-400/40 text-[#e9d5ff] min-w-[200px]">
                  <div className="map-popup-title text-violet-400 border-b border-violet-400/20 pb-1">
                    {dc.name}
                  </div>
                  {dc.company && (
                    <div className="map-popup-row">
                      Operator: <span className="text-[#c4b5fd]">{dc.company}</span>
                    </div>
                  )}
                  {dc.street && (
                    <div className="map-popup-row">
                      Address:{' '}
                      <span className="text-white">
                        {dc.street}
                        {dc.zip ? ` ${dc.zip}` : ''}
                      </span>
                    </div>
                  )}
                  {dc.city && (
                    <div className="map-popup-row">
                      Location:{' '}
                      <span className="text-white">
                        {dc.city}
                        {dc.country ? `, ${dc.country}` : ''}
                      </span>
                    </div>
                  )}
                  {!dc.city && dc.country && (
                    <div className="map-popup-row">
                      Country: <span className="text-white">{dc.country}</span>
                    </div>
                  )}
                  {outagesInCountry.length > 0 && (
                    <div className="mt-1.5 px-2 py-1 bg-red-500/15 border border-red-400/40 rounded text-[10px] text-[#ff6b6b]">
                      OUTAGE IN REGION —{' '}
                      {outagesInCountry.map((o) => `${o.region_name} (${o.severity}%)`).join(', ')}
                    </div>
                  )}
                  <div className="mt-1.5 text-[10px] text-violet-600 tracking-wider">
                    DATA CENTER
                  </div>
                </div>
              </Popup>
            );
          })()}

        {/* Power Plant click popup */}
        {selectedEntity?.type === 'power_plant' && (() => {
            const pp = data?.power_plants?.find((_: any, i: number) => `pp-${i}` === selectedEntity.id);
            if (!pp) return null;
            return (
                <Popup
                    longitude={pp.lng}
                    latitude={pp.lat}
                    closeButton={false}
                    closeOnClick={false}
                    onClose={() => onEntityClick?.(null)}
                    className="threat-popup"
                    maxWidth="280px"
                >
                    <div className="map-popup bg-[#1a0f00] border border-amber-400/40 text-[#fde68a] min-w-[200px]">
                        <div className="map-popup-title text-amber-400 border-b border-amber-400/20 pb-1">
                            {pp.name}
                        </div>
                        {pp.fuel_type && (
                            <div className="map-popup-row">
                                Fuel: <span className="text-[#fbbf24]">{pp.fuel_type}</span>
                            </div>
                        )}
                        {pp.capacity_mw != null && (
                            <div className="map-popup-row">
                                Capacity: <span className="text-white">{pp.capacity_mw.toLocaleString()} MW</span>
                            </div>
                        )}
                        {pp.owner && (
                            <div className="map-popup-row">
                                Operator: <span className="text-white">{pp.owner}</span>
                            </div>
                        )}
                        {pp.country && (
                            <div className="map-popup-row">
                                Country: <span className="text-white">{pp.country}</span>
                            </div>
                        )}
                        <div className="mt-1.5 text-[10px] text-amber-600 tracking-wider">
                            POWER PLANT
                        </div>
                    </div>
                </Popup>
            );
        })()}

        {/* VIIRS Change Node click popup */}
        {selectedEntity?.type === 'viirs_change_node' && (() => {
            const node = data?.viirs_change_nodes?.find(
                (_: any, i: number) => `viirs-${i}` === selectedEntity.id
            );
            if (!node) return null;
            const isLoss = node.mean_change_pct < 0;
            return (
                <Popup
                    longitude={node.lng}
                    latitude={node.lat}
                    closeButton={false}
                    closeOnClick={false}
                    onClose={() => onEntityClick?.(null)}
                    className="threat-popup"
                    maxWidth="280px"
                >
                    <div className="map-popup bg-black/90 border border-cyan-500/30 text-white min-w-[200px]">
                        <div className="map-popup-title text-cyan-400 border-b border-cyan-500/20 pb-1 tracking-wider">
                            VIIRS NIGHT LIGHTS
                        </div>
                        <div className="map-popup-row">
                            Region: <span className="text-white">{node.aoi_name}</span>
                        </div>
                        <div className="map-popup-row">
                            Change: <span className={`text-lg font-bold ${isLoss ? 'text-red-400' : 'text-green-400'}`}>
                                {isLoss ? '' : '+'}{node.mean_change_pct.toFixed(1)}%
                            </span>
                        </div>
                        <div className="map-popup-row">
                            Severity: <span className="text-white uppercase">{node.severity.replace('_', ' ')}</span>
                        </div>
                        <div className="mt-1.5 text-[10px] text-cyan-600 tracking-wider">
                            {isLoss ? 'LIGHTS WENT DARK' : 'LIGHTS INCREASED'}
                        </div>
                    </div>
                </Popup>
            );
        })()}

        {selectedEntity?.type === 'military_base' &&
          (() => {
            const base = data?.military_bases?.find(
              (_, i: number) => `milbase-${i}` === selectedEntity.id,
            );
            if (!base) return null;
            return (
              <MilitaryBasePopup
                base={base}
                oracleIntel={oracleIntel}
                onClose={() => onEntityClick?.(null)}
              />
            );
          })()}

        {/* Ukraine Air Raid Alert popup */}
        {selectedEntity?.type === 'ukraine_alert' &&
          (() => {
            const alert = data?.ukraine_alerts?.find((a) => String(a.id) === String(selectedEntity.id));
            if (!alert) return null;
            const accent = alert.color || '#ef4444';
            const geom = alert.geometry;
            const coords = geom?.type === 'Polygon' ? geom.coordinates?.[0]?.[0] : geom?.type === 'MultiPolygon' ? geom.coordinates?.[0]?.[0]?.[0] : null;
            if (!coords) return null;
            const started = alert.started_at ? new Date(alert.started_at) : null;
            const durationMin = started ? Math.round((Date.now() - started.getTime()) / 60000) : null;
            const durationStr = durationMin != null ? (durationMin >= 60 ? `${Math.floor(durationMin / 60)}h ${durationMin % 60}m` : `${durationMin}m`) : '';
            const alertLabel = ({ air_raid: 'AIR RAID', artillery_shelling: 'SHELLING', urban_fights: 'URBAN COMBAT', chemical: 'CHEMICAL', nuclear: 'NUCLEAR' } as Record<string, string>)[alert.alert_type] || alert.alert_type.toUpperCase();
            return (
              <Popup longitude={coords[0]} latitude={coords[1]} closeButton={false} closeOnClick={false} onClose={() => onEntityClick?.(null)} className="threat-popup" maxWidth="300px">
                <div className="map-popup bg-[#1a1035] min-w-[220px]" style={{ borderColor: `${accent}66` }}>
                  <div className="map-popup-title pb-1" style={{ color: accent, borderBottom: `1px solid ${accent}33` }}>
                    {alertLabel}
                  </div>
                  <div className="map-popup-row text-white text-[11px]">{alert.name_en || alert.location_title}</div>
                  <div className="map-popup-row">Oblast: <span className="text-white">{alert.location_title}</span></div>
                  {started && <div className="map-popup-row">Since: <span className="text-white">{started.toLocaleTimeString()}</span></div>}
                  {durationStr && <div className="map-popup-row">Duration: <span style={{ color: accent }}>{durationStr}</span></div>}
                  <div className="mt-1.5 text-[10px] tracking-wider text-gray-500">UKRAINE AIR RAID — ALERTS.IN.UA</div>
                </div>
              </Popup>
            );
          })()}

        {/* Weather Alert popup */}
        {selectedEntity?.type === 'weather_alert' &&
          (() => {
            const alert = data?.weather_alerts?.find((a) => sameEntityId(a.id, selectedEntity.id));
            if (!alert) return null;
            const sevColors: Record<string, string> = { Extreme: '#ef4444', Severe: '#f97316', Moderate: '#eab308', Minor: '#3b82f6' };
            const accent = sevColors[alert.severity] || '#3b82f6';
            const geom = alert.geometry;
            const coords = geom?.type === 'Polygon' ? geom.coordinates?.[0]?.[0] : geom?.type === 'MultiPolygon' ? geom.coordinates?.[0]?.[0]?.[0] : null;
            if (!coords) return null;
            return (
              <Popup longitude={coords[0]} latitude={coords[1]} closeButton={false} closeOnClick={false} onClose={() => onEntityClick?.(null)} className="threat-popup" maxWidth="300px">
                <div className="map-popup bg-[#1a1035] min-w-[220px]" style={{ borderColor: `${accent}66` }}>
                  <div className="map-popup-title pb-1" style={{ color: accent, borderBottom: `1px solid ${accent}33` }}>
                    {alert.event}
                  </div>
                  <div className="map-popup-row text-white text-[10px] leading-snug">{alert.headline}</div>
                  <div className="map-popup-row">Severity: <span style={{ color: accent }}>{alert.severity}</span></div>
                  {alert.expires && <div className="map-popup-row">Expires: <span className="text-white">{new Date(alert.expires).toLocaleString()}</span></div>}
                  <div className="mt-1 text-[10px] text-gray-400 leading-snug max-h-[60px] overflow-hidden">{alert.description}</div>
                </div>
              </Popup>
            );
          })()}

        {/* Air Quality popup */}
        {selectedEntity?.type === 'air_quality' &&
          (() => {
            const station = data?.air_quality?.find((s) => `aq-${s.id}` === selectedEntity.id);
            if (!station) return null;
            const aqiColors: Record<string, string> = { Good: '#22c55e', Moderate: '#eab308', 'Unhealthy (Sensitive)': '#f97316', Unhealthy: '#ef4444', 'Very Unhealthy': '#a855f7', Hazardous: '#7f1d1d' };
            const label = station.aqi <= 50 ? 'Good' : station.aqi <= 100 ? 'Moderate' : station.aqi <= 150 ? 'Unhealthy (Sensitive)' : station.aqi <= 200 ? 'Unhealthy' : station.aqi <= 300 ? 'Very Unhealthy' : 'Hazardous';
            const accent = aqiColors[label] || '#22c55e';
            return (
              <Popup longitude={station.lng} latitude={station.lat} closeButton={false} closeOnClick={false} onClose={() => onEntityClick?.(null)} className="threat-popup" maxWidth="260px">
                <div className="map-popup bg-[#1a1035] min-w-[180px]" style={{ borderColor: `${accent}66` }}>
                  <div className="map-popup-title pb-1" style={{ color: accent, borderBottom: `1px solid ${accent}33` }}>
                    {station.name}
                  </div>
                  <div className="map-popup-row">AQI: <span style={{ color: accent, fontWeight: 'bold' }}>{station.aqi}</span> <span className="text-gray-400">({label})</span></div>
                  <div className="map-popup-row">PM2.5: <span className="text-white">{station.pm25} µg/m³</span></div>
                  {station.country && <div className="map-popup-row">Country: <span className="text-white">{station.country}</span></div>}
                  <div className="mt-1.5 text-[10px] tracking-wider text-gray-500">AIR QUALITY — OPENAQ</div>
                </div>
              </Popup>
            );
          })()}

        {/* Earthquake popup */}
        {selectedEntity?.type === 'earthquake' &&
          (() => {
            const extra = (selectedEntity.extra || {}) as Record<string, unknown>;
            const idx = Number(selectedEntity.id);
            const eq = Number.isFinite(idx)
              ? data?.earthquakes?.[idx]
              : data?.earthquakes?.find((e) => e.id === String(selectedEntity.id));
            const lat = typeof eq?.lat === 'number' ? eq.lat : Number(extra.lat);
            const lng = typeof eq?.lng === 'number' ? eq.lng : Number(extra.lng);
            if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
            const mag = eq?.mag ?? Number(extra.mag);
            const place = eq?.place || String(extra.place || selectedEntity.name || 'Unknown location');
            const accent = mag >= 6 ? '#ef4444' : mag >= 4.5 ? '#f97316' : '#eab308';
            return (
              <Popup
                longitude={lng}
                latitude={lat}
                closeButton={false}
                closeOnClick={false}
                onClose={() => onEntityClick?.(null)}
                className="threat-popup"
                maxWidth="280px"
              >
                <div className="map-popup bg-[#1a1035] min-w-[200px]" style={{ borderColor: `${accent}66` }}>
                  <div className="map-popup-title pb-1" style={{ color: accent, borderBottom: `1px solid ${accent}33` }}>
                    M{Number.isFinite(mag) ? mag.toFixed(1) : '?'} — EARTHQUAKE
                  </div>
                  <div className="map-popup-row">
                    Location: <span className="text-white">{place}</span>
                  </div>
                  <div className="map-popup-row">
                    Coords:{' '}
                    <span className="text-white font-mono">
                      {lat.toFixed(3)}, {lng.toFixed(3)}
                    </span>
                  </div>
                  {oracleIntel?.found && (
                    <div className="mt-2 pt-2 border-t border-yellow-500/20">
                      <div className="text-[10px] font-mono text-yellow-500/80 tracking-wider mb-1">REGION INTEL</div>
                      <div className="text-[10px] font-mono text-white/70">
                        ORACLE: {oracleIntel.tier}
                        {oracleIntel.avg_sentiment != null && (
                          <span className="text-gray-400">
                            {' '}
                            · SENT {oracleIntel.avg_sentiment > 0 ? '+' : ''}
                            {oracleIntel.avg_sentiment.toFixed(2)}
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                  <div className="mt-1.5 text-[10px] tracking-wider" style={{ color: `${accent}99` }}>
                    SEISMIC — USGS
                  </div>
                </div>
              </Popup>
            );
          })()}

        {/* Volcano popup */}
        {selectedEntity?.type === 'volcano' &&
          (() => {
            const idx = parseInt(String(selectedEntity.id).replace('volcano-', ''), 10);
            const volcano = data?.volcanoes?.[idx];
            if (!volcano) return null;
            const now = new Date().getFullYear();
            const yearsAgo = volcano.last_eruption_year ? now - volcano.last_eruption_year : null;
            const accent = yearsAgo !== null && yearsAgo <= 50 ? '#ef4444' : yearsAgo !== null && yearsAgo <= 500 ? '#f97316' : '#6b7280';
            return (
              <Popup longitude={volcano.lng} latitude={volcano.lat} closeButton={false} closeOnClick={false} onClose={() => onEntityClick?.(null)} className="threat-popup" maxWidth="260px">
                <div className="map-popup bg-[#1a1035] min-w-[180px]" style={{ borderColor: `${accent}66` }}>
                  <div className="map-popup-title pb-1" style={{ color: accent, borderBottom: `1px solid ${accent}33` }}>
                    {volcano.name}
                  </div>
                  <div className="map-popup-row">Type: <span className="text-white">{volcano.type}</span></div>
                  <div className="map-popup-row">Country: <span className="text-white">{volcano.country}</span></div>
                  {volcano.region && <div className="map-popup-row">Region: <span className="text-white">{volcano.region}</span></div>}
                  <div className="map-popup-row">Elevation: <span className="text-white">{volcano.elevation?.toLocaleString()}m</span></div>
                  <div className="map-popup-row">Last Eruption: <span className="text-white">{volcano.last_eruption_year || 'Unknown'}</span></div>
                  <div className="mt-1.5 text-[10px] tracking-wider" style={{ color: `${accent}99` }}>
                    VOLCANO — SMITHSONIAN GVP
                  </div>
                </div>
              </Popup>
            );
          })()}

        {/* Fishing Event popup — cross-references with AIS when available */}
        {selectedEntity?.type === 'fishing_event' &&
          (() => {
            const event = data?.fishing_activity?.find((e) => (e.id || '') === selectedEntity.id);
            if (!event) return null;
            // Cross-reference with AIS ships by vessel name
            const vesselNameUpper = (event.vessel_name || '').toUpperCase().trim();
            const aisMatch = vesselNameUpper && data?.ships?.find((s) => {
              const shipName = (s.name || '').toUpperCase().trim();
              return shipName && (shipName === vesselNameUpper || shipName.includes(vesselNameUpper) || vesselNameUpper.includes(shipName));
            });
            return (
              <Popup longitude={event.lng} latitude={event.lat} closeButton={false} closeOnClick={false} onClose={() => onEntityClick?.(null)} className="threat-popup" maxWidth="320px">
                <div className="map-popup bg-[#1a1035] min-w-[220px]" style={{ borderColor: '#0ea5e966' }}>
                  <div className="flex justify-between items-start">
                    <div className="map-popup-title pb-1 flex-1" style={{ color: '#0ea5e9', borderBottom: '1px solid #0ea5e933' }}>
                      {event.vessel_name}
                    </div>
                    <button onClick={() => onEntityClick?.(null)} className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] ml-2 shrink-0">✕</button>
                  </div>
                  <div className="map-popup-row">Flag: <span className="text-white">{event.vessel_flag || 'Unknown'}</span></div>
                  <div className="map-popup-row">Activity: <span className="text-cyan-400 capitalize">{event.type}</span></div>
                  <div className="map-popup-row">Duration: <span className="text-white">{event.duration_hrs}h</span></div>
                  {event.start && <div className="map-popup-row">Start: <span className="text-white">{new Date(event.start).toLocaleDateString()}</span></div>}

                  {/* AIS cross-reference data */}
                  {aisMatch && (
                    <div className="mt-2 pt-2 border-t border-cyan-500/20">
                      <div className="text-[11px] font-mono text-cyan-400 tracking-wider mb-1">AIS CROSS-REFERENCE</div>
                      {aisMatch.mmsi && <div className="map-popup-row">MMSI: <span className="text-white">{aisMatch.mmsi}</span></div>}
                      {aisMatch.callsign && <div className="map-popup-row">Callsign: <span className="text-white">{aisMatch.callsign}</span></div>}
                      {aisMatch.type && <div className="map-popup-row">Vessel Type: <span className="text-cyan-400 uppercase">{aisMatch.type}</span></div>}
                      {aisMatch.destination && <div className="map-popup-row">Destination: <span className="text-cyan-400">{aisMatch.destination}</span></div>}
                      {aisMatch.sog > 0 && <div className="map-popup-row">Speed: <span className="text-white">{aisMatch.sog} kts</span></div>}
                      {aisMatch.cog > 0 && <div className="map-popup-row">Course: <span className="text-white">{Math.round(aisMatch.cog)}°</span></div>}
                      {aisMatch.country && <div className="map-popup-row">Country: <span className="text-white">{aisMatch.country}</span></div>}
                      {aisMatch.imo && <div className="map-popup-row">IMO: <span className="text-white">{aisMatch.imo}</span></div>}
                    </div>
                  )}

                  <div className="mt-1.5 text-[11px] tracking-wider text-gray-500">
                    FISHING — GLOBAL FISHING WATCH
                    {aisMatch && <span className="text-cyan-500"> + AIS</span>}
                  </div>
                </div>
              </Popup>
            );
          })()}

        {/* Fishing vessel → AIS destination route line */}
        {selectedEntity?.type === 'fishing_event' &&
          (() => {
            const event = data?.fishing_activity?.find((e) => (e.id || '') === selectedEntity.id);
            if (!event) return null;
            const vesselNameUpper = (event.vessel_name || '').toUpperCase().trim();
            if (!vesselNameUpper) return null;
            const aisMatch = data?.ships?.find((s) => {
              const shipName = (s.name || '').toUpperCase().trim();
              return shipName && (shipName === vesselNameUpper || shipName.includes(vesselNameUpper) || vesselNameUpper.includes(shipName));
            });
            const dest = aisMatch?.destination;
            if (!dest || dest === 'UNKNOWN') return null;
            return <FishingDestinationRoute vesselLat={event.lat} vesselLng={event.lng} destination={dest} />;
          })()}

        {(() => {
          if (selectedEntity?.type !== 'gt_risk' || !selectedEntity.extra) return null;
          const props = selectedEntity.extra as Record<string, unknown>;
          const lat = Number(props.lat);
          const lng = Number(props.lng);
          if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
          return (
            <GtRiskPopup
              region={String(props.region || props.name || selectedEntity.id)}
              risk={Number(props.risk ?? 0)}
              financial={Number(props.financial ?? 0)}
              unrest={Number(props.unrest ?? 0)}
              conflict={Number(props.conflict ?? 0)}
              contagion={Number(props.contagion ?? 0)}
              interpretation={String(props.interpretation || '')}
              lat={lat}
              lng={lng}
              onClose={() => onEntityClick?.(null)}
            />
          );
        })()}

        {(() => {
          if (selectedEntity?.type !== 'telegram_osint' || !data?.telegram_osint?.posts) return null;
          const allPosts = data.telegram_osint.posts;
          const clusterPosts = allPosts.filter((p) => {
            if (!p.coords || p.coords.length < 2) return false;
            const key = telegramClusterKey(p.coords[0], p.coords[1]);
            return key === selectedEntity.id || p.id === selectedEntity.id;
          });
          const anchor = clusterPosts[0]?.coords;
          if (!anchor || anchor.length < 2) return null;
          const avoidAlert = telegramClusterNearNewsAlert(anchor[0], anchor[1], data?.news);
          const [pinLat, pinLng] = telegramMapPinCoords(anchor[0], anchor[1], avoidAlert);
          return (
            <TelegramOsintPopup
              posts={clusterPosts}
              lat={pinLat}
              lng={pinLng}
              onClose={() => onEntityClick?.(null)}
            />
          );
        })()}

        {(() => {
          if (selectedEntity?.type !== 'gdelt' || !data?.gdelt) return null;
          const item = data.gdelt.find(
            (g) => (g.properties?.name || String(g.geometry?.coordinates)) === selectedEntity.id,
          );
          if (!item?.geometry?.coordinates) return null;
          return (
            <Popup
              longitude={item.geometry.coordinates[0]}
              latitude={item.geometry.coordinates[1]}
              closeButton={false}
              closeOnClick={false}
              onClose={() => onEntityClick?.(null)}
              anchor="bottom"
              offset={15}
            >
              <div className="bg-[var(--bg-secondary)]/90 backdrop-blur-md border border-orange-800 rounded-lg flex flex-col z-[100] font-mono shadow-[0_4px_30px_rgba(255,140,0,0.4)] pointer-events-auto overflow-hidden w-[440px]">
                <div className="p-2 border-b border-orange-500/30 bg-orange-950/40 flex justify-between items-center">
                  <h2 className="text-[11px] tracking-widest font-bold text-orange-400 flex items-center gap-1">
                    <AlertTriangle size={13} className="text-orange-400" /> NEWS ON THE GROUND
                  </h2>
                  <button
                    onClick={() => onEntityClick?.(null)}
                    className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                  >
                    ✕
                  </button>
                </div>
                <div className="p-3 flex flex-col gap-2">
                  <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-1">
                    <span className="text-[var(--text-muted)] text-[10px]">LOCATION</span>
                    <span className="text-white text-[12px] font-bold text-right ml-2 break-words max-w-[260px]">
                      {item.properties?.name || 'UNKNOWN REGION'}
                    </span>
                  </div>
                  {/* Enriched GDELT fields */}
                  {item.properties?.event_date && (
                    <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-1">
                      <span className="text-[var(--text-muted)] text-[10px]">DATE</span>
                      <span className="text-white text-[11px] font-bold">
                        {String(item.properties.event_date).replace(/(\d{4})(\d{2})(\d{2})/, '$1-$2-$3')}
                      </span>
                    </div>
                  )}
                  {((item.properties?.actors?.length ?? 0) > 0) && (
                    <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-1">
                      <span className="text-[var(--text-muted)] text-[10px]">ACTORS</span>
                      <span className="text-orange-300 text-[11px] font-bold text-right ml-2 max-w-[280px] truncate">
                        {item.properties.actors!.join(' vs ')}
                      </span>
                    </div>
                  )}
                  {item.properties?.goldstein != null && item.properties.goldstein !== 0 && (
                    <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-1">
                      <span className="text-[var(--text-muted)] text-[10px]">INTENSITY</span>
                      <span className={`text-[11px] font-bold ${item.properties.goldstein <= -5 ? 'text-red-400' : item.properties.goldstein <= -2 ? 'text-orange-400' : 'text-yellow-400'}`}>
                        {item.properties.goldstein > 0 ? '+' : ''}{item.properties.goldstein} Goldstein
                      </span>
                    </div>
                  )}
                  <div className="flex gap-3 border-b border-[var(--border-primary)] pb-1">
                    <div className="flex-1 flex justify-between items-center">
                      <span className="text-[var(--text-muted)] text-[10px]">EVENTS</span>
                      <span className="text-white text-[11px] font-bold">{item.properties?.count || 1}</span>
                    </div>
                    {(item.properties?.num_sources ?? 0) > 0 && (
                      <div className="flex-1 flex justify-between items-center">
                        <span className="text-[var(--text-muted)] text-[10px]">SOURCES</span>
                        <span className="text-white text-[11px] font-bold">{item.properties.num_sources}</span>
                      </div>
                    )}
                    {(item.properties?.num_articles ?? 0) > 0 && (
                      <div className="flex-1 flex justify-between items-center">
                        <span className="text-[var(--text-muted)] text-[10px]">ARTICLES</span>
                        <span className="text-white text-[11px] font-bold">{item.properties.num_articles}</span>
                      </div>
                    )}
                  </div>
                  <div className="flex flex-col gap-1 mt-1">
                    <span className="text-[var(--text-muted)] text-[10px]">
                      LATEST REPORTS: ({(item.properties?._urls_list || []).length})
                    </span>
                    <div className="flex flex-col gap-2 max-h-[320px] overflow-y-auto styled-scrollbar mt-1">
                      {(() => {
                        const urls: string[] = item.properties?._urls_list || [];
                        const headlines: string[] = item.properties?._headlines_list || [];
                        const snippets: string[] = item.properties?._snippets_list || [];
                        if (urls.length === 0)
                          return (
                            <span className="text-[var(--text-muted)] text-[11px]">
                              No articles available.
                            </span>
                          );
                        return urls.map((url: string, idx: number) => {
                          const headline = headlines[idx] || '';
                          const snippet = snippets[idx] || '';
                          let domain = '';
                          try {
                            domain = new URL(url).hostname.replace('www.', '');
                          } catch {
                            domain = '';
                          }
                          return (
                            <a
                              key={idx}
                              href={url}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="block py-2 border-b border-[var(--border-primary)]/50 last:border-0 cursor-pointer group"
                              style={{ pointerEvents: 'all' }}
                            >
                              <span className="text-orange-400 text-[13px] font-bold leading-snug group-hover:text-orange-300 block">
                                {headline || domain || 'View Article'}
                              </span>
                              {snippet && (
                                <span className="text-[var(--text-secondary)] text-[11px] leading-relaxed block mt-1">
                                  {snippet}
                                </span>
                              )}
                              {domain && (
                                <span className="text-[var(--text-muted)] text-[10px] block mt-1">
                                  {domain}
                                </span>
                              )}
                            </a>
                          );
                        });
                      })()}
                    </div>
                  </div>
                </div>
              </div>
            </Popup>
          );
        })()}

        {selectedEntity?.type === 'liveuamap' &&
          data?.liveuamap?.find((l) => String(l.id) === String(selectedEntity.id)) &&
          (() => {
            const item = data.liveuamap.find((l) => String(l.id) === String(selectedEntity.id));
            if (!item) return null;
            return (
              <Popup
                longitude={item.lng}
                latitude={item.lat}
                closeButton={false}
                closeOnClick={false}
                onClose={() => onEntityClick?.(null)}
                anchor="bottom"
                offset={15}
              >
                <div className="bg-[var(--bg-secondary)]/90 backdrop-blur-md border border-yellow-800 rounded-lg flex flex-col z-[100] font-mono shadow-[0_4px_30px_rgba(255,255,0,0.3)] pointer-events-auto overflow-hidden w-[280px]">
                  <div className="p-2 border-b border-yellow-500/30 bg-yellow-950/40 flex justify-between items-center">
                    <h2 className="text-[10px] tracking-widest font-bold text-yellow-400 flex items-center gap-1">
                      <AlertTriangle size={12} className="text-yellow-400" /> REGIONAL TACTICAL
                      EVENT
                    </h2>
                    <button
                      onClick={() => onEntityClick?.(null)}
                      className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                    >
                      ✕
                    </button>
                  </div>
                  <div className="p-3 flex flex-col gap-2">
                    <div className="flex flex-col gap-1 border-b border-[var(--border-primary)] pb-1">
                      <span className="text-yellow-400 text-[10px] font-bold leading-tight">
                        {item.title}
                      </span>
                    </div>
                    {item.description && (
                      <div className="text-[10px] text-white/70 leading-relaxed border-b border-[var(--border-primary)] pb-1.5">
                        {item.description}
                      </div>
                    )}
                    <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-1">
                      <span className="text-[var(--text-muted)] text-[10px]">REGION</span>
                      <span className="text-white text-[10px] font-bold">{item.region || 'Unknown'}</span>
                    </div>
                    <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-1">
                      <span className="text-[var(--text-muted)] text-[10px]">TIME</span>
                      <span className="text-white text-[10px] font-bold">
                        {item.date || (item.timestamp ? new Date(Number(item.timestamp) * 1000).toLocaleString() : 'UNKNOWN')}
                      </span>
                    </div>
                    {item.category && (
                      <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-1">
                        <span className="text-[var(--text-muted)] text-[10px]">TYPE</span>
                        <span className="text-yellow-300 text-[10px] font-bold">{item.category}</span>
                      </div>
                    )}
                    {item.source && (
                      <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-1">
                        <span className="text-[var(--text-muted)] text-[10px]">SOURCE</span>
                        <span className="text-white/60 text-[10px]">{item.source}</span>
                      </div>
                    )}
                    {item.link && (
                      <div className="flex justify-between items-center mt-1">
                        <a
                          href={item.link}
                          target="_blank"
                          rel="noreferrer"
                          className="text-yellow-400 hover:text-yellow-300 text-[10px] font-bold underline"
                        >
                          View Source Report
                        </a>
                      </div>
                    )}
                    {oracleIntel?.found && (
                      <div className="mt-2 pt-2 border-t border-cyan-500/20">
                        <div className="text-[11px] font-mono text-cyan-400 tracking-wider mb-1">ORACLE INTEL</div>
                        <div className="text-[11px] font-mono text-cyan-300/80">
                          <span className={oracleIntel.tier === 'CRITICAL' ? 'text-red-400' : oracleIntel.tier === 'ELEVATED' ? 'text-yellow-400' : 'text-green-400'}>
                            {oracleIntel.tier}
                          </span>
                          {' // '}
                          <span className={oracleIntel.avg_sentiment != null && oracleIntel.avg_sentiment < -0.05 ? 'text-red-400' : 'text-gray-400'}>
                            {oracleIntel.avg_sentiment != null ? `${oracleIntel.avg_sentiment > 0 ? '+' : ''}${oracleIntel.avg_sentiment.toFixed(2)} SENT` : ''}
                          </span>
                          {oracleIntel.market && (
                            <span className="text-purple-400">{' // '}{oracleIntel.market.consensus_pct}%</span>
                          )}
                        </div>
                        {oracleIntel.top_headline && (
                          <div className="text-[10px] text-white/60 mt-0.5 truncate">{oracleIntel.top_headline}</div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </Popup>
            );
          })()}

        {/* ── THREAT INTERCEPT — fullscreen intelligence dossier modal ── */}
        {(() => {
          if (selectedEntity?.type !== 'news' || !data?.news) return null;
          const item = data.news.find((n: any) => {
            const key = (n as any).alertKey || `${n.title}|${n.coords?.[0]},${n.coords?.[1]}`;
            return key === selectedEntity.id;
          }) as any;
          if (!item) return null;

          const rs = item.risk_score ?? 0;
          let threatHex = '#eab308';
          let threatColor = 'text-yellow-400';
          let borderColor = 'border-yellow-800';
          let bgHeaderColor = 'bg-yellow-950/50';
          if (rs >= 8) {
            threatHex = '#ef4444'; threatColor = 'text-red-400'; borderColor = 'border-red-700'; bgHeaderColor = 'bg-red-950/50';
          } else if (rs <= 4) {
            threatHex = '#22c55e'; threatColor = 'text-green-400'; borderColor = 'border-green-800'; bgHeaderColor = 'bg-green-950/50';
          }

          const sent = item.sentiment as number | undefined;
          const oScore = item.oracle_score as number | undefined;
          // Same tiers as the backend's machine assessment (oracle_service._build_assessment).
          const oTier = oScore != null ? (oScore >= 7 ? 'CRITICAL' : oScore >= 4 ? 'ELEVATED' : 'ROUTINE') : null;
          const oTierColor = oScore != null ? (oScore >= 7 ? 'text-red-400' : oScore >= 4 ? 'text-yellow-400' : 'text-cyan-300') : ''; // routine = neutral cyan, not an all-clear green
          const oTierBg = oScore != null ? (oScore >= 7 ? 'bg-red-500/10 border-red-500/30' : oScore >= 4 ? 'bg-yellow-500/10 border-yellow-500/30' : 'bg-cyan-500/10 border-cyan-500/30') : '';
          const sentColor = sent != null ? (sent < -0.1 ? 'text-red-400' : sent > 0.1 ? 'text-green-400' : 'text-gray-400') : '';
          const sentBg = sent != null ? (sent < -0.1 ? 'bg-red-500/10 border-red-500/30' : sent > 0.1 ? 'bg-green-500/10 border-green-500/30' : 'bg-gray-500/10 border-gray-500/30') : '';
          const sentArrow = sent != null ? (sent < -0.1 ? '▼' : sent > 0.1 ? '▲' : '●') : '';
          const sentLabel = sent != null ? (sent < -0.1 ? 'NEGATIVE' : sent > 0.1 ? 'POSITIVE' : 'NEUTRAL') : '';
          const pred = item.prediction_odds as any;
          // the cluster's article list includes the lead story itself; show only the others
          const articles = ((item.articles as any[]) || []).filter(
            (a: any) => !(a?.title === item.title && (a?.source || '') === (item.source || '')),
          );
          const clusterCount = articles.length;
          const isBreaking = item.breaking === true;

          if (typeof document === 'undefined') return null;
          // Portalled to <body> so it sits above the HUD columns (the map has its own stacking context).
          return createPortal(
            <div
              style={{
                position: 'fixed',
                top: 0, left: 0, right: 0, bottom: 0,
                zIndex: 9999,
                background: 'rgba(2,5,11,0.8)',
                backdropFilter: 'blur(12px)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '40px 20px',
              }}
              onClick={(e) => { if (e.target === e.currentTarget) onEntityClick?.(null); }}
              onKeyDown={(e: React.KeyboardEvent<HTMLDivElement>) => { if (e.key === 'Escape') onEntityClick?.(null); }}
              tabIndex={-1}
              ref={(el) => el?.focus()}
            >
              <div
                className={`sb-panel sb-modal border ${borderColor} flex flex-col font-mono overflow-hidden`}
                style={{
                  borderColor: `${threatHex}99`,
                  width: 'min(clamp(700px, 36vw, 900px), calc(100vw - 40px))',
                  maxHeight: 'calc(100vh - 80px)',
                  boxShadow: `0 0 36px ${threatHex}26, 0 30px 90px -30px rgba(0,0,0,0.9), inset 0 1px 0 rgba(255,255,255,0.05)`,
                }}
              >
                {/* ══════ HEADER ══════ */}
                <div className={`px-5 py-3 border-b ${borderColor}/60 ${bgHeaderColor} flex justify-between items-center shrink-0`}>
                  <div className="flex items-center gap-3">
                    <AlertTriangle size={18} className={threatColor} />
                    <span className={`text-[14px] tracking-[0.25em] font-bold ${threatColor}`}>
                      {isBreaking ? 'BREAKING INTERCEPT' : 'THREAT INTERCEPT'}
                    </span>
                    {isBreaking && <span className="text-[10px] bg-red-500 text-white px-2 py-0.5 rounded-sm font-bold animate-pulse">LIVE</span>}
                  </div>
                  <div className="flex items-center gap-3">
                    <span className={`text-[14px] ${threatColor} font-bold ${rs >= 8 ? 'animate-pulse' : ''}`}>
                      ALERT LVL: {rs}/10
                    </span>
                    <button
                      onClick={() => onEntityClick?.(null)}
                      aria-label="Close dossier"
                      className={`${threatColor} hover:text-white text-xl leading-none px-1.5 hover:bg-white/10 rounded-lg transition-colors`}
                    >
                      ✕
                    </button>
                  </div>
                </div>

                {/* ══════ SCROLLABLE BODY ══════ */}
                <div className="overflow-y-auto styled-scrollbar sb-scroll-fade flex flex-col flex-1 min-h-0 pb-4">

                  {/* ── HEADLINE ── */}
                  <div className="px-5 pt-4 pb-3">
                    <h2 className={`font-[family-name:var(--font-display)] text-[22px] font-semibold tracking-[0.01em] !leading-[1.25] [text-wrap:pretty] ${threatColor}`}>
                      {item.title}
                    </h2>
                    <div className="flex items-center gap-3 mt-2.5 text-[12px] text-[var(--text-muted)]">
                      <span className="text-white font-bold text-[12.5px]">{item.source || 'UNKNOWN'}</span>
                      {item.published && <span>• {formatDossierTime(item.published)}</span>}
                      {clusterCount > 0 && <span className="text-cyan-400 font-bold">• {clusterCount} RELATED {clusterCount === 1 ? 'REPORT' : 'REPORTS'}</span>}
                      {item.coords && (
                        <span className="ml-auto text-[11.5px] font-mono text-[var(--text-muted)]">
                          {item.coords[0].toFixed(3)}°, {item.coords[1].toFixed(3)}°
                        </span>
                      )}
                    </div>
                  </div>

                  {/* ── INTEL GRID: Oracle + Sentiment + Risk ── */}
                  <div className="px-5 pb-3">
                    <div className="grid grid-cols-3 gap-2">
                      {/* Oracle Score */}
                      <label className={`border rounded-xl p-3 text-center transition-colors hover:border-white/40 cursor-pointer ${oTierBg || 'bg-black/40 border-cyan-800/30'}`}>
                        <input type="checkbox" className="peer sr-only" aria-label="Explain Oracle Score" />
                        <div className="flex items-center justify-center gap-1 text-[11.5px] text-[var(--text-muted)] tracking-[0.14em] mb-1.5">
                          <span>ORACLE SCORE</span>
                          <Info size={12} />
                        </div>
                        <div className={`text-[28px] font-bold leading-none ${oTierColor || 'text-gray-500'}`}>
                          {oScore != null ? oScore.toFixed(1) : '—'}
                        </div>
                        {oTier && <div className={`text-[10px] font-bold ${oTierColor} mt-1`}>{oTier}</div>}
                        <div className="hidden peer-checked:block mt-2 border-t border-white/10 pt-2 text-left text-[10px] leading-relaxed text-cyan-100">
                          <div className="text-cyan-400 font-bold tracking-[0.16em] mb-1">SCALE</div>
                          <p>0-10 weighted signal score combining alert risk and source confidence.</p>
                          <p className="mt-1 text-[var(--text-muted)]">0-3 low, 4-5 moderate, 6-7 elevated, 8-10 critical.</p>
                        </div>
                      </label>
                      {/* Sentiment */}
                      <label className={`border rounded-xl p-3 text-center transition-colors hover:border-white/40 cursor-pointer ${sentBg || 'bg-black/40 border-cyan-800/30'}`}>
                        <input type="checkbox" className="peer sr-only" aria-label="Explain Sentiment" />
                        <div className="flex items-center justify-center gap-1 text-[11.5px] text-[var(--text-muted)] tracking-[0.14em] mb-1.5">
                          <span>SENTIMENT</span>
                          <Info size={12} />
                        </div>
                        <div className={`text-[28px] font-bold leading-none ${sentColor || 'text-gray-500'}`}>
                          {sent != null ? <><span className={sentArrow === '●' ? 'text-[0.6em] align-middle' : ''}>{sentArrow}</span> {sent > 0 ? '+' : ''}{sent.toFixed(2)}</> : '—'}
                        </div>
                        {sentLabel && <div className={`text-[10px] font-bold ${sentColor} mt-1`}>{sentLabel}</div>}
                        <div className="hidden peer-checked:block mt-2 border-t border-white/10 pt-2 text-left text-[10px] leading-relaxed text-cyan-100">
                          <div className="text-cyan-400 font-bold tracking-[0.16em] mb-1">SCALE</div>
                          <p>-1.00 to +1.00 headline tone. Negative reads more adverse; positive reads more constructive.</p>
                          <p className="mt-1 text-[var(--text-muted)]">Below -0.10 negative, -0.10 to +0.10 neutral, above +0.10 positive. It measures tone, not truth.</p>
                        </div>
                      </label>
                      {/* Threat Level */}
                      <label className={`border rounded-xl p-3 text-center transition-colors hover:border-white/40 cursor-pointer ${rs >= 8 ? 'bg-red-500/10 border-red-500/30' : rs >= 6 ? 'bg-orange-500/10 border-orange-500/30' : rs >= 4 ? 'bg-yellow-500/10 border-yellow-500/30' : 'bg-green-500/10 border-green-500/30'}`}>
                        <input type="checkbox" className="peer sr-only" aria-label="Explain Risk Level" />
                        <div className="flex items-center justify-center gap-1 text-[11.5px] text-[var(--text-muted)] tracking-[0.14em] mb-1.5">
                          <span>RISK LEVEL</span>
                          <Info size={12} />
                        </div>
                        <div className={`text-[28px] font-bold leading-none ${threatColor}`}>{rs}/10</div>
                        <div className={`text-[10px] font-bold ${threatColor} mt-1`}>
                          {rs >= 9 ? 'CRITICAL' : rs >= 7 ? 'HIGH' : rs >= 4 ? 'MEDIUM' : 'LOW'}
                        </div>
                        <div className="hidden peer-checked:block mt-2 border-t border-white/10 pt-2 text-left text-[10px] leading-relaxed text-cyan-100">
                          <div className="text-cyan-400 font-bold tracking-[0.16em] mb-1">SCALE</div>
                          <p>0-10 operational severity estimate based on source, topic, keywords, corroboration, and alert context.</p>
                          <p className="mt-1 text-[var(--text-muted)]">0-3 low, 4-6 medium, 7-8 high, 9-10 critical.</p>
                        </div>
                      </label>
                    </div>
                  </div>

                  {/* ── PREDICTION MARKET ANALYSIS ── */}
                  {pred && pred.consensus_pct != null && (
                    <div className="px-5 pb-3">
                      <div className="bg-purple-950/30 border border-purple-500/40 rounded p-4">
                        <div className="flex items-center justify-between gap-3 mb-2">
                          <div className="text-[10px] text-purple-400 tracking-[0.2em] font-bold">
                            PREDICTION MARKET ANALYSIS
                          </div>
                          {pred.polymarket_pct != null && (
                            <button
                              type="button"
                              onClick={() => window.open(buildPolymarketUrl(pred), '_blank', 'noopener,noreferrer')}
                              className="inline-flex items-center gap-1 text-[10px] text-purple-200 hover:text-white border border-purple-500/30 hover:border-purple-300/70 px-2 py-1 rounded transition-colors"
                              title="Open this market on Polymarket"
                            >
                              POLYMARKET <ExternalLink size={10} />
                            </button>
                          )}
                        </div>
                        <div className="text-[14px] text-purple-200 font-bold leading-snug mb-3">
                          &quot;{pred.title}&quot;
                        </div>
                        {/* Progress bar */}
                        <div className="bg-black/50 rounded overflow-hidden h-8 relative border border-purple-500/20 mb-3">
                          <div
                            className="h-full bg-gradient-to-r from-purple-700 to-purple-400 transition-all"
                            style={{ width: `${pred.consensus_pct}%` }}
                          />
                          <span className="absolute inset-0 flex items-center justify-center text-[14px] font-bold text-white drop-shadow-lg">
                            {pred.consensus_pct}% CONSENSUS PROBABILITY
                          </span>
                        </div>
                        <div className="flex gap-6 text-[11px]">
                          {pred.polymarket_pct != null && (
                            <button
                              type="button"
                              onClick={() => window.open(buildPolymarketUrl(pred), '_blank', 'noopener,noreferrer')}
                              className="flex items-center gap-2 hover:text-white transition-colors"
                              title="Open this market on Polymarket"
                            >
                              <span className="text-purple-400/70">Polymarket</span>
                              <span className="text-white font-bold text-[13px]">{pred.polymarket_pct}%</span>
                              <ExternalLink size={10} className="text-purple-400/70" />
                            </button>
                          )}
                          {pred.kalshi_pct != null && (
                            <div className="flex items-center gap-2">
                              <span className="text-purple-400/70">Kalshi</span>
                              <span className="text-white font-bold text-[13px]">{pred.kalshi_pct}%</span>
                            </div>
                          )}
                          {pred.match_score != null && (
                            <span className="text-purple-400/40 ml-auto text-[10px]">headline match: {(pred.match_score * 100).toFixed(0)}%</span>
                          )}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* SYS.ANALYSIS text omitted here: the score tiles above already show oracle tier and sentiment. */}

                  {/* ── CORROBORATING SOURCES ── */}
                  {articles.length > 0 && (
                    <div className="px-5 pb-3">
                      <div className="text-[10px] text-[var(--text-muted)] tracking-[0.2em] font-bold mb-2">
                        RELATED COVERAGE ({articles.length})
                      </div>
                      <div className="flex flex-col gap-1.5">
                        {articles.map((sub: any, si: number) => {
                          const subRs = sub.risk_score ?? 0;
                          const subColor = subRs >= 8 ? 'text-red-400' : subRs >= 6 ? 'text-orange-400' : subRs >= 4 ? 'text-yellow-400' : 'text-green-400';
                          return (
                            <div
                              key={si}
                              role="button"
                              tabIndex={0}
                              onClick={() => { const url = articleSourceUrl(sub.link); if (url) window.open(url, '_blank', 'noopener,noreferrer'); }}
                              onKeyDown={(e) => { const url = articleSourceUrl(sub.link); if (e.key === 'Enter' && url) window.open(url, '_blank', 'noopener,noreferrer'); }}
                              className="flex items-start gap-3 py-2 px-3 border-l-2 border-cyan-800/40 bg-black/30 rounded-r hover:bg-cyan-950/30 transition-colors group cursor-pointer"
                            >
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 text-[12px]">
                                  <span className="text-white font-bold">{sub.source}</span>
                                  <span className={`${subColor} font-bold`}>LVL: {subRs}/10</span>
                                  {sub.published && <span className="text-[var(--text-muted)] text-[12px]">{formatDossierTime(sub.published)}</span>}
                                </div>
                                <div className="sb-prose text-[12.5px] text-[var(--text-primary)] !leading-snug mt-0.5 group-hover:text-cyan-200 transition-colors">
                                  {sub.title}
                                </div>
                              </div>
                              <span className="text-[15px] leading-none text-cyan-500 group-hover:text-cyan-300 shrink-0 mt-0.5" aria-hidden="true">↗</span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>

                  {/* ── FOOTER (outside the scroller so it is always visible) ── */}
                  <div className="px-5 py-3 flex justify-between items-center border-t border-[var(--border-primary)] shrink-0">
                    {articleSourceUrl(item.link) ? (
                      <button
                        onClick={() => { const url = articleSourceUrl(item.link); if (url) window.open(url, '_blank', 'noopener,noreferrer'); }}
                        className="sb-btn-primary px-4 py-2 rounded-lg text-[12.5px] font-mono font-bold tracking-[0.1em] cursor-pointer"
                      >
                        GO TO ARTICLE ↗
                      </button>
                    ) : <span />}
                    <button
                      onClick={() => onEntityClick?.(null)}
                      className="text-[12px] font-mono tracking-[0.1em] text-[var(--text-secondary)] hover:text-white border border-[var(--border-primary)] hover:border-white/30 px-4 py-2 rounded-lg transition-colors"
                    >
                      CLOSE DOSSIER
                    </button>
                  </div>
              </div>
            </div>,
            document.body,
          );
        })()}

        {/* REGION DOSSIER — location pin on map (full intel shown in right panel) */}
        {selectedEntity?.type === 'region_dossier' && selectedEntity.extra && (
          <Marker
            longitude={selectedEntity.extra.lng}
            latitude={selectedEntity.extra.lat}
            anchor="bottom"
            style={{ zIndex: 10 }}
          >
            <div className="flex flex-col items-center pointer-events-none">
              {/* Pulsing ring */}
              <div className="w-8 h-8 rounded-full border-2 border-emerald-500 animate-ping absolute opacity-30" />
              {/* Pin dot */}
              <div className="w-4 h-4 rounded-full bg-emerald-500 border-2 border-emerald-300 shadow-[0_0_15px_rgba(16,185,129,0.6)]" />
              {/* Label */}
              <div className="mt-2 bg-black/80 border border-emerald-800 rounded px-2 py-1 text-[10px] font-mono text-emerald-400 tracking-widest whitespace-nowrap shadow-[0_0_10px_rgba(16,185,129,0.3)]">
                {regionDossierLoading ? 'COMPILING...' : '▶ INTEL TARGET'}
              </div>
            </div>
          </Marker>
        )}

        {/* SENTINEL-2 IMAGERY — fullscreen overlay modal */}
        {selectedEntity?.type === 'region_dossier' &&
          selectedEntity.extra &&
          regionDossier?.sentinel2 && (
            <RegionDossierPanel
              sentinel2={regionDossier.sentinel2}
              lat={selectedEntity.extra.lat}
              lng={selectedEntity.extra.lng}
              onClose={() => onEntityClick(null)}
            />
          )}

        {/* OPTIC INTERCEPT — fullscreen CCTV camera modal */}
        {selectedEntity?.type === 'cctv' &&
          (() => {
            const props = (selectedEntity.extra || {}) as Record<string, unknown>;
            const rawUrl = String(selectedEntity.media_url || props.media_url || '');
            const mt = String(props.media_type || (
              rawUrl.includes('.mp4') || rawUrl.includes('.webm') ? 'video' :
                rawUrl.includes('.m3u8') || rawUrl.includes('hls') ? 'hls' :
                  rawUrl.includes('.mjpg') || rawUrl.includes('.mjpeg') || rawUrl.includes('mjpg') ? 'mjpeg' : 'image'
            ));
            // Proxy external URLs through backend to bypass CORS
            const url = buildCctvProxyUrl(rawUrl);
            const isVideo = mt === 'video' || mt === 'hls';
            const cameraName = String(selectedEntity.name || props.name || 'UNKNOWN MOUNT').toUpperCase();
            const sourceAgency = String(props.source_agency || 'CCTV').toUpperCase();

            return (
              <CctvFullscreenModal
                url={url}
                rawUrl={rawUrl}
                mediaType={mt}
                isVideo={isVideo}
                cameraName={cameraName}
                sourceAgency={sourceAgency}
                cameraId={String(selectedEntity.id || '')}
                onClose={() => onEntityClick(null)}
              />
            );
          })()}

        {/* ── AI Intel Pin Detail popup ── */}
        {openPinDetailId && (
          <AIIntelPinDetail
            pinId={openPinDetailId}
            onClose={() => setOpenPinDetailId(null)}
            onDeleted={() => {
              setOpenPinDetailId(null);
              setAiIntelRefreshTick((t) => t + 1);
              onPinPlaced?.();
            }}
            onUpdated={() => setAiIntelRefreshTick((t) => t + 1)}
          />
        )}

        {/* ── Pin Placement Dialog (offset marker + connecting line) ── */}
        {pendingPin && (
          <Marker
            latitude={pendingPin.lat}
            longitude={pendingPin.lng}
            anchor="center"
            offset={[0, -120]}
            style={{ zIndex: 9990 }}
          >
            <div
              className="relative"
              onClick={(e) => e.stopPropagation()}
              onMouseDown={(e) => e.stopPropagation()}
              onKeyDown={(e) => {
                // Prevent global hotkeys (l/r/m/s/k/f/space) from firing while
                // typing in the pin dialog — the maplibre canvas is still in
                // the document and document-level listeners otherwise fire.
                e.stopPropagation();
                e.nativeEvent.stopImmediatePropagation();
              }}
              onKeyUp={(e) => {
                e.stopPropagation();
                e.nativeEvent.stopImmediatePropagation();
              }}
            >
              {/* Connecting line + dot at actual pin location */}
              <svg
                className="absolute pointer-events-none"
                style={{
                  left: '50%',
                  top: '50%',
                  width: 1,
                  height: 1,
                  overflow: 'visible',
                  zIndex: -1,
                }}
              >
                <line
                  x1={0}
                  y1={0}
                  x2={0}
                  y2={120}
                  stroke="#8b5cf6"
                  strokeWidth="1.5"
                  strokeDasharray="4,3"
                  className="opacity-80"
                />
                <circle cx={0} cy={120} r="4" fill="#8b5cf6" stroke="#0a0a14" strokeWidth="1.5" />
              </svg>

              {/* Arrow triangle pointing down to pin */}
              <div
                style={{
                  position: 'absolute',
                  bottom: '-6px',
                  left: '50%',
                  transform: 'translateX(-50%)',
                  width: 0,
                  height: 0,
                  borderLeft: '6px solid transparent',
                  borderRight: '6px solid transparent',
                  borderTop: '6px solid #8b5cf6',
                }}
              />

              {/* Dialog box */}
              <div
                className="bg-[#0a0a14] border-2 border-violet-500/60 p-3 font-mono"
                style={{ minWidth: 260, maxWidth: 300, transform: 'translateX(-50%)', marginLeft: '50%' }}
              >
                {/* Close button */}
                <button
                  onClick={() => { setPendingPin(null); setPinLabel(''); setPinNotes(''); }}
                  style={{
                    position: 'absolute',
                    top: 4,
                    right: 8,
                    background: 'transparent',
                    border: 'none',
                    cursor: 'pointer',
                    color: '#8b5cf6',
                    fontSize: 16,
                    fontWeight: 'bold',
                    lineHeight: 1,
                    opacity: 0.7,
                    zIndex: 20,
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.opacity = '1')}
                  onMouseLeave={(e) => (e.currentTarget.style.opacity = '0.7')}
                >
                  &times;
                </button>

                <div className="text-[12px] text-violet-400 tracking-widest mb-2 font-bold">
                  {pendingPin.entity ? 'PIN TO ENTITY' : 'PIN TO LOCATION'}
                </div>
                {pendingPin.entity && (
                  <div className="text-[10px] text-cyan-400 mb-2 px-2 py-1 bg-cyan-500/10 border border-cyan-500/20">
                    Tracking: {pendingPin.entity.entity_label || pendingPin.entity.entity_id}
                    <span className="text-cyan-600 ml-1">({pendingPin.entity.entity_type})</span>
                  </div>
                )}
                {/* Category selector */}
                <select
                  title="Pin category"
                  aria-label="Pin category"
                  value={pinCategory}
                  onChange={(e) => setPinCategory(e.target.value as PinCategory)}
                  className="w-full px-2 py-1.5 text-[11px] font-mono bg-black/50 border border-violet-500/30 text-white focus:border-violet-500/60 outline-none mb-1.5 border-l-4"
                  style={{ borderLeftColor: PIN_CATEGORY_COLORS[pinCategory] }}
                >
                  {(Object.keys(PIN_CATEGORY_LABELS) as PinCategory[]).map((cat) => (
                    <option key={cat} value={cat} className="bg-[#0a0a14]">
                      {PIN_CATEGORY_LABELS[cat]}
                    </option>
                  ))}
                </select>
                <input
                  ref={pinLabelInputRef}
                  type="text"
                  value={pinLabel}
                  onChange={(e) => setPinLabel(e.target.value)}
                  placeholder="Label..."
                  autoFocus
                  className="w-full px-2 py-1.5 text-[12px] font-mono bg-black/50 border border-violet-500/30 text-white placeholder:text-gray-600 focus:border-violet-500/60 outline-none mb-1.5"
                  onKeyDown={(e) => {
                    e.stopPropagation();
                    e.nativeEvent.stopImmediatePropagation();
                    if (e.key === 'Enter' && pinLabel.trim()) {
                      e.preventDefault();
                      handleSavePin();
                    }
                    if (e.key === 'Escape') {
                      setPendingPin(null); setPinLabel(''); setPinNotes(''); setPinCategory('custom');
                    }
                  }}
                />
                <textarea
                  value={pinNotes}
                  onChange={(e) => setPinNotes(e.target.value)}
                  placeholder="Notes (optional)..."
                  rows={2}
                  className="w-full px-2 py-1 text-[11px] font-mono bg-black/50 border border-violet-500/20 text-gray-300 placeholder:text-gray-600 focus:border-violet-500/40 outline-none resize-none mb-2"
                  onMouseDown={(e) => {
                    // Force-focus the textarea on click — the maplibre canvas
                    // otherwise steals focus back and typing gets swallowed.
                    e.stopPropagation();
                    (e.currentTarget as HTMLTextAreaElement).focus();
                  }}
                  onClick={(e) => {
                    e.stopPropagation();
                    (e.currentTarget as HTMLTextAreaElement).focus();
                  }}
                  onKeyDown={(e) => {
                    e.stopPropagation();
                    e.nativeEvent.stopImmediatePropagation();
                    if (e.key === 'Escape') {
                      setPendingPin(null); setPinLabel(''); setPinNotes(''); setPinCategory('custom');
                    }
                  }}
                />
                <div className="text-[10px] text-gray-500 mb-2">
                  {pendingPin.lat.toFixed(5)}, {pendingPin.lng.toFixed(5)}
                </div>
                <div className="flex gap-1.5">
                  <button
                    type="button"
                    disabled={!pinLabel.trim() || pinSaving}
                    onClick={handleSavePin}
                    className="flex-1 py-1.5 text-[11px] font-mono tracking-wider bg-violet-600/30 border border-violet-500/50 text-violet-300 hover:bg-violet-600/50 transition-colors disabled:opacity-40"
                  >
                    {pinSaving ? '...' : 'CONFIRM'}
                  </button>
                  <button
                    type="button"
                    onClick={() => { setPendingPin(null); setPinLabel(''); setPinNotes(''); }}
                    className="px-3 py-1.5 text-[11px] font-mono tracking-wider border border-gray-600/40 text-gray-400 hover:text-gray-300 transition-colors"
                  >
                    CANCEL
                  </button>
                </div>
              </div>
            </div>
          </Marker>
        )}

    </>
  );
}
