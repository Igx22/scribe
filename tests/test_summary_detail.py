"""Summary detail propagation, long-input notes, and model output budgets."""
import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import scribe as app
from tests import runtime_paths, seed_final


class SummaryDetailTests(unittest.TestCase):
    def test_cli_bounds_and_rendered_preview(self):
        with patch.dict(os.environ, {}, clear=True):
            parser = app.build_parser()
        self.assertEqual(parser.parse_args([]).report_tabs, [1, 3, 5, 10, "transcript"])
        for value in ("0", "11", "2.5"):
            with self.subTest(value=value), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    parser.parse_args(["--report-tabs", value])
        preview = io.StringIO()
        with patch.object(app, "load_env"), contextlib.redirect_stdout(preview):
            self.assertEqual(app.main(["--show-prompt", "--report-tabs", "5"]), 0)
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


class SummaryConfigurationTests(unittest.TestCase):
    def test_environment_lists_are_normalized_like_cli_values(self):
        for value, expected in (("1,5,10", [1, 5, 10]), ("1, 5, 10", [1, 5, 10]),
                                ("1 5 10", [1, 5, 10]), ("10,1,10", [10, 1]), ("5,5", [5]),
                                ("1,3,5,10,transcript", [1, 3, 5, 10, "transcript"]),
                                ("transcript, 5, TRANSCRIPT", ["transcript", 5])):
            with self.subTest(value=value), patch.dict(os.environ, {"SCRIBE_REPORT_TABS": value}, clear=True):
                self.assertEqual(app.build_parser().parse_args([]).report_tabs, expected)
                self.assertEqual(app.build_parser().parse_args(["--report-tabs", "3", "7"]).report_tabs,
                                 [3, 7])

    def test_environment_overrides_dotenv_and_cli_overrides_both(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {"SCRIBE_REPORT_TABS": "3,7"}, clear=True):
            env = Path(tmp) / ".env"
            env.write_text('SCRIBE_REPORT_TABS="1, 5, 10"\n')
            app.load_env(env)
            self.assertEqual(app.build_parser().parse_args([]).report_tabs, [3, 7])
            self.assertEqual(app.build_parser().parse_args(["--report-tabs", "5"]).report_tabs, [5])

    def test_invalid_environment_is_rejected_but_explicit_cli_still_works(self):
        for value in ("", "   ", "1,,5", "1,11", "five", "2.5", "log", "transcript,"):
            with self.subTest(value=value), patch.dict(os.environ, {"SCRIBE_REPORT_TABS": value}, clear=True):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    app.build_parser().parse_args([])
                self.assertEqual(app.build_parser().parse_args(["--report-tabs", "1,5,10"]).report_tabs,
                                 [1, 5, 10])

    def test_main_uses_default_or_dotenv_tabs_and_cli_always_writes_html(self):
        load_env = app.load_env
        for configured, options, tabs in (
                (None, [], [1, 3, 5, 10, "transcript"]),
                ('"1, 5, 10"', [], [1, 5, 10]),
                ("5", [], [5]),
                ("transcript", [], ["transcript"]),
                ("1,5,transcript", ["--report-tabs", "transcript", "3"], ["transcript", 3]),
                ("1,3,5,10", ["--report-tabs", "5"], [5]),
                ("5", ["--report-tabs", "1", "10"], [1, 10])):
            with self.subTest(configured=configured, options=options), tempfile.TemporaryDirectory() as tmp, \
                    patch.dict(os.environ, {}, clear=True):
                root = Path(tmp)
                env = root / ".env"
                env.write_text("OPENAI_API_KEY=unit-test-key\n" +
                               (f"SCRIBE_REPORT_TABS={configured}\n" if configured is not None else ""))
                source = root / "meeting.mkv"; source.write_bytes(b"fixture")
                output = root / "output"
                log, _ = app.output_paths(source, output)
                seed_args = app.build_parser().parse_args(["--output-dir", str(output)])
                seed_args.cache_dir = root / "cache"
                seed_final(source, seed_args)
                before = (log.read_bytes(), log.stat().st_mtime_ns)
                with runtime_paths(cache_dir=root / "cache"), \
                        patch.object(app, "load_env", side_effect=lambda: load_env(env)), \
                        patch.object(app, "summarize", side_effect=lambda *a, detail: f"Summary at level {detail}.") as summarize, \
                        patch.object(app, "extract_report_metadata", return_value={"topic": "Test conversation.", "roles": {}}), \
                        patch.object(app, "extract_audio") as extract, patch.object(app, "ensure_models") as models:
                    self.assertEqual(app.main(["-f", str(source), "--summary-only", "--output-dir", str(output),
                                               *options]), 0)
                self.assertEqual([call.kwargs["detail"] for call in summarize.call_args_list], app.summary_levels(tabs))
                extract.assert_not_called(); models.assert_not_called()
                self.assertEqual(before, (log.read_bytes(), log.stat().st_mtime_ns))
                _, summary = app.output_paths(source, output)
                self.assertTrue(summary.is_file())
                self.assertEqual(summary.suffix, ".html")
                self.assertFalse(summary.with_suffix(".md").exists())
                self.assertEqual('id="tab-transcript"' in summary.read_text(), "transcript" in tabs)
                for level in app.summary_levels(tabs):
                    self.assertIn(f"Summary at level {level}.", summary.read_text())

    def test_removed_summary_detail_option_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            app.build_parser().parse_args(["--summary-detail", "5"])


if __name__ == "__main__":
    unittest.main()
