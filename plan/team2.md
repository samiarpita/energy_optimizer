# ⚡ Team Member 2 Plan: Mathematical Optimization & Energy Physics
**Focus Area:** Linear Programming (PuLP/CBC), Energy Balance, Battery Storage Dynamics & Schedule Generation  
**Estimated Time:** 4 Hours (Sprint 7:00 PM – 11:00 PM)

---

## 1. Exclusive File Ownership (Only Member 2 touches these files)
To avoid any Git merge conflict, **Member 2 exclusively owns**:
- `app/optimizer/lp_solver.py` (PuLP Linear Programming formulation and solver execution)
- `app/optimizer/rules.py` (Deterministic translation of directives into solver constraints)
- `tests/test_member2_optimizer.py` (Isolated unit tests for Member 2)

> ⚠️ **Rule:** Do not touch `app/llm/` or `app/main.py`. You do not need real LLM responses to test your code; you can use mock/sample directives directly from `sample_cases.json`.

---

## 2. Input & Output Contract

### What You Receive (Input):
```python
hours: List[HourEntry]              # 24 items: [hour, demand_kwh, solar_kwh, tariff_bdt_per_kwh]
battery: BatteryInfo                # capacity_kwh, initial_energy_kwh, minimum_energy_kwh, 
                                    # max_charge_kwh_per_hour, max_discharge_kwh_per_hour
directives: List[DirectiveInterpretation] # Validated directives from Member 1
```

### What You Must Return (Output):
An optimization result object:
```python
{
    "hourly_plan": [
        {
            "hour": 0,
            "grid_kwh": 90.0,
            "solar_used_kwh": 0.0,
            "battery_action": "idle",      # Must be one of: "charge", "discharge", "idle"
            "battery_kwh": 0.0,           # Non-negative, 0.0 when idle
            "battery_energy_after_kwh": 110.0 # Energy level at the end of this hour
        },
        # ... 23 more hourly entries for hours 1 to 23 ...
    ],
    "total_grid_kwh": 2692.5,             # Sum of grid_kwh across all 24 hours
    "total_cost_bdt": 38365.0,            # Sum of (grid_kwh[h] * tariff_bdt_per_kwh[h])
    "peak_grid_kwh": 175.0,               # Maximum hourly grid_kwh
    "plan_summary": "Optimized 24-hour schedule minimizing total grid cost while respecting all battery constraints and operator directives."
}
```

---

## 3. Mathematical Optimization Formulation (PuLP / SciPy)

### 3.1 Decision Variables (for $h = 0 \dots 23$):
- $grid\_kwh[h] \ge 0$ (Continuous)
- $solar\_used\_kwh[h] \ge 0$ (Continuous)
- $charge\_kwh[h] \ge 0$ (Continuous)
- $discharge\_kwh[h] \ge 0$ (Continuous)
- $battery\_energy[h]$ (Continuous, energy at end of hour $h$)

### 3.2 Objective Function:
Minimize the total grid electricity cost over the 24-hour horizon:
$$\min \sum_{h=0}^{23} \left( grid\_kwh[h] \times tariff\_bdt\_per\_kwh[h] \right)$$

### 3.3 Core Constraints:
1. **Energy Balance (Every Hour):**
   $$grid\_kwh[h] + solar\_used\_kwh[h] + discharge\_kwh[h] = demand\_kwh[h] + charge\_kwh[h]$$
2. **Solar Curtailment Limit:**
   $$0 \le solar\_used\_kwh[h] \le effective\_solar[h]$$
   *(Note: Grid export is not allowed; unused solar is simply curtailed).*
3. **Battery State Transition:**
   - For $h = 0$: $battery\_energy[0] = initial\_energy\_kwh + charge\_kwh[0] - discharge\_kwh[0]$
   - For $h = 1 \dots 23$: $battery\_energy[h] = battery\_energy[h-1] + charge\_kwh[h] - discharge\_kwh[h]$
4. **Battery Energy Bounds:**
   $$effective\_min\_reserve[h] \le battery\_energy[h] \le capacity\_kwh$$
5. **Hourly Charge / Discharge Rate Limits:**
   $$charge\_kwh[h] \le max\_charge\_kwh\_per\_hour$$
   $$discharge\_kwh[h] \le max\_discharge\_kwh\_per\_hour$$
6. **End-of-Day Neutrality (Crucial Rule!):**
   $$battery\_energy[23] = initial\_energy\_kwh$$
   *(The battery cannot end the day at a lower state of charge than it started).*

---

## 4. How to Translate Operator Directives into Constraints

In `app/optimizer/rules.py`, apply directive modifications **before** solving:

| Directive | Code Effect on Math Model |
| :--- | :--- |
| `solar_reduction` | For $h \in hours$: $effective\_solar[h] = original\_solar[h] \times factor$ |
| `minimum_battery_reserve` | For $h \in hours$: $effective\_min\_reserve[h] = \max(base\_min, directive\_min)$ |
| `no_charge_window` | For $h \in hours$: $charge\_kwh[h] == 0$ |
| `no_discharge_window` | For $h \in hours$: $discharge\_kwh[h] == 0$ |
| `max_grid_window` | For $h \in hours$: $grid\_kwh[h] \le max\_grid\_kwh$ |
| `no_op` | Do nothing. |

---

## 5. Action Determination Post-Processing
After solving the LP:
```python
for h in range(24):
    c = value(charge_kwh[h])
    d = value(discharge_kwh[h])
    
    if c > 0.001:
        action = "charge"
        mag = c
    elif d > 0.001:
        action = "discharge"
        mag = d
    else:
        action = "idle"
        mag = 0.0
```

---

## 6. Step-by-Step Execution Plan (Hour by Hour)

### ⏱️ Hour 1 (7:00 PM – 7:45 PM): Base PuLP Linear Model
1. Install `pulp`. Create `app/optimizer/lp_solver.py`.
2. Implement standard 24-hour solver with zero directives:
   - Formulate variables, objective, energy balance, battery transitions, rate limits, and end-of-day neutrality.
   - Verify it solves in <20ms using CBC default solver.

### ⏱️ Hour 2 (7:45 PM – 8:45 PM): Directive Integration (`rules.py`)
1. In `app/optimizer/rules.py`, write helper function `apply_directives(hours, battery, directives)`.
2. Add support for all 5 active directives:
   - Solar reduction scaling factor.
   - Dynamic minimum reserve per hour.
   - Force charge/discharge variables to 0 for window hours.
   - Grid import caps.

### ⏱️ Hour 3 (8:45 PM – 9:45 PM): Validation on 10 Public Cases
1. Create `tests/test_member2_optimizer.py`.
2. Load the 10 public test cases from `sample_cases.json`.
3. Feed the expected directives and input scenario into your solver.
4. Verify that:
   - Energy balance error $< 0.01$ kWh for all 24 hours.
   - `battery_energy_after_kwh[23] == initial_energy_kwh` (within 0.01 tolerance).
   - Recalculated total cost matches the reference optimal cost within tolerance.

### ⏱️ Hour 4 (9:45 PM – 10:45 PM): Summary Generation & Code Freeze
1. Write a short dynamic generator for `plan_summary` (e.g. *"Reduces grid cost by discharging during peak tariff hours (18-20) and charges during low-cost morning hours while respecting all directives."*).
2. Clean up code, remove debug prints, ensure execution takes under 50ms.

---

## 7. How to Test Your Code in Complete Isolation
Run:
```bash
python -m unittest tests/test_member2_optimizer.py
```
*(Write tests that run all 10 sample cases with ground-truth directives and verify optimal cost and physics validity).*
