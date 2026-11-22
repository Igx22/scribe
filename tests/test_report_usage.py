import json
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import report_usage
import scribe as app
from tests import seed_final


class ReportUsageTests(unittest.TestCase):
    def test_prices_recorded_responses_with_cache_and_audio(self):
        pricing = json.loads(report_usage.PRICING_FILE.read_text(encoding="utf-8"))
        run = {
            "text_usage": [
                {"stage": "summary level 1", "model": "gpt-6.2-astra-2026-11-18",
                 "service_tier": "default", "status": "incomplete",
                 "usage": {"input_tokens": 300_000, "output_tokens": 1_000,
                           "input_tokens_details": {"cached_tokens": 200_000, "cache_write_tokens": 50_000,
                               "cache_write_tokens_details": {"ttl_30m_tokens": 40_000, "ttl_12h_tokens": 10_000}}}},
                {"stage": "YouTube comment filter", "model": "gpt-6-luna", "service_tier": "fast",
                 "usage": {"input_tokens": 1_000, "output_tokens": 1_000}},
            ],
            "audio_usage": [{"usage": {"type": "duration", "seconds": 120}}],
        }
        groups = report_usage.summarize_usage(run, pricing)
        self.assertEqual(groups["Video summaries"].input_cost, Decimal("2.16"))
        self.assertEqual(groups["Video summaries"].output_cost, Decimal("0.06"))
        self.assertEqual(groups["Comment filtering"].cost, Decimal("0.0012"))
        self.assertEqual(groups["Cloud transcription"].cost, Decimal("0.009"))
        footer = report_usage.render_usage(run)
        for text in ("3 requests", "301,000", "2,000", "≈ 2.230", "120 s reported", "Cost breakdown"):
            self.assertIn(text, footer)

    def test_missing_prices_and_usage_keep_the_estimate_partial(self):
        run = {"text_usage": [
            {"stage": "summary level 1", "model": "gpt-6.2-astra", "service_tier": "default",
             "usage": {"input_tokens": 1_000, "output_tokens": 1_000}},
            {"stage": "report header", "model": "custom-model", "service_tier": "default",
             "usage": {"input_tokens": 4_000, "output_tokens": 500}},
            {"stage": "reconciliation", "model": "gpt-6.2-astra", "usage": None},
        ]}
        footer = report_usage.render_usage(run)
        self.assertIn("5,000", footer)
        self.assertIn("1,500", footer)
        self.assertIn("≈ 0.048", footer)
        self.assertIn("partial est.", footer)
        self.assertIn("Unavailable", footer)
        self.assertIn("No new API usage recorded", report_usage.render_usage({}))

    def test_process_file_renders_run_usage_and_excludes_reused_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "meeting.mkv"
            source.write_bytes(b"recording")
            args = app.build_parser().parse_args([
                "--summary-only", "--report-tabs", "1", "--output-dir", str(root),
                "--summarize-model", "gpt-6.2-astra:xhigh"])
            args.cache_dir = root / "cache"
            seed_final(source, args)
            _, summary = app.output_paths(source, args.output_dir)

            def summarize(transcript, key, model, effort, *, detail):
                app.record_text_usage({"model": model, "service_tier": "default",
                                       "usage": {"input_tokens": 2_000, "output_tokens": 500}}, model, effort)
                return "Recorded summary"

            with patch.object(app, "summarize", side_effect=summarize) as call, \
                    patch.object(app, "extract_report_metadata", return_value={"topic": "Meeting", "roles": {}}):
                app.process_file(source, args, "test-key")
                html = summary.read_text(encoding="utf-8")
                self.assertIn("≈ 0.036", html)
                self.assertIn("<details><summary>Cost breakdown</summary>", html)
                self.assertFalse(summary.with_suffix(".err").exists())
                app.process_file(source, args, "test-key")
                call.assert_called_once()
                html = summary.read_text(encoding="utf-8")
                self.assertIn("Recorded summary", html)
                self.assertIn("No new API usage recorded", html)
