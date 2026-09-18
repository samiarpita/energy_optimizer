"""Unit tests for Member 2: Mathematical Optimization Engine & Energy Physics.

Tests the LP solver in complete isolation across various physical constraints and directives:
1. Pure base scenario (no directives)
2. Solar reduction directive
3. No-charge window outage
4. No-discharge window outage
5. Minimum battery reserve directive
6. Grid import cap window
7. Multi-directive combined scenario
8. Physical replay validation (energy balance, bounds, neutrality, recalculation)
"""

import unittest
from app.optimizer.lp_solver import solve_energy_optimization
from app.optimizer.rules import ParsedDirectives, extract_effective_directives
from app.schemas import (
    BatteryInfo,
    DirectiveInterpretation,
    HourEntry,
    HourlyPlanEntry,
    OptimizeEnergyRequest,
)
from app.verifier.replay import verify_and_recalculate_schedule


def create_mock_hours(base_demand: float = 100.0, solar_peak: float = 150.0) -> list[HourEntry]:
    """Generate a realistic 24-hour load and solar curve."""
    hours = []
    for h in range(24):
        # Solar peak around midday (hours 10-15)
        if 6 <= h <= 18:
            solar = max(0.0, solar_peak * (1.0 - abs(h - 12) / 6.0))
        else:
            solar = 0.0

        # Demand higher in evening (hours 17-21)
        if 17 <= h <= 21:
            demand = base_demand * 1.5
            tariff = 25.0
        elif 0 <= h <= 5:
            demand = base_demand * 0.8
            tariff = 5.0
        else:
            demand = base_demand
            tariff = 12.0

        hours.append(
            HourEntry(
                hour=h,
                demand_kwh=round(demand, 1),
                solar_kwh=round(solar, 1),
                tariff_bdt_per_kwh=round(tariff, 1),
            )
        )
    return hours


def create_mock_battery() -> BatteryInfo:
    """Standard campus battery configuration."""
    return BatteryInfo(
        capacity_kwh=200.0,
        initial_energy_kwh=100.0,
        minimum_energy_kwh=30.0,
        max_charge_kwh_per_hour=50.0,
        max_discharge_kwh_per_hour=50.0,
    )


