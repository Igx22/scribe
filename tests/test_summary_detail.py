"""Summary detail propagation, long-input notes, and model output budgets."""
import contextlib
import io
import unittest
from unittest.mock import patch

import scribe as app


class SummaryDetailTests(unittest.TestCase):
    def test_cli_bounds_and_rendered_preview(self):
        parser = app.build_parser()
        self.assertEqual(parser.parse_args([]).summary_detail, 1)
        for value in ("0", "11", "2.5"):
            with self.subTest(value=value), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    parser.parse_args(["--summary-detail", value])
        preview = io.StringIO()
        with patch.object(app, "load_env"), contextlib.redirect_stdout(preview):
            self.assertEqual(app.main(["--show-prompt", "--summary-detail", "5"]), 0)
        self.assertIn("5/10", preview.getvalue())
        self.assertIn("1200-2250", preview.getvalue())
        self.assertNotIn("{summary_", preview.getvalue())

    def test_high_detail_keeps_multi_page_answer_and_has_room_for_it(self):
        calls = []
        answer = "fact " * 1500
        def fake(*args, **kwargs):
            calls.append((args, kwargs))
            return answer
        result = app.summarize("source " * 8000, "key", "model", "medium", call=fake, detail=5)
        self.assertEqual(len(result.split()), 1500)
        self.assertEqual(len(calls), 1)
        self.assertGreater(calls[0][1]["max_output_tokens"], 12000)

    def test_short_answer_is_not_expanded_to_meet_page_guide(self):
        calls = []
        def fake(*args, **kwargs):
            calls.append(args)
            return "No decision was reached."
        result = app.summarize("Brief source.", "key", "model", "medium", call=fake, detail=10)
        self.assertEqual(result, "No decision was reached.")
        self.assertEqual(len(calls), 1)

    def test_shortening_uses_selected_ceiling_instead_of_one_page(self):
        calls = []
        oversized = "fact " * 2300
        def fake(*args, **kwargs):
            calls.append(args)
            return oversized if len(calls) == 1 else "fact " * 1800
        result = app.summarize("source " * 10000, "key", "model", "medium", call=fake, detail=5)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(calls[1][4].split()), 2300)
        self.assertIn("at most 2250 words", calls[1][3])
        self.assertEqual(len(result.split()), 1800)

    def test_long_input_keeps_all_parts_and_more_detail_in_notes(self):
        calls = []
        def fake(key, model, effort, instructions, data, **kwargs):
            calls.append((instructions, data, kwargs))
            return "Notes." if instructions == app.notes_prompt(10) else "Summary."
        text = "BEGIN\n\n" + "word " * 40000 + "\n\nEND_OF_RECORDING"
        self.assertEqual(app.summarize(text, "key", "model", "medium", call=fake, detail=10), "Summary.")
        notes = [call for call in calls if call[0] == app.notes_prompt(10)]
        self.assertGreater(len(notes), 1)
        self.assertIn("BEGIN", notes[0][1])
        self.assertIn("END_OF_RECORDING", notes[-1][1])
        self.assertGreater(notes[0][2]["max_output_tokens"], 12000)
        self.assertEqual(calls[-1][0], app.summary_prompt(10))
        self.assertGreater(calls[-1][2]["max_output_tokens"], notes[0][2]["max_output_tokens"])


if __name__ == "__main__":
    unittest.main()
