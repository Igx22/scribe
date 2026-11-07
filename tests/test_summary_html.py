"""Multiple detail levels, escaped HTML, output protection, and paid-call resume."""
import contextlib
from html.parser import HTMLParser
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import scribe as app


class Elements(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.elements = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


class SummaryHtmlTests(unittest.TestCase):
    def setup_case(self, root, *extra):
        source = root / "meeting.mkv"
        source.write_bytes(b"input")
        args = app.build_parser().parse_args([
            "--output-dir", str(root / "data"), "--cache-dir", str(root / "cache"),
            "--summary-detail", "1", "5", "10", *extra])
        log, summary = app.output_paths(source, args.output_dir, args.summary_detail)
        app.atomic_write(log, "Reviewed conversation.\n")
        return source, args, log, summary

    def test_cli_accepts_spaces_commas_and_deduplicates_in_requested_order(self):
        parser = app.build_parser()
        for values in (["10", "1", "5", "1"], ["10,1,5,1"], ["10,1", "5"]):
            self.assertEqual(parser.parse_args(["--summary-detail", *values]).summary_detail, [10, 1, 5])
        self.assertEqual(parser.parse_args(["--summary-detail", "5,5"]).summary_detail, 5)
        for values in ([], ["1,,5"], ["1,11"], ["0,5"], ["1..10"], ["5,"], ["one"]):
            with self.subTest(values=values), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    parser.parse_args(["--summary-detail", *values])

    def test_multiple_prompt_preview_needs_no_api(self):
        output = io.StringIO()
        with patch.object(app, "load_env"), patch.object(app, "api_request") as api, \
                contextlib.redirect_stdout(output):
            self.assertEqual(app.main(["--show-prompt", "--summary-detail", "1,5,10"]), 0)
        api.assert_not_called()
        for level in (1, 5, 10):
            self.assertIn(f"Summary detail level: {level}/10", output.getvalue())

    def test_html_escapes_source_and_model_text_and_connects_accessible_tabs(self):
        text = app.summary_html(Path('<img src=x onerror=alert(1)>@@TABS@@.mkv'), {
            10: 'Привет, Alice & Bob.\n\n<script>alert("x")</script>\nSecond line.',
            1: 'A short summary.'})
        elements = Elements(text).elements
        self.assertNotIn("img", [tag for tag, attrs in elements])
        self.assertEqual(sum(tag == "script" for tag, attrs in elements), 1)
        self.assertIn("&lt;script&gt;", text)
        self.assertIn("Alice &amp; Bob", text)
        self.assertIn("Привет", text)
        self.assertIn("@@TABS@@.mkv", text)
        tabs = [attrs for tag, attrs in elements if attrs.get("role") == "tab"]
        panels = [attrs for tag, attrs in elements if attrs.get("role") == "tabpanel"]
        self.assertEqual([tab["aria-controls"] for tab in tabs], [panel["id"] for panel in panels])
        self.assertEqual([panel["aria-labelledby"] for panel in panels], [tab["id"] for tab in tabs])
        self.assertEqual([tab["aria-selected"] for tab in tabs], ["true", "false"])
        self.assertNotIn("hidden", panels[0])
        self.assertIn("hidden", panels[1])
        self.assertFalse(any("src" in attrs or "href" in attrs for tag, attrs in elements))

    def test_summary_only_generates_each_level_from_the_same_log_and_preserves_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, log, summary = self.setup_case(Path(tmp), "--summary-only")
            markdown = app.output_paths(source, args.output_dir)[1]
            app.atomic_write(markdown, "Original summary")
            before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in (log, markdown)]
            with patch.object(app, "summarize", side_effect=lambda *a, detail: f"Summary for {detail}.") as summarize, \
                    patch.object(app, "extract_audio") as extract, patch.object(app, "fuse_transcripts") as fusion:
                app.process_file(source, args, "key")
            self.assertEqual([call.kwargs["detail"] for call in summarize.call_args_list], [1, 5, 10])
            self.assertTrue(all(call.args[0] == log.read_text() for call in summarize.call_args_list))
            extract.assert_not_called(); fusion.assert_not_called()
            self.assertEqual(before, [(path.read_bytes(), path.stat().st_mtime_ns) for path in (log, markdown)])
            self.assertEqual(summary.suffix, ".html")
            for level in (1, 5, 10):
                self.assertIn(f"Summary for {level}.", summary.read_text())

    def test_failure_preserves_existing_html_and_retries_only_unfinished_levels(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, log, summary = self.setup_case(Path(tmp), "--summary-only")
            app.atomic_write(summary, "Previous HTML")
            before = (summary.read_bytes(), summary.stat().st_mtime_ns)
            with patch.object(app, "summarize", side_effect=["Brief.", app.AppError("timeout")]) as summarize:
                with self.assertRaisesRegex(app.AppError, "timeout"):
                    app.process_file(source, args, "key")
            self.assertEqual(before, (summary.read_bytes(), summary.stat().st_mtime_ns))
            with patch.object(app, "summarize", side_effect=["Expanded.", "Detailed."]) as summarize:
                app.process_file(source, args, "key")
            self.assertEqual([call.kwargs["detail"] for call in summarize.call_args_list], [5, 10])
            self.assertIn("Brief.", summary.read_text())
            # A deliberate regeneration after successful publication starts fresh.
            with patch.object(app, "summarize", return_value="Fresh.") as summarize:
                app.process_file(source, args, "key")
            self.assertEqual(summarize.call_count, 3)

    def test_pending_levels_are_invalidated_by_changed_settings_or_force(self):
        for change in ("transcript", "model", "effort", "details", "prompt", "force"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                source, args, log, summary = self.setup_case(Path(tmp), "--summary-only")
                with patch.object(app, "summarize", side_effect=["Old brief.", app.AppError("timeout")]):
                    with self.assertRaises(app.AppError):
                        app.process_file(source, args, "key")
                if change == "transcript":
                    app.atomic_write(log, "Edited conversation.")
                elif change == "model":
                    args.summarize_model = ("another-model", "medium")
                elif change == "effort":
                    args.summarize_model = ("gpt-6.1-sol", "high")
                elif change == "details":
                    args.summary_detail = [1, 10]
                elif change == "force":
                    args.force = True
                prompt = app.SUMMARIZATION_PROMPT + (" Changed." if change == "prompt" else "")
                with patch.object(app, "SUMMARIZATION_PROMPT", prompt), \
                        patch.object(app, "summarize", return_value="Fresh.") as summarize:
                    app.process_file(source, args, "key")
                self.assertEqual([call.kwargs["detail"] for call in summarize.call_args_list],
                                 app.summary_levels(args.summary_detail))
                self.assertNotIn("Old brief.", summary.read_text())

    def test_completed_html_or_markdown_skips_before_cache_or_network(self):
        for extension in (".md", ".html"):
            with self.subTest(extension=extension), tempfile.TemporaryDirectory() as tmp:
                source, args, log, summary = self.setup_case(Path(tmp))
                existing = summary.with_suffix(extension)
                app.atomic_write(existing, "Reviewed summary")
                before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in (log, existing)]
                with patch.object(app, "_process_file") as process, patch.object(app, "ensure_models") as models, \
                        patch.object(app, "load_env"), patch.dict(app.os.environ, {"OPENAI_API_KEY": ""}):
                    app.process_file(source, args, "")
                    self.assertEqual(app.main(["-f", str(source), "--output-dir", str(args.output_dir),
                                               "--summary-detail", "1,5,10"]), 0)
                process.assert_not_called(); models.assert_not_called()
                self.assertFalse(args.cache_dir.exists())
                self.assertEqual(before, [(p.read_bytes(), p.stat().st_mtime_ns) for p in (log, existing)])

    def test_unowned_html_without_a_log_is_protected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, log, summary = self.setup_case(Path(tmp))
            log.unlink()
            app.atomic_write(summary, "Keep this report")
            args.summary_detail = 1
            with patch.object(app, "extract_audio") as extract:
                with self.assertRaisesRegex(app.AppError, "ownership"):
                    app.process_file(source, args, "key")
            extract.assert_not_called()
            self.assertEqual(summary.read_text(), "Keep this report\n")

    def test_summary_only_archives_a_known_stale_alternate_format_only_after_generation_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, log, summary = self.setup_case(Path(tmp), "--summary-only")
            markdown = app.output_paths(source, args.output_dir)[1]
            app.atomic_write(markdown, "Summary of the old conversation")
            with patch.object(app, "summarize", return_value="Old HTML summary."):
                app.process_file(source, args, "key")
            old_html = summary.read_bytes()
            app.atomic_write(log, "Edited conversation.")
            with patch.object(app, "summarize", side_effect=app.AppError("timeout")):
                with self.assertRaises(app.AppError):
                    app.process_file(source, args, "key")
            self.assertEqual(summary.read_bytes(), old_html)
            self.assertTrue(markdown.is_file())
            with patch.object(app, "summarize", return_value="Summary of edited conversation."):
                app.process_file(source, args, "key")
            self.assertFalse(markdown.exists())
            self.assertTrue(any(args.cache_dir.glob("*/outputs/*/previous-*.summary.md")))
            self.assertIn("Summary of edited conversation.", summary.read_text())

    def test_forced_transcription_archives_both_formats_before_failed_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, log, summary = self.setup_case(Path(tmp), "--force", "--transcription-model", "gpt-transcribe")
            for path in app.summary_paths(source, args.output_dir):
                app.atomic_write(path, "Previous " + path.suffix)
            chunks = [{"start": 0, "end": 2, "text": "Changed speech."}]
            with patch.object(app, "extract_audio"), patch.object(app, "transcribe_gpt", return_value=chunks), \
                    patch.object(app, "summarize", side_effect=app.AppError("timeout")):
                with self.assertRaises(app.AppError):
                    app.process_file(source, args, "key")
            self.assertTrue(all(not path.exists() for path in app.summary_paths(source, args.output_dir)))
            self.assertTrue(any(args.cache_dir.glob("*/outputs/*/previous-*.summary.html")))
            self.assertTrue(any(args.cache_dir.glob("*/outputs/*/previous-*.summary.md")))
            self.assertIn("Changed speech.", log.read_text())

    def test_disabled_summaries_do_not_generate_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, log, summary = self.setup_case(Path(tmp), "--summary-only", "--summarize-model", "none")
            with patch.object(app, "load_env"), patch.object(app, "summarize") as summarize:
                self.assertEqual(app.main(["-f", str(source), "--summary-only", "--summary-detail", "1,10",
                                           "--summarize-model", "none", "--output-dir", str(args.output_dir)]), 0)
            summarize.assert_not_called()
            self.assertFalse(summary.exists())


if __name__ == "__main__":
    unittest.main()
