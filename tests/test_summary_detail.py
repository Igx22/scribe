"""Combined summary requests, per-level validation, and model output budgets."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import scribe as app
from tests import runtime_paths, seed_final, summary_answers


class SummaryDetailTests(unittest.TestCase):
    def test_cli_bounds_and_rendered_preview(self):
        with patch.dict(os.environ, {}, clear=True):
            parser = app.build_parser()
        self.assertEqual(parser.parse_args([]).report_tabs, [1, 3, 5, 10])
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

    def test_combined_schema_and_budget_cover_selected_levels(self):
        answer = {"summary_1": "Brief.", "summary_5": "fact " * 1500}
        with patch.object(app, "api_request", return_value=json.dumps(answer)) as request:
            result = app.summarize("source " * 8000, "key", "gpt-6.2-sol", "xhigh", levels=[1, 5])
        request.assert_called_once()
        self.assertEqual(request.call_args.args[1:3], ("gpt-6.2-sol", "xhigh"))
        self.assertEqual(request.call_args.kwargs["schema"]["required"], ["summary_1", "summary_5"])
        self.assertIn("1200-2250", request.call_args.args[3])
        self.assertGreater(request.call_args.kwargs["max_output_tokens"], 12000)
        self.assertEqual(len(result[5].split()), 1500)

    def test_short_answer_is_not_expanded_to_meet_page_guide(self):
        with patch.object(app, "api_request", return_value='{"summary_10":"No decision was reached."}') as request:
            result = app.summarize("Brief source.", "key", "gpt-6.2-sol", "xhigh", levels=[10])
        self.assertEqual(result, {10: "No decision was reached."})
        request.assert_called_once()

    def test_invalid_levels_fail_without_a_second_request(self):
        for answer in ("not JSON", '{"summary_1":"One."}', '{"summary_1":"One.","summary_5":" "}',
                       json.dumps({"summary_1": "One.", "summary_5": "fact " * 2300})):
            with self.subTest(answer=answer[:50]), patch.object(app, "api_request", return_value=answer) as request:
                with self.assertRaisesRegex(app.AppError, "existing summaries are preserved"):
                    app.summarize("Transcript.", "key", "gpt-6.2-sol", "xhigh", levels=[1, 5])
                request.assert_called_once()

    def test_output_budget_is_capped_at_model_limit(self):
        levels = list(range(1, 11))
        reply = json.dumps({f"summary_{level}": "Summary." for level in levels})
        with patch.object(app, "api_request", return_value=reply) as request:
            app.summarize("Transcript.", "key", "gpt-6.2-sol", "xhigh", levels=levels)
        self.assertEqual(request.call_args.kwargs["max_output_tokens"], 128000)


class SummaryConfigurationTests(unittest.TestCase):
    def test_environment_lists_are_normalized_like_cli_values(self):
        for value, expected in (("1,5,10", [1, 5, 10]), ("1, 5, 10", [1, 5, 10]),
                                ("1 5 10", [1, 5, 10]), ("10,1,10", [10, 1]), ("5,5", [5]),
                                ("1,3,5,10,transcript", [1, 3, 5, 10]),
                                ("transcript, 5, TRANSCRIPT", [5])):
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
                (None, [], [1, 3, 5, 10]),
                ('"1, 5, 10"', [], [1, 5, 10]),
                ("5", [], [5]),
                ("transcript", [], []),
                ("1,5,transcript", ["--report-tabs", "transcript", "3"], [3]),
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
                        patch.object(app, "summarize", side_effect=summary_answers(lambda detail: f"Summary at level {detail}.")) as summarize, \
                        patch.object(app, "extract_report_metadata", return_value={"topic": "Test conversation.", "roles": {}}), \
                        patch.object(app, "extract_audio") as extract, patch.object(app, "ensure_models") as models:
                    self.assertEqual(app.main(["-f", str(source), "--summary-only", "--output-dir", str(output),
                                               *options]), 0)
                self.assertEqual([call.kwargs["levels"] for call in summarize.call_args_list], [tabs] if tabs else [])
                extract.assert_not_called(); models.assert_not_called()
                self.assertEqual(before, (log.read_bytes(), log.stat().st_mtime_ns))
                _, summary = app.output_paths(source, output)
                self.assertTrue(summary.is_file())
                self.assertEqual(summary.suffix, ".html")
                self.assertFalse(summary.with_suffix(".md").exists())
                self.assertIn('id="tab-transcript"', summary.read_text())
                for level in app.summary_levels(tabs):
                    self.assertIn(f"Summary at level {level}.", summary.read_text())

    def test_removed_summary_detail_option_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            app.build_parser().parse_args(["--summary-detail", "5"])


if __name__ == "__main__":
    unittest.main()
