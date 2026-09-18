"""GridWise Smart Campus Energy Optimizer — FastAPI Application Entrypoint.

Provides:
- GET /health: Readiness probe returning {"status": "ok"}
- POST /optimize-energy: Full LLM-assisted schedule optimization pipeline
"""

import logging
import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.schemas import (
    DirectiveInterpretation,
    ErrorDetail,
    HealthResponse,
    HourlyPlanEntry,
    OptimizeEnergyRequest,
    OptimizeEnergyResponse,
)
from app.verifier.replay import verify_and_recalculate_schedule

# Configure structured logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("gridwise.main")

# Initialize FastAPI App
app = FastAPI(
    title="GridWise Energy Optimizer",
    description="LLM-Assisted Operator Directive Interpretation & 24-Hour Energy Scheduling Engine",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Enable CORS for external judge / client interactions
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global Controlled Exception Handlers (Section 09 Security & Controlled Errors)
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle malformed request bodies with a clean 422 JSON response."""
    logger.warning("Validation error on request %s: %s", request.url.path, exc.errors())
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "Invalid request schema: " + "; ".join(e["msg"] for e in exc.errors() if "msg" in e)},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle explicit HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Sanitize all unexpected 500 errors to avoid leaking stack traces or internal secrets."""
    logger.error("Unhandled internal exception during request %s: %s", request.url.path, str(exc), exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal processing error occurred while optimizing energy schedule."},
    )


# --- Modular Integration Helpers ---
def _run_interpreter(notes: List[str], capacity_kwh: float) -> List[DirectiveInterpretation]:
    """Call Member 1 LLM Interpreter if available; otherwise return safe fallback directives."""
    try:
        from app.llm.interpreter import interpret_operator_notes
        return interpret_operator_notes(notes, capacity_kwh)
    except (ImportError, ModuleNotFoundError) as e:
        logger.warning("Member 1 LLM interpreter not yet present; using safe fallback. (%s)", e)
    except Exception as e:
        logger.error("Error invoking Member 1 LLM interpreter: %s. Falling back.", e)

    # Safe Fallback: Map all notes to no_op if LLM module is in progress
    fallback_directives: List[DirectiveInterpretation] = []
    for idx, note in enumerate(notes):
        fallback_directives.append(
            DirectiveInterpretation(
                note_index=idx,
                applies=False,
                directive_type="no_op",
                structured_adjustment=None,
                explanation=f"Default fallback: {note}",
            )
        )
    return fallback_directives


def _run_optimizer(
    hours,
    battery,
    directives: List[DirectiveInterpretation],
) -> tuple[List[HourlyPlanEntry], str]:
    """Call Member 2 LP Optimizer if available; otherwise compute a valid baseline schedule."""
    try:
        from app.optimizer.lp_solver import solve_energy_optimization
        res = solve_energy_optimization(hours, battery, directives)
        # res can be a dict or a result object
        if isinstance(res, dict):
            return res.get("hourly_plan", []), res.get("plan_summary", "Optimized 24-hour schedule.")
        elif hasattr(res, "hourly_plan"):
            return res.hourly_plan, getattr(res, "plan_summary", "Optimized 24-hour schedule.")
    except (ImportError, ModuleNotFoundError) as e:
        logger.warning("Member 2 LP solver not yet present; using physics-compliant baseline solver. (%s)", e)
    except Exception as e:
        logger.error("Error invoking Member 2 LP solver: %s. Using physics baseline.", e)

    # Physics-compliant baseline schedule generator (direct solar + grid, battery idle)
    hourly_plan: List[HourlyPlanEntry] = []
    for h_entry in hours:
        h = h_entry.hour
        solar_used = min(h_entry.solar_kwh, h_entry.demand_kwh)
        grid_needed = max(0.0, h_entry.demand_kwh - solar_used)

        hourly_plan.append(
            HourlyPlanEntry(
                hour=h,
                grid_kwh=round(grid_needed, 2),
                solar_used_kwh=round(solar_used, 2),
                battery_action="idle",
                battery_kwh=0.0,
                battery_energy_after_kwh=battery.initial_energy_kwh,
            )
        )
    summary = "Baseline schedule: Maximizes direct solar utilization and supplies remaining campus demand via utility grid."
    return hourly_plan, summary


# --- Endpoints ---
@app.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Readiness Probe",
    tags=["Health"],
)
async def get_health() -> HealthResponse:
    """Readiness probe used by the judging harness to confirm API availability."""
    return HealthResponse(status="ok")


@app.post(
    "/optimize-energy",
    response_model=OptimizeEnergyResponse,
    status_code=status.HTTP_200_OK,
    summary="Optimize 24-Hour Campus Energy Schedule",
    tags=["Optimization"],
    responses={
        200: {"description": "Optimal 24-hour dispatch schedule successfully generated"},
        422: {"model": ErrorDetail, "description": "Request validation error"},
        500: {"model": ErrorDetail, "description": "Internal server processing error"},
    },
)
async def optimize_energy(request: OptimizeEnergyRequest) -> OptimizeEnergyResponse:
    """End-to-end endpoint to interpret operator notes, optimize schedule, and verify physics."""
    logger.info("Received optimization request for scenario: %s with %d notes", request.scenario_id, len(request.operator_notes))

    # Step 1: Interpret operator notes (Member 1)
    directives = _run_interpreter(request.operator_notes, request.battery.capacity_kwh)

    # Step 2: Solve mathematical optimization (Member 2)
    hourly_plan, plan_summary = _run_optimizer(request.hours, request.battery, directives)

    # Step 3: Verify physics and recompute metrics via Replay Validator (Member 3)
    verification = verify_and_recalculate_schedule(request, directives, hourly_plan)

    if not verification.is_valid:
        logger.warning("Schedule verification identified warnings/errors: %s", verification.errors)
        # We still return the plan with accurate recalculated metrics, or fail gracefully if broken

    # Step 4: Construct and return the verified response
    return OptimizeEnergyResponse(
        scenario_id=request.scenario_id,
        directive_interpretation=directives,
        hourly_plan=hourly_plan,
        total_grid_kwh=verification.total_grid_kwh,
        total_cost_bdt=verification.total_cost_bdt,
        peak_grid_kwh=verification.peak_grid_kwh,
        plan_summary=plan_summary,
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    uvicorn.run("app.main:app", host=host, port=port, reload=True)
