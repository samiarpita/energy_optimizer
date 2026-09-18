# 🚀 Team Member 3 Plan: API Architecture, Replay Verifier, DevOps & Video
**Focus Area:** FastAPI Endpoints, Pipeline Integration, Independent Schedule Verifier, Cloud Deployment & 3-Min Video  
**Estimated Time:** 4 Hours (Sprint 7:00 PM – 11:00 PM)

---

## 1. Exclusive File Ownership (Only Member 3 touches these files)
To avoid any Git merge conflict, **Member 3 exclusively owns**:
- `app/main.py` (FastAPI app, routes `/health` and `/optimize-energy`, controlled error handling)
- `app/schemas.py` (Pydantic models for request & response matching Sections 07 & 10)
- `app/verifier/replay.py` (Independent replay validator that checks constraints before returning)
- `scripts/test_public_samples.py` (Official public test runner)
- `Dockerfile` & `.dockerignore` (Container image setup)
- `docs/video_script.md` (3-minute video presentation script)

> ⚠️ **Rule:** Member 3 acts as the Project Architect. You define the schemas first, connect Member 1 and Member 2's code together, and handle deployment and video.

---

## 2. Shared Canonical Contracts (`app/schemas.py`)
In the first 30 minutes, Member 3 must create `app/schemas.py` so Member 1 and Member 2 have identical types to import:
- `OptimizeEnergyRequest` (Fields: `scenario_id`, `operator_notes`, `hours`, `battery`)
- `HourEntry` (Fields: `hour`, `demand_kwh`, `solar_kwh`, `tariff_bdt_per_kwh`)
- `BatteryInfo` (Fields: `capacity_kwh`, `initial_energy_kwh`, `minimum_energy_kwh`, `max_charge_kwh_per_hour`, `max_discharge_kwh_per_hour`)
- `DirectiveInterpretation` (Fields: `note_index`, `applies`, `directive_type`, `structured_adjustment`, `explanation`)
- `HourlyPlanEntry` (Fields: `hour`, `grid_kwh`, `solar_used_kwh`, `battery_action`, `battery_kwh`, `battery_energy_after_kwh`)
- `OptimizeEnergyResponse` (Fields: `scenario_id`, `directive_interpretation`, `hourly_plan`, `total_grid_kwh`, `total_cost_bdt`, `peak_grid_kwh`, `plan_summary`)

---

## 3. Independent Replay Verifier (`app/verifier/replay.py`)
Before sending any response to the judge, this module simulates the plan independently:
1. **Hourly Check:**
   - Check energy balance: $|(grid + solar\_used + discharge) - (demand + charge)| \le 0.01$.
   - Check solar limit: $solar\_used \le effective\_solar + 0.01$.
   - Check battery limits: $E\_after \le capacity$, $E\_after \ge min\_reserve$, $battery\_kwh \le rate\_limit$.
2. **End-of-Day Check:**
   - Confirm $|E\_after[23] - initial\_energy| \le 0.01$.
3. **Directive Verification:**
   - If `no_charge_window` active, confirm $charge == 0$.
   - If `no_discharge_window` active, confirm $discharge == 0$.
   - If `max_grid_window` active, confirm $grid \le cap$.
4. **Recalculation:**
   - Recompute `total_grid_kwh = sum(grid_kwh)`.
   - Recompute `total_cost_bdt = sum(grid_kwh * tariff)`.
   - Recompute `peak_grid_kwh = max(grid_kwh)`.

---

## 4. Step-by-Step Execution Plan (Hour by Hour)

### ⏱️ Hour 1 (7:00 PM – 7:45 PM): Schemas & Basic API Skeleton
1. Initialize Git repo and `.gitignore`.
2. Write `app/schemas.py` with strict Pydantic v2 validation.
3. Write `app/main.py`:
   - `GET /health` returning `{"status": "ok"}` (Status 200).
   - `POST /optimize-energy` (stub returning mock response).
4. Verify Swagger UI works at `http://localhost:8000/docs`.

### ⏱️ Hour 2 (7:45 PM – 8:45 PM): Integration & Replay Verifier
1. Connect Member 1's function:
   ```python
   directives = interpret_operator_notes(req.operator_notes, req.battery.capacity_kwh)
   ```
2. Connect Member 2's function:
   ```python
   plan_result = solve_energy_optimization(req.hours, req.battery, directives)
   ```
3. Implement `app/verifier/replay.py`:
   - Call `verify_schedule(req, directives, plan_result)`.
   - If recalculation has rounding differences, overwrite totals with the recomputed values.
4. Assemble and return `OptimizeEnergyResponse`.

### ⏱️ Hour 3 (8:45 PM – 9:45 PM): Cloud Deployment & Docker Hub Push
1. **Dockerfile:** Write clean multi-stage Python 3.11 Dockerfile.
   - Expose port `8000`, bind to `0.0.0.0`.
2. **Build & Test Local Docker:**
   ```bash
   docker build -t gridwise:test .
   docker run -p 8000:8000 -e GEMINI_API_KEY="..." gridwise:test
   curl http://localhost:8000/health
   ```
3. **Push to Docker Hub:**
   ```bash
   docker tag gridwise:test <USERNAME>/gridwise-optimizer:latest
   docker push <USERNAME>/gridwise-optimizer:latest
   ```
4. **Deploy Live API:**
   - Deploy on **Render / Railway / Koyeb** (or cloud VM with public IP).
   - Test external reachability from mobile phone or outside WiFi:
     `curl https://<YOUR-DEPLOYED-URL>/health`

### ⏱️ Hour 4 (9:45 PM – 10:45 PM): Public Testing, 3-Min Video & Submission
1. Run `python scripts/test_public_samples.py` against both localhost and the live deployed public URL. Confirm all 10 cases score 100%.
2. **Record 3-Minute Architecture Video (Tie-breaker #1):**
   - **Minute 0:00 - 0:45:** Introduce team, problem understanding (GridWise smart campus scheduling + operator note parsing).
   - **Minute 0:45 - 1:45:** Architecture walkthrough: LLM prompt & schema $\to$ Deterministic guardrail $\to$ PuLP Linear Programming solver $\to$ Replay validator.
   - **Minute 1:45 - 2:45:** Live demonstration: Send a sample request via Swagger UI or cURL, show health check, show optimal schedule output.
   - **Minute 2:45 - 3:00:** Show Docker container running and conclusion. Keep strictly under 3 minutes!
3. Upload video to Google Drive / YouTube (unlisted) and ensure permissions are set to *"Anyone with the link can view"*.

---

## 5. Pre-Submission Checklist (10:45 PM)

- [ ] `GET /health` returns `{"status": "ok"}` on the public URL.
- [ ] `POST /optimize-energy` returns valid responses on the public URL.
- [ ] Docker image is pullable (`docker pull <USERNAME>/gridwise-optimizer:latest`).
- [ ] No API keys, `.env`, or secrets committed in Git (`git status`, check commits).
- [ ] Video is uploaded, accessible, and strictly $\le$ 3:00 minutes.
- [ ] Keep GitHub repository **PRIVATE** until 11:00 PM, then make it **PUBLIC** for evaluation.
