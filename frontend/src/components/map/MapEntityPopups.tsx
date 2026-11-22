'use client';

import React from 'react';
import { Marker, Popup } from 'react-map-gl/maplibre';
import { PIN_CATEGORY_LABELS, PIN_CATEGORY_COLORS, type PinCategory } from '@/types/aiIntel';
import { MapSelectedEntityPopups } from './MapSelectedEntityPopups';

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
    image,
    imo,
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
    white,
    whitespace,
    wider,
    widest,
    wiki,
    wikiUrl,
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
        <MapSelectedEntityPopups p={p} />

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
                  style={{ borderLeftColor: PIN_CATEGORY_COLORS[pinCategory as PinCategory] }}
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
