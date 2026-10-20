"""Curated historical early-warning cases for GT backtesting.

Each positive case bundles pre-crisis costly-signal snippets drawn from documented
precursors (financial, unrest, conflict). Negative cases are cheap-talk controls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

CaseKind = Literal["positive", "negative"]


@dataclass(frozen=True)
class BacktestFeed:
    text: str
    source: str = "backtest"
    domain: str = "financial"
    days_before_event: int = 30


@dataclass(frozen=True)
class HistoricalCase:
    """Single labeled backtest scenario."""

    case_id: str
    name: str
    region: str
    domain: str
    kind: CaseKind
    event_date: str
    description: str
    feeds: tuple[BacktestFeed, ...] = field(default_factory=tuple)
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_feed_dicts(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for idx, feed in enumerate(self.feeds):
            items.append(
                {
                    "id": f"{self.case_id}-{idx}",
                    "text": feed.text,
                    "source": feed.source,
                    "region": self.region,
                    "domain": feed.domain or self.domain,
                    "published": feed.days_before_event,
                }
            )
        return items


def _variant_case(case: HistoricalCase, suffix: str, feeds: tuple[BacktestFeed, ...]) -> HistoricalCase:
    return HistoricalCase(
        case_id=f"{case.case_id}__{suffix}",
        name=f"{case.name} ({suffix})",
        region=case.region,
        domain=case.domain,
        kind=case.kind,
        event_date=case.event_date,
        description=case.description,
        feeds=feeds,
        tags=case.tags + (f"variant:{suffix}",),
    )


def expanded_historical_cases() -> tuple[HistoricalCase, ...]:
    """Base suite plus paraphrase variants for statistical confidence."""
    base = list(default_historical_cases())
    extras: list[HistoricalCase] = []

    variant_feeds: dict[str, tuple[tuple[BacktestFeed, ...], ...]] = {
        "fin_2008_us": (
            (
                BacktestFeed(
                    "Small businesses turn to payroll loan products as credit lines freeze.",
                    domain="financial",
                    days_before_event=100,
                ),
                BacktestFeed(
                    "FDIC monitors liquidity crunch; interbank spreads widen sharply.",
                    domain="financial",
                    days_before_event=60,
                ),
            ),
            (
                BacktestFeed(
                    "Merchant cash advance volumes spike; payroll loan demand at record highs.",
                    domain="financial",
                    days_before_event=80,
                ),
                BacktestFeed(
                    "Money market funds see inflows as deposit flight from regional banks continues.",
                    domain="financial",
                    days_before_event=40,
                ),
            ),
        ),
        "fin_2020_supply": (
            (
                BacktestFeed(
                    "Electronics firms report shipping delay and port congestion across Pearl River Delta.",
                    domain="financial",
                    days_before_event=45,
                ),
                BacktestFeed(
                    "Supply chain delay widens; logistics backlog hits automotive suppliers.",
                    domain="financial",
                    days_before_event=20,
                ),
            ),
            (
                BacktestFeed(
                    "Container shortage fuels shipping delay; supply chain delay indices jump.",
                    domain="financial",
                    days_before_event=35,
                ),
                BacktestFeed(
                    "Electronics assemblers warn of logistics backlog as port congestion spreads.",
                    domain="financial",
                    days_before_event=20,
                ),
                BacktestFeed(
                    "Automotive suppliers flag supply chain delay after factory shutdowns in Hubei.",
                    domain="financial",
                    days_before_event=10,
                ),
            ),
        ),
        "fin_2022_sanctions": (
            (
                BacktestFeed(
                    "Treasury drafts new sanctions escalation package on energy and finance sectors.",
                    domain="financial",
                    days_before_event=30,
                ),
                BacktestFeed(
                    "Capital flight accelerates; elite relocation flights depart Moscow airports.",
                    domain="financial",
                    days_before_event=14,
                ),
            ),
        ),
        "unrest_arab_spring_egypt": (
            (
                BacktestFeed(
                    "Cairo activists schedule mass rally; protest mobilization leaflets distributed.",
                    domain="unrest",
                    days_before_event=18,
                ),
                BacktestFeed(
                    "Labor federations call general strike; strike posters cover downtown.",
                    domain="unrest",
                    days_before_event=8,
                ),
            ),
        ),
        "conflict_2022_ukraine": (
            (
                BacktestFeed(
                    "Convoy of armored vehicles confirms troop movement near Sumy Oblast.",
                    source="t.me/war_monitor",
                    domain="conflict",
                    days_before_event=20,
                ),
                BacktestFeed(
                    "GNSS interference warnings follow GPS jamming spike along Belarus border.",
                    source="t.me/osintdefender",
                    domain="conflict",
                    days_before_event=10,
                ),
            ),
            (
                BacktestFeed(
                    "Military mobilization notices circulate; troop buildup confirmed by satellite firms.",
                    domain="conflict",
                    days_before_event=12,
                ),
            ),
        ),
        "neg_weather_us": (
            (
                BacktestFeed("Autumn foliage peaks in Vermont; pleasant hiking weather continues."),
                BacktestFeed("County fair announces pie contest and livestock exhibitions."),
            ),
            (
                BacktestFeed("Meteorologists predict mild hurricane season remainder for Gulf Coast."),
            ),
        ),
        "neg_sports_uk": (
            (
                BacktestFeed("Rugby Six Nations standings update after weekend fixtures."),
                BacktestFeed("Local marathon registration opens for charity runners."),
            ),
        ),
        "neg_tech_global": (
            (
                BacktestFeed("Chipmaker announces efficiency gains in next-generation processor."),
                BacktestFeed("Cloud provider opens new green datacenter in Nordic region."),
            ),
        ),
    }

    for case in base:
        variants = variant_feeds.get(case.case_id, ())
        for idx, feeds in enumerate(variants):
            extras.append(_variant_case(case, f"v{idx+1}", feeds))

    # Additional cheap-talk controls to widen negative sample
    cheap_talk_regions = (
        ("australia", "Museum opens contemporary art exhibit to strong attendance."),
        ("spain", "Tomato harvest festival scheduled; regional trains add weekend service."),
        ("south_korea", "K-pop group announces world tour dates for autumn."),
        ("mexico", "Coastal cleanup volunteers restore beach habitats before holiday season."),
        ("sweden", "City council approves bike lane expansion along waterfront."),
        ("norway", "Salmon exports remain stable; fishing fleets report normal catch volumes."),
        ("italy", "Truffle festival returns; restaurants publish seasonal tasting menus."),
        ("poland", "University researchers release open-source astronomy software."),
        ("thailand", "Monsoon rains ease; rice planting proceeds on normal schedule."),
        ("vietnam", "Electronics assembly plants report steady export order books."),
        ("south_africa", "Wildlife reserve reports rising ecotourism bookings."),
        ("argentina", "Wine harvest festival opens; export cooperatives meet volume targets."),
        ("netherlands", "Cycling championship draws international teams to canal district."),
        ("belgium", "Chocolate exporters report stable holiday shipment schedules."),
        ("portugal", "Offshore wind auction attracts multiple renewable bidders."),
        ("greece", "Island ferry operators add routes ahead of summer travel season."),
        ("turkey", "Cotton harvest forecast unchanged; textile orders stable."),
        ("indonesia", "Volcano monitoring reports routine activity; tourism continues."),
        ("philippines", "Coconut processors report normal logistics to export markets."),
        ("malaysia", "Palm oil shipments on schedule; port throughput normal."),
        ("new_zealand", "Sheep shearing competition draws rural crowds."),
        ("ireland", "Tech conference highlights open-source database tooling."),
        ("finland", "Sauna culture festival celebrates heritage with local artisans."),
        ("denmark", "Wind turbine maintenance contracts renewed on prior terms."),
        ("austria", "Ski resorts prepare slopes after early snowfall."),
        ("switzerland", "Watchmakers unveil mechanical movement prototypes at trade fair."),
        ("czech_republic", "Glassmakers export decorative pieces ahead of holiday season."),
        ("romania", "Carpathian hiking trails reopen after spring maintenance."),
        ("hungary", "Thermal bath tourism bookings rise for winter wellness season."),
        ("peru", "Coffee cooperatives report stable harvest and export schedules."),
        ("colombia", "Flower exporters prepare Valentine's shipments on normal cadence."),
        ("morocco", "Citrus harvest meets forecasts; agricultural credit unchanged."),
        ("kenya", "Tea auction volumes steady; freight routes operate normally."),
        ("nigeria", "Nollywood studio announces family comedy release dates."),
        ("ethiopia", "Coffee ceremony festival highlights regional bean varieties."),
        ("saudi_arabia", "Desert conservation project plants drought-resistant shrubs."),
        ("uae", "Airport duty-free operators expand luxury retail concourse."),
        ("qatar", "Stadium operators prepare hospitality packages for sporting events."),
        ("singapore", "Port authority reports container throughput on seasonal trend."),
        ("hong_kong", "Art auction previews draw collectors to harborfront gallery."),
        ("chile", "Vineyard tours report strong bookings ahead of harvest festival weekend."),
        ("uruguay", "Beef exporters maintain steady shipment schedules to European buyers."),
        ("iceland", "Geothermal spa resorts report normal winter visitor volumes."),
        ("luxembourg", "Fund administrators publish routine quarterly disclosure filings."),
        ("slovakia", "Mountain lodges prepare ski season openings after early snowfall."),
        ("croatia", "Adriatic ferry operators add summer routes on prior timetable."),
        ("bulgaria", "Rose oil cooperatives report stable export volumes to fragrance buyers."),
        ("serbia", "Danube barge traffic proceeds on normal freight schedules."),
        ("latvia", "Timber mills export lumber on unchanged contract terms."),
        ("lithuania", "Baltic wind farms complete scheduled turbine maintenance rotations."),
        ("estonia", "Digital residency applications processed at routine monthly pace."),
        ("panama", "Canal transit volumes remain on seasonal trend; shipping fees unchanged."),
    )
    for idx, (region, text) in enumerate(cheap_talk_regions):
        extras.append(
            HistoricalCase(
                case_id=f"neg_extra_{idx:02d}",
                name=f"Benign regional news ({region})",
                region=region,
                domain="financial",
                kind="negative",
                event_date="2020-01-01",
                description="Expanded cheap-talk control.",
                feeds=(BacktestFeed(text),),
                tags=("control", "expanded"),
            )
        )

    return tuple(base + extras)


def default_historical_cases() -> tuple[HistoricalCase, ...]:
    """Benchmark suite — expand as new validated precursors are added."""
    return (
        # ── Financial distress ─────────────────────────────────────────────
        HistoricalCase(
            case_id="fin_2008_us",
            name="2008 US financial crisis",
            region="united_states",
            domain="financial",
            kind="positive",
            event_date="2008-09-15",
            description="Payroll-loan distress, liquidity crunch, and deposit flight precursors.",
            tags=("2008", "financial", "lehman"),
            feeds=(
                BacktestFeed(
                    "Franchise operators increasingly rely on payroll loan facilities as working capital tightens.",
                    domain="financial",
                    days_before_event=120,
                ),
                BacktestFeed(
                    "Regional banks report liquidity crunch; CFOs warn of merchant cash advance reliance.",
                    domain="financial",
                    days_before_event=90,
                ),
                BacktestFeed(
                    "Deposit flight accelerates at mid-size lenders; analysts flag bank run risk.",
                    domain="financial",
                    days_before_event=45,
                ),
            ),
        ),
        HistoricalCase(
            case_id="fin_2020_supply",
            name="COVID supply-chain shock",
            region="china",
            domain="financial",
            kind="positive",
            event_date="2020-02-01",
            description="Port congestion and logistics backlog ahead of global supply shock.",
            tags=("covid", "supply_chain", "financial"),
            feeds=(
                BacktestFeed(
                    "Major port congestion reported; shipping delay spreads to electronics suppliers.",
                    domain="financial",
                    days_before_event=60,
                ),
                BacktestFeed(
                    "Automakers warn of supply chain delay and logistics backlog across Wuhan corridor.",
                    domain="financial",
                    days_before_event=30,
                ),
                BacktestFeed(
                    "Factory restarts slip as supply delay and port congestion persist into Q1.",
                    domain="financial",
                    days_before_event=14,
                ),
            ),
        ),
        HistoricalCase(
            case_id="fin_2022_sanctions",
            name="Russia sanctions escalation",
            region="russia",
            domain="financial",
            kind="positive",
            event_date="2022-02-24",
            description="Sanctions escalation and capital flight ahead of invasion.",
            tags=("sanctions", "ukraine", "financial"),
            feeds=(
                BacktestFeed(
                    "Western allies prepare new sanctions escalation on major Russian banks.",
                    domain="financial",
                    days_before_event=45,
                ),
                BacktestFeed(
                    "Oligarch jet movements suggest elite relocation and capital flight from Moscow.",
                    domain="financial",
                    days_before_event=21,
                ),
                BacktestFeed(
                    "Central bank intervenes as new sanctions tighten export controls on finance sector.",
                    domain="financial",
                    days_before_event=10,
                ),
            ),
        ),
        # ── Civil unrest ─────────────────────────────────────────────────
        HistoricalCase(
            case_id="unrest_arab_spring_tunisia",
            name="Arab Spring — Tunisia",
            region="tunisia",
            domain="unrest",
            kind="positive",
            event_date="2010-12-17",
            description="Protest mobilization and strike waves before Jasmine Revolution.",
            tags=("arab_spring", "unrest"),
            feeds=(
                BacktestFeed(
                    "Student groups announce protest mobilization after vendor self-immolation.",
                    domain="unrest",
                    days_before_event=14,
                ),
                BacktestFeed(
                    "Mass rally planned in Tunis; general strike called by labor unions.",
                    domain="unrest",
                    days_before_event=7,
                ),
            ),
        ),
        HistoricalCase(
            case_id="unrest_arab_spring_egypt",
            name="Arab Spring — Egypt",
            region="egypt",
            domain="unrest",
            kind="positive",
            event_date="2011-01-25",
            description="Mobilization spikes and security reshuffles before Tahrir.",
            tags=("arab_spring", "unrest"),
            feeds=(
                BacktestFeed(
                    "Opposition calls protest mobilization in Cairo; strike notices circulate online.",
                    domain="unrest",
                    days_before_event=21,
                ),
                BacktestFeed(
                    "Reports of political purge within interior ministry security apparatus reshuffle.",
                    domain="unrest",
                    days_before_event=10,
                ),
                BacktestFeed(
                    "Mass rally and strike coordination spreads; rally posters appear in Alexandria.",
                    domain="unrest",
                    days_before_event=5,
                ),
            ),
        ),
        HistoricalCase(
            case_id="unrest_2019_chile",
            name="Chile 2019 metro protests",
            region="chile",
            domain="unrest",
            kind="positive",
            event_date="2019-10-18",
            description="Transit fare protests escalate to general strike.",
            tags=("unrest", "latam"),
            feeds=(
                BacktestFeed(
                    "Students organize mass rally after metro fare hike; protest mobilization trending.",
                    domain="unrest",
                    days_before_event=10,
                ),
                BacktestFeed(
                    "Unions announce general strike; rally and strike hashtags spike nationwide.",
                    domain="unrest",
                    days_before_event=3,
                ),
            ),
        ),
        # ── Conflict / war ───────────────────────────────────────────────
        HistoricalCase(
            case_id="conflict_2022_ukraine",
            name="2022 Ukraine invasion buildup",
            region="ukraine",
            domain="conflict",
            kind="positive",
            event_date="2022-02-24",
            description="Troop movement and GPS jamming precursors on northern border.",
            tags=("ukraine", "conflict"),
            feeds=(
                BacktestFeed(
                    "OSINT reports troop movement and armored convoy near Belarus border.",
                    source="t.me/war_monitor",
                    domain="conflict",
                    days_before_event=30,
                ),
                BacktestFeed(
                    "GPS jamming spike reported along northern corridor; GNSS interference warnings issued.",
                    source="t.me/osintdefender",
                    domain="conflict",
                    days_before_event=14,
                ),
                BacktestFeed(
                    "Satellite imagery shows troop buildup; military mobilization near Kharkiv axis.",
                    domain="conflict",
                    days_before_event=7,
                ),
            ),
        ),
        HistoricalCase(
            case_id="conflict_2023_gaza",
            name="2023 Gaza conflict escalation",
            region="israel",
            domain="conflict",
            kind="positive",
            event_date="2023-10-07",
            description="Ceasefire breakdown and troop movement signals.",
            tags=("gaza", "conflict"),
            feeds=(
                BacktestFeed(
                    "Border units report troop movement near Gaza envelope; ceasefire broken overnight.",
                    domain="conflict",
                    days_before_event=14,
                ),
                BacktestFeed(
                    "Truce end announced; armored convoy repositioning reported by local observers.",
                    domain="conflict",
                    days_before_event=5,
                ),
            ),
        ),
        HistoricalCase(
            case_id="conflict_2020_nagorno",
            name="2020 Nagorno-Karabakh renewal",
            region="armenia",
            domain="conflict",
            kind="positive",
            event_date="2020-09-27",
            description="Artillery and troop buildup precursors.",
            tags=("caucasus", "conflict"),
            feeds=(
                BacktestFeed(
                    "Drone strikes reported on line of contact; troop movement on Armenian-Azeri border.",
                    domain="conflict",
                    days_before_event=21,
                ),
                BacktestFeed(
                    "GPS jamming spike reported in conflict zone; military mobilization notices leaked.",
                    domain="conflict",
                    days_before_event=7,
                ),
            ),
        ),
        # ── Recent financial / corporate distress pattern ────────────────
        HistoricalCase(
            case_id="fin_2023_banking",
            name="2023 regional banking stress",
            region="united_states",
            domain="financial",
            kind="positive",
            event_date="2023-03-10",
            description="Deposit flight and liquidity stress (SVB precursor pattern).",
            tags=("svb", "financial", "2023"),
            feeds=(
                BacktestFeed(
                    "Tech lenders face deposit flight; VC portfolio companies move payroll to money market funds.",
                    domain="financial",
                    days_before_event=21,
                ),
                BacktestFeed(
                    "Analysts warn liquidity crunch at regional banks holding long-duration bonds.",
                    domain="financial",
                    days_before_event=7,
                ),
            ),
        ),
        # ── Negative controls (cheap talk / benign) ─────────────────────
        HistoricalCase(
            case_id="neg_weather_us",
            name="Benign weather coverage",
            region="united_states",
            domain="financial",
            kind="negative",
            event_date="2019-06-01",
            description="No costly signals — should remain near baseline.",
            tags=("control",),
            feeds=(
                BacktestFeed("Sunny weekend expected across the Midwest with mild temperatures."),
                BacktestFeed("Local festival draws crowds; farmers market expands summer hours."),
            ),
        ),
        HistoricalCase(
            case_id="neg_sports_uk",
            name="Benign sports coverage",
            region="uk",
            domain="unrest",
            kind="negative",
            event_date="2018-07-01",
            description="Sports chatter without mobilization costly signals.",
            tags=("control",),
            feeds=(
                BacktestFeed("Premier league season review: top scorers and transfer rumors."),
                BacktestFeed("Cricket test match ends early due to rain delay at Lord's."),
            ),
        ),
        HistoricalCase(
            case_id="neg_tech_global",
            name="Benign tech product launch",
            region="global",
            domain="financial",
            kind="negative",
            event_date="2021-09-01",
            description="Corporate product news without distress markers.",
            tags=("control",),
            feeds=(
                BacktestFeed("Smartphone maker unveils new camera features at annual keynote."),
                BacktestFeed("Quarterly earnings beat expectations; dividend unchanged."),
            ),
        ),
        HistoricalCase(
            case_id="neg_tourism_france",
            name="Benign tourism recovery",
            region="france",
            domain="unrest",
            kind="negative",
            event_date="2022-08-01",
            description="Travel sector recovery without unrest signals.",
            tags=("control",),
            feeds=(
                BacktestFeed("Paris hotels report record summer bookings as tourism rebounds."),
                BacktestFeed("Airline adds routes to Nice and Marseille for holiday travelers."),
            ),
        ),
        HistoricalCase(
            case_id="neg_science_japan",
            name="Benign science news",
            region="japan",
            domain="conflict",
            kind="negative",
            event_date="2020-11-01",
            description="Research coverage without conflict markers.",
            tags=("control",),
            feeds=(
                BacktestFeed("Astronomy team publishes comet observations from Mount Fuji observatory."),
                BacktestFeed("Robotics lab demonstrates warehouse automation prototype."),
            ),
        ),
        HistoricalCase(
            case_id="neg_agriculture_brazil",
            name="Benign agriculture report",
            region="brazil",
            domain="financial",
            kind="negative",
            event_date="2017-03-01",
            description="Commodity harvest update without supply distress.",
            tags=("control",),
            feeds=(
                BacktestFeed("Soybean harvest forecast revised upward; export volumes steady."),
                BacktestFeed("Coffee cooperative reports normal shipping schedules to European buyers."),
            ),
        ),
        HistoricalCase(
            case_id="neg_culture_india",
            name="Benign culture coverage",
            region="india",
            domain="unrest",
            kind="negative",
            event_date="2016-11-01",
            description="Festival coverage without mobilization.",
            tags=("control",),
            feeds=(
                BacktestFeed("Diwali celebrations begin; cities decorate markets with lights."),
                BacktestFeed("Film festival opens in Mumbai with premiere screenings."),
            ),
        ),
        HistoricalCase(
            case_id="neg_infrastructure_canada",
            name="Benign infrastructure ribbon-cutting",
            region="canada",
            domain="financial",
            kind="negative",
            event_date="2015-05-01",
            description="Municipal news without financial stress.",
            tags=("control",),
            feeds=(
                BacktestFeed("New light-rail segment opens on schedule; commute times improve."),
                BacktestFeed("Municipal bond issuance funds library renovation at prior rates."),
            ),
        ),
    )