"""Public CLI boundaries and reuse of application-owned paths."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import scribe as app


class CliTests(unittest.TestCase):
    def test_removed_options_fail_before_processing_or_model_preparation(self):
        for options in (["--language", "en"], ["--vocabulary", "Example"],
                        ["--models-dir", "models"], ["--cache-dir", "cache"],
                        ["--download-models"]):
            with self.subTest(options=options), contextlib.redirect_stderr(io.StringIO()), \
                    patch.object(app, "load_env"), patch.object(app, "ensure_models") as models, \
                    patch.object(app, "process_files") as process:
                with self.assertRaises(SystemExit) as error:
                    app.main(options)
                self.assertEqual(error.exception.code, 2)
                models.assert_not_called()
                process.assert_not_called()

    def test_default_paths_ignore_the_working_directory_and_use_auto_recognition(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app.Path, "cwd", return_value=Path(tmp)):
            args = app.build_parser().parse_args([])
        self.assertEqual(args.models_dir, app.APP_DATA / "models")
        self.assertEqual(args.cache_dir, app.APP_DATA / ".cache")
        self.assertEqual(args.language, "auto")
        self.assertEqual(args.vocabulary, "")

    def test_default_cache_reuses_internal_final_across_working_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "application/data"
            source = root / "meeting.mkv"
            source.write_bytes(b"fixture")
            local = {"duration": 1, "words": [], "turns": [
                {"start": 0, "end": 1, "speaker": 1, "text": "Hello."}], "voices": []}
            options = ["-f", str(source), "--offline", "--output-dir", str(root / "out")]
            with patch.object(app, "APP_DATA", data), patch.object(app, "load_env"), \
                    patch.object(app.platform, "system", return_value="Darwin"), \
                    patch.object(app.platform, "machine", return_value="arm64"), \
                    patch.object(app.platform, "mac_ver", return_value=("14.0", (), "")), \
                    patch.object(app, "ensure_models"), patch.object(app, "extract_audio") as extract, \
                    patch.object(app, "local_recognition", return_value=local) as recognize, \
                    patch.object(app, "api_request", side_effect=AssertionError("Network forbidden")), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(app.main(options), 0)
                with patch.object(app.Path, "cwd", return_value=root / "another-directory"):
                    self.assertEqual(app.main(options), 0)
            extract.assert_called_once()
            recognize.assert_called_once()
            self.assertTrue(list((data / ".cache").glob("*/outputs/*/state.json")))
            self.assertFalse((root / "another-directory/data").exists())
