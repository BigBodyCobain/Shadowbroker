"""Classification vocabularies for the investigation domain.

The single most important product rule lives here: analytic products are
ranked on an *epistemic ladder* from raw fact to inference, and the rung is a
required, first-class attribute — never implied by styling or wording.
"""

from __future__ import annotations

from enum import Enum


class Classification(str, Enum):
    """Where a piece of information sits on the fact -> inference ladder.

    The ordering is meaningful (``order`` ascends with interpretive distance
    from ground truth) and is used by the UI to render facts and inferences
    with visibly different treatment.
    """

    RAW_OBSERVATION = "raw_observation"
    """A directly measured/reported fact from a source. Example: "Aircraft X
    observed at 41.9N, 29.1E at 14:32 UTC (ADS-B)." Not interpreted."""

    DERIVED_EVENT = "derived_event"
    """A meaningful occurrence computed deterministically from observations.
    Example: "Aircraft X changed heading by 32 degrees." Still factual, but a
    ShadowBroker-derived product rather than a raw source record."""

    ANALYSIS = "analysis"
    """A judgement about observations/events relative to context or history.
    Example: "This movement is unusual versus the aircraft's historical
    behaviour." Interpretation — clearly labelled as such."""

    HYPOTHESIS = "hypothesis"
    """A candidate explanation/inference that is NOT established fact.
    Example: "The movement may be associated with nearby activity." Must never
    be presented as confirmed."""

    @property
    def order(self) -> int:
        return _CLASSIFICATION_ORDER[self]

    @property
    def is_fact(self) -> bool:
        """True for rungs that assert something happened (not interpretation)."""
        return self in (Classification.RAW_OBSERVATION, Classification.DERIVED_EVENT)

    @property
    def is_inference(self) -> bool:
        return self in (Classification.ANALYSIS, Classification.HYPOTHESIS)

    @property
    def label(self) -> str:
        return _CLASSIFICATION_LABELS[self]


_CLASSIFICATION_ORDER = {
    Classification.RAW_OBSERVATION: 0,
    Classification.DERIVED_EVENT: 1,
    Classification.ANALYSIS: 2,
    Classification.HYPOTHESIS: 3,
}

_CLASSIFICATION_LABELS = {
    Classification.RAW_OBSERVATION: "Raw observation",
    Classification.DERIVED_EVENT: "Derived event",
    Classification.ANALYSIS: "Analysis",
    Classification.HYPOTHESIS: "Hypothesis",
}


class EntityType(str, Enum):
    """Kinds of entity the platform can track and relate.

    Open-ended: :data:`OTHER` is a valid catch-all so ingestion never fails on
    an unmodelled type. New named members can be added without migration
    because the value is stored as text.
    """

    AIRCRAFT = "aircraft"
    VESSEL = "vessel"
    SATELLITE = "satellite"
    PERSON = "person"
    ORGANIZATION = "organization"
    COMPANY = "company"
    LOCATION = "location"
    INFRASTRUCTURE = "infrastructure"
    IP = "ip"
    DOMAIN = "domain"
    TELEGRAM_CHANNEL = "telegram_channel"
    NEWS_SOURCE = "news_source"
    AIRPORT = "airport"
    PORT = "port"
    OTHER = "other"

    @classmethod
    def coerce(cls, value: object) -> "EntityType":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return cls.OTHER


class EvidenceKind(str, Enum):
    """The nature of an evidence artifact attached to an investigation."""

    OBSERVATION = "observation"
    EVENT = "event"
    SOURCE_DOCUMENT = "source_document"
    CORRELATION = "correlation"
    IMAGERY = "imagery"
    SIGNAL = "signal"
    ANALYST_NOTE = "analyst_note"
    EXTERNAL_REPORT = "external_report"
    OTHER = "other"

    @classmethod
    def coerce(cls, value: object) -> "EvidenceKind":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return cls.OTHER


class InvestigationStatus(str, Enum):
    OPEN = "open"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    CLOSED = "closed"
    ARCHIVED = "archived"

    @classmethod
    def coerce(cls, value: object) -> "InvestigationStatus":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return cls.OPEN


class HypothesisStatus(str, Enum):
    PROPOSED = "proposed"
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"

    @classmethod
    def coerce(cls, value: object) -> "HypothesisStatus":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return cls.PROPOSED


class AlertStatus(str, Enum):
    NEW = "new"
    ACKNOWLEDGED = "acknowledged"
    INVESTIGATING = "investigating"
    DISMISSED = "dismissed"
    RESOLVED = "resolved"

    @classmethod
    def coerce(cls, value: object) -> "AlertStatus":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return cls.NEW


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def order(self) -> int:
        return _SEVERITY_ORDER[self]

    @classmethod
    def coerce(cls, value: object) -> "Severity":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return cls.INFO


_SEVERITY_ORDER = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}
