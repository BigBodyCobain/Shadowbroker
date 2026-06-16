"""Game-theoretic early warning analytics with Bayesian updating and contagion graph."""

from __future__ import annotations

import logging
import re
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, DefaultDict

import networkx as nx
import numpy as np

from analytics.settings import GTAnalyticsSettings, get_gt_settings

logger = logging.getLogger(__name__)

DomainName = str  # financial | unrest | conflict

_DOMAINS: tuple[DomainName, ...] = ("financial", "unrest", "conflict")

_DEFAULT_LIKELIHOODS: dict[DomainName, dict[str, float]] = {
    "financial": {"distress": 0.75, "normal": 0.25},
    "unrest": {"distress": 0.82, "normal": 0.22},
    "conflict": {"distress": 0.78, "normal": 0.18},
}

_DEFAULT_SIGNAL_WEIGHTS: dict[str, float] = {
    "payroll_loan": 3.0,
    "supply_delay": 2.2,
    "elite_relocation": 2.8,
    "purge": 3.5,
    "protest_mobilize": 2.5,
    "gps_jamming": 2.7,
    "troop_movement": 3.0,
    "bank_run": 3.2,
    "sanctions_escalation": 2.4,
    "ceasefire_break": 2.6,
}

# Costly-signal regex patterns (cheap talk filtered by absence of match).
_SIGNAL_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "payroll_loan": [
        re.compile(r"payroll\s+loan", re.I),
        re.compile(r"merchant\s+cash\s+advance", re.I),
        re.compile(r"working\s+capital\s+loan", re.I),
    ],
    "supply_delay": [
        re.compile(r"supply\s+(chain\s+)?delay", re.I),
        re.compile(r"shipping\s+delay", re.I),
        re.compile(r"logistics\s+backlog", re.I),
        re.compile(r"port\s+congestion", re.I),
    ],
    "elite_relocation": [
        re.compile(r"elite\s+(asset\s+)?relocation", re.I),
        re.compile(r"oligarch\s+jet", re.I),
        re.compile(r"private\s+jet\s+exodus", re.I),
        re.compile(r"capital\s+flight", re.I),
    ],
    "purge": [
        re.compile(r"\bpurge\b", re.I),
        re.compile(r"political\s+purge", re.I),
        re.compile(r"security\s+apparatus\s+reshuffle", re.I),
    ],
    "protest_mobilize": [
        re.compile(r"protest\s+mobil", re.I),
        re.compile(r"mass\s+rally", re.I),
        re.compile(r"general\s+strike", re.I),
        re.compile(r"\bstrike\b", re.I),
        re.compile(r"\brally\b", re.I),
    ],
    "gps_jamming": [
        re.compile(r"gps\s+jam", re.I),
        re.compile(r"gnss\s+interference", re.I),
        re.compile(r"spoofing\s+spike", re.I),
    ],
    "troop_movement": [
        re.compile(r"troop\s+movement", re.I),
        re.compile(r"military\s+mobil", re.I),
        re.compile(r"armored\s+convoy", re.I),
        re.compile(r"troop\s+buildup", re.I),
    ],
    "bank_run": [
        re.compile(r"bank\s+run", re.I),
        re.compile(r"deposit\s+flight", re.I),
        re.compile(r"liquidity\s+crunch", re.I),
    ],
    "sanctions_escalation": [
        re.compile(r"sanctions?\s+escalat", re.I),
        re.compile(r"new\s+sanctions?", re.I),
        re.compile(r"export\s+controls?\s+tighten", re.I),
    ],
    "ceasefire_break": [
        re.compile(r"ceasefire\s+(broken|violated|collapse)", re.I),
        re.compile(r"truce\s+end", re.I),
    ],
}

_SIGNAL_DOMAINS: dict[str, DomainName] = {
    "payroll_loan": "financial",
    "supply_delay": "financial",
    "bank_run": "financial",
    "sanctions_escalation": "financial",
    "protest_mobilize": "unrest",
    "purge": "unrest",
    "elite_relocation": "financial",
    "gps_jamming": "conflict",
    "troop_movement": "conflict",
    "ceasefire_break": "conflict",
}


