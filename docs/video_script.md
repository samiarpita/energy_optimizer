# 🎬 GridWise 3-Minute Architecture & Demonstration Video Script
**Competition:** BUP CSE Fest 2026 Hackathon · Online Preliminary Round  
**Target Duration:** Exactly 2 minutes 50 seconds (Strict ceiling: 3:00 minutes)

---

## ⏱️ Video Timeline Breakdown

| Time Window | Segment | Visual On-Screen | Speaker & Key Talking Points |
| :--- | :--- | :--- | :--- |
| **0:00 – 0:45** | **Team Intro & Problem** | Title slide, Problem Overview graphic | Team greeting, problem context (smart campus 24h energy scheduling with unstructured notes). |
| **0:45 – 1:45** | **Architecture & Pipeline** | Architectural pipeline diagram | 4-stage pipeline: LLM reasoning $\to$ Guardrail $\to$ PuLP LP Solver $\to$ Replay Verifier. |
| **1:45 – 2:45** | **Live Demonstration** | Swagger UI (`/docs`) & cURL terminal | Health probe check (`GET /health`), send Scenario GRID-101, inspect returned schedule. |
| **2:45 – 3:00** | **DevOps & Conclusion** | Docker terminal & Cloud URL | Docker container run, public API check, final closing statement. |

---

## 🎙️ Verbatim Script

### 🕒 [0:00 – 0:45] Intro & Problem Understanding
*(Visual: Screen displays title slide with "GridWise — Smart Campus Energy Optimization Engine" and team member names).*

> **Speaker:**
> *"Hello respected judges and organizers of BUP CSE Fest 2026! We are Team GridWise.
> 
> Today, smart educational campuses produce localized solar energy and operate battery storage, but facility managers communicate unexpected operational constraints in unstructured natural language — such as panel cleanings, emergency backup reserves, or equipment testing.
> 
> The challenge is to automatically interpret these ambiguous notes, model 24 hours of solar, demand, and dynamic electricity tariffs, and generate an exact, cost-optimal dispatch schedule."*

---

### 🕒 [0:45 – 1:45] System Architecture & Zero-Drift Philosophy
*(Visual: Transition to the 4-Stage Architecture Diagram).*

> **Speaker:**
> *"To solve this with 100% reliability, we designed a zero-drift hybrid architecture combining AI reasoning with deterministic mathematical optimization:
> 
> 1. **LLM Directive Interpreter:** We leverage Google Gemini Flash with strict JSON schema enforcement to parse natural-language notes into structured directives while filtering out irrelevant distractors.
> 2. **Deterministic Guardrail Engine:** Treats LLM output as untrusted. It sorts hour arrays, validates bounds, and provides safe fallback if needed.
> 3. **Mathematical Optimizer (PuLP / CBC):** Formulates a 24-hour Linear Program that guarantees the global minimum electricity cost in under 20 milliseconds, strictly enforcing hourly energy balance and end-of-day battery neutrality.
> 4. **Independent Replay Verifier:** Simulates the schedule hour-by-hour before returning the HTTP response, verifying that every single constraint and directive is physically obeyed."*

---

### 🕒 [1:45 – 2:45] Live System Demonstration
*(Visual: Switch to Web Browser showing Swagger UI at `http://localhost:8000/docs`).*

> **Speaker:**
> *"Let's see GridWise in action.
> 
> First, we query `GET /health` — as you can see, it immediately responds with `status: ok`.
> 
> Next, let's execute `POST /optimize-energy` with Scenario `GRID-101`. Notice the operator notes include a solar drop between 1 PM and 3 PM, a battery charge prohibition from 2 PM to 4 PM, and a cafeteria menu distractor.
> 
> We execute the request:
> - In less than one second, the LLM correctly extracts the solar reduction and charging window while marking the cafeteria notice as `no_op`.
> - The PuLP solver schedules battery charging during low-cost morning tariff hours and discharges during evening peak tariff hours (6 PM to 8 PM).
> - The replay verifier recomputes total grid energy and cost with zero rounding discrepancy."*

---

### 🕒 [2:45 – 3:00] Deployment & Conclusion
*(Visual: Switch to terminal showing `docker run` or public deployed URL).*

> **Speaker:**
> *"Our service is containerized via a production multi-stage Dockerfile and deployed live with full OpenAPI documentation.
> 
> GridWise delivers the perfect bridge between natural-language understanding and exact energy physics. Thank you!"*

---

## 📋 Recording Checklist
- [ ] Screen resolution set to 1080p (1920x1080) at 100% scale.
- [ ] Clear audio with no background noise.
- [ ] Terminal font size enlarged for crisp readability.
- [ ] Timer running to ensure recording stops before 3:00 minutes.
- [ ] Export format: MP4 (H.264 / AAC).
