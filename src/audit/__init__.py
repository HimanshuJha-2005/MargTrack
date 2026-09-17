"""RideTrail: GPS-trace ride audit engine — embedded compliance layer for ride platforms."""

from .detect import audit_trace, distance_to_route_m
from .types import DetectedEvent, EventState, Trace, TracePoint, Verdict

__all__ = [
    "audit_trace",
    "distance_to_route_m",
    "DetectedEvent",
    "EventState",
    "Trace",
    "TracePoint",
    "Verdict",
]