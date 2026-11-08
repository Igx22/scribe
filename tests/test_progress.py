"""Honest local estimates and progress, using fake clocks and native processes."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import wave

import scribe as app


class FakeClock:
    now = 0
    def __call__(self):
        return self.now


class Terminal(io.StringIO):
    def isatty(self):
        return True


class TimingTests(unittest.TestCase):
    def test_rates_fixed_overhead_compatibility_and_bounded_private_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = app.TimingHistory(Path(tmp) / 'timings.json')
            key = app.timing_key('stage', {'model': 'fixture', 'threads': 4})
            self.assertIsNone(history.estimate(key, 100))
            for duration in [100, 200, 300]:
                history.record(key, duration, 20 + duration * 2)
            estimate = history.estimate(key, 200)
            self.assertAlmostEqual(estimate['seconds'], 420)
            self.assertAlmostEqual(estimate['loading_overhead'], 20)
            self.assertLess(estimate['low'], 420); self.assertGreater(estimate['high'], 420)
            self.assertIsNone(history.estimate(app.timing_key('stage', {'model': 'other'}), 200))
            self.assertIsNone(history.estimate(key, 10000))
            for _ in range(30): history.record(key, 200, 420)
            self.assertEqual(len(history.samples()), 12)
            self.assertNotIn(str(tmp), history.path.read_text())
            self.assertNotIn(app.platform.node(), history.path.read_text())
            with patch.object(app.os, 'cpu_count', return_value=999):
                self.assertIsNone(history.estimate(app.timing_key('stage', {'model': 'fixture', 'threads': 4}), 200))

    def test_corrupt_unwritable_and_contended_history_is_optional(self):
        import fcntl
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'timings.json'; history = app.TimingHistory(path)
            for text in ('{bad', '[]', '{"version":1,"samples":null}',
                         '{"version":1,"samples":[{"key":{},"audio":1,"elapsed":1e308}]}'):
                path.write_text(text)
                self.assertIsNone(history.estimate({}, 100))
            with patch.object(app, 'save_json', side_effect=OSError('read only')):
                history.record({}, 100, 10)
            with history.path.with_suffix('.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                with patch.object(app.time, 'sleep'):
                    history.record({}, 100, 10)
            self.assertEqual(history.samples(), [])

    def test_concurrent_updates_merge_without_overwriting_other_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = app.TimingHistory(Path(tmp) / 'timings.json')
            workers = [threading.Thread(target=history.record, args=({'stage': str(i)}, 100, 10)) for i in range(4)]
            for worker in workers: worker.start()
            for worker in workers: worker.join()
            self.assertEqual(len(history.samples()), 4)


class ProgressTests(unittest.TestCase):
    def test_callback_eta_throttle_finalization_and_success_learning(self):
        clock, output = FakeClock(), io.StringIO()
        history = Mock(); history.estimate.return_value = None
        with patch.object(app.time, 'monotonic', clock), contextlib.redirect_stdout(output):
            with app.StageProgress('WhisperX', 100, {}, history) as progress:
                progress.phase('Transcribing')
                clock.now = 10; progress.callback(10)
                clock.now = 20; progress.callback(20)
                self.assertIn('observed progress', output.getvalue())
                progress.callback(100)
                self.assertNotIn('100% of stage', output.getvalue())
                progress.phase('Finalizing')
                self.assertNotIn('100% of stage', output.getvalue())
                progress.complete()
            self.assertIn('Done', output.getvalue())
            self.assertIn('100% of stage', output.getvalue())
        history.record.assert_called_once()
        self.assertNotIn('\r', output.getvalue())

    def test_no_percentage_for_activity_only_and_overrun_is_explicit(self):
        clock, output = FakeClock(), io.StringIO()
        history = Mock(); history.estimate.return_value = dict(seconds=10)
        with patch.object(app.time, 'monotonic', clock), contextlib.redirect_stdout(output), \
                patch.dict(os.environ, {'HF_TOKEN': 'private-token'}):
            with app.StageProgress('Nemotron', 100, {}, history) as progress:
                clock.now = 16
                progress.runtime_message('Loading private-token model')
                progress.tick(force=True)
                self.assertIn('estimate exceeded; remaining unknown', output.getvalue())
                self.assertNotIn('private-token', output.getvalue())
                progress.complete()
        self.assertNotIn('%', output.getvalue())
        self.assertNotIn('remaining ~-', output.getvalue())

    def test_failed_or_interrupted_work_never_learns_or_claims_done(self):
        for error in [RuntimeError('failure'), KeyboardInterrupt()]:
            history = Mock(); history.estimate.return_value = None
            output = io.StringIO()
            with contextlib.redirect_stdout(output), self.assertRaises(type(error)):
                with app.StageProgress('Stage', 100, {}, history) as progress:
                    progress.callback(100)
                    raise error
            history.record.assert_not_called()
            self.assertNotIn('Done', output.getvalue())
            self.assertNotIn('100% of stage', output.getvalue())

    def test_percentage_boundaries_and_regression_do_not_imply_completion(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            progress = app.StageProgress('Stage', 100, {})
            progress.callback(-10)
            self.assertEqual(progress.percent, 0)
            progress.callback(150)
            self.assertEqual(progress.percent, 100)
            progress.callback(50); progress.callback(float('nan'))
            self.assertEqual(progress.percent, 100)
            progress.tick(force=True)
        self.assertIn('awaiting finalization', output.getvalue())
        self.assertNotIn('Done', output.getvalue())
        self.assertNotIn('100% of stage', output.getvalue())

    def test_tty_refresh_and_heartbeat_timer_do_not_require_inference_progress(self):
        clock, output = FakeClock(), Terminal()
        with patch.object(app.time, 'monotonic', clock), contextlib.redirect_stdout(output):
            progress = app.StageProgress('Stage', 100, {})
            progress.tick(force=True)
            initial = output.getvalue()
            clock.now = .5; progress.tick()
            self.assertEqual(initial, output.getvalue())
            clock.now = 1; progress.tick()
            self.assertGreater(len(output.getvalue()), len(initial))
            self.assertIn('\r', output.getvalue())
            app.say('Another message')
            self.assertTrue(output.getvalue().endswith('Another message\n'))
        progress.stop = Mock(); progress.stop.wait.side_effect = [False, False, True]
        with patch.object(progress, 'tick') as tick:
            progress.heartbeat()
        self.assertEqual(tick.call_count, 2)

    def test_real_whisperx_callback_arguments_and_final_validation(self):
        from tests.test_whisperx import WhisperXTests
        modules, loader, _, alignment = WhisperXTests().fake_whisperx()
        raw = loader.return_value.transcribe.return_value
        aligned = alignment.return_value
        def transcribe(*a, **kw):
            kw['progress_callback'](50); kw['progress_callback'](100)
            return raw
        def align(*a, **kw):
            kw['progress_callback'](50); kw['progress_callback'](100)
            return aligned
        loader.return_value.transcribe.side_effect = transcribe
        alignment.side_effect = align
        history = Mock(); history.estimate.return_value = None
        token = app.CURRENT_TIMING.set(history)
        try:
            with patch.dict('sys.modules', modules), contextlib.redirect_stdout(io.StringIO()):
                app.recognize([.1] * 32000, Path('/models'), 'en', '')
            self.assertEqual(history.record.call_count, 3, 'ASR, alignment and full recognizer')
            history.record.reset_mock()
            aligned['segments'][0]['words'][0]['start'] = -1
            with patch.dict('sys.modules', modules), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(app.AppError):
                app.recognize([.1] * 32000, Path('/models'), 'en', '')
            self.assertEqual(history.record.call_count, 1, 'Only successful ASR, not alignment/full recognizer')
        finally:
            app.CURRENT_TIMING.reset(token)


class ForecastTests(unittest.TestCase):
    def test_pre_run_history_and_cache_reuse_match_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'meeting.mkv'; source.write_bytes(b'fixture')
            wav = root / 'audio.wav'
            with wave.open(str(wav), 'wb') as writer:
                writer.setnchannels(1); writer.setsampwidth(2); writer.setframerate(16000)
                writer.writeframes(b'\0\0' * 16000 * 2)
            args = app.build_parser().parse_args([]); args.cache_dir = root / 'cache'
            settings = app.recognition_settings(source, args)
            history = app.TimingHistory(root / 'timings.json')
            token = app.CURRENT_TIMING.set(history)
            try:
                output = io.StringIO()
                with contextlib.redirect_stdout(output): app.forecast_local(wav, root, settings, args)
                self.assertIn('No comparable timing history', output.getvalue())
                history.record(app.timing_key('nemotron', app.diarization_spec('nemotron')['identity']), 2, 10)
                history.record(app.recognition_timing_key('whisperx.total', 'whisperx', 'auto', ''), 2, 30)
                output = io.StringIO()
                with contextlib.redirect_stdout(output): app.forecast_local(wav, root, settings, args)
                self.assertIn('Estimated local processing time:', output.getvalue())
                self.assertIn('API/reconciliation/report time', output.getvalue())
                voice_settings = {k: settings[k] for k in ('source', 'models', 'diarization')}
                word_settings = {k: v for k, v in settings.items() if k != 'diarization'}
                app.save_json(root / 'voices-stage.json', dict(settings=voice_settings, intervals=[]))
                app.save_json(root / 'words-stage.json', dict(settings=word_settings, words=[]))
                before = history.path.read_bytes()
                output = io.StringIO()
                with contextlib.redirect_stdout(output): app.forecast_local(wav, root, settings, args)
                self.assertIn('No local model computation needed', output.getvalue())
                self.assertNotIn('Estimated local processing time:', output.getvalue())
                self.assertEqual(before, history.path.read_bytes())
                args.force = True
                output = io.StringIO()
                with contextlib.redirect_stdout(output): app.forecast_local(wav, root, settings, args)
                self.assertIn('Estimated local processing time:', output.getvalue())
                self.assertIn('Reusing local checkpoints: none', output.getvalue())
            finally:
                app.CURRENT_TIMING.reset(token)


class NativeProgressTests(unittest.TestCase):
    def process(self, data, code=0):
        reader, writer = os.pipe()
        os.write(writer, data); os.close(writer)
        process = Mock(stdout=os.fdopen(reader, 'rb', buffering=0))
        process.poll.return_value = code; process.wait.return_value = code
        return process

    def test_streams_bounded_diagnostics_and_preserves_exit_status(self):
        process = self.process(b'Loading model\nDetecting speakers\nFailure details\n', 3)
        progress = Mock()
        with patch.object(app.subprocess, 'Popen', return_value=process) as start:
            result = app.run_native(['native', 'diarize'], env={'SAFE': '1'}, progress=progress)
        self.assertEqual(result.returncode, 3)
        self.assertIn('Failure details', result.stderr)
        self.assertIn('Loading model', str(progress.runtime_message.call_args_list))
        self.assertEqual(start.call_args.kwargs['stderr'], subprocess.STDOUT)
        self.assertTrue(process.stdout.closed)
        process.terminate.assert_not_called()

    def test_interrupt_terminates_kills_if_needed_and_reaps_child(self):
        process = self.process(b'')
        process.wait.side_effect = [KeyboardInterrupt(), subprocess.TimeoutExpired('native', 5), 0]
        with patch.object(app.subprocess, 'Popen', return_value=process), self.assertRaises(KeyboardInterrupt):
            app.run_native(['native'], env={}, progress=Mock())
        process.terminate.assert_called_once(); process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count, 3)
        self.assertTrue(process.stdout.closed)

    def test_spawn_failure_closes_selector_without_masking_error(self):
        selector = Mock()
        with patch.object(app.selectors, 'DefaultSelector', return_value=selector), \
                patch.object(app.subprocess, 'Popen', side_effect=OSError('Cannot execute')), \
                self.assertRaisesRegex(OSError, 'Cannot execute'):
            app.run_native(['native'], env={}, progress=Mock())
        selector.close.assert_called_once()

    def test_long_runtime_line_is_bounded(self):
        process = self.process(b'x' * 5000)
        progress = Mock()
        with patch.object(app.subprocess, 'Popen', return_value=process):
            result = app.run_native(['native'], env={}, progress=progress)
        self.assertLessEqual(len(result.stderr), 4096)
        self.assertTrue(all(len(call.args[0]) <= 160 for call in progress.runtime_message.call_args_list))

    def test_only_validated_native_results_record_success_timing(self):
        from tests.test_diarization import NemotronTests
        history = Mock(); history.estimate.return_value = None
        token = app.CURRENT_TIMING.set(history)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                case = NemotronTests(); audio, models = case.native_fixture(Path(tmp))
                with patch.object(app, 'run_native', case.native_response({'segments': [{'start': -1}]})), \
                        contextlib.redirect_stdout(io.StringIO()), self.assertRaises(app.AppError):
                    app.diarize(audio, models)
                history.record.assert_not_called()
                with patch.object(app, 'run_native', case.native_response({'segments': []})), \
                        contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(app.diarize(audio, models), [])
                history.record.assert_called_once()
        finally:
            app.CURRENT_TIMING.reset(token)
