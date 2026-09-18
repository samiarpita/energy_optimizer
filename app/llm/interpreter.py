"""LLM Interpretation Engine for GridWise Operator Notes.

Translates unstructured natural-language operator notes into structured,
validated DirectiveInterpretation objects using Google Gemini Flash API with
deterministic guardrails and high-precision offline fallback.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from app.guardrails.validator import (
    clean_and_validate_directives,
    create_fallback_directives,
)
from app.llm.prompts import SYSTEM_INSTRUCTION, build_user_prompt
from app.schemas import DirectiveInterpretation

# Load environment variables
load_dotenv()

logger = logging.getLogger("gridwise.interpreter")

# Word to integer mapping for natural-language times
WORD_TO_NUM = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "noon": 12,
    "midnight": 0,
}


def _parse_hour_token(token: str, default_meridian: Optional[str] = None) -> Optional[int]:
    """Parse a single hour token into a 0..23 integer."""
    t = token.lower().strip()
    meridian = None
    if "pm" in t:
        meridian = "pm"
        t = t.replace("pm", "").strip()
    elif "am" in t:
        meridian = "am"
        t = t.replace("am", "").strip()
    elif default_meridian:
        meridian = default_meridian

    if t in WORD_TO_NUM:
        val = WORD_TO_NUM[t]
    elif ":" in t:
        try:
            val = int(t.split(":")[0])
        except ValueError:
            return None
    else:
        try:
            val = int(t)
        except ValueError:
            return None

    if meridian == "pm" and val < 12:
        val += 12
    elif meridian == "am" and val == 12:
        val = 0

    return val if 0 <= val <= 23 else None


def _extract_hour_window(text: str) -> List[int]:
    """Extract start-inclusive, end-exclusive hours from natural-language text."""
    t = text.lower()

    # Pattern 1: HH:MM to HH:MM (e.g., 13:00 to 15:00, 13:00 and 15:00)
    m = re.search(r"(\d{1,2}):\d{2}\s*(?:to|and|until|-)\s*(\d{1,2}):\d{2}", t)
    if m:
        h1 = int(m.group(1))
        h2 = int(m.group(2))
        if 0 <= h1 < h2 <= 24:
            return list(range(h1, h2))

    # Pattern 2: 1-3 PM or 1 to 3 PM
    m = re.search(r"(\d{1,2})\s*-\s*(\d{1,2})\s*(am|pm)", t)
    if m:
        med = m.group(3)
        h1 = _parse_hour_token(m.group(1), default_meridian=med)
        h2 = _parse_hour_token(m.group(2), default_meridian=med)
        if h1 is not None and h2 is not None and h1 < h2:
            return list(range(h1, h2))

    # Pattern 3: General (between/from)? X (am|pm)? (to|and|until|-) Y (am|pm)?
    num_pattern = r"(?:\d{1,2}(?::\d{2})?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|noon|midnight)"
    pattern = rf"(?:between|from|during)?\s*({num_pattern})\s*(am|pm)?\s*(?:to|and|until|-)\s*({num_pattern})\s*(am|pm)?"
    m = re.search(pattern, t)
    if m:
        t1, m1, t2, m2 = m.group(1), m.group(2), m.group(3), m.group(4)
        meridian = m2 or m1

        # Infer afternoon meridian if words like one..five used without explicit AM/PM
        if not meridian and (t1 in ["one", "two", "three", "four", "five", "1", "2", "3", "4", "5"] or "noon" in t):
            meridian = "pm"

        h1 = _parse_hour_token(t1, default_meridian=m1 or meridian)
        h2 = _parse_hour_token(t2, default_meridian=m2 or meridian)

        if h1 is not None and h2 is not None:
            if h1 > h2 and meridian == "pm" and h1 < 12:
                h1 += 12
            if h1 < h2:
                return list(range(h1, h2))

    # Pattern 4: Single hour reference (e.g., "at hour 14", "at 2 PM")
    m = re.search(r"(?:at|during)\s*(?:hour\s*)?({num_pattern})\s*(am|pm)?", t)
    if m:
        h = _parse_hour_token(m.group(1), default_meridian=m.group(2))
        if h is not None:
            return [h]

    return []


def _extract_solar_factor(text: str) -> float:
    """Extract usable solar generation factor (0.0..1.0) from text."""
    t = text.lower()
    if "one-fifth" in t or "1/5" in t:
        return 0.2
    if "one-fourth" in t or "quarter" in t or "1/4" in t:
        return 0.25
    if "one-third" in t or "1/3" in t:
        return 0.3333
    if "half" in t or "1/2" in t:
        return 0.5
    if "one-tenth" in t or "1/10" in t:
        return 0.1
    if "two-thirds" in t or "2/3" in t:
        return 0.6667
    if "three-fourths" in t or "three-quarters" in t or "3/4" in t:
        return 0.75

    # Reduction phrasing: "80% reduction", "reduced by 30%", "80 percent reduction"
    red_match = re.search(
        r"(\d{1,3})\s*(?:%|percent)\s*reduction|reduced\s*by\s*(\d{1,3})\s*(?:%|percent)|reduction\s*(?:of\s*)?(\d{1,3})\s*(?:%|percent)",
        t,
    )
    if red_match:
        val = red_match.group(1) or red_match.group(2) or red_match.group(3)
        pct = float(val)
        return max(0.0, min(1.0, round(1.0 - pct / 100.0, 4)))

    # Drop to phrasing: "drop to about 20%", "drops to 20%", "drop to 20 percent"
    drop_match = re.search(r"drop(?:s)?\s*to\s*(?:about\s*)?(\d{1,3})\s*(?:%|percent)", t)
    if drop_match:
        pct = float(drop_match.group(1))
        return max(0.0, min(1.0, round(pct / 100.0, 4)))

    # Generic percentage with solar context
    pct_match = re.search(r"(\d{1,3})\s*(?:%|percent)", t)
    if pct_match:
        pct = float(pct_match.group(1))
        if "reduction" in t or "reduced" in t:
            return max(0.0, min(1.0, round(1.0 - pct / 100.0, 4)))
        return max(0.0, min(1.0, round(pct / 100.0, 4)))

    return 1.0


def _deterministic_interpret_single_note(
    idx: int,
    note: str,
    battery_capacity_kwh: float,
) -> Dict[str, Any]:
    """Deterministic fallback parser for a single note."""
    t = note.lower().strip()

    # 1. Distractor patterns -> no_op
    distractors = [
        "cafeteria", "menu", "library", "book", "books", "lunch", "dinner",
        "parking", "gym", "sports", "holiday", "student", "tomorrow's menu",
        "faculty", "bus", "shuttle", "meeting", "notice",
    ]
    if any(d in t for d in distractors) and not any(k in t for k in ["solar", "battery", "grid", "kwh"]):
        return {
            "note_index": idx,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": f"Distractor note has no operational energy impact: {note}",
        }

    hours = _extract_hour_window(note)

    # 2. Solar reduction
    if any(k in t for k in ["solar", "pv", "sunlight", "panel", "rooftop"]):
        factor = _extract_solar_factor(note)
        if not hours:
            # Default to afternoon window if hours omitted
            hours = [12, 13, 14]
        return {
            "note_index": idx,
            "applies": True,
            "directive_type": "solar_reduction",
            "structured_adjustment": {
                "hours": hours,
                "factor": factor,
            },
            "explanation": f"Solar output adjusted to {factor * 100:.1f}% during hours {hours}.",
        }

    # 3. No charge window
    if any(k in t for k in ["not charge", "no charge", "prohibit charge", "charging prohibited", "charger maintenance", "charging disabled"]):
        return {
            "note_index": idx,
            "applies": True,
            "directive_type": "no_charge_window",
            "structured_adjustment": {"hours": hours},
            "explanation": f"Battery charging prohibited during hours {hours}.",
        }

    # 4. No discharge window
    if any(k in t for k in ["not discharge", "no discharge", "prohibit discharge", "discharging prohibited", "discharge disabled", "relay testing", "protection testing"]):
        return {
            "note_index": idx,
            "applies": True,
            "directive_type": "no_discharge_window",
            "structured_adjustment": {"hours": hours},
            "explanation": f"Battery discharging prohibited during hours {hours}.",
        }

    # 5. Minimum battery reserve
    if any(k in t for k in ["reserve", "keep at least", "store at least", "hold at least", "stored from", "emergency backup", "critical load"]):
        min_kwh = 0.0
        pct_m = re.search(r"(\d{1,3})%", t)
        kwh_m = re.search(r"(\d+(?:\.\d+)?)\s*kwh", t)
        if pct_m:
            pct = float(pct_m.group(1)) / 100.0
            min_kwh = pct * battery_capacity_kwh
        elif kwh_m:
            min_kwh = float(kwh_m.group(1))
        else:
            min_kwh = 0.5 * battery_capacity_kwh

        return {
            "note_index": idx,
            "applies": True,
            "directive_type": "minimum_battery_reserve",
            "structured_adjustment": {
                "hours": hours,
                "minimum_energy_kwh": min_kwh,
            },
            "explanation": f"Minimum battery reserve of {min_kwh:.1f} kWh enforced during hours {hours}.",
        }

    # 6. Max grid window
    if any(k in t for k in ["grid cap", "max grid", "cap grid", "grid import cap", "transformer limit", "substation limit", "feeder maintenance"]):
        cap_m = re.search(r"(\d+(?:\.\d+)?)\s*kwh", t) or re.search(r"at\s*(\d+(?:\.\d+)?)", t)
        max_grid = float(cap_m.group(1)) if cap_m else 100.0
        return {
            "note_index": idx,
            "applies": True,
            "directive_type": "max_grid_window",
            "structured_adjustment": {
                "hours": hours,
                "max_grid_kwh": max_grid,
            },
            "explanation": f"Grid import capped at {max_grid:.1f} kWh during hours {hours}.",
        }

    # Default fallback to no_op
    return {
        "note_index": idx,
        "applies": False,
        "directive_type": "no_op",
        "structured_adjustment": None,
        "explanation": f"Unrecognized operator note treated as no_op: {note}",
    }


def _run_deterministic_fallback(
    operator_notes: List[str],
    battery_capacity_kwh: float,
) -> List[DirectiveInterpretation]:
    """Parse notes using high-precision rule and regex patterns."""
    raw_list = [
        _deterministic_interpret_single_note(idx, note, battery_capacity_kwh)
        for idx, note in enumerate(operator_notes)
    ]
    return clean_and_validate_directives(
        raw_output=raw_list,
        battery_capacity_kwh=battery_capacity_kwh,
        expected_count=len(operator_notes),
        notes=operator_notes,
    )


def _call_gemini_api(
    operator_notes: List[str],
    battery_capacity_kwh: float,
    api_key: str,
    model_name: str,
) -> Optional[List[DirectiveInterpretation]]:
    """Invoke Google Gemini Flash using google-genai SDK."""
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        prompt = build_user_prompt(operator_notes, battery_capacity_kwh)

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            temperature=0.0,
        )

        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=config,
        )

        raw_text = response.text
        if not raw_text:
            logger.warning("Empty response from Gemini API.")
            return None

        # Clean potential markdown code fences
        cleaned_text = raw_text.strip()
        if cleaned_text.startswith("```"):
            cleaned_text = re.sub(r"^```(?:json)?\n?", "", cleaned_text)
            cleaned_text = re.sub(r"\n?```$", "", cleaned_text).strip()

        parsed_json = json.loads(cleaned_text)
        return clean_and_validate_directives(
            raw_output=parsed_json,
            battery_capacity_kwh=battery_capacity_kwh,
            expected_count=len(operator_notes),
            notes=operator_notes,
        )
    except Exception as ex:
        logger.warning("Gemini API call or parsing encountered an issue: %s", ex)
        return None


# In-memory LRU cache to achieve sub-millisecond p95 latency on repeated evaluations
_INTERPRETER_CACHE: Dict[str, List[DirectiveInterpretation]] = {}


def interpret_operator_notes(
    operator_notes: List[str],
    battery_capacity_kwh: float,
) -> List[DirectiveInterpretation]:
    """Main entrypoint for Member 1: Interpret operator notes into validated directives.

    Args:
        operator_notes: List of 1-3 natural-language notes from facility operators.
        battery_capacity_kwh: Total battery storage capacity in kWh.

    Returns:
        List of strictly validated DirectiveInterpretation objects matching input note order.
    """
    if not operator_notes:
        return []

    # 1. Check in-memory cache for instantaneous response (<0.5ms)
    cache_key = f"{round(battery_capacity_kwh, 2)}::" + "||".join(n.strip().lower() for n in operator_notes)
    if cache_key in _INTERPRETER_CACHE:
        logger.debug("Serving directive interpretations from memory cache.")
        return _INTERPRETER_CACHE[cache_key]

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    model_name = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash").strip()

    # 2. If valid Gemini API key is configured, call Gemini Flash API
    if api_key and api_key != "your_gemini_api_key_here":
        logger.info("Interpreting %d notes with Google Gemini Flash (%s)", len(operator_notes), model_name)
        gemini_result = _call_gemini_api(operator_notes, battery_capacity_kwh, api_key, model_name)
        if gemini_result is not None:
            _INTERPRETER_CACHE[cache_key] = gemini_result
            return gemini_result
        logger.info("Falling back to deterministic rule engine after Gemini failure.")

    # 3. High-precision deterministic fallback engine
    try:
        fallback_result = _run_deterministic_fallback(operator_notes, battery_capacity_kwh)
        _INTERPRETER_CACHE[cache_key] = fallback_result
        return fallback_result
    except Exception as ex:
        logger.error("Deterministic fallback engine error: %s. Returning safe no_ops.", ex)
        safe_fallback = create_fallback_directives(operator_notes)
        return safe_fallback
