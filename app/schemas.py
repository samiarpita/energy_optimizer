"""Canonical Pydantic Schemas for GridWise Energy Optimization Engine.

Defines all request, response, battery, directive, and hourly plan models
used across the FastAPI endpoints, LLM interpreter, LP solver, and Replay Verifier.
"""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class HourEntry(BaseModel):
    """Single hour energy metrics."""
    hour: int = Field(..., ge=0, le=23, description="Hour of the day (0-23)")
    demand_kwh: float = Field(..., ge=0.0, description="Campus electricity demand in kWh")
    solar_kwh: float = Field(..., ge=0.0, description="Forecasted rooftop solar generation in kWh")
    tariff_bdt_per_kwh: float = Field(..., ge=0.0, description="Grid tariff rate in BDT per kWh")


class BatteryInfo(BaseModel):
    """Battery energy storage system parameters."""
    capacity_kwh: float = Field(..., gt=0.0, description="Total battery storage capacity in kWh")
    initial_energy_kwh: float = Field(..., ge=0.0, description="Energy stored in battery at start of day (hour 0) in kWh")
    minimum_energy_kwh: float = Field(..., ge=0.0, description="Minimum reserve energy required in kWh")
    max_charge_kwh_per_hour: float = Field(..., ge=0.0, description="Maximum charging rate in kWh/hour")
    max_discharge_kwh_per_hour: float = Field(..., ge=0.0, description="Maximum discharging rate in kWh/hour")

    @model_validator(mode="after")
    def validate_battery_bounds(self) -> "BatteryInfo":
        if self.initial_energy_kwh > self.capacity_kwh:
            raise ValueError("initial_energy_kwh cannot exceed capacity_kwh")
        if self.minimum_energy_kwh > self.capacity_kwh:
            raise ValueError("minimum_energy_kwh cannot exceed capacity_kwh")
        if self.initial_energy_kwh < self.minimum_energy_kwh:
            raise ValueError("initial_energy_kwh cannot be less than minimum_energy_kwh")
        return self


class OptimizeEnergyRequest(BaseModel):
    """Payload for POST /optimize-energy."""
    scenario_id: str = Field(..., min_length=1, description="Unique scenario identifier, e.g. GRID-101")
    operator_notes: List[str] = Field(default_factory=list, description="List of 1-3 natural-language operator notes")
    hours: List[HourEntry] = Field(..., min_length=24, max_length=24, description="Exact 24-hour profile (hours 0 to 23)")
    battery: BatteryInfo = Field(..., description="Battery specifications and operational limits")

    @field_validator("hours")
    @classmethod
    def validate_24_hours(cls, v: List[HourEntry]) -> List[HourEntry]:
        if len(v) != 24:
            raise ValueError("Request must contain exactly 24 hourly entries")
        hours_seen = [h.hour for h in v]
        if hours_seen != list(range(24)):
            raise ValueError("Hourly entries must be sequential from hour 0 to 23")
        return v


DirectiveType = Literal[
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op"
]


class DirectiveInterpretation(BaseModel):
    """Structured interpretation of a single operator note."""
    note_index: int = Field(..., ge=0, description="Zero-based index corresponding to operator_notes input")
    applies: bool = Field(..., description="True if the note impacts energy operations, False if distractor/irrelevant")
    directive_type: DirectiveType = Field(..., description="Canonical directive classification")
    structured_adjustment: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Structured parameter dictionary (hours, factor, minimum_energy_kwh, max_grid_kwh)"
    )
    explanation: str = Field(..., min_length=1, description="Concise human-readable rationale for the interpretation")

    @model_validator(mode="after")
    def validate_directive_semantics(self) -> "DirectiveInterpretation":
        if self.directive_type == "no_op":
            if self.applies:
                raise ValueError("no_op directive must have applies=False")
            if self.structured_adjustment is not None:
                raise ValueError("no_op directive must have structured_adjustment=None")
        else:
            if not self.applies:
                raise ValueError(f"Directive {self.directive_type} must have applies=True")
            if self.structured_adjustment is None:
                raise ValueError(f"Directive {self.directive_type} must include structured_adjustment dict")
        return self


BatteryAction = Literal["charge", "discharge", "idle"]


class HourlyPlanEntry(BaseModel):
    """Single hour scheduled energy flows."""
    hour: int = Field(..., ge=0, le=23, description="Hour of the day (0-23)")
    grid_kwh: float = Field(..., ge=0.0, description="Energy imported from the utility grid in kWh")
    solar_used_kwh: float = Field(..., ge=0.0, description="Solar generation consumed or charged in kWh")
    battery_action: BatteryAction = Field(..., description="Action taken by battery: 'charge', 'discharge', or 'idle'")
    battery_kwh: float = Field(..., ge=0.0, description="Magnitude of energy charged or discharged in kWh (0.0 if idle)")
    battery_energy_after_kwh: float = Field(..., ge=0.0, description="Energy stored in battery at the end of the hour in kWh")


class OptimizeEnergyResponse(BaseModel):
    """Full optimization response payload matching Hackathon specifications."""
    scenario_id: str = Field(..., description="Echo of request scenario_id")
    directive_interpretation: List[DirectiveInterpretation] = Field(..., description="List of interpreted operator notes in order")
    hourly_plan: List[HourlyPlanEntry] = Field(..., min_length=24, max_length=24, description="Optimal 24-hour dispatch schedule")
    total_grid_kwh: float = Field(..., ge=0.0, description="Sum of grid imports over 24 hours in kWh")
    total_cost_bdt: float = Field(..., ge=0.0, description="Total electricity cost over 24 hours in BDT")
    peak_grid_kwh: float = Field(..., ge=0.0, description="Maximum hourly grid import across the 24 hours in kWh")
    plan_summary: str = Field(..., min_length=1, description="Executive summary describing the optimization strategy")


class HealthResponse(BaseModel):
    """Readiness probe response model."""
    status: Literal["ok"] = "ok"


class ErrorDetail(BaseModel):
    """Controlled error response structure."""
    detail: str
