# 🤖 Team Member 1 Plan: LLM Interpretation & Deterministic Guardrails
**Focus Area:** Natural-Language Understanding, Prompt Engineering, Directive Guardrails & Safe Fallback  
**Estimated Time:** 4 Hours (Sprint 7:00 PM – 11:00 PM)

---

## 1. Exclusive File Ownership (Only Member 1 touches these files)
To avoid any Git merge conflict, **Member 1 exclusively owns**:
- `app/llm/interpreter.py` (Calls Google Gemini Flash API with structured schema)
- `app/llm/prompts.py` (System prompts, few-shot examples, directive definition rules)
- `app/guardrails/validator.py` (Deterministic validation, range checks, sorting hours, fallback)
- `tests/test_member1_llm.py` (Isolated unit tests for Member 1)

> ⚠️ **Rule:** Do not edit `app/schemas.py`, `app/optimizer/`, or `app/main.py`. Member 3 defines the schema, Member 2 builds the optimizer.

---

## 2. Input & Output Contract

### What You Receive (Input):
```python
operator_notes: List[str]  # e.g. ["PV will drop to 20% from 1 PM to 3 PM", "Cafeteria changes menu"]
battery_capacity_kwh: float  # e.g. 200.0 (needed if note specifies "50% of battery capacity")
```

### What You Must Return (Output):
A list of validated `DirectiveInterpretation` objects in exact `note_index` order `0..N-1`:
```python
[
    {
        "note_index": 0,
        "applies": True,
        "directive_type": "solar_reduction",
        "structured_adjustment": {
            "hours": [13, 14],  # Sorted ascending, unique integers 0..23
            "factor": 0.2       # Usable fraction (80% reduction = 0.2 factor)
        },
        "explanation": "Solar availability is reduced to 20% between 1 PM and 3 PM."
    },
    {
        "note_index": 1,
        "applies": False,
        "directive_type": "no_op",
        "structured_adjustment": None,
        "explanation": "This note does not affect today's energy schedule."
    }
]
```

---

## 3. The 6 Supported Directives & Extraction Logic

| Directive Type | When to Trigger | Required `structured_adjustment` |
| :--- | :--- | :--- |
| **`solar_reduction`** | Panel cleaning, dust, clouds, inverter work reducing PV. | `{"hours": [int], "factor": float}` *(0.0 ≤ factor ≤ 1.0)* |
| **`minimum_battery_reserve`** | Emergency backup, reserve holding, critical load protection. | `{"hours": [int], "minimum_energy_kwh": float}` |
| **`no_charge_window`** | Charger maintenance, inspection, isolated charging circuit. | `{"hours": [int]}` |
| **`no_discharge_window`** | Relay testing, protection testing, discharge disabled. | `{"hours": [int]}` |
| **`max_grid_window`** | Substation limit, transformer constraint, grid import cap. | `{"hours": [int], "max_grid_kwh": float}` |
| **`no_op`** | Cafeteria menus, student notices, library hours, distractors. | `null` (`applies: False`) |

---

## 4. Guardrail Rules You Must Deterministically Enforce

Even if the LLM hallucinates or returns sloppy JSON, your `validator.py` MUST fix or safely reject it:
1. **Index Order:** Entries must strictly follow `note_index`: `0, 1, ..., N-1`.
2. **Hour Formatting:**
   - Always unique integers `0 ≤ hour ≤ 23`.
   - Always strictly sorted in ascending order (`[13, 14]`, never `[14, 13]`).
   - Time window convention is start-inclusive, end-exclusive:
     - *"1 PM to 3 PM"* $\to$ `[13, 14]`
     - *"from noon until 2 PM"* $\to$ `[12, 13]`
     - *"from 6 PM until 10 PM"* $\to$ `[18, 19, 20, 21]`
3. **Solar Factor:** If note says *"drop to 20%"*, factor = `0.2`. If note says *"80% reduction"*, factor = `1.0 - 0.8 = 0.2`. Must be clamped to `[0.0, 1.0]`.
4. **Percentage to kWh Conversion:** If note says *"Keep at least 50% stored"*, calculate `0.5 * battery_capacity_kwh`.
5. **`applies` Semantics:**
   - If `directive_type == "no_op"`, then `applies = False` and `structured_adjustment = None`.
   - For all other 5 directive types, `applies = True` and `structured_adjustment` must be a valid dict.
6. **Safe Failure Mode:**
   - If LLM crashes, times out, or returns illegal JSON, **fallback to `no_op`** (`applies: False`, `null`). **Never crash the server or invent random directives!**

---

## 5. Step-by-Step Execution Plan (Hour by Hour)

### ⏱️ Hour 1 (7:00 PM – 7:45 PM): Prompt Engineering & Gemini Client
1. Set up `app/llm/interpreter.py` using `google-genai` SDK or official REST API.
2. In `app/llm/prompts.py`, write a strict system prompt with:
   - Clear definition of the 6 directives.
   - Pydantic response schema or JSON mode enforcement (`response_mime_type="application/json"`).
   - 3-4 few-shot examples covering solar reduction, percentage reserves, and distractors.

### ⏱️ Hour 2 (7:45 PM – 8:45 PM): Guardrail Validator & Normalizer
1. Write `app/guardrails/validator.py`:
   - Function `clean_and_validate_directives(raw_llm_output, battery_capacity)`.
   - Ensure every hour list is sorted and deduplicated.
   - Convert percentages to numeric kWh if the LLM output missed it.
   - Enforce `applies = False` for `no_op`.
2. Handle retry logic: If Gemini returns non-JSON, retry once with temperature 0. If it still fails, return safe `no_op`.

### ⏱️ Hour 3 (8:45 PM – 9:45 PM): Paraphrase Robustness & Edge Cases
Hidden test cases will use paraphrased language! Test your module against tricky phrasing:
- *"PV production will drop to about 20% between 13:00 and 15:00"* $\to$ `factor: 0.2`, `hours: [13, 14]`
- *"Panel washing from one until three will leave roughly one-fifth of normal solar output"* $\to$ `factor: 0.2`, `hours: [13, 14]`
- *"Expect an 80% reduction in rooftop solar during the 1-3 PM maintenance window"* $\to$ `factor: 0.2`, `hours: [13, 14]`
- *"The cafeteria menu changes tomorrow"* $\to$ `no_op`
- *"The library is extending book-return hours"* $\to$ `no_op`

### ⏱️ Hour 4 (9:45 PM – 10:45 PM): Integration Verification & Code Freeze
1. Coordinate with Member 3 to ensure your `interpret_operator_notes()` function plugs directly into `app/main.py`.
2. Run all 10 sample cases from `sample_cases.json` and verify 100% directive match.

---

## 6. How to Test Your Code in Complete Isolation
You do **not** need the server or the optimizer running to test your code! Run:
```bash
python -m unittest tests/test_member1_llm.py
```
*(Write tests that feed the 10 public sample notes directly to `interpret_operator_notes` and assert that the returned directive type, hours, and values match expected outputs).*
