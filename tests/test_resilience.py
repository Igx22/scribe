"""Speech-based language selection, bounded recovery, and output error history."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
import scribe as app
from tests import seed_final


class LanguageProbeTests(unittest.TestCase):
    def test_leading_silence_overlaps_and_short_speech_preserve_original_spans(self):
        audio = np.zeros(150 * 16000, dtype=np.float32)
        audio[70 * 16000:74 * 16000] = .2
        probes = app.speech_probes(audio, [dict(start=70, end=73), dict(start=72, end=74)])
        self.assertEqual(len(probes), 1)
        self.assertEqual(probes[0][1], [[70, 74]])
        self.assertEqual(len(probes[0][0]), 4 * 16000)
        self.assertTrue(np.all(probes[0][0] == .2))
        self.assertFalse(np.any(audio[:70 * 16000]))
        self.assertEqual(app.speech_probes(audio, []), [])
        self.assertEqual(app.speech_probes(np.zeros(32000), [dict(start=0, end=2)]), [])

    def test_detection_samples_more_speech_on_weak_or_conflicting_evidence(self):
        audio = np.ones(120 * 16000, dtype=np.float32)
        probes = app.speech_probes(audio, [dict(start=0, end=120)])
        detect = Mock(side_effect=[[[("<|en|>", .36), ("<|ru|>", .3)]],
                                   [[("<|ru|>", .99), ("<|en|>", .01)]],
                                   [[("<|ru|>", .99), ("<|en|>", .01)]]])
        core = SimpleNamespace(feat_kwargs={"feature_size": 128}, encode=Mock(),
                               model=SimpleNamespace(detect_language=detect))
        mel = Mock()
        with patch.dict("sys.modules", {"whisperx.audio": SimpleNamespace(log_mel_spectrogram=mel)}):
            result = app.detect_speech_language(SimpleNamespace(model=core), probes)
        self.assertEqual(result['language'], 'ru')
        self.assertTrue(result['weak_or_mixed'])
        self.assertEqual(detect.call_count, 3)
        self.assertEqual(result['probes'][2]['spans'], [[60, 90]])
        detect.side_effect = None
        detect.return_value = [[("<|en|>", .99), ("<|ru|>", .01)]]
        detect.reset_mock()
        with patch.dict("sys.modules", {"whisperx.audio": SimpleNamespace(log_mel_spectrogram=mel)}):
            self.assertEqual(app.detect_speech_language(SimpleNamespace(model=core), probes)['language'], 'en')
        self.assertEqual(detect.call_count, 1)

    def test_corrected_language_is_explicit_without_cropping_recognition_audio(self):
        from tests.test_whisperx import WhisperXTests
        modules, loader, alignment, _ = WhisperXTests().fake_whisperx(language='ru')
        audio = np.zeros(100 * 16000, dtype=np.float32)
        audio[67 * 16000:97 * 16000] = .2
        evidence = {}
        with patch.dict('sys.modules', modules):
            app.recognize(audio, Path('/models'), 'auto', '',
                          voice_intervals=[dict(start=67, end=97)], evidence=evidence)
        call = loader.return_value.transcribe.call_args
        self.assertIs(call.args[0], audio)
        self.assertEqual(call.kwargs['language'], 'ru')
        self.assertEqual(call.kwargs['task'], 'transcribe')
        self.assertEqual(evidence['probes'][0]['spans'], [[67, 97]])
        self.assertIn('align/ru', alignment.call_args.kwargs['model_name'])


class RecoveryTests(unittest.TestCase):
    def turns(self):
        return [dict(start=i * 600, end=i * 600 + 2, speaker=1, text=f'Original {i}') for i in range(3)]

    def test_only_failed_part_retries_and_later_parts_survive_then_resume(self):
        turns = self.turns()
        chunks = app.transcript_chunks(turns)
        requests = []
        def call(*args, **kwargs):
            payload = json.loads(args[4]); requests.append(payload)
            anchors = payload['source_b_fixed_anchors']
            if anchors[0]['id'] == 1:
                return '{bad JSON'
            return json.dumps(dict(turns=[dict(id=a['id'], text='Corrected ' + str(a['id'])) for a in anchors],
                                   unassigned_text='', speaker_names=[]))
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            issues = []
            fused, _ = app.fuse_transcripts(chunks, turns, cache, 'secret-key', 'model', 'high', call=call, issues=issues)
            self.assertEqual([t['text'] for t in fused], ['Corrected 0', 'Original 1', 'Corrected 2'])
            self.assertEqual([t['start'] for t in fused], [0, 600, 1200])
            self.assertEqual(len(requests), 5)
            self.assertEqual([i['part'] for i in issues], [2])
            self.assertIn('validation_feedback', requests[2])
            rejected = list(cache.glob('reconciliation.rejected.*.json'))
            self.assertEqual(len(rejected), 3)
            self.assertIn('{bad JSON', rejected[0].read_text())
            requests.clear()
            app.fuse_transcripts(chunks, turns, cache, 'secret-key', 'model', 'high', call=call)
            self.assertEqual(len(requests), 3, 'Successful parts must use checkpoints')

    def test_marker_loss_keeps_corrected_words_without_spending_a_retry(self):
        turns = [dict(start=0, end=2, speaker=1, text='Known [speaker uncertain: wrong words]')]
        reply = Mock(return_value=json.dumps(dict(turns=[dict(id=0, text='Исправленные слова')],
                                                   unassigned_text='', speaker_names=[])))
        with tempfile.TemporaryDirectory() as tmp:
            issues = []
            fused, _ = app.fuse_transcripts(app.transcript_chunks(turns), turns, Path(tmp), '', 'm', 'medium', call=reply, issues=issues)
        self.assertEqual(reply.call_count, 1)
        self.assertEqual(fused[0]['text'], '[speaker uncertain: Исправленные слова]')
        self.assertEqual(issues, [])
        self.assertEqual(turns[0]['text'], 'Known [speaker uncertain: wrong words]')

    def test_feedback_retry_can_recover_and_transport_failure_is_not_retried(self):
        turns = self.turns()[:1]
        good = json.dumps(dict(turns=[dict(id=0, text='Fixed')], unassigned_text='', speaker_names=[]))
        with tempfile.TemporaryDirectory() as tmp:
            reply = Mock(side_effect=['{}', good])
            issues = []
            fused, _ = app.fuse_transcripts(app.transcript_chunks(turns), turns, Path(tmp), '', 'm', 'medium', call=reply, issues=issues)
            self.assertEqual(fused[0]['text'], 'Fixed'); self.assertFalse(issues)
            self.assertEqual(reply.call_count, 2)
        with tempfile.TemporaryDirectory() as tmp:
            reply = Mock(side_effect=app.AppError('Quota exhausted'))
            issues = []
            fused, _ = app.fuse_transcripts(app.transcript_chunks(turns), turns, Path(tmp), '', 'm', 'medium', call=reply, issues=issues)
            self.assertEqual(reply.call_count, 1)
            self.assertEqual(fused, turns)
            self.assertEqual(len(issues), 1)


class ErrorHistoryTests(unittest.TestCase):
    def fixture(self, root, *options):
        source = root / 'meeting.mkv'; source.write_bytes(b'fixture')
        args = app.build_parser().parse_args(['--output-dir', str(root / 'out'), '--report-tabs', '1,transcript', *options])
        args.cache_dir = root / 'cache'
        return source, args, app.output_paths(source, args.output_dir)[1].with_suffix('.err')

    def test_early_failure_then_clean_run_history_and_skip_preserve_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, err = self.fixture(Path(tmp), '--summary-only')
            log, report = app.output_paths(source, args.output_dir)
            seed_final(source, args, 'Saved log')
            app.atomic_write(report, 'Existing HTML')
            with patch.object(app, 'summarize', side_effect=app.AppError('failed private-api-key hf_secret')), \
                    patch.dict(app.os.environ, {'HF_TOKEN': 'hf_secret'}):
                with self.assertRaises(app.AppError):
                    app.process_file(source, args, 'private-api-key')
            self.assertEqual(report.read_text(), 'Existing HTML\n')
            self.assertNotIn('private-api-key', err.read_text()); self.assertNotIn('hf_secret', err.read_text())
            entry = app.read_json(err)['runs'][0]
            self.assertEqual(entry['status'], 'failed')
            self.assertEqual(entry['events'][0]['stage'], 'summary level 1')
            self.assertEqual(entry['events'][0]['model'], app.DEFAULT_MODEL)
            with patch.object(app, 'summarize', return_value='Summary'), \
                    patch.object(app, 'extract_report_metadata', return_value={'topic': 'Meeting', 'roles': {}}):
                app.process_file(source, args, 'private-api-key')
            history = app.read_json(err)['runs']
            self.assertEqual([r['status'] for r in history], ['failed', 'complete'])
            before = err.read_bytes(), err.stat().st_mtime_ns
            args.summary_only = False
            app.process_file(source, args, 'private-api-key')
            self.assertEqual(before, (err.read_bytes(), err.stat().st_mtime_ns))

    def test_clean_run_has_no_error_file_and_unknown_or_symlink_file_is_protected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, args, err = self.fixture(root)
            with patch.object(app, '_process_file'):
                app.process_file(source, args, '')
            self.assertFalse(err.exists())
            app.atomic_write(err, 'Private existing content')
            with patch.object(app, '_process_file') as work, self.assertRaisesRegex(app.AppError, 'ownership'):
                app.process_file(source, args, '')
            work.assert_not_called()
            self.assertEqual(err.read_text(), 'Private existing content\n')
            target = root / 'other'; target.write_text('Preserved')
            err.unlink(); err.symlink_to(target)
            with self.assertRaisesRegex(app.AppError, 'symlink'):
                app.process_file(source, args, '')
            self.assertEqual(target.read_text(), 'Preserved')

    def test_extraction_failure_is_recorded_before_log_or_html_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, err = self.fixture(Path(tmp))
            with patch.object(app, 'extract_audio', side_effect=app.AppError('Damaged audio')):
                with self.assertRaises(app.AppError): app.process_file(source, args, '')
            run = app.read_json(err)['runs'][0]
            self.assertEqual(run['events'][0]['stage'], 'audio extraction')
            self.assertFalse(app.output_paths(source, args.output_dir)[1].exists())

    def test_model_preparation_failure_and_recovered_validation_are_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, err = self.fixture(Path(tmp))
            with patch.object(app, 'ensure_models', side_effect=app.AppError('Missing offline asset')):
                with self.assertRaises(app.AppError):
                    app.process_file(source, args, '', prepare_models=True)
            self.assertEqual(app.read_json(err)['runs'][0]['events'][0]['stage'], 'model preparation')
            turns = RecoveryTests().turns()[:1]
            good = json.dumps(dict(turns=[dict(id=0, text='Recovered')], unassigned_text='', speaker_names=[]))
            def work(*a, **k):
                return app.fuse_transcripts(app.transcript_chunks(turns), turns, args.cache_dir,
                                            'secret-key', 'm', 'high', call=Mock(side_effect=['secret-key', good]))
            with patch.object(app, '_process_file', side_effect=work):
                app.process_file(source, args, 'secret-key')
            history = app.read_json(err)['runs']
            self.assertEqual([r['status'] for r in history], ['failed', 'complete'])
            self.assertEqual(history[1]['events'][0]['response'], '[redacted]')
            self.assertEqual(history[1]['events'][0]['model'], 'm')
            self.assertNotIn('secret-key', err.read_text())

    def test_partial_pipeline_html_and_sources_remain_truthful(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, err = self.fixture(Path(tmp), '--transcription-model', app.COMBINED_MODE)
            turns = RecoveryTests().turns()
            chunks = app.transcript_chunks(turns)
            local = dict(duration=1202, turns=turns, voices=[dict(start=0, end=1202, speaker=1)], words=[])
            def reply(*a, **k):
                anchors = json.loads(a[4])['source_b_fixed_anchors']
                return json.dumps(dict(turns=[] if anchors[0]['id'] == 1 else [dict(id=t['id'], text='Corrected') for t in anchors],
                                       unassigned_text='', speaker_names=[]))
            with patch.object(app, 'extract_audio'), patch.object(app, 'local_recognition', return_value=local), \
                    patch.object(app, 'transcribe_gpt', return_value=chunks), patch.object(app, 'api_request', side_effect=reply), \
                    patch.object(app, 'summarize', return_value='Summary'), \
                    patch.object(app, 'extract_report_metadata', return_value={'topic': 'Meeting', 'roles': {}}):
                app.process_file(source, args, 'key')
                args.summary_only = True
                app.process_file(source, args, 'key')
            log, report = app.output_paths(source, args.output_dir)
            state = app.read_json(next(args.cache_dir.glob('*/outputs/*/state.json')))
            self.assertFalse(state['pipeline_complete'])
            self.assertEqual(state['source_mode'], 'partially-reconciled')
            self.assertIn('RECONCILIATION INCOMPLETE', log.read_text())
            self.assertIn('Part 2: 10:00–20:00', log.read_text())
            self.assertIn('Original 1', log.read_text()); self.assertIn('Corrected', log.read_text())
            self.assertIn('class="reconciliation-warning"', report.read_text())
            self.assertEqual(app.final_transcript_badge(log.read_text()), 'GPT-6.1-sol')
            self.assertEqual([run['status'] for run in app.read_json(err)['runs']], ['partial', 'partial'])
            self.assertEqual(len(app.read_json(err)['runs'][0]['events']), 3)
            cache = args.cache_dir / app.digest_file(source)
            final = app.final_reference(cache, state['final'], required=True)['payload']
            self.assertTrue(app.final_sources(source, final))

    def test_all_failed_parts_keep_local_provenance_and_no_gpt_badge(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, err = self.fixture(Path(tmp), '--transcription-model', app.COMBINED_MODE)
            turns = RecoveryTests().turns()[:1]
            local = dict(duration=2, turns=turns, voices=[dict(start=0, end=2, speaker=1)], words=[])
            with patch.object(app, 'extract_audio'), patch.object(app, 'local_recognition', return_value=local), \
                    patch.object(app, 'transcribe_gpt', return_value=app.transcript_chunks(turns)), \
                    patch.object(app, 'api_request', side_effect=app.AppError('Quota exhausted')), \
                    patch.object(app, 'summarize', return_value='Summary'), \
                    patch.object(app, 'extract_report_metadata', return_value={'topic': 'Meeting', 'roles': {}}):
                app.process_file(source, args, 'key')
            log, report = app.output_paths(source, args.output_dir)
            self.assertEqual(app.final_transcript_badge(log.read_text()), 'WhisperX Turbo')
            self.assertIn('RECONCILIATION INCOMPLETE', log.read_text())
            self.assertIn('class="reconciliation-warning"', report.read_text())
            self.assertEqual(app.read_json(err)['runs'][0]['status'], 'partial')
