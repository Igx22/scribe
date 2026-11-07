"""Mode isolation, offline guarantees, completion skipping, and CLI behavior."""
import contextlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import scribe as app
from tests import runtime_paths


class ModeTests(unittest.TestCase):
    def setUp(self):
        final = patch.object(app, "fuse_transcripts", side_effect=lambda chunks, turns, *a, **k: (turns, []))
        final.start()
        self.addCleanup(final.stop)
        metadata = patch.object(app, "extract_report_metadata", return_value={"topic": "Test conversation.", "roles": {}})
        metadata.start()
        self.addCleanup(metadata.stop)

    def test_offline_launcher_cannot_bootstrap_a_missing_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            launcher = Path(tmp) / "scribe.sh"
            shutil.copy2(app.APP_DIR / "scribe.sh", launcher)
            result = subprocess.run(["/bin/bash", str(launcher), "--offline"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("Installing", result.stdout + result.stderr)
            self.assertFalse((Path(tmp) / "data").exists())

    def setup_case(self, root, *options):
        source = root / "recording.mkv"
        source.write_bytes(b"fixture")
        args = app.build_parser().parse_args([
            "-f", str(source),
            "--output-dir", str(root / "data"), "--report-tabs", "1", *options])
        args.cache_dir = root / "data/.cache"
        local = {"duration": 2, "words": [], "voices": [], "turns": [
            {"start": 0, "end": 2, "speaker": 1, "text": "Recognized locally."}]}
        chunks = [{"index": 0, "start": 0, "end": 2, "text": "Recognized via API."}]
        return source, args, local, chunks

    def test_offline_overrides_api_options_and_makes_no_network_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, local, _ = self.setup_case(Path(tmp), "--offline",
                "--transcription-model", "gpt-transcribe+whisperx", "--summarize-model", "gpt-6-luna:high")
            with patch.object(app, "extract_audio"), patch.object(app, "local_recognition", return_value=local), \
                    patch.object(app.urllib.request, "urlopen", side_effect=AssertionError("Network forbidden")), \
                    patch.object(app, "transcribe_gpt") as gpt, patch.object(app, "fuse_transcripts", side_effect=lambda chunks, turns, *a, **k: (turns, [])) as fuse, \
                    patch.object(app, "summarize") as summary:
                app.process_file(source, args, "configured-key")
            self.assertEqual(args.transcription_model, "whisperx")
            self.assertIsNone(args.summarize_model)
            gpt.assert_not_called(); fuse.assert_not_called(); summary.assert_not_called()
            log, summary_path = app.output_paths(source, args.output_dir)
            self.assertIn("Recognized locally.", log.read_text())
            self.assertFalse(summary_path.exists())

    def test_api_only_reconciles_text_without_local_recognition(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, _, chunks = self.setup_case(Path(tmp),
                "--transcription-model", "gpt-transcribe-online", "--summarize-model", "none")
            with patch.object(app, "extract_audio"), patch.object(app, "transcribe_gpt", return_value=chunks), \
                    patch.object(app, "local_recognition") as local, patch.object(app, "fuse_transcripts", side_effect=lambda chunks, turns, *a, **k: (turns, [])) as fuse, \
                    patch.object(app, "summarize") as summary:
                app.process_file(source, args, "key")
            local.assert_not_called(); fuse.assert_called_once(); summary.assert_not_called()
            self.assertTrue(fuse.call_args.kwargs["single_source"])
            log, summary_path = app.output_paths(source, args.output_dir)
            self.assertIn("Recognized via API.", log.read_text())
            self.assertIn("Speaker labels and word-level timing are unavailable", log.read_text())
            self.assertNotIn("] A\n", log.read_text())
            self.assertFalse(summary_path.exists())

    def test_api_only_failure_does_not_run_local_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, _, _ = self.setup_case(Path(tmp), "--transcription-model", "gpt-transcribe-online")
            with patch.object(app, "extract_audio"), \
                    patch.object(app, "transcribe_gpt", side_effect=app.AppError("credits exhausted")), \
                    patch.object(app, "local_recognition") as local, patch.object(app, "summarize") as summary:
                with self.assertRaisesRegex(app.AppError, "credits exhausted"):
                    app.process_file(source, args, "key")
            local.assert_not_called(); summary.assert_not_called()
            self.assertFalse(app.output_paths(source, args.output_dir)[0].exists())

    def test_none_disables_summary_but_all_still_fuses_with_sol(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, local, chunks = self.setup_case(Path(tmp), "--transcription-model", app.COMBINED_MODE, "--summarize-model", "none")
            with patch.object(app, "extract_audio"), patch.object(app, "local_recognition", return_value=local), \
                    patch.object(app, "transcribe_gpt", return_value=chunks), \
                    patch.object(app, "fuse_transcripts", return_value=(local["turns"], [])) as fuse, \
                    patch.object(app, "summarize") as summary:
                app.process_file(source, args, "key")
            self.assertEqual(fuse.call_args.args[4:6], ("gpt-6.1-sol", "medium"))
            summary.assert_not_called()

    def test_completed_pair_skips_before_cache_creation_and_model_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, args, _, _ = self.setup_case(root)
            log, summary = app.output_paths(source, args.output_dir)
            app.atomic_write(log, "User-edited log")
            app.atomic_write(summary, "User-edited summary")
            before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in (log, summary)]
            with patch.object(app, "_process_file") as process, patch.object(app, "ensure_models") as models, \
                    patch.object(app, "load_env"), patch.object(app.Path, "cwd", return_value=root), \
                    patch.object(app.urllib.request, "urlopen", side_effect=AssertionError("Network forbidden")):
                app.process_file(source, args, "")
                self.assertEqual(app.main(["-f", str(source), "--report-tabs", "10"]), 0)
            process.assert_not_called(); models.assert_not_called()
            self.assertFalse(args.cache_dir.exists())
            self.assertEqual(before, [(p.read_bytes(), p.stat().st_mtime_ns) for p in (log, summary)])

    def test_summary_only_bypasses_completion_skip_and_preserves_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, _, _ = self.setup_case(Path(tmp), "--summary-only",
                "--summarize-model", "gpt-6-luna:high", "--report-tabs", "5")
            log, summary_path = app.output_paths(source, args.output_dir)
            app.atomic_write(log, "Reviewed text")
            app.atomic_write(summary_path, "Previous summary")
            with patch.object(app, "summarize", return_value="New summary") as summary, \
                    patch.object(app, "extract_audio") as extract:
                app.process_file(source, args, "key")
            extract.assert_not_called()
            self.assertEqual(summary.call_args.args[2:], ("gpt-6-luna", "high"))
            self.assertEqual(summary.call_args.kwargs["detail"], 5)
            self.assertEqual(log.read_text(), "Reviewed text\n")
            self.assertIn("New summary", summary_path.read_text())

    def test_model_packaging_and_removed_options(self):
        parser = app.build_parser()
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(app.build_parser().parse_args([]).summarize_model, ("gpt-6.1-sol", "medium"))
        self.assertEqual(parser.parse_args(["--summarize-model", "gpt-6-luna"]).summarize_model,
                         ("gpt-6-luna", "medium"))
        self.assertIsNone(parser.parse_args(["--summarize-model", "none"]).summarize_model)
        for options in (["--model", "gpt-6-luna"], ["--reasoning", "medium"],
                        ["--transcription-model", "whisper"], ["--summarize-model", "gpt-6-luna:invalid"]):
            with self.subTest(options=options), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    parser.parse_args(options)
        offline = parser.parse_args(["--offline", "--summary-only"])
        with self.assertRaisesRegex(app.AppError, "offline"):
            app.configure_mode(offline)

    def test_api_only_main_does_not_prepare_local_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, args, _, chunks = self.setup_case(root)
            with runtime_paths(cache_dir=args.cache_dir), \
                    patch.object(app, "load_env"), patch.object(app, "ensure_models") as models, \
                    patch.object(app, "extract_audio"), patch.object(app, "transcribe_gpt", return_value=chunks), \
                    patch.object(app, "local_recognition") as local:
                self.assertEqual(app.main(["-f", str(source), "--transcription-model", "gpt-transcribe-online",
                    "--summarize-model", "none", "--output-dir", str(args.output_dir)]), 0)
            models.assert_not_called(); local.assert_not_called()


if __name__ == "__main__":
    unittest.main()
