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
        for text in ("3 requests", "301,000", "2,000", "≈ 2.230", "120 s reported", "Cost breakdown",
                     "Model / reasoning", "gpt-transcribe<small>Reasoning not applicable",
                     "gpt-6.2-astra-2026-11-18<small>Reasoning not recorded"):
            self.assertIn(text, footer)

    def test_model_effort_pairs_stay_with_their_stage(self):
        first = {"stage": "summary level 1", "model": "gpt-6.2-sol", "effort": "xhigh"}
        run = {"text_usage": [
            first, {**first, "stage": "summary level 3"}, {**first, "effort": "medium"},
            {**first, "model": "custom<model>", "effort": "custom<effort>"},
            {"stage": "YouTube comment filter", "model": "gpt-6-luna", "effort": "none"},
        ]}
        footer = report_usage.render_usage(run)
        summaries = footer.split('Video summaries <small>· 4</small></th>')[1].split('</tr>')[0]
        self.assertEqual(summaries.count("gpt-6.2-sol<small>Reasoning: xhigh"), 1)
        self.assertIn("gpt-6.2-sol<small>Reasoning: medium", summaries)
        self.assertIn("custom&lt;model&gt;<small>Reasoning: custom&lt;effort&gt;", summaries)
        filtering = footer.split('Comment filtering <small>· 1</small></th>')[1].split('</tr>')[0]
        self.assertIn("gpt-6-luna<small>Reasoning: none", filtering)
        self.assertNotIn("gpt-6-luna", summaries)

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
                app.record_text_usage({"model": model + "-2026-11-18", "reasoning": {"effort": "high"},
                                       "service_tier": "default",
                                       "usage": {"input_tokens": 2_000, "output_tokens": 500}}, model, effort)
                return "Recorded summary"

            def header_request(key, model, effort, *args, **kwargs):
                app.record_text_usage({"service_tier": "default",
                                       "usage": {"input_tokens": 1_000, "output_tokens": 100}}, model, effort)
                return json.dumps({"topic": "", "topic_evidence": [], "participant_roles": []})

            with patch.object(app, "summarize", side_effect=summarize) as call, \
                    patch.object(app, "api_request", side_effect=header_request) as header_call:
                app.process_file(source, args, "test-key")
                html = summary.read_text(encoding="utf-8")
                self.assertIn("≈ 0.039", html)
                self.assertIn("<details><summary>Cost breakdown</summary>", html)
                self.assertIn("gpt-6.2-astra-2026-11-18<small>Reasoning: high", html)
                self.assertIn("gpt-6.2-sol<small>Reasoning: medium", html)
                self.assertFalse(summary.with_suffix(".err").exists())
                app.process_file(source, args, "test-key")
                call.assert_called_once()
                header_call.assert_called_once()
                html = summary.read_text(encoding="utf-8")
                self.assertIn("Recorded summary", html)
                self.assertIn("No new API usage recorded", html)
