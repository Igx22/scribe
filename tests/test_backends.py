"""Backend selection, cloud/fusion contracts, fallback, and resumable billing tests."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

import scribe as app


class BackendTests(unittest.TestCase):
    def setUp(self):
        metadata = patch.object(app, "extract_report_metadata", return_value={"topic": "Test conversation.", "roles": {}})
        metadata.start()
        self.addCleanup(metadata.stop)

    def make_pipeline(self, root):
        source = root / "meeting.mkv"
        source.write_bytes(b"input")
        args = app.build_parser().parse_args([
            "-f", str(source), "--cache-dir", str(root / "cache"),
            "--output-dir", str(root / "data"), "--report-tabs", "1", "--transcription-model", app.COMBINED_MODE])
        local = {"duration": 2, "words": [], "voices": [], "turns": [
            {"start": 0, "end": 2, "speaker": 1, "uncertain": False, "text": "Local source text."}]}
        return source, args, local

    def test_default_whisperx_and_explicit_mlx(self):
        self.assertEqual(app.build_parser().parse_args([]).transcription_model, "whisperx")
        self.assertEqual(app.build_parser().parse_args(["--transcription-model", "mlx"]).transcription_model,
                         "mlx")

    def test_gpt_audio_failure_still_reconciles_local_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, local = self.make_pipeline(Path(tmp))
            with patch.object(app, "extract_audio"), patch.object(app, "local_recognition", return_value=local), \
                    patch.object(app, "transcribe_gpt", side_effect=app.AppError("credits exhausted")), \
                    patch.object(app, "fuse_transcripts", side_effect=lambda chunks, turns, *a, **k: (turns, [])) as fuse, \
                    patch.object(app, "summarize", return_value="Local-only summary") as summarize:
                app.process_file(source, args, "unit-test-key")
                fuse.assert_called_once()
                self.assertTrue(fuse.call_args.kwargs["single_source"])
                self.assertIn("Local source text.", summarize.call_args.args[0])
                self.assertNotIn("GPT-Transcribe text +", summarize.call_args.args[0])
            log, summary = app.output_paths(source, args.output_dir)
            self.assertTrue(log.exists()); self.assertTrue(summary.exists())

    def test_successful_pipeline_summarizes_fused_log_and_reuses_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, local = self.make_pipeline(Path(tmp))
            chunks = [{"index": 0, "start": 0, "end": 2, "text": "Better source."}]
            fused = [{**local["turns"][0], "text": "Corrected final text."}]
            with patch.object(app, "extract_audio"), patch.object(app, "local_recognition", return_value=local), \
                    patch.object(app, "transcribe_gpt", return_value=chunks) as gpt, \
                    patch.object(app, "fuse_transcripts", return_value=(fused, [])) as fuse, \
                    patch.object(app, "summarize", return_value="Final summary") as summarize:
                app.process_file(source, args, "unit-test-key")
                self.assertIn("Corrected final text.", summarize.call_args.args[0])
                self.assertNotIn("Local source text.", summarize.call_args.args[0])
                app.process_file(source, args, "unit-test-key")
                summarize.assert_called_once(); fuse.assert_called_once(); gpt.assert_called_once()

    def test_text_api_failure_still_saves_local_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, local = self.make_pipeline(Path(tmp))
            with patch.object(app, "extract_audio"), patch.object(app, "local_recognition", return_value=local), \
                    patch.object(app, "transcribe_gpt", side_effect=app.AppError("network")), \
                    patch.object(app, "fuse_transcripts", side_effect=app.AppError("quota")), \
                    patch.object(app, "summarize", side_effect=app.AppError("quota")):
                with self.assertRaises(app.AppError):
                    app.process_file(source, args, "unit-test-key")
            log, summary = app.output_paths(source, args.output_dir)
            self.assertIn("Local source text.", log.read_text())
            self.assertFalse(summary.exists())

    def test_backend_switch_does_not_leave_a_stale_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, local = self.make_pipeline(Path(tmp))
            chunks = [{"index": 0, "start": 0, "end": 2, "text": "Better source."}]
            fused = [{**local["turns"][0], "text": "Fused text."}]
            with patch.object(app, "extract_audio"), patch.object(app, "local_recognition", return_value=local), \
                    patch.object(app, "transcribe_gpt", return_value=chunks), \
                    patch.object(app, "fuse_transcripts", return_value=(fused, [])), \
                    patch.object(app, "summarize", return_value="Old fused summary"):
                app.process_file(source, args, "key")
                args.transcription_model, args.transcribe_only = "mlx", True
                args.force = True
                app.process_file(source, args, "")
            _, summary = app.output_paths(source, args.output_dir)
            self.assertFalse(summary.exists())
            self.assertTrue(any(args.cache_dir.glob("*/outputs/*/previous-*.summary.html")))

    def test_different_output_directory_has_separate_ownership_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, args, local = self.make_pipeline(root)
            args.transcription_model, args.transcribe_only = "mlx", True
            with patch.object(app, "extract_audio"), patch.object(app, "local_recognition", return_value=local):
                app.process_file(source, args, "")
                args.output_dir = root / "another-output"
                log, _ = app.output_paths(source, args.output_dir)
                app.atomic_write(log, "Do not replace this unrelated log.")
                with self.assertRaisesRegex(app.AppError, "ownership"):
                    app.process_file(source, args, "")
                self.assertIn("unrelated", log.read_text())

    def test_fusion_failure_uses_local_and_keeps_gpt_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, local = self.make_pipeline(Path(tmp))
            chunks = [{"index": 0, "start": 0, "end": 2, "text": "Better source."}]
            with patch.object(app, "extract_audio"), patch.object(app, "local_recognition", return_value=local), \
                    patch.object(app, "transcribe_gpt", return_value=chunks), \
                    patch.object(app, "fuse_transcripts", side_effect=app.AppError("invalid anchors")), \
                    patch.object(app, "summarize", return_value="Summary") as summarize:
                app.process_file(source, args, "unit-test-key")
                self.assertIn("Local source text.", summarize.call_args.args[0])
            self.assertTrue(any(args.cache_dir.glob("*/sources/gpt-transcribe.txt")))

    def test_local_recognizers_reconcile_text_without_uploading_audio(self):
        for model in ["whisperx", "mlx"]:
            with self.subTest(model=model), tempfile.TemporaryDirectory() as tmp:
                source, args, local = self.make_pipeline(Path(tmp))
                args.transcription_model, args.transcribe_only = model, True
                with patch.object(app, "extract_audio"), patch.object(app, "local_recognition", return_value=local), \
                        patch.object(app, "transcribe_gpt") as gpt, patch.object(app, "fuse_transcripts", side_effect=lambda chunks, turns, *a, **k: (turns, [])) as fuse, \
                        patch.object(app, "summarize") as summarize:
                    app.process_file(source, args, "")
                    gpt.assert_not_called(); fuse.assert_called_once(); summarize.assert_not_called()
                    self.assertTrue(fuse.call_args.kwargs["single_source"])

    def test_fusion_preserves_anchors_and_caches(self):
        turns = [{"start": 1, "end": 2, "speaker": 2, "uncertain": False, "text": "misheard"}]
        chunks = [{"index": 0, "start": 0, "end": 3, "text": "Correct term."}]
        calls = []
        def fake(*args, **kwargs):
            calls.append(kwargs)
            return json.dumps({"turns": [{"id": 0, "text": "Correct term."}], "unassigned_text": "",
                               "speaker_names": []})
        with tempfile.TemporaryDirectory() as tmp:
            for _ in range(2):
                fused, extra = app.fuse_transcripts(chunks, turns, Path(tmp), "k", "m", "medium", call=fake)
                self.assertEqual(fused[0]["speaker"], 2)
                self.assertEqual((fused[0]["start"], fused[0]["end"]), (1, 2))
                self.assertEqual(fused[0]["text"], "Correct term.")
                self.assertEqual(extra, [])
            self.assertEqual(len(calls), 1)
            self.assertIn("schema", calls[0])

    def test_fusion_rejects_missing_ids_or_removed_uncertainty(self):
        turns = [{"start": 0, "end": 2, "speaker": 1, "uncertain": True,
                  "text": "[speaker uncertain: words]"}]
        chunks = [{"index": 0, "start": 0, "end": 3, "text": "Words"}]
        for result in [{"turns": [], "unassigned_text": "", "speaker_names": []},
                       {"turns": [{"id": 0, "text": "Words"}], "unassigned_text": "", "speaker_names": []}]:
            with self.subTest(result=result), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(app.AppError):
                    app.fuse_transcripts(chunks, turns, Path(tmp), "k", "m", "medium",
                        call=lambda *a, **k: json.dumps(result))

    def test_gpt_resumes_without_rebilling_completed_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); wav_path = root / "audio.wav"
            with wave.open(str(wav_path), "wb") as writer:
                writer.setnchannels(1); writer.setsampwidth(2); writer.setframerate(16000)
                writer.writeframes(b"\0\0" * 16000 * 5)
            calls = []
            def fail_third(part, *args):
                calls.append(1)
                if len(calls) == 3:
                    raise app.AppError("network")
                return {"text": "chunk"}
            with patch.object(app, "AUDIO_CHUNK_SECONDS", 2):
                with self.assertRaises(app.AppError):
                    app.transcribe_gpt(wav_path, root / "cache", {}, "k", "auto", "", request_fn=fail_third)
                resumed = []
                chunks = app.transcribe_gpt(wav_path, root / "cache", {}, "k", "auto", "",
                    request_fn=lambda *a: resumed.append(1) or {"text": "last"})
                self.assertEqual(len(resumed), 1)
                self.assertEqual([(c["start"], c["end"]) for c in chunks], [(0, 2), (2, 4), (4, 5)])

    def test_gpt_multipart_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            part = Path(tmp) / "part.wav"; part.write_bytes(b"RIFF fake WAV")
            seen = []
            def fake(request, **kwargs):
                seen.append(request)
                return io.BytesIO(json.dumps({"text": "Transcript", "languages": [{"code": "ru"}]}).encode())
            with patch.object(app.urllib.request, "urlopen", fake):
                self.assertEqual(app.gpt_audio_request(part, "test-key", "auto", "dstack, control plane")["text"], "Transcript")
            self.assertEqual(seen[0].full_url, app.AUDIO_API_URL)
            body = seen[0].data.decode()
            self.assertIn('name="languages[]"\r\n\r\nen', body)
            self.assertIn('name="languages[]"\r\n\r\nru', body)
            self.assertLess(body.index('name="languages[]"\r\n\r\nen'),
                            body.index('name="languages[]"\r\n\r\nru'))
            self.assertIn('name="keywords[]"\r\n\r\ndstack', body)
            self.assertNotIn('name="language"', body)


if __name__ == "__main__":
    unittest.main()
