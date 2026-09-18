# 👥 GridWise Team Action Plan — Master Index

Welcome to the 4-hour sprint execution roadmap for **BUP CSE Fest 2026 Hackathon**.

To ensure zero Git merge conflicts and complete independence during development, the workload has been strictly divided into 3 modular sub-plans:

| Member / Role | Focus Area | Exclusive File Ownership | Individual Plan Link |
| :--- | :--- | :--- | :--- |
| **Member 1** | **LLM & Guardrails Lead** | `app/llm/*`, `app/guardrails/*`, `tests/test_member1_llm.py` | 📄 [plan/team1.md](file:///d:/bup%20hackayhon/energy_optimizer/plan/team1.md) |
| **Member 2** | **Optimization & Physics Lead** | `app/optimizer/*`, `tests/test_member2_optimizer.py` | 📄 [plan/team2.md](file:///d:/bup%20hackayhon/energy_optimizer/plan/team2.md) |
| **Member 3** | **API, DevOps, QA & Video Lead** | `app/main.py`, `app/schemas.py`, `app/verifier/*`, `Dockerfile`, scripts | 📄 [plan/team3.md](file:///d:/bup%20hackayhon/energy_optimizer/plan/team3.md) |

---

## ⚡ Zero-Conflict Contract Architecture

```
Member 3 creates `schemas.py`
            │
            ├─────────────────────────────────────────┐
            ▼                                         ▼
   Member 1 (LLM Lead)                       Member 2 (Math Lead)
  - Input: operator_notes                   - Input: hours, battery, directives
  - Output: List[DirectiveInterpretation]   - Output: 24h Hourly Plan + Min Cost
            │                                         │
            └────────────────────┬────────────────────┘
                                 ▼
                       Member 3 (Integrator)
                      - Wires in `app/main.py`
                      - Runs `replay.py` verification
                      - Deploys & records 3-min video
```

Click on your individual plan link above to see your exact hourly deliverables, input/output data structures, and isolated test instructions!
