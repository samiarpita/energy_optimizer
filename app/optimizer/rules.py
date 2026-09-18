"""Directive Translation & Operational Constraint Rules.

Translates validated DirectiveInterpretation objects into numerical constraint bounds
and operational window masks used by the Linear Programming solver.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set, Union
from app.schemas import BatteryInfo, DirectiveInterpretation, HourEntry


@dataclass
class ParsedDirectives:
    """Operational constraints extracted from validated directives."""
    solar_factors: Dict[int, float] = field(default_factory=lambda: {h: 1.0 for h in range(24)})
    min_reserves: Dict[int, float] = field(default_factory=dict)
    no_charge_hours: Set[int] = field(default_factory=set)
    no_discharge_hours: Set[int] = field(default_factory=set)
    grid_caps: Dict[int, float] = field(default_factory=dict)


def extract_effective_directives(
    battery: Union[BatteryInfo, dict],
    directives: List[Union[DirectiveInterpretation, dict]],
) -> ParsedDirectives:
    """Extract hourly masks and bounds from validated directives.

    Args:
        battery: Battery specification containing base minimum_energy_kwh and capacity_kwh.
        directives: Validated directive interpretations.

    Returns:
        ParsedDirectives with hourly solar factors, reserves, and window masks.
    """
    base_min = (
        battery.minimum_energy_kwh
        if isinstance(battery, BatteryInfo)
        else float(battery.get("minimum_energy_kwh", 0.0))
    )
    capacity = (
        battery.capacity_kwh
        if isinstance(battery, BatteryInfo)
        else float(battery.get("capacity_kwh", float("inf")))
    )

    parsed = ParsedDirectives()
    parsed.min_reserves = {h: base_min for h in range(24)}

    for d in directives:
        # Handle both Pydantic models and dictionaries
        if isinstance(d, DirectiveInterpretation):
            applies = d.applies
            d_type = d.directive_type
            adj = d.structured_adjustment or {}
        else:
            applies = d.get("applies", False)
            d_type = d.get("directive_type", "no_op")
            adj = d.get("structured_adjustment") or {}

        if not applies or d_type == "no_op":
            continue

        hours = adj.get("hours", [])

        if d_type == "solar_reduction":
            factor = float(adj.get("factor", 1.0))
            # Clamp factor to [0.0, 1.0]
            factor = max(0.0, min(1.0, factor))
            for h in hours:
                if 0 <= h < 24:
                    parsed.solar_factors[h] = min(parsed.solar_factors[h], factor)

        elif d_type == "minimum_battery_reserve":
            req_reserve = float(adj.get("minimum_energy_kwh", base_min))
            # Reserve cannot exceed battery capacity
            req_reserve = min(capacity, max(0.0, req_reserve))
            for h in hours:
                if 0 <= h < 24:
                    parsed.min_reserves[h] = max(parsed.min_reserves[h], req_reserve)

        elif d_type == "no_charge_window":
            for h in hours:
                if 0 <= h < 24:
                    parsed.no_charge_hours.add(h)

        elif d_type == "no_discharge_window":
            for h in hours:
                if 0 <= h < 24:
                    parsed.no_discharge_hours.add(h)

        elif d_type == "max_grid_window":
            cap = float(adj.get("max_grid_kwh", float("inf")))
            cap = max(0.0, cap)
            for h in hours:
                if 0 <= h < 24:
                    if h in parsed.grid_caps:
                        parsed.grid_caps[h] = min(parsed.grid_caps[h], cap)
                    else:
                        parsed.grid_caps[h] = cap

    return parsed
