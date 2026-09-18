"""Linear Programming Optimization Engine using PuLP and COIN-OR CBC.

Formulates and solves the 24-hour smart campus energy dispatch problem:
- Minimizes total grid electricity import cost across 24 hours.
- Strictly satisfies energy conservation balance every hour.
- Adheres to battery energy bounds, hourly rate limits, and end-of-day neutrality.
- Respects all active operator directives (solar reduction, reserves, outages, grid caps).
"""

import logging
import warnings
from typing import Any, Dict, List, Union
import pulp

# Suppress internal PuLP v4 transition deprecation warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module="pulp.*")

from app.optimizer.rules import ParsedDirectives, extract_effective_directives
from app.schemas import (
    BatteryInfo,
    DirectiveInterpretation,
    HourEntry,
    HourlyPlanEntry,
)

logger = logging.getLogger("gridwise.optimizer")


def solve_energy_optimization(
    hours: List[Union[HourEntry, dict]],
    battery: Union[BatteryInfo, dict],
    directives: List[Union[DirectiveInterpretation, dict]],
) -> Dict[str, Any]:
    """Solve the 24-hour campus energy scheduling problem via Linear Programming.

    Args:
        hours: 24-hour sequential list of demand, solar forecast, and grid tariffs.
        battery: Battery technical specifications and operational limits.
        directives: Validated natural-language operator directives.

    Returns:
        Dict containing:
        - hourly_plan: List of 24 HourlyPlanEntry objects
        - total_grid_kwh: Sum of grid energy imported over 24 hours
        - total_cost_bdt: Total electricity bill in BDT
        - peak_grid_kwh: Maximum hourly grid import
        - plan_summary: Concise explanation of the schedule strategy
    """
    # 1. Normalize inputs
    battery_capacity = (
        battery.capacity_kwh
        if isinstance(battery, BatteryInfo)
        else float(battery["capacity_kwh"])
    )
    battery_initial = (
        battery.initial_energy_kwh
        if isinstance(battery, BatteryInfo)
        else float(battery["initial_energy_kwh"])
    )
    battery_min_reserve = (
        battery.minimum_energy_kwh
        if isinstance(battery, BatteryInfo)
        else float(battery["minimum_energy_kwh"])
    )
    max_charge_rate = (
        battery.max_charge_kwh_per_hour
        if isinstance(battery, BatteryInfo)
        else float(battery["max_charge_kwh_per_hour"])
    )
    max_discharge_rate = (
        battery.max_discharge_kwh_per_hour
        if isinstance(battery, BatteryInfo)
        else float(battery["max_discharge_kwh_per_hour"])
    )

    # 2. Extract operational constraints from directives
    rules: ParsedDirectives = extract_effective_directives(battery, directives)

    # 3. Initialize PuLP Minimization Problem
    prob = pulp.LpProblem("Campus_Energy_Optimizer", pulp.LpMinimize)

    # 4. Define Decision Variables (24 hours)
    grid = [pulp.LpVariable(f"grid_{h}", lowBound=0.0, cat="Continuous") for h in range(24)]
    solar_used = [pulp.LpVariable(f"solar_used_{h}", lowBound=0.0, cat="Continuous") for h in range(24)]
    charge = [pulp.LpVariable(f"charge_{h}", lowBound=0.0, cat="Continuous") for h in range(24)]
    discharge = [pulp.LpVariable(f"discharge_{h}", lowBound=0.0, cat="Continuous") for h in range(24)]
    energy_after = [
        pulp.LpVariable(f"energy_after_{h}", lowBound=0.0, upBound=battery_capacity, cat="Continuous")
        for h in range(24)
    ]
    peak_var = pulp.LpVariable("peak_grid_import", lowBound=0.0, cat="Continuous")

    # 5. Objective Function:
    # Primary: Minimize SUM(grid[h] * tariff[h])
    # Secondary: 1e-4 * peak_var (breaks ties by shaving grid peaks)
    # Tertiary: 1e-6 * throughput (prevents simultaneous charge/discharge)
    cost_terms = []
    throughput_penalty_terms = []

    for h in range(24):
        h_entry = hours[h]
        tariff = (
            h_entry.tariff_bdt_per_kwh
            if isinstance(h_entry, HourEntry)
            else float(h_entry["tariff_bdt_per_kwh"])
        )
        cost_terms.append(grid[h] * tariff)
        throughput_penalty_terms.append(1e-6 * (charge[h] + discharge[h]))

    prob += pulp.lpSum(cost_terms) + (1e-4 * peak_var) + pulp.lpSum(throughput_penalty_terms)

    # 6. Apply Constraints
    for h in range(24):
        # Tie peak_var to peak grid import
        prob += grid[h] <= peak_var, f"Peak_Bound_{h}"
        h_entry = hours[h]
        demand = (
            h_entry.demand_kwh
            if isinstance(h_entry, HourEntry)
            else float(h_entry["demand_kwh"])
        )
        base_solar = (
            h_entry.solar_kwh
            if isinstance(h_entry, HourEntry)
            else float(h_entry["solar_kwh"])
        )

        effective_solar = base_solar * rules.solar_factors.get(h, 1.0)

        # Constraint A: Solar Utilization Limit (Curtailment allowed, no grid export)
        prob += solar_used[h] <= effective_solar, f"Solar_Limit_{h}"

        # Constraint B: Hourly Energy Balance (Supply == Demand)
        # grid + solar_used + discharge == demand + charge
        prob += (
            grid[h] + solar_used[h] + discharge[h] == demand + charge[h],
            f"Energy_Balance_{h}",
        )

        # Constraint C: Battery State Dynamics
        if h == 0:
            prob += (
                energy_after[0] == battery_initial + charge[0] - discharge[0],
                f"Battery_State_{h}",
            )
        else:
            prob += (
                energy_after[h] == energy_after[h - 1] + charge[h] - discharge[h],
                f"Battery_State_{h}",
            )

        # Constraint D: Dynamic Battery Reserve (Minimum allowed level)
        active_min_reserve = rules.min_reserves.get(h, battery_min_reserve)
        prob += energy_after[h] >= active_min_reserve, f"Min_Reserve_{h}"

        # Constraint E: Battery Hourly Charge / Discharge Limits
        if h in rules.no_charge_hours:
            prob += charge[h] == 0.0, f"No_Charge_{h}"
        else:
            prob += charge[h] <= max_charge_rate, f"Max_Charge_{h}"

        if h in rules.no_discharge_hours:
            prob += discharge[h] == 0.0, f"No_Discharge_{h}"
        else:
            prob += discharge[h] <= max_discharge_rate, f"Max_Discharge_{h}"

        # Constraint F: Grid Import Windows (Cap on utility draw)
        if h in rules.grid_caps:
            prob += grid[h] <= rules.grid_caps[h], f"Grid_Cap_{h}"

    # Constraint G: End-of-Day Neutrality (Final battery energy == Initial battery energy)
    prob += energy_after[23] == battery_initial, "End_Of_Day_Neutrality"

    # 7. Solve with COIN-OR CBC (msg=0 disables verbose console spam)
    solver = pulp.PULP_CBC_CMD(msg=0)
    status = prob.solve(solver)

    if status != pulp.LpStatusOptimal:
        logger.error("LP failed to find optimal solution. Status: %s", pulp.LpStatus[status])
        # Fallback to pure solar + grid baseline if infeasible
        return _generate_fallback_schedule(hours, battery)

    # 8. Post-Process Decision Variables & Ensure Physical Consistency
    hourly_plan: List[HourlyPlanEntry] = []
    current_battery = battery_initial

    for h in range(24):
        h_entry = hours[h]
        demand = (
            h_entry.demand_kwh
            if isinstance(h_entry, HourEntry)
            else float(h_entry["demand_kwh"])
        )

        c = max(0.0, float(pulp.value(charge[h])))
        d = max(0.0, float(pulp.value(discharge[h])))
        s = max(0.0, float(pulp.value(solar_used[h])))

        # Strict cancellation of simultaneous charge & discharge
        cancel = min(c, d)
        c -= cancel
        d -= cancel

        # Determine battery action
        if c > 1e-3:
            action = "charge"
            bat_kwh = c
        elif d > 1e-3:
            action = "discharge"
            bat_kwh = d
        else:
            action = "idle"
            bat_kwh = 0.0

        # Exact update of battery state
        current_battery = current_battery + c - d

        # Strictly balance grid to satisfy supply == demand exactly
        # grid = demand + charge - solar_used - discharge
        g = max(0.0, demand + c - s - d)

        hourly_plan.append(
            HourlyPlanEntry(
                hour=h,
                grid_kwh=round(g, 4),
                solar_used_kwh=round(s, 4),
                battery_action=action,
                battery_kwh=round(bat_kwh, 4),
                battery_energy_after_kwh=round(current_battery, 4),
            )
        )

    # 9. Compute Summary Metrics
    total_grid = sum(entry.grid_kwh for entry in hourly_plan)
    total_cost = sum(
        entry.grid_kwh
        * (
            hours[entry.hour].tariff_bdt_per_kwh
            if isinstance(hours[entry.hour], HourEntry)
            else float(hours[entry.hour]["tariff_bdt_per_kwh"])
        )
        for entry in hourly_plan
    )
    peak_grid = max(entry.grid_kwh for entry in hourly_plan)

    # 10. Generate Descriptive Plan Summary
    applied_types = {
        (d.directive_type if isinstance(d, DirectiveInterpretation) else d.get("directive_type"))
        for d in directives
        if (d.applies if isinstance(d, DirectiveInterpretation) else d.get("applies", False))
    }
    applied_types.discard("no_op")

    if applied_types:
        summary_directives = ", ".join(sorted(applied_types))
        summary = (
            f"Optimized 24-hour schedule applying directives ({summary_directives}). "
            f"Pre-charges battery during economical hours and discharges during peak tariff periods "
            f"while preserving end-of-day battery neutrality."
        )
    else:
        summary = (
            "Optimized 24-hour schedule shifts battery energy into high-tariff evening hours "
            "while maintaining all physical battery limits and end-of-day neutrality."
        )

    return {
        "hourly_plan": hourly_plan,
        "total_grid_kwh": round(total_grid, 2),
        "total_cost_bdt": round(total_cost, 2),
        "peak_grid_kwh": round(peak_grid, 2),
        "plan_summary": summary,
    }


