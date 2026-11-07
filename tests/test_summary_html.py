"""Multiple detail levels, escaped HTML, output protection, and paid-call resume."""
import contextlib
from html.parser import HTMLParser
import io
from pathlib import Path
import shutil
import subprocess
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


class EmbeddedLog(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.in_log = False
        self.text = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == "div" and dict(attrs).get("class") == "transcript-content":
            self.in_log = True

    def handle_endtag(self, tag):
        if tag == "div":
            self.in_log = False

    def handle_data(self, text):
        if self.in_log:
            self.text.append(text)


class DetailDots(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.level = None
        self.counts = {}
        self.hidden = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "span" and attrs.get("class") == "detail-dots":
            self.level = int(attrs["data-count"])
            self.counts[self.level] = 0
            self.hidden.append(attrs.get("aria-hidden"))
        if tag == "i" and attrs.get("class") == "dot":
            self.counts[self.level] += 1

    def handle_endtag(self, tag):
        if tag == "span":
            self.level = None


class SummaryHtmlTests(unittest.TestCase):
    def setUp(self):
        metadata = patch.object(app, "extract_report_metadata", return_value={"topic": "Test conversation.", "roles": {}})
        metadata.start()
        self.addCleanup(metadata.stop)

    def setup_case(self, root, *extra):
        source = root / "meeting.mkv"
        source.write_bytes(b"input")
        args = app.build_parser().parse_args([
            "--output-dir", str(root / "data"), "--cache-dir", str(root / "cache"),
            "--report-tabs", "1", "5", "10", "transcript", *extra])
        log, summary = app.output_paths(source, args.output_dir)
        app.atomic_write(log, "Reviewed conversation.\n")
        return source, args, log, summary

    def test_cli_accepts_spaces_commas_and_deduplicates_in_requested_order(self):
        parser = app.build_parser()
        for values in (["10", "1", "5", "1"], ["10,1,5,1"], ["10,1", "5"]):
            self.assertEqual(parser.parse_args(["--report-tabs", *values]).report_tabs, [10, 1, 5])
        self.assertEqual(parser.parse_args(["--report-tabs", "5,5"]).report_tabs, [5])
        for values in ([], ["1,,5"], ["1,11"], ["0,5"], ["1..10"], ["5,"], ["one"]):
            with self.subTest(values=values), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    parser.parse_args(["--report-tabs", *values])

    def test_selected_tabs_control_order_visibility_and_transcript_inclusion(self):
        for selection in ([5], ["transcript"], ["transcript", 3], [1, 3, 5, 10, "transcript"]):
            with self.subTest(selection=selection):
                summaries = {level: "Summary." for level in app.summary_levels(selection)}
                text = app.summary_html(Path("meeting.mkv"), summaries,
                                        transcript="PRIVATE_TRANSCRIPT_SENTINEL", tabs=selection)
                elements = Elements(text).elements
                tabs = [attrs for tag, attrs in elements if attrs.get("role") == "tab"]
                panels = [attrs for tag, attrs in elements if attrs.get("role") == "tabpanel"]
                self.assertEqual([tab["id"] for tab in tabs], [f"tab-{tab}" for tab in selection])
                self.assertEqual([tab["aria-controls"] for tab in tabs], [panel["id"] for panel in panels])
                self.assertEqual([tab["aria-selected"] for tab in tabs], ["true"] + ["false"] * (len(tabs) - 1))
                self.assertNotIn("hidden", panels[0])
                self.assertTrue(all("hidden" in panel for panel in panels[1:]))
                self.assertEqual("PRIVATE_TRANSCRIPT_SENTINEL" in text, "transcript" in selection)
                self.assertEqual("Full transcript included." in text,
                                 bool(summaries) and "transcript" in selection)
                self.assertNotIn(">Log<", text)
                self.assertNotIn("@@CONTENTS@@", text)

    def test_multiple_prompt_preview_needs_no_api(self):
        output = io.StringIO()
        with patch.object(app, "load_env"), patch.object(app, "api_request") as api, \
                contextlib.redirect_stdout(output):
            self.assertEqual(app.main(["--show-prompt", "--report-tabs", "1,5,10"]), 0)
        api.assert_not_called()
        for level in (1, 5, 10):
            self.assertIn(f"Summary detail level: {level}/10", output.getvalue())

    @unittest.skipUnless(shutil.which("node"), "Node.js is optional for offline JavaScript checks")
    def test_theme_persistence_and_tab_navigation_with_blocked_storage(self):
        text = app.summary_html(Path("meeting.mkv"), {1: "Brief.", 10: "Detailed."}, transcript="Full transcript.")
        result = subprocess.run([shutil.which("node"), str(Path(__file__).with_name("report_theme_check.cjs"))],
                                input=text, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_html_escapes_source_and_model_text_and_connects_accessible_tabs(self):
        text = app.summary_html(Path('<img src=x onerror=alert(1)>@@TABS@@.mkv'), {
            10: 'Привет, Alice & Bob.\n\n<script>alert("x")</script>\nSecond line.',
            1: 'A short summary.'}, transcript="Original log.")
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
        self.assertEqual([tab["aria-selected"] for tab in tabs], ["true", "false", "false"])
        self.assertEqual([tab["id"] for tab in tabs], ["tab-10", "tab-1", "tab-transcript"])
        self.assertNotIn("hidden", panels[0])
        self.assertIn("hidden", panels[1])
        self.assertFalse(any("src" in attrs or "href" in attrs for tag, attrs in elements))

    def test_summary_only_generates_each_level_from_the_same_log_and_preserves_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, log, summary = self.setup_case(Path(tmp), "--summary-only")
            markdown = summary.with_suffix(".md")
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
            self.assertIn("Reviewed conversation.\n", summary.read_text())

    def test_embedded_log_preserves_text_and_cannot_inject_html_or_external_assets(self):
        transcript = ('\nDETAILED TRANSCRIPT\n\tAlice & Bob — Привет.\n\n'
                      '</div><script>alert("log")</script><img src="https://example.invalid/image">\n'
                      'https://example.invalid/recording.log.md\n@@SOURCE@@\n  Trailing spaces.  \n')
        rendered = app.summary_html(Path("meeting.mkv"), {1: "Brief.", 3: "Overview.", 5: "Expanded.", 10: "Detailed."},
                                    transcript=transcript)
        self.assertEqual("".join(EmbeddedLog(rendered).text), transcript)
        elements = Elements(rendered).elements
        self.assertEqual([attrs["id"] for tag, attrs in elements if attrs.get("role") == "tab"],
                         ["tab-1", "tab-3", "tab-5", "tab-10", "tab-transcript"])
        self.assertEqual(sum(tag == "script" for tag, attrs in elements), 1)
        self.assertFalse(any(tag in ("img", "link", "iframe", "object", "embed") for tag, attrs in elements))
        self.assertFalse(any(key in attrs for tag, attrs in elements for key in ("src", "href", "srcset")))
        icon = [attrs for tag, attrs in elements if attrs.get("class") == "transcript-icon"]
        self.assertEqual(icon, [{"class": "transcript-icon", "aria-hidden": "true"}])

    def test_long_log_is_embedded_without_truncation(self):
        transcript = "BEGIN_LOG\n" + "Long conversation. " * 20000 + "\nEND_LOG\n"
        rendered = app.summary_html(Path("meeting.mkv"), {1: "Brief.", 10: "Detailed."}, transcript=transcript)
        self.assertEqual("".join(EmbeddedLog(rendered).text), transcript)

    def test_each_detail_level_has_exactly_that_many_decorative_dots(self):
        summaries = {level: "Summary." for level in range(1, 11)}
        rendered = app.summary_html(Path("meeting.mkv"), summaries, transcript="Full log.")
        dots = DetailDots(rendered)
        self.assertEqual(dots.counts, {level: level for level in range(1, 11)})
        self.assertEqual(dots.hidden, ["true"] * 10)
        tabs = [attrs["id"] for tag, attrs in Elements(rendered).elements if attrs.get("role") == "tab"]
        self.assertEqual(tabs, [f"tab-{level}" for level in range(1, 11)] + ["tab-transcript"])

    def test_copied_html_remains_complete_without_the_original_log_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, log, summary = self.setup_case(Path(tmp), "--summary-only")
            transcript = "DETAILED TRANSCRIPT\n\n[00:00–00:02] Alice\nOriginal words & uncertainty [speaker uncertain: retained].\n"
            app.atomic_write(log, transcript)
            with patch.object(app, "summarize", return_value="Summary.") as summarize:
                app.process_file(source, args, "key")
            self.assertEqual(summarize.call_count, 3)
            shared = Path(tmp) / "shared" / "report.html"
            shared.parent.mkdir(); shared.write_bytes(summary.read_bytes())
            log.unlink()
            self.assertEqual(list(shared.parent.iterdir()), [shared])
            self.assertEqual("".join(EmbeddedLog(shared.read_text()).text), transcript)

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
        for change in ("transcript", "model", "effort", "details", "transcript-tab", "order", "prompt", "force"):
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
                    args.report_tabs = [1, 10]
                elif change == "transcript-tab":
                    args.report_tabs.remove("transcript")
                elif change == "order":
                    args.report_tabs.reverse()
                elif change == "force":
                    args.force = True
                prompt = app.SUMMARIZATION_PROMPT + (" Changed." if change == "prompt" else "")
                with patch.object(app, "SUMMARIZATION_PROMPT", prompt), \
                        patch.object(app, "summarize", return_value="Fresh.") as summarize:
                    app.process_file(source, args, "key")
                self.assertEqual([call.kwargs["detail"] for call in summarize.call_args_list],
                                 app.summary_levels(args.report_tabs))
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
                                               "--report-tabs", "1,5,10"]), 0)
                process.assert_not_called(); models.assert_not_called()
                self.assertFalse(args.cache_dir.exists())
                self.assertEqual(before, [(p.read_bytes(), p.stat().st_mtime_ns) for p in (log, existing)])

    def test_unowned_html_without_a_log_is_protected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, log, summary = self.setup_case(Path(tmp))
            log.unlink()
            app.atomic_write(summary, "Keep this report")
            args.report_tabs = [1]
            with patch.object(app, "extract_audio") as extract:
                with self.assertRaisesRegex(app.AppError, "ownership"):
                    app.process_file(source, args, "key")
            extract.assert_not_called()
            self.assertEqual(summary.read_text(), "Keep this report\n")

    def test_summary_only_archives_a_known_stale_alternate_format_only_after_generation_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, log, summary = self.setup_case(Path(tmp), "--summary-only")
            markdown = summary.with_suffix(".md")
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
            source, args, log, summary = self.setup_case(Path(tmp), "--force", "--transcription-model", "gpt-transcribe-online")
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
                self.assertEqual(app.main(["-f", str(source), "--summary-only", "--report-tabs", "1,10",
                                           "--summarize-model", "none", "--output-dir", str(args.output_dir)]), 0)
            summarize.assert_not_called()
            self.assertFalse(summary.exists())


if __name__ == "__main__":
    unittest.main()
