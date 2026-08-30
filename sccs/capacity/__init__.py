# SCCS Capacity Probe
#
# Reports how much plan quota each orchestrated CLI agent has left, so a CAO
# supervisor can route work by remaining capacity instead of guessing.
#
# Lazy re-exports keep `import sccs` cheap (same pattern as sccs/__init__.py).

from __future__ import annotations

from sccs.capacity.report import build_report, derive_routing
from sccs.capacity.schema import (
    CapacityReport,
    ProviderCapacity,
    QuotaScope,
    QuotaWindow,
    RoutingAdvice,
)

__all__ = [
    "CapacityReport",
    "ProviderCapacity",
    "QuotaScope",
    "QuotaWindow",
    "RoutingAdvice",
    "build_report",
    "derive_routing",
]
