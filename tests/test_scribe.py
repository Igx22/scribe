"""Run: data/.venv/bin/python3 -I -B -m unittest discover -s tests -t . -v

No API key, network, ML models or billable requests are needed for these checks.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import wave

import scribe as app


class AppTests(unittest.TestCase):
    def setUp(self):
        final = patch.object(app, "fuse_transcripts", side_effect=lambda chunks, turns, *a, **k: (turns, []))
        final.start()
        self.addCleanup(final.stop)
        metadata = patch.object(app, "extract_report_metadata", return_value={"topic": "Test conversation.", "roles": {}})
        metadata.start()
        self.addCleanup(metadata.stop)

    def test_saved_model_path_uses_home_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            home = root / "home"
            with patch.object(app.Path, "home", return_value=home):
                self.assertEqual(app.portable_model_path(home / "project/models"),
                                 "~/project/models")
                self.assertEqual(app.portable_model_path(root / "shared/models"),
                                 str(root / "shared/models"))

    def test_file_selection_and_output_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with self.assertRaisesRegex(app.AppError, "data"):
                app.collect_files([], root)
            data = root / "data"
            data.mkdir()
            with self.assertRaisesRegex(app.AppError, "No MKV"):
                app.collect_files([], root)
            a, b = data / "recording 1.mkv", data / "recording 2.MKV"
            outside = root / "explicit input.mkv"
            a.touch(); b.touch(); outside.touch(); (data / "ignore.mp4").touch()
            (data / "nested").mkdir(); (data / "nested/ignore.mkv").touch()
            self.assertEqual(set(app.collect_files([], root)), {a, b})
            self.assertEqual(app.collect_files([str(b), str(a), str(b)], root), [b, a])
            self.assertEqual(app.collect_files([str(outside)], root), [outside])
            with patch.object(app.Path, "cwd", return_value=root):
                self.assertEqual(app.output_paths(a), (data / "recording 1.log.md", data / "recording 1.summary.html"))

    def test_bare_names_search_data_and_movies_and_explicit_paths_use_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            cwd, home = root / "launch directory", root / "home"
            data, movies = cwd / "data", home / "Movies"
            data.mkdir(parents=True); movies.mkdir(parents=True)
            local, movie, explicit = data / "local.mkv", movies / "movie.mkv", cwd / "current.mkv"
            for path in (local, movie, explicit):
                path.touch()
            with patch.object(app.Path, "home", return_value=home):
                self.assertEqual(app.collect_files(["local.mkv", "movie.mkv", "local.mkv"], cwd), [local, movie])
                self.assertEqual(app.collect_files(["./current.mkv", "data/local.mkv"], cwd), [explicit, local])
                with self.assertRaisesRegex(app.AppError, "Searched:.*data.*Movies"):
                    app.collect_files(["current.mkv"], cwd)
                (movies / "local.mkv").touch()
                with self.assertRaisesRegex(app.AppError, "Ambiguous filename"):
                    app.collect_files(["local.mkv"], cwd)
                (movies / "local.mkv").unlink()
                (movies / "local.mkv").symlink_to(local)
                self.assertEqual(app.collect_files(["local.mkv"], cwd), [local])
            with patch.object(app.Path, "cwd", return_value=cwd):
                self.assertEqual(app.output_paths(movie), (data / "movie.log.md", data / "movie.summary.html"))
                custom = root / "custom outputs"
                self.assertEqual(app.output_paths(movie, custom), (custom / "movie.log.md", custom / "movie.summary.html"))

    def test_input_directory_scans_only_mkv_files_and_deduplicates_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            recordings = root / "meeting recordings"
            recordings.mkdir()
            first, second = recordings / "a.mkv", recordings / "b.MKV"
            first.touch(); second.touch()
            (recordings / "alias.mkv").symlink_to(first)
            (recordings / "ignore.mp4").touch()
            (recordings / "nested.mkv").mkdir()
            (recordings / "nested.mkv/ignore.mkv").touch()
            (root / "data").mkdir(); (root / "data/other.mkv").touch()
            home_relative = Path("~") / os.path.relpath(recordings, Path.home())
            for selected in (recordings, Path("meeting recordings"), home_relative):
                with self.subTest(selected=selected):
                    self.assertEqual(app.collect_files([], root, selected), [first, second])

    def test_input_directory_errors_precede_processing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            empty, regular = root / "empty", root / "recording.mkv"
            empty.mkdir(); regular.touch()
            (empty / "nested").mkdir(); (empty / "nested/hidden.mkv").touch()
            for directory, message in ((root / "missing", "Input directory"),
                                       (regular, "not a directory"), (empty, "No MKV")):
                with self.subTest(directory=directory), patch.object(app, "load_env"), \
                        patch.object(app, "ensure_models") as models, \
                        patch.object(app, "process_file") as process, \
                        patch.object(app.urllib.request, "urlopen", side_effect=AssertionError("Network forbidden")):
                    with self.assertRaisesRegex(app.AppError, message):
                        app.main(["--input-dir", str(directory)])
                    models.assert_not_called(); process.assert_not_called()

    def test_input_directory_and_explicit_file_selection_are_mutually_exclusive(self):
        for options in (["--input-dir", "recordings", "-f", "meeting.mkv"],
                        ["-f", "meeting.mkv", "--input-dir", "recordings"]):
            with self.subTest(options=options), patch("sys.stderr", new=io.StringIO()), \
                    self.assertRaises(SystemExit):
                app.build_parser().parse_args(options)

    def test_input_directory_does_not_change_default_output_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            recordings = root / "recordings"
            recordings.mkdir(); (recordings / "meeting.mkv").touch()
            with patch.object(app, "load_env"), patch.object(app.Path, "cwd", return_value=root), \
                    patch.object(app, "process_file") as process:
                self.assertEqual(app.main(["--input-dir", "recordings",
                                          "--transcription-model", "gpt-transcribe-online",
                                          "--summarize-model", "none"]), 0)
            source, args, _ = process.call_args.args
            self.assertEqual(source, recordings / "meeting.mkv")
            self.assertEqual(args.output_dir, root / "data")

    def test_input_directory_can_share_outputs_and_skip_completed_recordings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            recordings = root / "Movies"
            recordings.mkdir()
            sources = [recordings / "first.mkv", recordings / "second.MKV"]
            for source in sources:
                source.write_bytes(b"original recording")
            options = ["--input-dir", str(recordings), "--output-dir", str(recordings),
                       "--cache-dir", str(root / "cache"), "--transcription-model", "gpt-transcribe-online",
                       "--report-tabs", "1", "transcript"]
            chunks = [{"index": 0, "start": 0, "end": 2, "text": "Meeting words."}]
            with patch.object(app, "load_env"), patch.dict(os.environ, {"OPENAI_API_KEY": "unit-test-key"}), \
                    patch.object(app, "extract_audio"), patch.object(app, "transcribe_gpt", return_value=chunks) as gpt, \
                    patch.object(app, "summarize", return_value="Meeting summary.") as summary, \
                    patch.object(app, "ensure_models") as models:
                self.assertEqual(app.main(options), 0)
            self.assertEqual(gpt.call_count, 2); self.assertEqual(summary.call_count, 2)
            models.assert_not_called()
            outputs = [path for source in sources for path in app.output_paths(source, recordings)]
            for source in sources:
                self.assertEqual(source.read_bytes(), b"original recording")
                log, report = app.output_paths(source, recordings)
                self.assertIn("Meeting words.", log.read_text())
                self.assertIn("Meeting summary.", report.read_text())
                self.assertIn('id="tab-transcript"', report.read_text())
            before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in outputs]
            with patch.object(app, "load_env"), patch.dict(os.environ, {"OPENAI_API_KEY": ""}), \
                    patch.object(app, "process_file") as process, patch.object(app, "ensure_models") as models, \
                    patch.object(app.urllib.request, "urlopen", side_effect=AssertionError("Network forbidden")):
                self.assertEqual(app.main(options), 0)
            process.assert_not_called(); models.assert_not_called()
            self.assertEqual(before, [(path.read_bytes(), path.stat().st_mtime_ns) for path in outputs])

    def test_env_is_data_and_environment_wins(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"OPENAI_MODEL": "existing"}, clear=True):
            p = Path(tmp) / ".env"
            p.write_text('OPENAI_MODEL=ignored\nOPENAI_API_KEY="local-example"\nBAD=$(touch /tmp/no)\n')
            app.load_env(p)
            self.assertEqual(os.environ["OPENAI_MODEL"], "existing")
            self.assertEqual(os.environ["OPENAI_API_KEY"], "local-example")
            self.assertEqual(os.environ["BAD"], "$(touch /tmp/no)")

    def test_main_routes_movies_input_to_launch_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            cwd, home = root / "launch", root / "home"
            cwd.mkdir(); (home / "Movies").mkdir(parents=True)
            movie = home / "Movies/recording.mkv"
            movie.touch()
            with patch.dict(os.environ, {"OPENAI_API_KEY": "unit-test-key"}), \
                    patch.object(app, "load_env"), \
                    patch.object(app.Path, "cwd", return_value=cwd), \
                    patch.object(app.Path, "home", return_value=home), \
                    patch.object(app, "process_file") as process:
                self.assertEqual(app.main(["-f", "recording.mkv", "--summary-only"]), 0)
                process.assert_called_once()
                source, args, _ = process.call_args.args
                self.assertEqual(source, movie)
                self.assertEqual(args.output_dir, cwd / "data")

    def test_voice_numbers_are_used_without_semantic_reassignment(self):
        intervals = [{"start": 0, "end": 2, "speaker": 1}, {"start": 2, "end": 4, "speaker": 2}]
        words = [{"start": .2, "end": 1, "text": " Answer.", "unclear": False},
                 {"start": 2.2, "end": 3, "text": " Question?", "unclear": False}]
        turns = app.assign_speakers(words, intervals)
        self.assertEqual([t["speaker"] for t in turns], [1, 2])
        text = app.transcript_text(Path("example.mkv"), 4, turns)
        self.assertIn("] A\n", text)
        self.assertIn("] B\n", text)
        self.assertNotIn("SPEAKER 1", text)
        self.assertEqual([app.speaker_label(n) for n in (1, 2, 3, 4, 26, 27)],
                         ["A", "B", "C", "D", "Z", "AA"])
        self.assertNotIn("#", text)

    def test_overlap_is_marked_and_unrecognized_turn_not_dropped(self):
        intervals = [{"start": 0, "end": 2, "speaker": 1}, {"start": .2, "end": 1, "speaker": 2},
                     {"start": 5, "end": 6, "speaker": 2}]
        turns = app.assign_speakers([{"start": .3, "end": .7, "text": "Yes", "unclear": False}], intervals)
        self.assertTrue(turns[0]["uncertain"])
        self.assertTrue(any(t["start"] == 5 and t["text"] == "[unintelligible]" for t in turns))

    def test_one_uncertain_word_does_not_mark_a_whole_turn(self):
        intervals = [{"start": 0, "end": 3, "speaker": 1},
                     {"start": 1, "end": 1.5, "speaker": 2}]
        words = [{"start": .1, "end": .6, "text": "Clear beginning", "unclear": False},
                 {"start": 1.1, "end": 1.3, "text": " maybe", "unclear": True},
                 {"start": 2, "end": 2.5, "text": " clear ending.", "unclear": False}]
        turns = app.assign_speakers(words, intervals)
        self.assertEqual(len(turns), 1)
        self.assertFalse(turns[0]["uncertain"])
        self.assertEqual(turns[0]["text"],
            "Clear beginning [speaker uncertain; low-confidence speech: maybe] clear ending.")
        text = app.transcript_text(Path("example.mkv"), 3, turns)
        self.assertIn("] A\nClear beginning", text)
        self.assertNotIn("possible overlap / uncertain", text)
        self.assertNotIn("[unintelligible]\n", text)

    def test_tentative_recognized_words_are_retained(self):
        words = [{"start": 0, "end": .5, "text": "name", "unclear": True},
                 {"start": .5, "end": 1, "text": " afterwards", "unclear": False}]
        turns = app.assign_speakers(words, [{"start": 0, "end": 2, "speaker": 1}])
        self.assertEqual(turns[0]["text"], "[low-confidence speech: name] afterwards")

    def response(self, value):
        return io.BytesIO(json.dumps(value).encode())

    def test_api_request_contract_and_output_extraction(self):
        seen = []
        def fake(request, **kwargs):
            seen.append(request)
            return self.response({"status": "completed", "output": [
                {"type": "reasoning", "summary": []},
                {"type": "message", "content": [{"type": "output_text", "text": "Conversation outcome."}]}],
                "usage": {"input_tokens": 100, "output_tokens": 200}})
        with patch.object(app.urllib.request, "urlopen", fake):
            self.assertEqual(app.api_request("unit-test-key", "gpt-6.1-sol", "high", "Prompt", "Text"), "Conversation outcome.")
        payload = json.loads(seen[0].data)
        self.assertEqual(seen[0].full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(payload["reasoning"], {"effort": "high"})
        self.assertFalse(payload["store"])
        self.assertEqual(payload["input"], "Text")
        self.assertNotIn("temperature", payload)

    def test_incomplete_or_empty_api_response_not_saved_as_success(self):
        for value in [{"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}},
                      {"status": "completed", "output": []}]:
            with self.subTest(value=value), patch.object(app.urllib.request, "urlopen", return_value=self.response(value)):
                with self.assertRaises(app.AppError):
                    app.api_request("unit-test-key", "gpt-6.1-sol", "medium", "Prompt", "Text")

    def test_credit_error_is_not_retried(self):
        error = urllib.error.HTTPError(app.API_URL, 429, "quota", {},
            self.response({"error": {"code": "credit_balance_exhausted"}}))
        with patch.object(app.urllib.request, "urlopen", side_effect=error) as request, patch.object(app.time, "sleep") as sleep:
            with self.assertRaisesRegex(app.AppError, "credits"):
                app.api_request("unit-test-key", "gpt-6.1-sol", "medium", "Prompt", "Text")
            request.assert_called_once()
            sleep.assert_not_called()

    def test_long_recording_includes_every_part(self):
        text = "BEGIN\n\n" + "word " * 40000 + "\n\nEND_OF_RECORDING"
        calls = []
        def fake(key, model, effort, instructions, data, **kwargs):
            calls.append((instructions, data))
            return "notes" if instructions == app.notes_prompt(1) else "Outcome."
        self.assertEqual(app.summarize(text, "test", "gpt-6.1-sol", "medium", call=fake), "Outcome.")
        note_inputs = [data for prompt, data in calls if prompt == app.notes_prompt(1)]
        self.assertIn("BEGIN", note_inputs[0])
        self.assertIn("END_OF_RECORDING", note_inputs[-1])
        self.assertGreater(len(note_inputs), 1)
        self.assertEqual(calls[-1][0], app.summary_prompt(1))

    def test_resume_api_failure_uses_existing_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "meeting.mkv"; source.write_bytes(b"input")
            args = app.build_parser().parse_args(["-f", str(source), "--cache-dir", str(root / "cache"),
                                                 "--output-dir", str(root / "data"),
                                                 "--transcription-model", "mlx", "--report-tabs", "1"])
            log, summary = app.output_paths(source, args.output_dir)
            log.parent.mkdir()
            log.write_text("Reviewed transcript", encoding="utf-8")
            settings = app.recognition_settings(source, args)
            cache_id = hashlib.sha256(str(source).encode()).hexdigest()[:16]
            app.save_json(app.output_state_path(args.cache_dir / cache_id, log),
                          {"settings": settings, "selection": {"transcription_model": "mlx", "fusion": {
                              "model": app.DEFAULT_MODEL, "effort": app.DEFAULT_EFFORT, "version": 2,
                              "prompt": hashlib.sha256((app.FUSION_PROMPT + app.SINGLE_SOURCE_PROMPT).encode()).hexdigest()}},
                           "pipeline_complete": True})
            with patch.object(app, "summarize", side_effect=app.AppError("network")), patch.object(app, "extract_audio") as extract:
                with self.assertRaises(app.AppError):
                    app.process_file(source, args, "test-key")
                extract.assert_not_called()
            self.assertTrue(log.is_file()); self.assertFalse(summary.exists())
            with patch.object(app, "summarize", return_value="Completed summary") as summarize:
                app.process_file(source, args, "test-key")
                app.process_file(source, args, "test-key")
                summarize.assert_called_once()
            self.assertIn("Completed summary", summary.read_text())

    def test_checked_archive_download_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data = b"small fake model"
            archive_path = root / "fixture.tar.bz2"
            with tarfile.open(archive_path, "w:bz2") as archive:
                member = tarfile.TarInfo("directory/model.onnx"); member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
            item = {"path": "diarization/segmentation.onnx", "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(), "url": archive_path.as_uri(),
                    "archive_member": "directory/model.onnx", "download_size": archive_path.stat().st_size,
                    "download_sha256": app.digest_file(archive_path)}
            resources = root / "resources"
            app.save_json(resources / "models-manifest.json", {"files": [item]})
            with patch.object(app, "RESOURCE_DIR", resources):
                app.ensure_models(root / "models")
                self.assertEqual((root / "models" / item["path"]).read_bytes(), data)
                app.ensure_models(root / "models", offline=True, verify=True)
                (root / "models" / item["path"]).write_bytes(b"corrupt")
                with self.assertRaises(app.AppError):
                    app.ensure_models(root / "models", offline=True, verify=True)


if __name__ == "__main__":
    unittest.main()
