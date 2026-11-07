"""Monitor timing, OBS-style finalization metadata, and pipeline boundaries."""
import contextlib
import io
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import scribe as app


def element(element_id, payload):
    width = next(width for width in range(1, 9) if len(payload) < (1 << (7 * width)) - 1)
    size = ((1 << (7 * width)) | len(payload)).to_bytes(width, "big")
    return element_id.to_bytes((element_id.bit_length() + 7) // 8, "big") + size + payload


def mkv_fixture(*, unknown=False, duration=1.0, audio=True, cluster=True, padding=0):
    header = element(0x1A45DFA3, element(0x4282, b"matroska"))
    info = element(0x1549A966, element(0x4489, struct.pack(">d", duration)))
    tracks = element(0x1654AE6B, element(0xAE, element(0x83, b"\x02" if audio else b"\x01")
                                      + element(0x86, b"A_AAC" if audio else b"V_TEST")))
    # These fixtures test container metadata, not decodable media content.
    payload = info + tracks + (element(0x1F43B675, element(0xE7, b"\x00")) if cluster else b"")
    if padding:
        payload += element(0xEC, b"\x00" * padding)
    return header + (b"\x18\x53\x80\x67\xff" + payload if unknown else element(0x18538067, payload))


class MonitorTests(unittest.TestCase):
    def drive(self, args, events, *, steps=12):
        clock = {"now": 0, "step": 0}
        def sleep(seconds):
            clock["now"] += seconds
            clock["step"] += 1
            if clock["step"] in events:
                events[clock["step"]]()
            if clock["step"] >= steps:
                raise KeyboardInterrupt
        output = io.StringIO()
        with patch.object(app.time, "monotonic", side_effect=lambda: clock["now"]), \
                patch.object(app.time, "sleep", side_effect=sleep), contextlib.redirect_stdout(output), \
                self.assertRaises(KeyboardInterrupt):
            app.main(args)
        return output.getvalue()

    def options(self, root, *extra):
        return ["--monitor-dir", str(root), "--output-dir", str(root),
                "--cache-dir", str(root / "cache"), *extra]

    def test_readiness_requires_observed_stability_and_reports_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "meeting.mkv"
            source.write_bytes(mkv_fixture())
            snapshot = app.monitor_snapshot(source)
            with patch.object(app, "inspect_obs_mkv", wraps=app.inspect_obs_mkv) as inspect:
                ready, message = app.obs_mkv_readiness(source, 29, snapshot)
                self.assertFalse(ready); inspect.assert_not_called()
                ready, message = app.obs_mkv_readiness(source, 30, snapshot)
            self.assertTrue(ready)
            self.assertIn("matches file size", message)
            self.assertIn("A_AAC", message)

    def test_readiness_rejects_unfinished_malformed_and_audio_less_files(self):
        cases = [b"", b"not an MKV", mkv_fixture(unknown=True), mkv_fixture()[:-1],
                 mkv_fixture() + b"extra", mkv_fixture(duration=0), mkv_fixture(duration=float("nan")),
                 mkv_fixture(audio=False), mkv_fixture(cluster=False),
                 mkv_fixture().replace(b"\x44\x89\x88", b"\x44\x89\x87", 1),
                 mkv_fixture().replace(b"\x1f\x43\xb6\x75\x83", b"\x1f\x43\xb6\x75\xff", 1)]
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "meeting.mkv"
            for content in cases:
                with self.subTest(content=content):
                    source.write_bytes(content)
                    ready, message = app.obs_mkv_readiness(source, 60, app.monitor_snapshot(source))
                    self.assertFalse(ready, message)
                    self.assertIn("Not ready", message)

    def test_readiness_rechecks_file_identity_after_inspection(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "meeting.mkv"
            source.write_bytes(mkv_fixture())
            snapshot = app.monitor_snapshot(source)
            with patch.object(app, "monitor_snapshot", side_effect=[snapshot, (*snapshot[:2], 999, 0, 0)]):
                ready, message = app.obs_mkv_readiness(source, 30, snapshot)
            self.assertFalse(ready)
            self.assertIn("changed during", message)

    def test_empty_folder_and_stationary_files_do_not_trigger_processing(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "load_env"), \
                patch.object(app, "process_files") as process, patch.object(app, "ensure_models") as models, \
                patch.object(app.urllib.request, "urlopen", side_effect=AssertionError("Network forbidden")):
            root = Path(tmp)
            existing = root / "existing.mkv"
            existing.write_bytes(mkv_fixture())
            def metadata_only():
                stat = existing.stat()
                os.utime(existing, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000000))
            text = self.drive(self.options(root), {
                1: metadata_only, 2: lambda: (root / "arrived-complete.mkv").write_bytes(mkv_fixture())})
            self.assertIn("Stationary files are ignored", text)
            process.assert_not_called(); models.assert_not_called()
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "load_env"), \
                patch.object(app, "process_files") as process:
            self.drive(self.options(Path(tmp)), {}, steps=3)
            process.assert_not_called()

    def test_existing_growing_recording_is_selected_among_100_stationary_files(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "load_env"), \
                patch.object(app, "process_files", return_value=0) as process, \
                patch.object(app, "inspect_obs_mkv", wraps=app.inspect_obs_mkv) as inspect:
            root = Path(tmp)
            for index in range(100):
                (root / f"old-{index}.mkv").write_bytes(mkv_fixture())
            source = root / "active.mkv"
            source.write_bytes(mkv_fixture(unknown=True)[:20])
            text = self.drive(self.options(root), {
                1: lambda: source.write_bytes(mkv_fixture(unknown=True)),
                8: lambda: source.write_bytes(mkv_fixture())}, steps=17)
            process.assert_called_once()
            self.assertEqual(process.call_args.args[0], [source.resolve()])
            self.assertEqual({call.args[0] for call in inspect.call_args_list}, {source.resolve()})
            self.assertIn("Growth detected:", text)
            self.assertIn("Segment size is unknown", text)

    def test_two_existing_growing_recordings_are_both_processed(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "load_env"), \
                patch.object(app, "process_files", return_value=0) as process:
            root = Path(tmp)
            sources = [root / "first.mkv", root / "second.mkv"]
            for source in sources:
                source.write_bytes(mkv_fixture()[:20])
            def grow():
                for source in sources:
                    source.write_bytes(mkv_fixture())
            self.drive(self.options(root), {1: grow})
            self.assertEqual([call.args[0] for call in process.call_args_list],
                             [[source.resolve()] for source in sources])

    def test_new_uppercase_mkv_waits_for_finalization_and_stability_then_runs_once(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "load_env"), \
                patch.object(app, "process_files", return_value=0) as process:
            root = Path(tmp)
            source = root / "new recording.MKV"
            def create():
                source.write_bytes(mkv_fixture(unknown=True)[:20])
                (root / "ignore.mp4").write_bytes(mkv_fixture())
                (root / "nested").mkdir(); (root / "nested/ignore.mkv").write_bytes(mkv_fixture())
            text = self.drive(self.options(root), {1: create,
                2: lambda: source.write_bytes(mkv_fixture(unknown=True)),
                9: lambda: source.write_bytes(mkv_fixture())}, steps=18)
            process.assert_called_once()
            self.assertEqual(process.call_args.args[0], [source.resolve()])
            self.assertIn("Segment size is unknown", text)
            self.assertIn("Size:", text); self.assertIn("Criteria:", text)
            self.assertIn("Starting normal Scribe processing", text)

    def test_truncation_or_replacement_requires_fresh_observed_growth(self):
        for replace in (False, True):
            with self.subTest(replace=replace), tempfile.TemporaryDirectory() as tmp, \
                    patch.object(app, "load_env"), patch.object(app, "process_files") as process:
                root = Path(tmp)
                source = root / "recording.mkv"
                source.write_bytes(mkv_fixture()[:20])
                def reset():
                    if replace:
                        replacement = root / "replacement.tmp"
                        replacement.write_bytes(mkv_fixture(padding=200))
                        replacement.replace(source)
                    else:
                        source.write_bytes(mkv_fixture())
                self.drive(self.options(root), {
                    1: lambda: source.write_bytes(mkv_fixture(padding=100)), 2: reset})
                process.assert_not_called()

    def test_mtime_only_change_resets_the_stability_window(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "load_env"):
            root = Path(tmp)
            source = root / "new.mkv"
            processed_at = []
            ticks = {"value": 0}
            def touch():
                stat = source.stat()
                os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000000))
            def mark():
                ticks["value"] += 1
            events = {step: mark for step in range(1, 18)}
            events[1] = lambda: (mark(), source.write_bytes(mkv_fixture()))
            events[2] = lambda: (mark(), source.write_bytes(mkv_fixture(padding=10)))
            events[6] = lambda: (mark(), touch())
            with patch.object(app, "process_files", side_effect=lambda *args: processed_at.append(ticks["value"]) or 0):
                self.drive(self.options(root), events, steps=17)
            self.assertEqual(processed_at, [12])

    def test_failed_file_is_not_retried_and_next_new_file_is_processed(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "load_env"), \
                patch.dict(os.environ, {"OPENAI_API_KEY": "secret-test-key"}), \
                patch.object(app, "process_files", side_effect=[app.AppError("bad secret-test-key"), 0]) as process:
            root = Path(tmp)
            text = self.drive(self.options(root), {
                1: lambda: (root / "first.mkv").write_bytes(mkv_fixture()),
                2: lambda: (root / "first.mkv").write_bytes(mkv_fixture(padding=10)),
                9: lambda: (root / "second.mkv").write_bytes(mkv_fixture()),
                10: lambda: (root / "second.mkv").write_bytes(mkv_fixture(padding=10))}, steps=19)
            self.assertEqual(process.call_count, 2)
            self.assertIn("ordinary -f run", text)
            self.assertNotIn("secret-test-key", text)

    def test_completed_pair_skips_before_inspection_or_model_preparation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "load_env"), \
                patch.object(app, "inspect_obs_mkv") as inspect, patch.object(app, "ensure_models") as models:
            root = Path(tmp)
            source = root / "new.mkv"
            log, report = app.output_paths(source, root)
            log.write_text("Keep log"); report.write_text("Keep report")
            before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in (log, report)]
            text = self.drive(self.options(root), {1: lambda: source.write_bytes(mkv_fixture()),
                2: lambda: source.write_bytes(mkv_fixture(padding=10))})
            self.assertIn("Skipping new.mkv", text)
            inspect.assert_not_called(); models.assert_not_called()
            self.assertEqual(before, [(path.read_bytes(), path.stat().st_mtime_ns) for path in (log, report)])

    def test_new_files_with_colliding_output_names_are_not_processed(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "load_env"), \
                patch.object(app, "process_files") as process:
            root = Path(tmp)
            watched = root / "watched"
            watched.mkdir()
            targets = []
            for name in ("first", "second"):
                folder = root / name
                folder.mkdir()
                target = folder / "meeting.mkv"
                target.write_bytes(mkv_fixture())
                targets.append(target)
            def create():
                for index, target in enumerate(targets):
                    (watched / f"link-{index}.mkv").symlink_to(target)
            def grow():
                for target in targets:
                    target.write_bytes(mkv_fixture(padding=10))
            text = self.drive(self.options(watched), {1: create, 2: grow})
            self.assertIn("colliding output names", text)
            process.assert_not_called()

    def test_new_file_uses_normal_pipeline_and_preserves_recording(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "load_env"), \
                patch.dict(os.environ, {"OPENAI_API_KEY": "unit-test-key"}), \
                patch.object(app, "extract_audio"), \
                patch.object(app, "transcribe_gpt", return_value=[{"index": 0, "start": 0, "end": 1, "text": "Words."}]) as gpt, \
                patch.object(app, "summarize", return_value="Summary."), \
                patch.object(app, "extract_report_metadata", return_value={"topic": "Topic.", "roles": {}}):
            root = Path(tmp)
            source = root / "new.mkv"
            original = mkv_fixture()
            self.drive(self.options(root, "--transcription-model", "gpt-transcribe-online", "--report-tabs", "1"),
                       {1: lambda: source.write_bytes(original[:20]), 2: lambda: source.write_bytes(original)})
            gpt.assert_called_once()
            log, report = app.output_paths(source, root)
            self.assertIn("Words.", log.read_text())
            self.assertIn("Summary.", report.read_text())
            self.assertEqual(source.read_bytes(), original)

    def test_change_during_extraction_stops_before_paid_requests(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "load_env"), \
                patch.dict(os.environ, {"OPENAI_API_KEY": "unit-test-key"}), \
                patch.object(app, "transcribe_gpt") as gpt:
            root = Path(tmp)
            source = root / "new.mkv"
            def change(*args):
                source.write_bytes(mkv_fixture() + b"changed")
            with patch.object(app, "extract_audio", side_effect=change):
                text = self.drive(self.options(root, "--transcription-model", "gpt-transcribe-online"),
                                   {1: lambda: source.write_bytes(mkv_fixture()[:20]),
                                    2: lambda: source.write_bytes(mkv_fixture())})
            self.assertIn("Source changed during audio extraction", text)
            gpt.assert_not_called()

    def test_offline_monitor_keeps_cloud_stages_disabled(self):
        local = {"duration": 1, "voices": [{"start": 0, "end": 1, "speaker": 1}],
                 "turns": [{"start": 0, "end": 1, "speaker": 1, "text": "Local words."}]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "load_env"), \
                patch.object(app, "ensure_models") as models, patch.object(app, "extract_audio"), \
                patch.object(app, "local_recognition", return_value=local), \
                patch.object(app, "transcribe_gpt") as gpt, patch.object(app, "fuse_transcripts") as fuse, \
                patch.object(app, "api_request", side_effect=AssertionError("API forbidden")), \
                patch.object(app.urllib.request, "urlopen", side_effect=AssertionError("Network forbidden")):
            root = Path(tmp)
            source = root / "new.mkv"
            self.drive(self.options(root, "--offline"), {1: lambda: source.write_bytes(mkv_fixture()[:20]),
                                                       2: lambda: source.write_bytes(mkv_fixture())})
            gpt.assert_not_called(); fuse.assert_not_called()
            self.assertTrue(models.call_args.args[1])
            log, report = app.output_paths(source, root)
            self.assertIn("Local words.", log.read_text())
            self.assertFalse(report.exists())

    def test_monitor_rejects_conflicting_options_and_missing_folder(self):
        for options in (["-f", "file.mkv"], ["--input-dir", "folder"], ["--force"],
                        ["--summary-only"], ["--setup"], ["--show-prompt"]):
            with self.subTest(options=options), patch.object(app, "load_env"), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises((SystemExit, app.AppError)):
                app.main(["--monitor-dir", "folder", *options])
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "load_env"), \
                self.assertRaisesRegex(app.AppError, "not a directory"):
            app.main(["--monitor-dir", str(Path(tmp) / "missing")])


if __name__ == "__main__":
    unittest.main()
