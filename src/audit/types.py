"""Data models for the ride audit pipeline."""

from dataclasses import dataclass, field
from enum import Enum


class Verdict(str, Enum):
    CLEAN = "CLEAN"
    VIOLATION = "VIOLATION"
    AMBIGUOUS = "AMBIGUOUS"


class EventState(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


@dataclass
class TracePoint:
    lat: float
    lon: float
    t: float = 0.0  # seconds since trace start


@dataclass
class Trace:
    points: list[TracePoint] = field(default_factory=list)


@dataclass
class DetectedEvent:
    verdict: Verdict
    reason: str = ""
    # substring indices into the trace at the violation (for dashboard replay)
    seg_start: int = -1
    seg_end: int = -1
    severity: str = "LOW"  # LOW | MEDIUM | HIGH
    state: EventState = EventState.PENDING_REVIEW