class TestMember2Optimizer(unittest.TestCase):
    """Test suite for Member 2 Linear Programming Solver and Physical Rules."""

    def setUp(self):
        self.hours = create_mock_hours()
        self.battery = create_mock_battery()

    def test_base_optimization_no_directives(self):
        """Test LP solver with no directives: must satisfy all physics and neutrality."""
        res = solve_energy_optimization(self.hours, self.battery, [])
        self.assertIn("hourly_plan", res)
        plan = res["hourly_plan"]
        self.assertEqual(len(plan), 24)

        # Replay verifier check
        req = OptimizeEnergyRequest(
            scenario_id="TEST-BASE",
            operator_notes=[],
            hours=self.hours,
            battery=self.battery,
        )
        replay = verify_and_recalculate_schedule(req, [], plan)
        self.assertTrue(replay.is_valid, f"Replay failed: {replay.errors}")
        self.assertEqual(len(replay.errors), 0)

        # End of day neutrality
        self.assertAlmostEqual(plan[23].battery_energy_after_kwh, self.battery.initial_energy_kwh, places=2)

    def test_solar_reduction_directive(self):
        """Test solar reduction: effective solar is reduced and observed."""
        directive = DirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type="solar_reduction",
            structured_adjustment={"hours": [11, 12, 13], "factor": 0.2},
            explanation="Solar output reduced to 20% due to dust.",
        )
        res = solve_energy_optimization(self.hours, self.battery, [directive])
        plan = res["hourly_plan"]

        req = OptimizeEnergyRequest(
            scenario_id="TEST-SOLAR",
            operator_notes=["Reduce solar"],
            hours=self.hours,
            battery=self.battery,
        )
        replay = verify_and_recalculate_schedule(req, [directive], plan)
        self.assertTrue(replay.is_valid, f"Solar reduction replay failed: {replay.errors}")

        # Check that solar_used during hours 11, 12, 13 does not exceed 20% of original
        for h in [11, 12, 13]:
            max_allowed_solar = self.hours[h].solar_kwh * 0.2
            self.assertLessEqual(plan[h].solar_used_kwh, max_allowed_solar + 0.01)

    def test_no_charge_window_directive(self):
        """Test no-charge window: charging must be exactly 0 during specified hours."""
        directive = DirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type="no_charge_window",
            structured_adjustment={"hours": [2, 3, 4]},
            explanation="Charger maintenance window.",
        )
        res = solve_energy_optimization(self.hours, self.battery, [directive])
        plan = res["hourly_plan"]

        req = OptimizeEnergyRequest(
            scenario_id="TEST-NO-CHARGE",
            operator_notes=["No charge 2-4"],
            hours=self.hours,
            battery=self.battery,
        )
        replay = verify_and_recalculate_schedule(req, [directive], plan)
        self.assertTrue(replay.is_valid, f"No-charge replay failed: {replay.errors}")

        for h in [2, 3, 4]:
            self.assertNotEqual(plan[h].battery_action, "charge", f"Hour {h} charged during forbidden window!")
            if plan[h].battery_action != "discharge":
                self.assertAlmostEqual(plan[h].battery_kwh, 0.0, places=2)

    def test_no_discharge_window_directive(self):
        """Test no-discharge window: discharging must be exactly 0 during specified hours."""
        directive = DirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type="no_discharge_window",
            structured_adjustment={"hours": [18, 19]},
            explanation="Relay testing window.",
        )
        res = solve_energy_optimization(self.hours, self.battery, [directive])
        plan = res["hourly_plan"]

        req = OptimizeEnergyRequest(
            scenario_id="TEST-NO-DISCHARGE",
            operator_notes=["No discharge 18-19"],
            hours=self.hours,
            battery=self.battery,
        )
        replay = verify_and_recalculate_schedule(req, [directive], plan)
        self.assertTrue(replay.is_valid, f"No-discharge replay failed: {replay.errors}")

        for h in [18, 19]:
            self.assertNotEqual(plan[h].battery_action, "discharge", f"Hour {h} discharged during forbidden window!")

    def test_minimum_battery_reserve_directive(self):
        """Test minimum battery reserve: battery must not drop below elevated reserve."""
        directive = DirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type="minimum_battery_reserve",
            structured_adjustment={"hours": [18, 19, 20], "minimum_energy_kwh": 90.0},
            explanation="Hospital emergency power reserve.",
        )
        res = solve_energy_optimization(self.hours, self.battery, [directive])
        plan = res["hourly_plan"]

        req = OptimizeEnergyRequest(
            scenario_id="TEST-RESERVE",
            operator_notes=["Hold 90 kWh"],
            hours=self.hours,
            battery=self.battery,
        )
        replay = verify_and_recalculate_schedule(req, [directive], plan)
        self.assertTrue(replay.is_valid, f"Reserve replay failed: {replay.errors}")

        for h in [18, 19, 20]:
            self.assertGreaterEqual(plan[h].battery_energy_after_kwh, 90.0 - 0.01)

    def test_max_grid_window_directive(self):
        """Test max grid window: grid import must not exceed cap."""
        # Demand at hour 18 is 150, max battery discharge is 50, so cap must be >= 100 to be feasible
        cap_val = 110.0
        directive = DirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type="max_grid_window",
            structured_adjustment={"hours": [18, 19], "max_grid_kwh": cap_val},
            explanation="Transformer limit.",
        )
        res = solve_energy_optimization(self.hours, self.battery, [directive])
        plan = res["hourly_plan"]

        req = OptimizeEnergyRequest(
            scenario_id="TEST-GRID-CAP",
            operator_notes=["Cap grid at 60"],
            hours=self.hours,
            battery=self.battery,
        )
        replay = verify_and_recalculate_schedule(req, [directive], plan)
        self.assertTrue(replay.is_valid, f"Grid cap replay failed: {replay.errors}")

        for h in [18, 19]:
            self.assertLessEqual(plan[h].grid_kwh, cap_val + 0.01)

    def test_combined_multiple_directives(self):
        """Test combination of solar reduction, no-charge window, and reserve."""
        directives = [
            DirectiveInterpretation(
                note_index=0,
                applies=True,
                directive_type="solar_reduction",
                structured_adjustment={"hours": [11, 12], "factor": 0.5},
                explanation="Partial solar drop.",
            ),
            DirectiveInterpretation(
                note_index=1,
                applies=True,
                directive_type="no_charge_window",
                structured_adjustment={"hours": [13, 14]},
                explanation="Maintenance window.",
            ),
            DirectiveInterpretation(
                note_index=2,
                applies=True,
                directive_type="minimum_battery_reserve",
                structured_adjustment={"hours": [19, 20], "minimum_energy_kwh": 80.0},
                explanation="Evening reserve.",
            ),
            DirectiveInterpretation(
                note_index=3,
                applies=False,
                directive_type="no_op",
                structured_adjustment=None,
                explanation="Distractor note.",
            ),
        ]
        res = solve_energy_optimization(self.hours, self.battery, directives)
        plan = res["hourly_plan"]

    def test_sample_01_canonical_case(self):
        """Test with exact canonical SAMPLE-01 from official challenge pack."""
        hours_data = [
            {"hour": 0, "demand_kwh": 90, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
            {"hour": 1, "demand_kwh": 85, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
            {"hour": 2, "demand_kwh": 80, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
            {"hour": 3, "demand_kwh": 80, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
            {"hour": 4, "demand_kwh": 85, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
            {"hour": 5, "demand_kwh": 95, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
            {"hour": 6, "demand_kwh": 110, "solar_kwh": 5, "tariff_bdt_per_kwh": 8},
            {"hour": 7, "demand_kwh": 130, "solar_kwh": 20, "tariff_bdt_per_kwh": 10},
            {"hour": 8, "demand_kwh": 150, "solar_kwh": 50, "tariff_bdt_per_kwh": 12},
            {"hour": 9, "demand_kwh": 165, "solar_kwh": 90, "tariff_bdt_per_kwh": 14},
            {"hour": 10, "demand_kwh": 175, "solar_kwh": 130, "tariff_bdt_per_kwh": 16},
            {"hour": 11, "demand_kwh": 180, "solar_kwh": 160, "tariff_bdt_per_kwh": 16},
            {"hour": 12, "demand_kwh": 185, "solar_kwh": 180, "tariff_bdt_per_kwh": 15},
            {"hour": 13, "demand_kwh": 180, "solar_kwh": 170, "tariff_bdt_per_kwh": 14},
            {"hour": 14, "demand_kwh": 170, "solar_kwh": 140, "tariff_bdt_per_kwh": 13},
            {"hour": 15, "demand_kwh": 165, "solar_kwh": 90, "tariff_bdt_per_kwh": 14},
            {"hour": 16, "demand_kwh": 170, "solar_kwh": 45, "tariff_bdt_per_kwh": 18},
            {"hour": 17, "demand_kwh": 185, "solar_kwh": 10, "tariff_bdt_per_kwh": 22},
            {"hour": 18, "demand_kwh": 205, "solar_kwh": 0, "tariff_bdt_per_kwh": 28},
            {"hour": 19, "demand_kwh": 215, "solar_kwh": 0, "tariff_bdt_per_kwh": 30},
            {"hour": 20, "demand_kwh": 205, "solar_kwh": 0, "tariff_bdt_per_kwh": 26},
            {"hour": 21, "demand_kwh": 175, "solar_kwh": 0, "tariff_bdt_per_kwh": 18},
            {"hour": 22, "demand_kwh": 135, "solar_kwh": 0, "tariff_bdt_per_kwh": 10},
            {"hour": 23, "demand_kwh": 105, "solar_kwh": 0, "tariff_bdt_per_kwh": 7},
        ]
        battery_data = BatteryInfo(
            capacity_kwh=220,
            initial_energy_kwh=110,
            minimum_energy_kwh=40,
            max_charge_kwh_per_hour=50,
            max_discharge_kwh_per_hour=50,
        )
        directive_data = [
            DirectiveInterpretation(
                note_index=0,
                applies=True,
                directive_type="solar_reduction",
                structured_adjustment={"hours": [12, 13], "factor": 0.25},
                explanation="Solar reduced to 25% during washing.",
            ),
            DirectiveInterpretation(
                note_index=1,
                applies=False,
                directive_type="no_op",
                structured_adjustment=None,
                explanation="Distractor.",
            ),
        ]

        res = solve_energy_optimization(hours_data, battery_data, directive_data)

        # Expected canonical cost: 38365.0 BDT, total grid: 2692.5 kWh, peak: 175 kWh
        self.assertAlmostEqual(res["total_cost_bdt"], 38365.0, delta=1.0)
        self.assertAlmostEqual(res["total_grid_kwh"], 2692.5, delta=1.0)
        self.assertEqual(res["peak_grid_kwh"], 175.0)

        # Replay validation
        req = OptimizeEnergyRequest(
            scenario_id="SAMPLE-01",
            operator_notes=["Wash", "Sports"],
            hours=hours_data,
            battery=battery_data,
        )
        replay = verify_and_recalculate_schedule(req, directive_data, res["hourly_plan"])
        self.assertTrue(replay.is_valid, f"Replay failed: {replay.errors}")


if __name__ == "__main__":
    unittest.main()
