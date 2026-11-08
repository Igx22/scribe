"""SCR-093: content identity, internal JSON, stage isolation and safe migration."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import scribe as app
from tests import test_all_mode
from tests.test_source_reports import PanelText


class ContentCacheTests(unittest.TestCase):
    def fixture(self, root, *options):
        return test_all_mode.AllModeTests().setup_case(root, *options)

    def run_pipeline(self, source, args, **options):
        return test_all_mode.AllModeTests().run_pipeline(source, args, **options)

    def test_full_file_identity_detects_middle_changes_with_preserved_size_and_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'same.mkv'
            source.write_bytes(b'a' * (4 * 1024 * 1024))
            stamp = source.stat()
            first = app.source_signature(source)
            edge = app.legacy_source_signature(source)
            with source.open('r+b') as writer:
                writer.seek(2 * 1024 * 1024); writer.write(b'b')
            os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            self.assertEqual(edge, app.legacy_source_signature(source))
            self.assertNotEqual(first['sha256'], app.source_signature(source)['sha256'])
            self.assertEqual(app.source_signature(source)['sha256'], hashlib.sha256(source.read_bytes()).hexdigest())

    def test_hashing_detects_a_source_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'meeting.mkv'; source.write_bytes(b'first')
            digest = app.digest_file
            def changed(path):
                result = digest(path); path.write_bytes(b'other'); return result
            with patch.object(app, 'digest_file', side_effect=changed), self.assertRaisesRegex(app.AppError, 'changed while hashing'):
                app.source_signature(source)

    def test_same_bytes_rename_date_and_output_change_reuse_final_and_refresh_display(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, args, cache = self.fixture(root, '--transcribe-only')
            self.run_pipeline(source, args)
            source = source.rename(root / '2026-11-08 renamed.mkv')
            os.utime(source, None)
            args.output_dir = root / 'elsewhere'
            with patch.object(app, 'digest_file', wraps=app.digest_file) as digest:
                stages = self.run_pipeline(source, args)
            for stage in stages[:5]:
                stage.assert_not_called()
            self.assertEqual(sum(call.args[0] == source for call in digest.call_args_list), 1)
            log, _ = app.output_paths(source, args.output_dir)
            self.assertIn('Source file: ' + source.name, log.read_text())
            self.assertNotIn('Source file: meeting.mkv', log.read_text())
            manifest = app.read_json(cache / 'manifest.json')
            self.assertEqual(manifest['filenames'], ['meeting.mkv', source.name])
            self.assertEqual(cache.name, app.digest_file(source))

    def test_same_filename_different_bytes_have_different_content_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, args, cache = self.fixture(root, '--transcribe-only')
            self.run_pipeline(source, args)
            other = root / 'other' / source.name; other.parent.mkdir(); other.write_bytes(b'different')
            args.output_dir = root / 'out-other'
            self.run_pipeline(other, args)
            self.assertNotEqual(cache.name, app.digest_file(other))
            self.assertTrue((args.cache_dir / app.digest_file(other) / 'manifest.json').is_file())

    def test_processing_artifacts_are_flat_json_and_configuration_variants_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, args, cache = self.fixture(root, '--transcribe-only')
            self.run_pipeline(source, args)
            first = {p.name: p.read_bytes() for p in cache.glob('alignment.*.json')}
            args.output_dir = root / 'changed'; args.vocabulary = 'Alice, Bob'
            _, cloud, words, voice, *_ = self.run_pipeline(source, args)
            cloud.assert_called_once(); voice.assert_not_called(); self.assertEqual(words.call_count, 2)
            for name, data in first.items():
                self.assertEqual((cache / name).read_bytes(), data)
            self.assertEqual(len(list(cache.glob('alignment.whisperx-turbo.*.json'))), 2)
            for path in cache.iterdir():
                if path.is_file():
                    self.assertEqual(path.suffix, '.json')
                    self.assertIsInstance(app.read_json(path), dict)
            self.assertFalse(list(cache.glob('**/sources/*')))
            self.assertTrue(list(cache.glob('materialization.final-transcript.*.json')))
            self.assertFalse(list(cache.glob('materialization.final-transcript.*.md')))
            self.assertFalse(list(cache.glob('**/fusion/*')))
            self.assertFalse(list(cache.glob('**/report-header/*')))
            args.vocabulary = ''; args.output_dir = root / 'original-again'
            for stage in self.run_pipeline(source, args)[:5]:
                stage.assert_not_called()

    def test_summary_only_uses_internal_json_with_present_edited_deleted_or_moved_exports(self):
        for change in ('present', 'edited', 'deleted', 'moved'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source, args, cache = self.fixture(root)
                self.run_pipeline(source, args)
                log, report = app.output_paths(source, args.output_dir)
                original = log.read_text()
                if change == 'edited':
                    log.write_text('USER EDITS MUST NOT ENTER THE PIPELINE\n')
                elif change == 'deleted':
                    log.unlink()
                elif change == 'moved':
                    log.rename(root / 'kept.log.md'); args.output_dir = root / 'new-location'
                args.summary_only = True; args.summarize_model = ('different-summary-model', 'high')
                stages = self.run_pipeline(source, args)
                for stage in stages[:5]:
                    stage.assert_not_called()
                summary = stages[5]
                self.assertEqual(summary.call_count, 4)
                self.assertTrue(all(call.args[0] == original for call in summary.call_args_list))
                current_log, report = app.output_paths(source, args.output_dir)
                self.assertEqual(PanelText(report.read_text()).text['panel-transcript'], original)
                if change == 'edited':
                    self.assertIn('USER EDITS', current_log.read_text())
                else:
                    self.assertEqual(current_log.read_text(), original)

    def test_summary_model_and_force_preserve_the_selected_reconciliation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, args, cache = self.fixture(root)
            self.run_pipeline(source, args)
            original_output = args.output_dir
            identity = app.output_state_path(cache, app.output_paths(source, original_output)[0]).parent.name
            original_ref = app.read_json(cache / 'manifest.json')['selected_finals'][identity]
            args.output_dir = root / 'other-final'; args.summarize_model = ('other-model', 'high')
            self.run_pipeline(source, args)
            args.output_dir = original_output; args.summary_only = True; args.force = True
            stages = self.run_pipeline(source, args)
            for stage in stages[:5]: stage.assert_not_called()
            self.assertEqual(stages[5].call_count, 4)
            self.assertEqual(app.read_json(cache / 'manifest.json')['selected_finals'][identity], original_ref)
            saved = app.final_reference(cache, original_ref, required=True)
            self.assertEqual(saved['settings']['request']['selection']['fusion']['model'], app.DEFAULT_MODEL)

    def test_export_alone_missing_invalid_and_ambiguous_internal_results_fail_without_inference(self):
        for problem in ('export-only', 'missing', 'corrupt', 'ambiguous', 'manifest'):
            with self.subTest(problem=problem), tempfile.TemporaryDirectory() as tmp:
                source, args, cache = self.fixture(Path(tmp))
                if problem != 'export-only':
                    self.run_pipeline(source, args)
                    manifest = app.read_json(cache / 'manifest.json')
                    ref = manifest['selected_final']
                    if problem == 'missing': (cache / ref['file']).unlink()
                    elif problem == 'corrupt':
                        saved = app.read_json(cache / ref['file']); saved['payload']['turns'][0]['text'] = 'tampered'
                        app.save_json(cache / ref['file'], saved)
                    elif problem == 'ambiguous':
                        manifest['selected_finals'] = {}; manifest['selected_final'] = [ref, ref]
                        app.save_json(cache / 'manifest.json', manifest)
                    else: (cache / 'manifest.json').write_text('{broken')
                else:
                    app.atomic_write(app.output_paths(source, args.output_dir)[0], 'Export only')
                args.summary_only = True
                with patch.object(app, 'extract_audio') as extract, patch.object(app, 'fuse_transcripts') as fusion, \
                     patch.object(app, 'local_recognition') as local, patch.object(app, 'transcribe_gpt') as cloud:
                    with self.assertRaisesRegex(app.AppError, 'internal final JSON|manifest'):
                        app.process_file(source, args, 'key')
                for stage in (extract, fusion, local, cloud): stage.assert_not_called()

    def test_materialization_rebuilds_without_inference_and_summary_levels_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, cache = self.fixture(Path(tmp))
            self.run_pipeline(source, args)
            paths = list(cache.glob('materialization.final-transcript.*.json'))
            original = paths[0].read_bytes(); paths[0].unlink()
            args.summary_only = True
            stages = self.run_pipeline(source, args)
            for stage in stages: stage.assert_not_called()
            self.assertEqual(paths[0].read_bytes(), original)

    def test_corrupt_word_artifact_recomputes_only_affected_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, args, cache = self.fixture(root, '--transcribe-only')
            self.run_pipeline(source, args)
            next(cache.glob('alignment.whisperx-turbo.*.json')).write_text('{broken')
            manifest = app.read_json(cache / 'manifest.json'); manifest['requests'] = {}
            app.save_json(cache / 'manifest.json', manifest)
            args.output_dir = root / 'repair'
            _, cloud, words, voice, *_ = self.run_pipeline(source, args)
            cloud.assert_not_called(); voice.assert_not_called()
            self.assertEqual([call.args[-1] for call in words.call_args_list], ['whisperx'])

    def test_content_lock_blocks_duplicate_work_in_other_output_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, cache = self.fixture(Path(tmp), '--transcribe-only')
            lock_dir = args.cache_dir / 'locks'; lock_dir.mkdir(parents=True)
            with (lock_dir / ('source-' + app.digest_file(source) + '.lock')).open('w') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch.object(app, 'extract_audio') as extract, self.assertRaisesRegex(app.AppError, 'recording content'):
                    app.process_file(source, args, 'key')
                extract.assert_not_called()
            self.run_pipeline(source, args)
            self.assertIsNotNone(app.read_json(cache / 'manifest.json')['selected_final'])

    def test_interrupted_atomic_artifact_write_preserves_previous_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            app.save_artifact(cache, 'recognition.test', {'model': 'test'}, {'text': 'before'})
            path = next(cache.glob('*.json')); before = path.read_bytes()
            with patch.object(app.os, 'replace', side_effect=OSError('interrupted')), self.assertRaises(OSError):
                app.save_artifact(cache, 'recognition.test', {'model': 'test'}, {'text': 'after'})
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(cache.iterdir()), [path])

    def test_source_changed_during_extraction_stops_before_any_recognition(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, _ = self.fixture(Path(tmp), '--transcribe-only')
            stamp = source.stat()
            def changed(*unused):
                source.write_bytes(b'different')
                os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            with patch.object(app, 'extract_audio', side_effect=changed), patch.object(app, 'transcribe_gpt') as cloud, \
                 patch.object(app, 'local_recognition') as local, self.assertRaisesRegex(app.AppError, 'changed during audio extraction'):
                app.process_file(source, args, 'key')
            cloud.assert_not_called(); local.assert_not_called()

    def test_edited_lone_export_and_unknown_or_symlink_outputs_remain_protected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, _ = self.fixture(Path(tmp), '--transcribe-only')
            self.run_pipeline(source, args)
            log, report = app.output_paths(source, args.output_dir)
            log.write_text('Edited export')
            with patch.object(app, 'extract_audio') as extract, self.assertRaisesRegex(app.AppError, 'edited'):
                app.process_file(source, args, 'key')
            extract.assert_not_called(); self.assertEqual(log.read_text(), 'Edited export')
            target = source.parent / 'private'; target.write_text('keep')
            log.unlink(); log.symlink_to(target); args.force = True
            with self.assertRaisesRegex(app.AppError, 'symlink'): app.process_file(source, args, 'key')
            self.assertEqual(target.read_text(), 'keep')


class LegacyCacheTests(unittest.TestCase):
    def fixture(self, root):
        source = root / 'meeting.mkv'; source.write_bytes(b'legacy-recording')
        args = app.build_parser().parse_args(['--summary-only', '--report-tabs', '1,transcript', '--output-dir', str(root / 'out')])
        args.cache_dir = root / 'cache'
        old = args.cache_dir / hashlib.sha256(str(source).encode()).hexdigest()[:16]
        settings = app.recognition_settings(source, args, app.legacy_source_signature(source))
        words = [dict(start=.2, end=1., text='Original words.', unclear=False)]
        voices = [dict(start=0., end=2., speaker=1)]
        local = dict(duration=2., words=words, voices=voices, turns=app.assign_speakers(words, voices))
        selection = {'transcription_model': 'whisperx', 'fusion': {'model': app.DEFAULT_MODEL, 'effort': app.DEFAULT_EFFORT,
            'version': 3, 'prompt': hashlib.sha256((app.FUSION_PROMPT + app.SINGLE_SOURCE_PROMPT).encode()).hexdigest()}}
        reply = json.dumps(dict(turns=[dict(id=0, text='Corrected words.')], unassigned_text='', speaker_names=[]))
        with patch.object(app, 'api_request', return_value=reply):
            final = app.reconcile_final(source, args, 'key', old, selection, local, None)
        for path in old.glob('reconciliation.part-*.json'):
            saved = app.read_json(path)
            old_settings = {k: v for k, v in saved['settings'].items() if k != 'validator'}
            signature = hashlib.sha256(json.dumps(old_settings, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            app.save_json(old / 'fusion' / (signature + '.json'), saved['payload']['result']); path.unlink()
        app.save_json(old / 'words-stage.json', {'settings': {k: v for k, v in settings.items() if k != 'diarization'},
                                                'duration': 2., 'words': words})
        app.save_json(old / 'voices-stage.json', {'settings': {k: settings[k] for k in ('source', 'models', 'diarization')},
                                                 'intervals': voices})
        text = app.render_final(source, final)
        log, _ = app.output_paths(source, args.output_dir)
        app.save_json(app.output_state_path(old, log), {'settings': settings, 'selection': selection, 'pipeline_complete': True,
            'transcript_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'source_reports': {'version': 1, 'source': settings['source'], 'transcript_sha256': hashlib.sha256(text.encode()).hexdigest(),
                               'reports': app.final_sources(source, final)}})
        app.atomic_write(log, 'MANUAL EXPORT EDITS')
        return source, args, old, text

    def test_compatible_legacy_json_reconstructs_final_without_calls_and_preserves_originals(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, old, expected = self.fixture(Path(tmp))
            originals = {p: p.read_bytes() for p in old.rglob('*.json')}
            with patch.object(app, 'extract_audio') as extract, patch.object(app, 'api_request') as api, \
                 patch.object(app, 'fuse_transcripts') as fusion, patch.object(app, 'local_recognition') as local, \
                 patch.object(app, 'summarize', return_value='Summary'), \
                 patch.object(app, 'extract_report_metadata', return_value={'topic': '', 'roles': {}}):
                app.process_file(source, args, 'key')
            extract.assert_not_called(); api.assert_not_called(); fusion.assert_not_called(); local.assert_not_called()
            log, report = app.output_paths(source, args.output_dir)
            self.assertEqual(log.read_text(), 'MANUAL EXPORT EDITS\n')
            self.assertEqual(PanelText(report.read_text()).text['panel-transcript'], expected)
            for path, data in originals.items(): self.assertEqual(path.read_bytes(), data)
            cache = args.cache_dir / app.digest_file(source)
            saved = app.read_json(next(cache.glob('reconciliation.final-transcript.*.json')))
            self.assertEqual(saved['provenance']['origin'], 'legacy-json')
            self.assertIn('not a historical full-file hash', saved['provenance']['historical_source_identity'])
            self.assertTrue(all(app.read_json(p)['provenance']['raw_payload'] == 'unavailable'
                                for p in cache.glob('alignment.*.json')))
            self.assertFalse(list(cache.glob('recognition.whisperx-turbo.*.json')))

    def test_missing_legacy_parts_or_inconsistent_snapshot_fail_without_importing_export(self):
        for missing in ('part', 'words', 'snapshot'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                source, args, old, _ = self.fixture(Path(tmp))
                if missing == 'part': next((old / 'fusion').glob('*.json')).unlink()
                elif missing == 'words': (old / 'words-stage.json').unlink()
                else:
                    path = app.output_state_path(old, app.output_paths(source, args.output_dir)[0])
                    state = app.read_json(path); state['source_reports']['reports'][0]['text'] = 'unrelated source'
                    app.save_json(path, state)
                with patch.object(app, 'extract_audio') as extract, patch.object(app, 'api_request') as api, \
                     self.assertRaisesRegex(app.AppError, 'Legacy JSON|Legacy reconciliation'):
                    app.process_file(source, args, 'key')
                extract.assert_not_called(); api.assert_not_called()
                self.assertEqual(app.output_paths(source, args.output_dir)[0].read_text(), 'MANUAL EXPORT EDITS\n')


class WhisperXRawCacheTests(unittest.TestCase):
    def test_asr_survives_alignment_failure_and_alignment_rebuild_needs_no_inference(self):
        import copy
        import sys
        import wave
        import numpy as np
        from tests import test_whisperx
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'meeting.mkv'; source.write_bytes(b'recording')
            wav = root / 'audio.wav'
            with wave.open(str(wav), 'wb') as writer:
                writer.setnchannels(1); writer.setsampwidth(2); writer.setframerate(16000)
                writer.writeframes(b'\xcc\x0c' * 32000)
            args = app.build_parser().parse_args(['--offline']); app.configure_mode(args); args.language = 'en'
            settings = app.recognition_settings(source, args); cache = root / 'cache'
            aligned = {'segments': [{'start': np.float64(0), 'end': np.float64(2), 'words': [
                {'word': 'Hello', 'start': np.float64(.1), 'end': np.float64(.5), 'score': np.float32(.5)}]}]}
            modules, loader, align_loader, align = test_whisperx.WhisperXTests().fake_whisperx(aligned=aligned)
            align.side_effect = app.AppError('alignment unavailable')
            voices = [dict(start=0., end=2., speaker=1)]
            with patch.dict(sys.modules, modules), patch.object(app, 'diarize', return_value=voices) as diarize:
                with self.assertRaisesRegex(app.AppError, 'alignment unavailable'):
                    app.local_recognition(wav, cache, settings, args)
                raw = next(cache.glob('recognition.whisperx-turbo.*.json'))
                before = raw.read_bytes()
                self.assertTrue(list(cache.glob('diarization.nemotron-3.*.json')))
                self.assertFalse(list(cache.glob('alignment.*.json')))
                align.side_effect = None
                loader.reset_mock(); align_loader.reset_mock(); diarize.reset_mock()
                result = app.local_recognition(wav, cache, settings, args)
                loader.assert_not_called(); diarize.assert_not_called(); align_loader.assert_called_once()
                self.assertEqual(raw.read_bytes(), before)
                self.assertEqual(result['words'][0]['text'], ' Hello')
                self.assertTrue(list(cache.glob('alignment.whisperx-turbo.raw.*.json')))
                normalized = [p for p in cache.glob('alignment.whisperx-turbo.*.json') if '.raw.' not in p.name][0]
                normalized.unlink()
                align_loader.reset_mock(); align.reset_mock(); loader.reset_mock()
                app.local_recognition(wav, cache, settings, args)
                loader.assert_not_called(); align_loader.assert_not_called(); align.assert_not_called()
                manifest = copy.deepcopy(app.model_manifest())
                manifest['whisperx']['identity']['alignment_revisions']['en'] = 'new-aligner-revision'
                with patch.object(app, 'model_manifest', return_value=manifest):
                    changed = app.recognition_settings(source, args)
                    app.local_recognition(wav, cache, changed, args)
                loader.assert_not_called(); align_loader.assert_called_once(); diarize.assert_not_called()
                self.assertEqual(raw.read_bytes(), before)
                self.assertEqual(len(list(cache.glob('recognition.whisperx-turbo.*.json'))), 1)

    def test_offline_final_reuses_without_models_network_or_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, args, cache = test_all_mode.AllModeTests().setup_case(root, '--offline')
            test_all_mode.AllModeTests().run_pipeline(source, args)
            args.output_dir = root / 'offline-again'
            with patch.object(app.urllib.request, 'urlopen', side_effect=AssertionError('network forbidden')):
                stages = test_all_mode.AllModeTests().run_pipeline(source, args)
            for stage in stages: stage.assert_not_called()
            log, report = app.output_paths(source, args.output_dir)
            self.assertTrue(log.is_file()); self.assertFalse(report.exists())
            ref = app.read_json(cache / 'manifest.json')['selected_final']
            self.assertEqual(app.final_reference(cache, ref)['payload']['status'], 'offline')


class LegacySummaryCacheTests(unittest.TestCase):
    fixture = LegacyCacheTests.fixture
    def test_pending_summary_and_validated_header_migrate_without_text_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, old, expected = self.fixture(Path(tmp))
            output = app.output_state_path(old, app.output_paths(source, args.output_dir)[0]).parent
            app.save_json(output / 'summary-pending.json', {'settings': {
                'model': app.DEFAULT_MODEL, 'effort': app.DEFAULT_EFFORT,
                'transcript': hashlib.sha256(expected.encode()).hexdigest(),
                'prompt': hashlib.sha256(app.SUMMARIZATION_PROMPT.encode()).hexdigest(),
                'notes_prompt': hashlib.sha256(app.PART_NOTES_PROMPT.encode()).hexdigest()},
                'answers': {'1': 'Previously completed summary.'}})
            result = {'topic': 'Conversation review', 'topic_evidence': [{'turn_id': 0, 'quote': 'Corrected words.'}],
                      'participant_roles': []}
            scratch = old / 'fixture-header'
            app.extract_report_metadata(expected, 'key', app.DEFAULT_MODEL, app.DEFAULT_EFFORT, scratch,
                                        call=lambda *a, **k: json.dumps(result))
            for path in scratch.glob('*.json'):
                saved = app.read_json(path)
                signature = hashlib.sha256(json.dumps(saved['settings'], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                app.save_json(output / 'report-header' / (signature + '.json'), {'signature': signature, 'result': result})
                path.unlink()
            scratch.rmdir()
            originals = {p: p.read_bytes() for p in old.rglob('*.json')}
            with patch.object(app, 'api_request') as api, patch.object(app, 'summarize') as summary:
                app.process_file(source, args, 'key')
            api.assert_not_called(); summary.assert_not_called()
            report = app.output_paths(source, args.output_dir)[1].read_text()
            self.assertIn('Previously completed summary.', report)
            self.assertIn('Conversation review', report)
            for path, data in originals.items(): self.assertEqual(path.read_bytes(), data)


class BatchPreparationTests(unittest.TestCase):
    def test_cached_first_recording_does_not_skip_preparation_for_next_uncached_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, args, _ = test_all_mode.AllModeTests().setup_case(root, '--offline')
            test_all_mode.AllModeTests().run_pipeline(source, args)
            other = root / 'other.mkv'; other.write_bytes(b'uncached recording')
            local = {'duration': 1, 'words': [], 'voices': [],
                     'turns': [dict(start=0, end=1, speaker=1, text='Local words.')]}
            with patch.object(app.platform, 'system', return_value='Darwin'), \
                 patch.object(app.platform, 'machine', return_value='arm64'), \
                 patch.object(app.platform, 'mac_ver', return_value=('14.0', (), '')), \
                 patch.object(app, 'extract_audio') as extract, patch.object(app, 'ensure_models') as prepare, \
                 patch.object(app, 'local_recognition', return_value=local):
                self.assertEqual(app.process_files([source, other], args), 0)
            prepare.assert_called_once(); extract.assert_called_once()
            self.assertEqual(extract.call_args.args[0], other)
