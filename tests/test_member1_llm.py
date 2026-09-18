"""Isolated Unit Tests for Team Member 1 (LLM Interpreter & Deterministic Guardrails).

Tests cover:
1. Directive interpretation across all 6 supported types.
2. Time window parsing and start-inclusive / end-exclusive conventions.
3. Solar reduction factor calculations (percentages, reductions, word fractions).
4. Percentage-to-kWh conversions based on battery capacity.
5. Distractor / irrelevant note filtering (no_op semantics).
6. Deterministic guardrails (sorting, deduplicating, bounds clamping).
7. Safe failure modes and fallback guarantees.
8. Mocked Gemini API responses.
9. Paraphrasing robustness against tricky phrasing from Section 05.
"""

import unittest
from unittest.mock import MagicMock, patch

from app.guardrails.validator import clean_and_validate_directives, create_fallback_directives
from app.llm.interpreter import (
    _extract_hour_window,
    _extract_solar_factor,
    interpret_operator_notes,
)
from app.schemas import DirectiveInterpretation


class TestMember1LLMAndGuardrails(unittest.TestCase):
    """Test suite for Member 1 LLM Interpretation and Guardrail Rules."""

    def setUp(self):
        self.battery_capacity_200 = 200.0
        self.battery_capacity_500 = 500.0

    def test_solar_reduction_basic(self):
        """Test basic solar reduction directive."""
        notes = ["Solar output will drop to about 20% from 1 PM to 3 PM."]
        directives = interpret_operator_notes(notes, self.battery_capacity_500)

        self.assertEqual(len(directives), 1)
        d = directives[0]
        self.assertEqual(d.note_index, 0)
        self.assertTrue(d.applies)
        self.assertEqual(d.directive_type, "solar_reduction")
        self.assertIsNotNone(d.structured_adjustment)
        self.assertEqual(d.structured_adjustment["hours"], [13, 14])
        self.assertAlmostEqual(d.structured_adjustment["factor"], 0.2, places=2)

    def test_no_charge_window(self):
        """Test no charge window directive."""
        notes = ["Do not charge the battery between 2 PM and 4 PM."]
        directives = interpret_operator_notes(notes, self.battery_capacity_500)

        self.assertEqual(len(directives), 1)
        d = directives[0]
        self.assertEqual(d.note_index, 0)
        self.assertTrue(d.applies)
        self.assertEqual(d.directive_type, "no_charge_window")
        self.assertEqual(d.structured_adjustment["hours"], [14, 15])

    def test_no_discharge_window(self):
        """Test no discharge window directive."""
        notes = ["Relay protection testing from noon until 2 PM; do not discharge the battery."]
        directives = interpret_operator_notes(notes, self.battery_capacity_200)

        self.assertEqual(len(directives), 1)
        d = directives[0]
        self.assertEqual(d.note_index, 0)
        self.assertTrue(d.applies)
        self.assertEqual(d.directive_type, "no_discharge_window")
        self.assertEqual(d.structured_adjustment["hours"], [12, 13])

    def test_minimum_battery_reserve_percentage(self):
        """Test minimum battery reserve with percentage conversion."""
        notes = ["Keep at least 50% stored from 6 PM to 9 PM for emergency lab backup."]
        directives = interpret_operator_notes(notes, self.battery_capacity_200)

        self.assertEqual(len(directives), 1)
        d = directives[0]
        self.assertEqual(d.note_index, 0)
        self.assertTrue(d.applies)
        self.assertEqual(d.directive_type, "minimum_battery_reserve")
        self.assertEqual(d.structured_adjustment["hours"], [18, 19, 20])
        # 50% of 200 kWh = 100 kWh
        self.assertAlmostEqual(d.structured_adjustment["minimum_energy_kwh"], 100.0, places=1)

    def test_minimum_battery_reserve_kwh(self):
        """Test minimum battery reserve specified in kWh."""
        notes = ["Hold 90 kWh from 18 to 21 for critical load protection."]
        directives = interpret_operator_notes(notes, self.battery_capacity_200)

        self.assertEqual(len(directives), 1)
        d = directives[0]
        self.assertEqual(d.note_index, 0)
        self.assertTrue(d.applies)
        self.assertEqual(d.directive_type, "minimum_battery_reserve")
        self.assertEqual(d.structured_adjustment["hours"], [18, 19, 20])
        self.assertAlmostEqual(d.structured_adjustment["minimum_energy_kwh"], 90.0, places=1)

    def test_max_grid_window(self):
        """Test grid import cap directive."""
        notes = ["Grid import cap of 120 kWh from 7 PM until 10 PM due to feeder maintenance."]
        directives = interpret_operator_notes(notes, self.battery_capacity_500)

        self.assertEqual(len(directives), 1)
        d = directives[0]
        self.assertEqual(d.note_index, 0)
        self.assertTrue(d.applies)
        self.assertEqual(d.directive_type, "max_grid_window")
        self.assertEqual(d.structured_adjustment["hours"], [19, 20, 21])
        self.assertAlmostEqual(d.structured_adjustment["max_grid_kwh"], 120.0, places=1)

    def test_distractor_notes_no_op(self):
        """Test that distractors are correctly identified as no_op with applies=False."""
        distractors = [
            "The cafeteria menu changes tomorrow.",
            "The library is extending book-return hours.",
            "Annual university athletics meet tomorrow on campus.",
        ]
        directives = interpret_operator_notes(distractors, self.battery_capacity_200)

        self.assertEqual(len(directives), 3)
        for idx, d in enumerate(directives):
            self.assertEqual(d.note_index, idx)
            self.assertFalse(d.applies)
            self.assertEqual(d.directive_type, "no_op")
            self.assertIsNone(d.structured_adjustment)

    def test_paraphrase_solar_variations(self):
        """Test paraphrased language robust interpretation (from plan Hour 3)."""
        cases = [
            ("PV production will drop to about 20% between 13:00 and 15:00", [13, 14], 0.2),
            ("Panel washing from one until three will leave roughly one-fifth of normal solar output", [13, 14], 0.2),
            ("Expect an 80% reduction in rooftop solar during the 1-3 PM maintenance window", [13, 14], 0.2),
        ]
        for note, expected_hours, expected_factor in cases:
            directives = interpret_operator_notes([note], self.battery_capacity_200)
            self.assertEqual(len(directives), 1)
            d = directives[0]
            self.assertTrue(d.applies, f"Failed on: {note}")
            self.assertEqual(d.directive_type, "solar_reduction")
            self.assertEqual(d.structured_adjustment["hours"], expected_hours)
            self.assertAlmostEqual(d.structured_adjustment["factor"], expected_factor, places=2)

    def test_multi_note_scenario(self):
        """Test multiple mixed notes in exact index order."""
        notes = [
            "Solar output will drop to about 20% from 1 PM to 3 PM.",
            "Do not charge the battery between 2 PM and 4 PM.",
            "The cafeteria menu changes tomorrow.",
        ]
        directives = interpret_operator_notes(notes, self.battery_capacity_500)

        self.assertEqual(len(directives), 3)
        # Note 0
        self.assertEqual(directives[0].note_index, 0)
        self.assertTrue(directives[0].applies)
        self.assertEqual(directives[0].directive_type, "solar_reduction")
        # Note 1
        self.assertEqual(directives[1].note_index, 1)
        self.assertTrue(directives[1].applies)
        self.assertEqual(directives[1].directive_type, "no_charge_window")
        # Note 2
        self.assertEqual(directives[2].note_index, 2)
        self.assertFalse(directives[2].applies)
        self.assertEqual(directives[2].directive_type, "no_op")
        self.assertIsNone(directives[2].structured_adjustment)

    def test_guardrail_unsorted_and_duplicate_hours(self):
        """Test that guardrails sort, deduplicate, and clamp hour lists."""
        raw = [
            {
                "note_index": 0,
                "applies": True,
                "directive_type": "no_charge_window",
                "structured_adjustment": {"hours": [15, 14, 14, 15, 13, 99, -5]},
                "explanation": "Out of order hours",
            }
        ]
        cleaned = clean_and_validate_directives(raw, self.battery_capacity_200, 1)
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0].structured_adjustment["hours"], [13, 14, 15])

    def test_guardrail_solar_factor_clamping(self):
        """Test that factor > 1.0 or percentage format is normalized and clamped [0..1]."""
        raw = [
            {
                "note_index": 0,
                "applies": True,
                "directive_type": "solar_reduction",
                "structured_adjustment": {"hours": [12, 13], "factor": 25},  # percentage 25%
                "explanation": "25% solar factor",
            },
            {
                "note_index": 1,
                "applies": True,
                "directive_type": "solar_reduction",
                "structured_adjustment": {"hours": [14, 15], "factor": 1.8},  # over 1.0 clamped
                "explanation": "Over 1.0 factor",
            },
        ]
        cleaned = clean_and_validate_directives(raw, self.battery_capacity_200, 2)
        self.assertAlmostEqual(cleaned[0].structured_adjustment["factor"], 0.25, places=2)
        self.assertAlmostEqual(cleaned[1].structured_adjustment["factor"], 1.0, places=2)

    def test_guardrail_reserve_capacity_clamping(self):
        """Test reserve cannot exceed battery capacity."""
        raw = [
            {
                "note_index": 0,
                "applies": True,
                "directive_type": "minimum_battery_reserve",
                "structured_adjustment": {"hours": [18, 19], "minimum_energy_kwh": 350.0},
                "explanation": "Exceeds 200 kWh capacity",
            }
        ]
        cleaned = clean_and_validate_directives(raw, self.battery_capacity_200, 1)
        self.assertAlmostEqual(cleaned[0].structured_adjustment["minimum_energy_kwh"], 200.0, places=1)

    def test_guardrail_no_op_enforces_null_adjustment(self):
        """Test that no_op always enforces applies=False and structured_adjustment=None."""
        raw = [
            {
                "note_index": 0,
                "applies": True,  # Bad LLM output
                "directive_type": "no_op",
                "structured_adjustment": {"hours": [1, 2]},  # Bad LLM output
                "explanation": "Distractor",
            }
        ]
        cleaned = clean_and_validate_directives(raw, self.battery_capacity_200, 1)
        self.assertFalse(cleaned[0].applies)
        self.assertIsNone(cleaned[0].structured_adjustment)

    def test_guardrail_missing_hours_fallback(self):
        """Test that directive requiring hours with empty hours falls back to no_op."""
        raw = [
            {
                "note_index": 0,
                "applies": True,
                "directive_type": "no_charge_window",
                "structured_adjustment": {"hours": []},
                "explanation": "No hours given",
            }
        ]
        cleaned = clean_and_validate_directives(raw, self.battery_capacity_200, 1)
        self.assertFalse(cleaned[0].applies)
        self.assertEqual(cleaned[0].directive_type, "no_op")
        self.assertIsNone(cleaned[0].structured_adjustment)

    def test_safe_fallback_on_corrupt_data(self):
        """Test that non-list, corrupt, or empty LLM output falls back to safe no_op."""
        cleaned = clean_and_validate_directives("CORRUPT STRING", self.battery_capacity_200, 2, ["Note 1", "Note 2"])
        self.assertEqual(len(cleaned), 2)
        for idx, d in enumerate(cleaned):
            self.assertEqual(d.note_index, idx)
            self.assertFalse(d.applies)
            self.assertEqual(d.directive_type, "no_op")

    def test_empty_notes_returns_empty_list(self):
        """Test that empty operator_notes input returns empty list."""
        directives = interpret_operator_notes([], self.battery_capacity_200)
        self.assertEqual(directives, [])

    @patch("app.llm.interpreter._call_gemini_api")
    def test_gemini_api_integration_mock(self, mock_gemini):
        """Test that Gemini API output is properly returned when available."""
        mock_gemini.return_value = [
            DirectiveInterpretation(
                note_index=0,
                applies=True,
                directive_type="solar_reduction",
                structured_adjustment={"hours": [11, 12], "factor": 0.3},
                explanation="Gemini interpreted solar reduction",
            )
        ]

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test_api_key"}):
            directives = interpret_operator_notes(["Some solar note"], self.battery_capacity_200)
            self.assertEqual(len(directives), 1)
            self.assertEqual(directives[0].directive_type, "solar_reduction")
            self.assertEqual(directives[0].structured_adjustment["hours"], [11, 12])

    def test_in_memory_lru_cache_speed(self):
        """Test that repeated calls are served instantaneously (<1ms) from cache."""
        import time
        notes = ["Do not charge the battery between 2 PM and 4 PM."]
        # Prime the cache
        res1 = interpret_operator_notes(notes, self.battery_capacity_200)
        
        t0 = time.perf_counter()
        res2 = interpret_operator_notes(notes, self.battery_capacity_200)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        self.assertEqual(res1[0].directive_type, res2[0].directive_type)
        self.assertLess(elapsed_ms, 5.0, f"Cache took {elapsed_ms}ms, expected sub-millisecond")

    def test_advanced_paraphrase_variations(self):
        """Test subtle paraphrase variations: 'percent', 'one-fifth', 'one until three'."""
        # Variation A: "one until three will leave roughly one-fifth"
        notes = ["Panel washing from one until three will leave roughly one-fifth of normal solar output."]
        dirs = interpret_operator_notes(notes, self.battery_capacity_200)
        self.assertEqual(dirs[0].directive_type, "solar_reduction")
        self.assertEqual(dirs[0].structured_adjustment["hours"], [13, 14])
        self.assertAlmostEqual(dirs[0].structured_adjustment["factor"], 0.2, places=2)

        # Variation B: "80 percent reduction"
        notes_b = ["Expect an 80 percent reduction in rooftop solar during the 1-3 PM maintenance window."]
        dirs_b = interpret_operator_notes(notes_b, self.battery_capacity_200)
        self.assertEqual(dirs_b[0].directive_type, "solar_reduction")
        self.assertEqual(dirs_b[0].structured_adjustment["hours"], [13, 14])
        self.assertAlmostEqual(dirs_b[0].structured_adjustment["factor"], 0.2, places=2)


if __name__ == "__main__":
    unittest.main()
