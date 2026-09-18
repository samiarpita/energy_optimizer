"""Deterministic Guardrails & Output Normalizer for LLM Directive Interpretations.

Guarantees that all LLM outputs satisfy the strict canonical schema:
- Deterministic index order (0..N-1)
- Ascending, deduplicated, bounded hour arrays [0..23]
- Proper numeric clamping for solar factors [0.0..1.0]
- Percentage-to-kWh conversions for battery reserve limits
- Strict applies / structured_adjustment semantics
- Safe non-destructive fallback to no_op
"""

import logging
from typing import Any, Dict, List, Optional
from app.schemas import DirectiveInterpretation, DirectiveType

logger = logging.getLogger("gridwise.guardrails")

VALID_DIRECTIVE_TYPES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
}


def _clean_hours(raw_hours: Any) -> List[int]:
    """Extract, deduplicate, clamp, and sort hours strictly in ascending order."""
    if not isinstance(raw_hours, list):
        return []
    valid = set()
    for h in raw_hours:
        try:
            val = int(h)
            if 0 <= val <= 23:
                valid.add(val)
        except (ValueError, TypeError):
            continue
    return sorted(list(valid))


def create_fallback_directives(
    notes: Optional[List[str]] = None,
    count: Optional[int] = None,
) -> List[DirectiveInterpretation]:
    """Create safe no_op fallback directives for any unhandled or corrupt state."""
    total = len(notes) if notes is not None else (count or 0)
    fallbacks: List[DirectiveInterpretation] = []
    for idx in range(total):
        note_text = notes[idx] if notes and idx < len(notes) else f"Note {idx}"
        fallbacks.append(
            DirectiveInterpretation(
                note_index=idx,
                applies=False,
                directive_type="no_op",
                structured_adjustment=None,
                explanation=f"Safe fallback: {note_text}",
            )
        )
    return fallbacks