def _generate_fallback_schedule(
    hours: List[Union[HourEntry, dict]],
    battery: Union[BatteryInfo, dict],
) -> Dict[str, Any]:
    """Safe fallback schedule that consumes direct solar and imports remaining grid power."""
    initial_energy = (
        battery.initial_energy_kwh
        if isinstance(battery, BatteryInfo)
        else float(battery["initial_energy_kwh"])
    )

    plan: List[HourlyPlanEntry] = []
    total_grid = 0.0
    total_cost = 0.0
    peak_grid = 0.0

    for h in range(24):
        h_entry = hours[h]
        demand = (
            h_entry.demand_kwh
            if isinstance(h_entry, HourEntry)
            else float(h_entry["demand_kwh"])
        )
        solar = (
            h_entry.solar_kwh
            if isinstance(h_entry, HourEntry)
            else float(h_entry["solar_kwh"])
        )
        tariff = (
            h_entry.tariff_bdt_per_kwh
            if isinstance(h_entry, HourEntry)
            else float(h_entry["tariff_bdt_per_kwh"])
        )

        solar_used = min(solar, demand)
        grid_needed = max(0.0, demand - solar_used)

        plan.append(
            HourlyPlanEntry(
                hour=h,
                grid_kwh=round(grid_needed, 4),
                solar_used_kwh=round(solar_used, 4),
                battery_action="idle",
                battery_kwh=0.0,
                battery_energy_after_kwh=round(initial_energy, 4),
            )
        )
        total_grid += grid_needed
        total_cost += grid_needed * tariff
        if grid_needed > peak_grid:
            peak_grid = grid_needed

    return {
        "hourly_plan": plan,
        "total_grid_kwh": round(total_grid, 2),
        "total_cost_bdt": round(total_cost, 2),
        "peak_grid_kwh": round(peak_grid, 2),
        "plan_summary": "Fallback schedule: supplies demand through direct solar and grid import with idle battery.",
    }
