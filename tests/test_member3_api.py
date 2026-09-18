"""Unit and Integration Tests for Team Member 3 (FastAPI & Replay Verifier)."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.schemas import (
    BatteryInfo,
    DirectiveInterpretation,
    HourEntry,
    HourlyPlanEntry,
    OptimizeEnergyRequest,
    OptimizeEnergyResponse,
)
from app.verifier.replay import verify_and_recalculate_schedule

client = TestClient(app)


# --- Sample Test Fixtures ---
def create_valid_hours():
    return [
        HourEntry(
            hour=h,
            demand_kwh=100.0 + h * 5,
            solar_kwh=50.0 if 8 <= h <= 16 else 0.0,
            tariff_bdt_per_kwh=5.0 if h < 17 else 15.0,
        )
        for h in range(24)
    ]


def create_valid_battery():
    return BatteryInfo(
        capacity_kwh=200.0,
        initial_energy_kwh=100.0,
        minimum_energy_kwh=30.0,
        max_charge_kwh_per_hour=50.0,
        max_discharge_kwh_per_hour=50.0,
    )


def create_valid_request():
    return OptimizeEnergyRequest(
        scenario_id="TEST-SCENARIO-01",
        operator_notes=["Solar output drops to 50% from 12 to 14", "Distractor note"],
        hours=create_valid_hours(),
        battery=create_valid_battery(),
    )


# --- 1. Schemas Validation Tests ---
def test_battery_info_bounds_validation():
    # initial_energy > capacity should raise ValidationError
    with pytest.raises(ValidationError):
        BatteryInfo(
            capacity_kwh=100.0,
            initial_energy_kwh=150.0,
            minimum_energy_kwh=20.0,
            max_charge_kwh_per_hour=30.0,
            max_discharge_kwh_per_hour=30.0,
        )

    # initial_energy < minimum_energy should raise ValidationError
    with pytest.raises(ValidationError):
        BatteryInfo(
            capacity_kwh=100.0,
            initial_energy_kwh=10.0,
            minimum_energy_kwh=20.0,
            max_charge_kwh_per_hour=30.0,
            max_discharge_kwh_per_hour=30.0,
        )


def test_hour_entry_range_validation():
    with pytest.raises(ValidationError):
        HourEntry(hour=24, demand_kwh=100, solar_kwh=0, tariff_bdt_per_kwh=5)

    with pytest.raises(ValidationError):
        HourEntry(hour=-1, demand_kwh=100, solar_kwh=0, tariff_bdt_per_kwh=5)


def test_directive_interpretation_validation():
    # no_op with applies=True is invalid
    with pytest.raises(ValidationError):
        DirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type="no_op",
            structured_adjustment=None,
            explanation="Invalid",
        )

    # solar_reduction without structured_adjustment is invalid
    with pytest.raises(ValidationError):
        DirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type="solar_reduction",
            structured_adjustment=None,
            explanation="Invalid",
        )


# --- 2. Replay Verifier Tests ---
def test_replay_verifier_valid_baseline():
    req = create_valid_request()
    directives = [
        DirectiveInterpretation(
            note_index=0,
            applies=False,
            directive_type="no_op",
            structured_adjustment=None,
            explanation="None",
        )
    ]

    # Construct clean physics-compliant plan (solar first, then grid, battery idle)
    plan = []
    for h in req.hours:
        solar_used = min(h.solar_kwh, h.demand_kwh)
        grid_used = h.demand_kwh - solar_used
        plan.append(
            HourlyPlanEntry(
                hour=h.hour,
                grid_kwh=grid_used,
                solar_used_kwh=solar_used,
                battery_action="idle",
                battery_kwh=0.0,
                battery_energy_after_kwh=req.battery.initial_energy_kwh,
            )
        )

    result = verify_and_recalculate_schedule(req, directives, plan)
    assert result.is_valid is True
    assert len(result.errors) == 0
    assert result.total_grid_kwh > 0
    assert result.total_cost_bdt > 0


def test_replay_verifier_detects_energy_balance_violation():
    req = create_valid_request()
    directives = []

    plan = []
    for h in req.hours:
        plan.append(
            HourlyPlanEntry(
                hour=h.hour,
                grid_kwh=0.0,  # Under-supplying demand!
                solar_used_kwh=0.0,
                battery_action="idle",
                battery_kwh=0.0,
                battery_energy_after_kwh=req.battery.initial_energy_kwh,
            )
        )

    result = verify_and_recalculate_schedule(req, directives, plan)
    assert result.is_valid is False
    assert any("Energy balance violation" in err for err in result.errors)


def test_replay_verifier_detects_neutrality_violation():
    req = create_valid_request()
    directives = []

    plan = []
    for h in req.hours:
        solar_used = min(h.solar_kwh, h.demand_kwh)
        grid_used = h.demand_kwh - solar_used
        # End at 150 kWh instead of initial 100 kWh
        bat_after = 150.0 if h.hour == 23 else req.battery.initial_energy_kwh
        plan.append(
            HourlyPlanEntry(
                hour=h.hour,
                grid_kwh=grid_used,
                solar_used_kwh=solar_used,
                battery_action="idle",
                battery_kwh=0.0,
                battery_energy_after_kwh=bat_after,
            )
        )

    result = verify_and_recalculate_schedule(req, directives, plan)
    assert result.is_valid is False
    assert any("neutrality" in err.lower() for err in result.errors)


def test_replay_verifier_detects_directive_violation():
    req = create_valid_request()
    directives = [
        DirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type="no_charge_window",
            structured_adjustment={"hours": [10, 11]},
            explanation="Prohibit charging from 10 to 12",
        )
    ]

    plan = []
    battery_level = req.battery.initial_energy_kwh
    for h in req.hours:
        solar_used = min(h.solar_kwh, h.demand_kwh)
        grid_used = h.demand_kwh - solar_used
        action = "idle"
        bat_kwh = 0.0

        # Intentionally violate on hour 10
        if h.hour == 10:
            action = "charge"
            bat_kwh = 20.0
            grid_used += 20.0
            battery_level += 20.0
        elif h.hour == 15:
            # Discharge back to maintain neutrality
            action = "discharge"
            bat_kwh = 20.0
            grid_used -= 20.0
            battery_level -= 20.0

        plan.append(
            HourlyPlanEntry(
                hour=h.hour,
                grid_kwh=grid_used,
                solar_used_kwh=solar_used,
                battery_action=action,
                battery_kwh=bat_kwh,
                battery_energy_after_kwh=battery_level,
            )
        )

    result = verify_and_recalculate_schedule(req, directives, plan)
    assert result.is_valid is False
    assert any("no_charge_window" in err for err in result.errors)


# --- 3. FastAPI Endpoint Tests ---
def test_health_route():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_optimize_energy_route_success():
    req = create_valid_request()
    response = client.post("/optimize-energy", json=req.model_dump())
    assert response.status_code == 200

    data = response.json()
    assert data["scenario_id"] == "TEST-SCENARIO-01"
    assert len(data["hourly_plan"]) == 24
    assert len(data["directive_interpretation"]) == len(req.operator_notes)
    assert data["total_grid_kwh"] >= 0.0
    assert data["total_cost_bdt"] >= 0.0
    assert data["peak_grid_kwh"] >= 0.0
    assert len(data["plan_summary"]) > 0


def test_optimize_energy_route_validation_error():
    # Send malformed payload (only 5 hours instead of 24)
    bad_payload = {
        "scenario_id": "BAD-01",
        "operator_notes": [],
        "hours": [
            {"hour": 0, "demand_kwh": 100, "solar_kwh": 0, "tariff_bdt_per_kwh": 5}
        ],
        "battery": {
            "capacity_kwh": 100,
            "initial_energy_kwh": 50,
            "minimum_energy_kwh": 10,
            "max_charge_kwh_per_hour": 20,
            "max_discharge_kwh_per_hour": 20,
        },
    }
    response = client.post("/optimize-energy", json=bad_payload)
    assert response.status_code == 422
    assert "detail" in response.json()


def test_optimize_energy_empty_notes():
    req = OptimizeEnergyRequest(
        scenario_id="EMPTY-NOTES-SCENARIO",
        operator_notes=[],
        hours=create_valid_hours(),
        battery=create_valid_battery(),
    )
    response = client.post("/optimize-energy", json=req.model_dump())
    assert response.status_code == 200
    data = response.json()
    assert data["scenario_id"] == "EMPTY-NOTES-SCENARIO"
    assert len(data["directive_interpretation"]) == 0
    assert len(data["hourly_plan"]) == 24


def test_all_10_public_sample_cases():
    """Execute all 10 sample cases from scripts/sample_cases.json through the API."""
    import json
    import os

    cases_file = os.path.join(os.path.dirname(__file__), "..", "scripts", "sample_cases.json")
    assert os.path.exists(cases_file), f"Missing {cases_file}"

    with open(cases_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    cases = data.get("cases", [])
    assert len(cases) == 10, f"Expected exactly 10 cases in sample_cases.json, got {len(cases)}"

    for idx, case_wrapper in enumerate(cases, 1):
        payload = case_wrapper.get("input", case_wrapper)
        scenario_id = payload.get("scenario_id", f"SAMPLE-{idx}")

        response = client.post("/optimize-energy", json=payload)
        assert response.status_code == 200, f"Case {scenario_id} failed with status {response.status_code}: {response.text}"

        res_data = response.json()
        assert res_data["scenario_id"] == scenario_id
        assert len(res_data["hourly_plan"]) == 24
        assert len(res_data["directive_interpretation"]) == len(payload.get("operator_notes", []))
        assert res_data["total_grid_kwh"] >= 0.0
        assert res_data["total_cost_bdt"] >= 0.0
        assert res_data["peak_grid_kwh"] >= 0.0
        assert len(res_data["plan_summary"]) > 0

        # Validate physics independently
        parsed_req = OptimizeEnergyRequest(**payload)
        parsed_dirs = [DirectiveInterpretation(**d) for d in res_data["directive_interpretation"]]
        parsed_plan = [HourlyPlanEntry(**p) for p in res_data["hourly_plan"]]

        replay_res = verify_and_recalculate_schedule(parsed_req, parsed_dirs, parsed_plan)
        assert replay_res.is_valid is True, f"Case {scenario_id} replay check failed: {replay_res.errors}"

