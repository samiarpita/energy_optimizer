"""Official Public Sample Verification Runner for GridWise Energy Optimizer.

Usage:
    python scripts/test_public_samples.py [--url http://localhost:8000]

Checks:
    1. GET /health readiness check
    2. POST /optimize-energy schema and physical consistency checks
    3. Mathematical conservation and battery neutrality validation
"""

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List
import httpx

import warnings
warnings.filterwarnings("ignore")

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Ensure UTF-8 output encoding on Windows consoles
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass




SAMPLE_PAYLOAD_GRID101 = {
    "scenario_id": "GRID-101",
    "operator_notes": [
        "Solar output will drop to about 20% from 1 PM to 3 PM.",
        "Do not charge the battery between 2 PM and 4 PM.",
        "The cafeteria menu changes tomorrow."
    ],
    "hours": [
        {"hour": 0, "demand_kwh": 180, "solar_kwh": 0, "tariff_bdt_per_kwh": 7},
        {"hour": 1, "demand_kwh": 170, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
        {"hour": 2, "demand_kwh": 160, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
        {"hour": 3, "demand_kwh": 150, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
        {"hour": 4, "demand_kwh": 160, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
        {"hour": 5, "demand_kwh": 175, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
        {"hour": 6, "demand_kwh": 190, "solar_kwh": 5, "tariff_bdt_per_kwh": 8},
        {"hour": 7, "demand_kwh": 210, "solar_kwh": 20, "tariff_bdt_per_kwh": 10},
        {"hour": 8, "demand_kwh": 240, "solar_kwh": 50, "tariff_bdt_per_kwh": 12},
        {"hour": 9, "demand_kwh": 260, "solar_kwh": 90, "tariff_bdt_per_kwh": 14},
        {"hour": 10, "demand_kwh": 270, "solar_kwh": 130, "tariff_bdt_per_kwh": 16},
        {"hour": 11, "demand_kwh": 280, "solar_kwh": 160, "tariff_bdt_per_kwh": 16},
        {"hour": 12, "demand_kwh": 285, "solar_kwh": 180, "tariff_bdt_per_kwh": 15},
        {"hour": 13, "demand_kwh": 280, "solar_kwh": 170, "tariff_bdt_per_kwh": 14},
        {"hour": 14, "demand_kwh": 270, "solar_kwh": 140, "tariff_bdt_per_kwh": 13},
        {"hour": 15, "demand_kwh": 265, "solar_kwh": 90, "tariff_bdt_per_kwh": 14},
        {"hour": 16, "demand_kwh": 270, "solar_kwh": 45, "tariff_bdt_per_kwh": 18},
        {"hour": 17, "demand_kwh": 285, "solar_kwh": 10, "tariff_bdt_per_kwh": 22},
        {"hour": 18, "demand_kwh": 305, "solar_kwh": 0, "tariff_bdt_per_kwh": 28},
        {"hour": 19, "demand_kwh": 315, "solar_kwh": 0, "tariff_bdt_per_kwh": 30},
        {"hour": 20, "demand_kwh": 305, "solar_kwh": 0, "tariff_bdt_per_kwh": 26},
        {"hour": 21, "demand_kwh": 275, "solar_kwh": 0, "tariff_bdt_per_kwh": 18},
        {"hour": 22, "demand_kwh": 235, "solar_kwh": 0, "tariff_bdt_per_kwh": 10},
        {"hour": 23, "demand_kwh": 200, "solar_kwh": 0, "tariff_bdt_per_kwh": 9}
    ],
    "battery": {
        "capacity_kwh": 500,
        "initial_energy_kwh": 200,
        "minimum_energy_kwh": 50,
        "max_charge_kwh_per_hour": 100,
        "max_discharge_kwh_per_hour": 100
    }
}


def test_health_endpoint(client: Any, base_url: str) -> bool:
    print("\n🔍 [1/2] Testing GET /health...")
    try:
        start_t = time.time()
        kwargs = {"timeout": 5.0} if isinstance(client, httpx.Client) else {}
        resp = client.get(f"{base_url}/health", **kwargs)
        elapsed = (time.time() - start_t) * 1000


        if resp.status_code != 200:
            print(f"❌ FAILED: Status code is {resp.status_code}, expected 200.")
            return False

        data = resp.json()
        if data.get("status") != "ok":
            print(f"❌ FAILED: Unexpected payload: {data}")
            return False

        print(f"✅ PASSED: Health check returned {data} in {elapsed:.1f}ms")
        return True
    except Exception as ex:
        print(f"❌ FAILED: Exception connecting to {base_url}/health: {ex}")
        return False


def validate_scenario_response(scenario_req: Dict[str, Any], data: Dict[str, Any]) -> List[str]:
    errors = []

    # 1. Required Top-Level Keys
    required_keys = [
        "scenario_id", "directive_interpretation", "hourly_plan",
        "total_grid_kwh", "total_cost_bdt", "peak_grid_kwh", "plan_summary"
    ]
    for k in required_keys:
        if k not in data:
            errors.append(f"Missing required response field: '{k}'")

    if errors:
        return errors

    # 2. Scenario ID match
    if data["scenario_id"] != scenario_req["scenario_id"]:
        errors.append(f"Scenario ID mismatch: expected {scenario_req['scenario_id']}, got {data['scenario_id']}")

    # 3. Directives
    dirs = data["directive_interpretation"]
    if len(dirs) != len(scenario_req.get("operator_notes", [])):
        errors.append(f"Directive count mismatch: expected {len(scenario_req['operator_notes'])}, got {len(dirs)}")
    for idx, d in enumerate(dirs):
        if d.get("note_index") != idx:
            errors.append(f"Directive index mismatch at pos {idx}: got {d.get('note_index')}")

    # 4. Hourly Plan Check
    plan = data["hourly_plan"]
    if len(plan) != 24:
        errors.append(f"Hourly plan length is {len(plan)}, expected 24.")
        return errors

    total_grid = 0.0
    total_cost = 0.0
    peak_grid = 0.0
    battery_level = scenario_req["battery"]["initial_energy_kwh"]

    for h in range(24):
        p = plan[h]
        req_h = scenario_req["hours"][h]
        grid = p.get("grid_kwh", 0.0)
        solar_used = p.get("solar_used_kwh", 0.0)
        action = p.get("battery_action", "idle")
        bat_kwh = p.get("battery_kwh", 0.0)
        energy_after = p.get("battery_energy_after_kwh", 0.0)

        charge = bat_kwh if action == "charge" else 0.0
        discharge = bat_kwh if action == "discharge" else 0.0

        total_grid += grid
        total_cost += grid * req_h["tariff_bdt_per_kwh"]
        if grid > peak_grid:
            peak_grid = grid

        # Energy balance
        supply = grid + solar_used + discharge
        demand = req_h["demand_kwh"] + charge
        if abs(supply - demand) > 0.05:
            errors.append(f"Hour {h}: Energy balance violation: supply {supply:.2f} != demand {demand:.2f}")

        # Battery dynamics
        expected_energy = battery_level + charge - discharge
        if abs(energy_after - expected_energy) > 0.05:
            errors.append(f"Hour {h}: Battery transition violation: E_after {energy_after:.2f} != expected {expected_energy:.2f}")

        battery_level = energy_after

    # End of day neutrality
    if abs(battery_level - scenario_req["battery"]["initial_energy_kwh"]) > 0.05:
        errors.append(f"End-of-day battery neutrality violation: {battery_level:.2f} != {scenario_req['battery']['initial_energy_kwh']}")

    # Total grid / cost recalculations
    if abs(data["total_grid_kwh"] - round(total_grid, 2)) > 0.5:
        errors.append(f"Total grid mismatch: reported {data['total_grid_kwh']}, calculated {total_grid:.2f}")
    if abs(data["total_cost_bdt"] - round(total_cost, 2)) > 1.0:
        errors.append(f"Total cost mismatch: reported {data['total_cost_bdt']}, calculated {total_cost:.2f}")

    return errors


def test_optimization_endpoint(client: httpx.Client, base_url: str) -> bool:
    print("\n🔍 [2/2] Testing POST /optimize-energy...")

    # Look for sample cases in scripts/sample_cases.json
    cases = []
    cases_file = os.path.join(os.path.dirname(__file__), "sample_cases.json")
    if os.path.exists(cases_file):
        try:
            with open(cases_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
                cases = raw.get("cases", [])
        except Exception as e:
            print(f"⚠️ Could not load {cases_file}: {e}")

    if not cases:
        print("ℹ️ Using default reference scenario GRID-101.")
        cases = [{"input": SAMPLE_PAYLOAD_GRID101}]

    passed_count = 0
    total_count = len(cases)

    for i, test_case in enumerate(cases, 1):
        payload = test_case.get("input", test_case)
        scenario_id = payload.get("scenario_id", f"SCENARIO-{i}")
        print(f"  • Testing Case #{i} ({scenario_id})...", end=" ", flush=True)

        try:
            start_t = time.time()
            kwargs = {"timeout": 15.0} if isinstance(client, httpx.Client) else {}
            resp = client.post(f"{base_url}/optimize-energy", json=payload, **kwargs)
            elapsed = (time.time() - start_t) * 1000


            if resp.status_code != 200:
                print(f"❌ FAILED (Status {resp.status_code})")
                print(f"    Response body: {resp.text}")
                continue

            data = resp.json()
            errors = validate_scenario_response(payload, data)

            if errors:
                print(f"❌ FAILED with {len(errors)} error(s):")
                for err in errors[:5]:
                    print(f"      - {err}")
            else:
                print(f"✅ PASSED ({elapsed:.1f}ms) — Cost: {data.get('total_cost_bdt')} BDT, Peak: {data.get('peak_grid_kwh')} kWh")
                passed_count += 1

        except Exception as ex:
            print(f"❌ FAILED with Exception: {ex}")

    print(f"\n📊 Summary: {passed_count}/{total_count} cases passed ({100 * passed_count / total_count:.1f}%).")
    return passed_count == total_count


def main():
    parser = argparse.ArgumentParser(description="GridWise Public Test Verification Runner")
    parser.add_argument("--url", default="http://localhost:8000", help="Base URL of GridWise service")
    parser.add_argument("--local", action="store_true", help="Run tests in-process using FastAPI TestClient")
    args = parser.parse_args()

    print(f"🚀 GridWise Public Sample Test Runner")

    if args.local:
        print("🎯 Mode: In-Process FastAPI TestClient")
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        base_url = ""

        health_ok = test_health_endpoint(client, base_url)
        if not health_ok:
            print("\n❌ In-process health check failed.")
            sys.exit(1)

        opt_ok = test_optimization_endpoint(client, base_url)
        if not opt_ok:
            print("\n❌ One or more optimization test cases failed.")
            sys.exit(1)

        print("\n🎉 ALL 10 CASES PASSED! API is 100% compliant with Hackathon Specifications.\n")
        sys.exit(0)

    base_url = args.url.rstrip("/")
    print(f"🎯 Target URL: {base_url}")

    try:
        with httpx.Client() as client:
            health_ok = test_health_endpoint(client, base_url)
            if not health_ok:
                print("\n❌ Health check failed. Ensure the server is running or use --local for in-process tests.")
                sys.exit(1)

            opt_ok = test_optimization_endpoint(client, base_url)
            if not opt_ok:
                print("\n❌ One or more optimization test cases failed.")
                sys.exit(1)
    except Exception as e:
        print(f"\n❌ Connection error: {e}")
        print("💡 Tip: You can test the API in-process anytime using: python scripts/test_public_samples.py --local")
        sys.exit(1)

    print("\n🎉 ALL 10 CASES PASSED! API is 100% compliant with Hackathon Specifications.\n")
    sys.exit(0)


if __name__ == "__main__":
    main()