@dataclass
class RegionState:
    """Per-region Bayesian beliefs and metadata."""

    priors: dict[DomainName, float] = field(default_factory=lambda: defaultdict(float))
    coords: list[float] | None = None
    signal_volume: DefaultDict[str, float] = field(default_factory=lambda: defaultdict(float))
    update_count: int = 0


@dataclass
class HistoryEntry:
    timestamp: str
    domain: DomainName
    signals: dict[str, float]
    strength: float
    prior: float
    posterior: float
    source: str
    deviation_score: float


class GT_EarlyWarning:
    """
    Game-Theoretic Early Warning System with Bayesian updating.

    Tracks distress probabilities per region/domain, classifies costly signals vs
    cheap talk, and propagates risk through an entity interaction graph.
    """

    def __init__(self, settings: GTAnalyticsSettings | None = None) -> None:
        self.settings = settings or get_gt_settings()
        self.G: nx.Graph = nx.Graph()
        self._regions: dict[str, RegionState] = {}
        self._history: dict[str, list[HistoryEntry]] = defaultdict(list)
        self._seen_item_ids: set[str] = set()
        self._lock = threading.RLock()

        self.likelihoods = dict(_DEFAULT_LIKELIHOODS)
        self.signal_weights = dict(_DEFAULT_SIGNAL_WEIGHTS)
        self.signal_weights.update(self.settings.signal_weight_overrides)

        self._base_prior = float(self.settings.base_prior)

    def _utcnow(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _region_state(self, region: str) -> RegionState:
        key = str(region or "global").strip().lower() or "global"
        if key not in self._regions:
            state = RegionState()
            for domain in _DOMAINS:
                state.priors[domain] = self._base_prior
            self._regions[key] = state
        return self._regions[key]

    def get_prior(self, region: str, domain: DomainName) -> float:
        with self._lock:
            return float(self._region_state(region).priors.get(domain, self._base_prior))

    def set_prior(self, region: str, domain: DomainName, value: float) -> None:
        with self._lock:
            state = self._region_state(region)
            state.priors[domain] = float(
                np.clip(value, self.settings.min_prob, self.settings.max_prob)
            )

    def composite_risk(self, region: str) -> float:
        """Weighted composite across domains (conflict weighted highest)."""
        weights = {"financial": 0.25, "unrest": 0.35, "conflict": 0.40}
        with self._lock:
            state = self._region_state(region)
            total = 0.0
            weight_sum = 0.0
            for domain, weight in weights.items():
                total += float(state.priors.get(domain, self._base_prior)) * weight
                weight_sum += weight
            return float(total / weight_sum) if weight_sum else self._base_prior

    def classify_signals(self, text: str, source: str = "") -> dict[str, float]:
        """Return weighted costly-signal strengths detected in text."""
        text_lower = (text or "").lower()
        signals: dict[str, float] = {}

        for signal_name, patterns in _SIGNAL_PATTERNS.items():
            weight = float(self.signal_weights.get(signal_name, 1.0))
            if any(pattern.search(text_lower) for pattern in patterns):
                signals[signal_name] = weight

        rally_strike_count = text_lower.count("rally") + text_lower.count("strike")
        if rally_strike_count > 3:
            signals["protest_mobilize"] = signals.get("protest_mobilize", 0.0) + 1.5

        # Source credibility nudge (Telegram OSINT channels treated as moderate-cost signals).
        if source and "t.me/" in source.lower() and signals:
            for key in list(signals):
                signals[key] = round(signals[key] * 1.05, 3)

        return signals

    def _deviation_score(self, region: str, domain: DomainName, strength: float) -> float:
        """Deviation from rolling regional norm — herding/coordination detector input."""
        with self._lock:
            state = self._region_state(region)
            baseline = max(state.signal_volume[domain], 1.0)
            state.signal_volume[domain] += strength
            state.update_count += 1
            return float(strength / baseline)

    def bayesian_update(
        self,
        region: str,
        domain: DomainName,
        evidence_strength: float = 1.0,
    ) -> float:
        """
        Bayesian update: P(distress|evidence) from likelihood table and prior.

        evidence_strength scales how far belief moves toward the likelihood posterior.
        """
        domain = domain if domain in _DOMAINS else "financial"
        lik = self.likelihoods.get(domain, self.likelihoods["financial"])

        with self._lock:
            state = self._region_state(region)
            prior = float(state.priors.get(domain, self._base_prior))

            p_e_given_d = lik["distress"]
            p_e_given_not_d = lik["normal"]
            p_e = (p_e_given_d * prior) + (p_e_given_not_d * (1.0 - prior))

            if p_e <= 0:
                posterior = prior
            else:
                posterior = (p_e_given_d * prior) / p_e

            scaled = prior + (posterior - prior) * float(evidence_strength)
            clipped = float(np.clip(scaled, self.settings.min_prob, self.settings.max_prob))
            state.priors[domain] = clipped
            return clipped

    def _update_graph(
        self,
        region: str,
        entities: list[str],
        strength: float,
        coords: list[float] | None,
    ) -> None:
        region_key = str(region or "global").strip().lower() or "global"
        self.G.add_node(region_key, node_type="region", region=region_key)
        if coords and len(coords) >= 2:
            self.G.nodes[region_key]["coords"] = coords

        for entity in entities:
            entity_key = str(entity).strip()
            if not entity_key:
                continue
            self.G.add_node(entity_key, node_type="entity", region=region_key)
            self.G.add_edge(
                region_key,
                entity_key,
                weight=float(strength),
                timestamp=self._utcnow(),
            )

        for i, e1 in enumerate(entities):
            for e2 in entities[i + 1 :]:
                k1, k2 = str(e1).strip(), str(e2).strip()
                if not k1 or not k2:
                    continue
                self.G.add_edge(
                    k1,
                    k2,
                    weight=float(strength),
                    timestamp=self._utcnow(),
                )

    def process_feed_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Process one normalized feed item and update beliefs + contagion graph."""
        region = str(item.get("region") or item.get("geotag") or "global").strip().lower()
        text = str(item.get("text") or "")
        source = str(item.get("source") or "unknown")
        explicit_domain = str(item.get("domain") or "").strip().lower()
        entities = list(item.get("entities") or [])
        coords = item.get("coords")
        item_id = str(item.get("id") or f"{source}|{hash(text)}")

        if self.settings.watched_channels:
            channel = ""
            for entity in entities:
                if str(entity).startswith("channel:"):
                    channel = str(entity).split(":", 1)[-1].lower()
                    break
            if channel and channel not in {c.lower() for c in self.settings.watched_channels}:
                return {
                    "region": region,
                    "skipped": True,
                    "reason": "channel_not_watched",
                    "risk_score": self.composite_risk(region),
                    "signals": {},
                }

        with self._lock:
            if item_id and item_id in self._seen_item_ids:
                return {
                    "region": region,
                    "skipped": True,
                    "reason": "duplicate",
                    "risk_score": self.composite_risk(region),
                    "signals": {},
                }
            if item_id:
                self._seen_item_ids.add(item_id)

        signals = self.classify_signals(text, source)
        total_strength = float(sum(signals.values()))

        if total_strength <= 0:
            return {
                "region": region,
                "risk_score": self.composite_risk(region),
                "signals": {},
                "contagion_potential": self._get_contagion_score(region),
            }

        domains_touched: set[DomainName] = set()
        if explicit_domain in _DOMAINS:
            domains_touched.add(explicit_domain)
        for signal_name in signals:
            domains_touched.add(_SIGNAL_DOMAINS.get(signal_name, explicit_domain or "financial"))
        if not domains_touched:
            domains_touched.add("financial")

        evidence_strength = min(
            total_strength / max(self.settings.evidence_scale, 0.1),
            self.settings.evidence_cap,
        )

        posteriors: dict[str, float] = {}
        deviation = 0.0
        for domain in domains_touched:
            prior = self.get_prior(region, domain)
            deviation = max(deviation, self._deviation_score(region, domain, total_strength))
            posterior = self.bayesian_update(
                region=region,
                domain=domain,
                evidence_strength=evidence_strength * (1.0 + 0.15 * deviation),
            )
            posteriors[domain] = posterior

        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            with self._lock:
                state = self._region_state(region)
                try:
                    state.coords = [float(coords[0]), float(coords[1])]
                except (TypeError, ValueError):
                    pass

        self._update_graph(region, entities, total_strength, coords if isinstance(coords, list) else None)

        composite = self.composite_risk(region)
        entry = HistoryEntry(
            timestamp=self._utcnow(),
            domain=explicit_domain if explicit_domain in _DOMAINS else next(iter(domains_touched)),
            signals=signals,
            strength=total_strength,
            prior=self._base_prior,
            posterior=composite,
            source=source,
            deviation_score=deviation,
        )
        with self._lock:
            history = self._history[region]
            history.append(entry)
            max_hist = max(10, int(self.settings.max_history_per_region))
            if len(history) > max_hist:
                self._history[region] = history[-max_hist:]

        logger.info(
            "GT update region=%s domains=%s composite=%.3f signals=%d deviation=%.2f",
            region,
            ",".join(sorted(domains_touched)),
            composite,
            len(signals),
            deviation,
        )

        return {
            "region": region,
            "domains": sorted(domains_touched),
            "domain_posteriors": posteriors,
            "risk_score": composite,
            "signals": signals,
            "deviation_score": deviation,
            "contagion_potential": self._get_contagion_score(region),
            "interpretation": self._interpret_risk(composite),
        }

    def _interpret_risk(self, risk: float) -> str:
        threshold = float(self.settings.high_risk_threshold)
        if risk >= threshold:
            return (
                f"Elevated strategic risk ({risk:.2f} ≥ {threshold:.2f}). "
                "Watch for costly-signal clustering and cross-region contagion."
            )
        if risk >= threshold * 0.7:
            return "Moderate risk — monitor for herding and repeated costly signals."
        return "Baseline risk — no strong costly-signal cluster detected."

    def _get_contagion_score(self, region: str) -> float:
        """Graph-based contagion: mean composite risk of graph neighbors."""
        region_key = str(region or "global").strip().lower() or "global"
        with self._lock:
            if region_key not in self.G:
                return 0.0
            try:
                neighbors = list(self.G.neighbors(region_key))
            except nx.NetworkXError:
                return 0.0
            if not neighbors:
                return 0.0
            neighbor_risks = [self.composite_risk(str(n)) for n in neighbors]
            return float(np.mean(neighbor_risks))

    def compute_herding_clusters(self) -> list[dict[str, Any]]:
        """Louvain community detection on entity graph (coordination/herding proxy)."""
        with self._lock:
            if self.G.number_of_edges() == 0:
                return []

            weighted = nx.Graph()
            for u, v, data in self.G.edges(data=True):
                weight = float(data.get("weight") or 0.0)
                if weight < self.settings.louvain_min_weight:
                    continue
                if weighted.has_edge(u, v):
                    weighted[u][v]["weight"] = weighted[u][v].get("weight", 0.0) + weight
                else:
                    weighted.add_edge(u, v, weight=weight)

            if weighted.number_of_edges() == 0:
                return []

            try:
                communities = list(nx.community.louvain_communities(weighted, weight="weight", seed=42))
            except Exception as exc:
                logger.warning("Louvain clustering failed: %s", exc)
                return []

            clusters: list[dict[str, Any]] = []
            for idx, community in enumerate(communities):
                members = sorted(str(node) for node in community)
                region_members = [m for m in members if m in self._regions]
                risks = [self.composite_risk(r) for r in region_members]
                clusters.append(
                    {
                        "cluster_id": idx,
                        "size": len(members),
                        "members": members[:50],
                        "mean_risk": float(np.mean(risks)) if risks else self._base_prior,
                        "regions": region_members,
                    }
                )
            clusters.sort(key=lambda row: row["mean_risk"], reverse=True)
            return clusters

    def get_risk_heatmap(self) -> dict[str, Any]:
        """GeoJSON FeatureCollection for frontend risk overlay."""
        features: list[dict[str, Any]] = []
        with self._lock:
            items = list(self._regions.items())[: max(1, self.settings.max_heatmap_features)]

        for region, state in items:
            coords = state.coords
            geometry: dict[str, Any]
            if coords and len(coords) >= 2:
                geometry = {"type": "Point", "coordinates": [float(coords[1]), float(coords[0])]}
            else:
                geometry = {"type": "Point", "coordinates": [0.0, 0.0]}

            composite = self.composite_risk(region)
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "region": region,
                        "risk": round(composite, 4),
                        "financial": round(float(state.priors.get("financial", self._base_prior)), 4),
                        "unrest": round(float(state.priors.get("unrest", self._base_prior)), 4),
                        "conflict": round(float(state.priors.get("conflict", self._base_prior)), 4),
                        "contagion": round(self._get_contagion_score(region), 4),
                        "updates": state.update_count,
                    },
                    "geometry": geometry,
                }
            )

        return {"type": "FeatureCollection", "features": features}

    def get_dossier(self, region: str) -> dict[str, Any]:
        """Explainable GT rationale and recent signal history for a region."""
        region_key = str(region or "global").strip().lower() or "global"
        with self._lock:
            state = self._region_state(region_key)
            recent = list(self._history.get(region_key, [])[-10:])

        composite = self.composite_risk(region_key)
        return {
            "region": region_key,
            "current_risk": round(composite, 4),
            "domain_risks": {
                domain: round(float(state.priors.get(domain, self._base_prior)), 4)
                for domain in _DOMAINS
            },
            "recent_signals": [
                {
                    "timestamp": entry.timestamp,
                    "domain": entry.domain,
                    "signals": entry.signals,
                    "strength": entry.strength,
                    "posterior": round(entry.posterior, 4),
                    "source": entry.source,
                    "deviation_score": round(entry.deviation_score, 3),
                }
                for entry in recent
            ],
            "contagion_risk": round(self._get_contagion_score(region_key), 4),
            "herding_clusters": self.compute_herding_clusters()[:5],
            "interpretation": self._interpret_risk(composite),
            "scenarios": self._build_scenarios(region_key, composite),
        }

    def _build_scenarios(self, region: str, composite: float) -> list[dict[str, str]]:
        threshold = float(self.settings.high_risk_threshold)
        if composite < threshold * 0.7:
            return [
                {
                    "name": "Status quo",
                    "summary": "Signals remain diffuse; no coordinated costly-signal cascade.",
                }
            ]
        if composite < threshold:
            return [
                {
                    "name": "Escalation watch",
                    "summary": "Rising costly-signal density — coordination risk within 4-8 weeks.",
                },
                {
                    "name": "False alarm",
                    "summary": "Cheap-talk amplification without follow-on costly signals.",
                },
            ]
        return [
            {
                "name": "Contagion spread",
                "summary": "High posterior + graph coupling — adjacent regions likely to update upward.",
            },
            {
                "name": "Localized shock",
                "summary": "Region-specific distress; contagion limited if graph neighbors stay quiet.",
            },
        ]

    def snapshot(self) -> dict[str, Any]:
        """Serialize engine state for debugging or persistence."""
        with self._lock:
            return {
                "regions": {
                    region: {
                        "priors": dict(state.priors),
                        "coords": state.coords,
                        "updates": state.update_count,
                    }
                    for region, state in self._regions.items()
                },
                "graph_nodes": self.G.number_of_nodes(),
                "graph_edges": self.G.number_of_edges(),
                "processed_items": len(self._seen_item_ids),
            }