def clean_and_validate_directives(
    raw_output: Any,
    battery_capacity_kwh: float,
    expected_count: int,
    notes: Optional[List[str]] = None,
) -> List[DirectiveInterpretation]:
    """Clean, normalize, and deterministically enforce schema on raw LLM directive outputs.

    Args:
        raw_output: Raw deserialized JSON output from LLM (expected List[dict]).
        battery_capacity_kwh: Maximum battery capacity in kWh for percentage conversions.
        expected_count: Number of operator notes that must be matched (0..N-1).
        notes: Optional original operator notes list for fallback context.

    Returns:
        List of validated DirectiveInterpretation objects with strictly ordered note_index.
    """
    if expected_count <= 0:
        return []

    # Map parsed objects by note_index
    parsed_by_index: Dict[int, Dict[str, Any]] = {}

    if isinstance(raw_output, list):
        for item in raw_output:
            if isinstance(item, dict):
                idx = item.get("note_index")
                if isinstance(idx, int) and 0 <= idx < expected_count:
                    parsed_by_index[idx] = item
            elif isinstance(item, DirectiveInterpretation):
                parsed_by_index[item.note_index] = item.model_dump()

    # Build validated directives for each note index 0..expected_count-1
    results: List[DirectiveInterpretation] = []

    for idx in range(expected_count):
        raw_item = parsed_by_index.get(idx)
        note_text = notes[idx] if notes and idx < len(notes) else ""

        if not raw_item:
            logger.warning("Missing LLM output for note_index %d. Using safe no_op fallback.", idx)
            results.append(
                DirectiveInterpretation(
                    note_index=idx,
                    applies=False,
                    directive_type="no_op",
                    structured_adjustment=None,
                    explanation=f"Default fallback: {note_text}" if note_text else "No interpretation returned.",
                )
            )
            continue

        raw_type = str(raw_item.get("directive_type", "no_op")).strip().lower()
        if raw_type not in VALID_DIRECTIVE_TYPES:
            raw_type = "no_op"

        explanation = str(raw_item.get("explanation", "")).strip()
        if not explanation:
            explanation = f"Interpreted directive for note {idx}."

        raw_adj = raw_item.get("structured_adjustment")

        # Process each directive type with deterministic normalization
        try:
            if raw_type == "no_op":
                results.append(
                    DirectiveInterpretation(
                        note_index=idx,
                        applies=False,
                        directive_type="no_op",
                        structured_adjustment=None,
                        explanation=explanation,
                    )
                )
                continue

            if not isinstance(raw_adj, dict):
                # Active directive missing structured_adjustment -> fallback to no_op
                logger.warning("Active directive %s for note %d has invalid adjustment %s", raw_type, idx, raw_adj)
                results.append(
                    DirectiveInterpretation(
                        note_index=idx,
                        applies=False,
                        directive_type="no_op",
                        structured_adjustment=None,
                        explanation=f"Fallback from invalid {raw_type}: missing parameters.",
                    )
                )
                continue

            # Clean and validate hour window
            hours = _clean_hours(raw_adj.get("hours"))
            if not hours:
                # Directives requiring hours cannot operate with empty hours
                logger.warning("Directive %s for note %d has empty hour list; falling back to no_op.", raw_type, idx)
                results.append(
                    DirectiveInterpretation(
                        note_index=idx,
                        applies=False,
                        directive_type="no_op",
                        structured_adjustment=None,
                        explanation=f"Fallback from {raw_type}: no valid operating hours found.",
                    )
                )
                continue

            cleaned_adj: Dict[str, Any] = {"hours": hours}

            if raw_type == "solar_reduction":
                raw_factor = raw_adj.get("factor")
                factor = 1.0
                if raw_factor is not None:
                    try:
                        if isinstance(raw_factor, str) and "%" in raw_factor:
                            factor = float(raw_factor.replace("%", "")) / 100.0
                        else:
                            factor = float(raw_factor)
                            # If factor expressed as percentage (e.g. 20 for 20%), normalize to fraction
                            if factor >= 2.0 and factor <= 100.0:
                                factor = factor / 100.0
                    except (ValueError, TypeError):
                        factor = 1.0

                # Check if reduction fraction was specified instead of factor
                if "reduction" in raw_adj:
                    try:
                        red = float(raw_adj["reduction"])
                        if red > 1.0 and red <= 100.0:
                            red = red / 100.0
                        factor = 1.0 - red
                    except (ValueError, TypeError):
                        pass

                # Clamp factor strictly between 0.0 and 1.0
                factor = max(0.0, min(1.0, round(factor, 4)))
                cleaned_adj["factor"] = factor

            elif raw_type == "minimum_battery_reserve":
                min_kwh = None
                if "minimum_energy_kwh" in raw_adj:
                    try:
                        min_kwh = float(raw_adj["minimum_energy_kwh"])
                    except (ValueError, TypeError):
                        min_kwh = None

                # Check if given as percentage or fraction of capacity
                if min_kwh is None or "percentage" in raw_adj or "reserve_percentage" in raw_adj:
                    pct_val = raw_adj.get("percentage") or raw_adj.get("reserve_percentage")
                    if pct_val is not None:
                        try:
                            pct = float(pct_val)
                            if pct > 1.0:
                                pct = pct / 100.0
                            min_kwh = pct * battery_capacity_kwh
                        except (ValueError, TypeError):
                            pass

                # If min_kwh was <= 1.0 while battery capacity is large (e.g. 0.5 given meaning 50%)
                if min_kwh is not None and min_kwh <= 1.0 and battery_capacity_kwh > 5.0:
                    # Likely a fraction rather than absolute 0.5 kWh
                    if "percent" in note_text.lower() or "%" in note_text:
                        min_kwh = min_kwh * battery_capacity_kwh

                if min_kwh is None:
                    min_kwh = 0.0

                # Clamp minimum reserve between 0 and battery capacity
                min_kwh = max(0.0, min(battery_capacity_kwh, round(min_kwh, 2)))
                cleaned_adj["minimum_energy_kwh"] = min_kwh

            elif raw_type == "no_charge_window":
                pass  # only 'hours' required

            elif raw_type == "no_discharge_window":
                pass  # only 'hours' required

            elif raw_type == "max_grid_window":
                max_grid = 0.0
                if "max_grid_kwh" in raw_adj:
                    try:
                        max_grid = float(raw_adj["max_grid_kwh"])
                    except (ValueError, TypeError):
                        max_grid = 0.0
                cleaned_adj["max_grid_kwh"] = max(0.0, round(max_grid, 2))

            # Build DirectiveInterpretation Pydantic object
            directive = DirectiveInterpretation(
                note_index=idx,
                applies=True,
                directive_type=raw_type,  # type: ignore
                structured_adjustment=cleaned_adj,
                explanation=explanation,
            )
            results.append(directive)

        except Exception as ex:
            logger.error("Error validating directive index %d (%s): %s. Falling back to no_op.", idx, raw_type, ex)
            results.append(
                DirectiveInterpretation(
                    note_index=idx,
                    applies=False,
                    directive_type="no_op",
                    structured_adjustment=None,
                    explanation=f"Fallback due to validation error: {note_text}",
                )
            )

    return results
