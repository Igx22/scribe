"""Three independent recognizers, one diarizer, isolated caches and no fusion."""
import hashlib
import io
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

import scribe as app
from tests.test_source_reports import PanelText
from tests.test_summary_html import Elements


class AllModeTests(unittest.TestCase):
    def setup_case(self, root, *extra):
        source = root / 'meeting.mkv'
        source.write_bytes(b'recording')
        args = app.build_parser().parse_args(['--transcription-model', 'all', '--cache-dir', str(root / 'cache'),
            '--output-dir', str(root / 'out'), '--report-tabs', '1,3,5,10,transcript', *extra])
        cache = args.cache_dir / hashlib.sha256(str(source).encode()).hexdigest()[:16]
        return source, args, cache

    @staticmethod
    def extract(source, output):
        with wave.open(str(output), 'wb') as writer:
            writer.setnchannels(1); writer.setsampwidth(2); writer.setframerate(16000)
            writer.writeframes(b'\0\0' * 64000)

    @staticmethod
    def words(backend):
        return [{'start': .25, 'end': 1.5, 'text': f'{backend.upper()}_ORIGINAL words.', 'unclear': False}]

    def run_pipeline(self, source, args, *, fail_cloud=False, fail_mlx=False):
        def recognize(audio, models, language, vocabulary, backend):
            if fail_mlx and backend == 'mlx':
                raise app.AppError('MLX unavailable')
            return self.words(backend)
        voices = [{'start': 0., 'end': 4., 'speaker': 1}]
        with patch.object(app, 'extract_audio', side_effect=self.extract) as extract, \
             patch.object(app, 'gpt_audio_request', side_effect=app.AppError('API unavailable') if fail_cloud else None,
                          return_value={'text': 'GPT_ORIGINAL words.'}) as cloud, \
             patch.object(app, 'recognize', side_effect=recognize) as asr, \
             patch.object(app, 'diarize', return_value=voices) as diarize, \
             patch.object(app, 'fuse_transcripts', side_effect=AssertionError('All must not reconcile')) as fuse, \
             patch.object(app, 'summarize', side_effect=lambda *a, detail: f'Summary {detail}') as summarize, \
             patch.object(app, 'extract_report_metadata', return_value={'topic': 'Recognition comparison', 'roles': {}}):
            app.process_file(source, args, 'fixture-key')
        return extract, cloud, asr, diarize, fuse, summarize

    def test_all_runs_three_recognizers_once_uses_one_diarization_and_embeds_every_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, cache = self.setup_case(Path(tmp))
            extract, cloud, asr, diarize, fuse, summarize = self.run_pipeline(source, args)
            extract.assert_called_once(); cloud.assert_called_once(); diarize.assert_called_once(); fuse.assert_not_called()
            self.assertEqual([call.args[-1] for call in asr.call_args_list], ['whisperx', 'mlx'])
            self.assertEqual(summarize.call_count, 4)
            self.assertTrue(all('WHISPERX_ORIGINAL' in c.args[0] and 'MLX_ORIGINAL' not in c.args[0]
                                and 'GPT_ORIGINAL' not in c.args[0] for c in summarize.call_args_list))
            log, report = app.output_paths(source, args.output_dir)
            panels = PanelText(report.read_text()).text
            self.assertEqual(panels['panel-transcript'], log.read_text())
            for identifier, text in [('gpt', 'GPT_ORIGINAL'), ('whisperx', 'WHISPERX_ORIGINAL'), ('mlx', 'MLX_ORIGINAL')]:
                self.assertIn(text, panels['panel-source-' + identifier])
            self.assertIn('Detected voices: 1', panels['panel-source-diarization'])
            self.assertEqual(len([a for _, a in Elements(report.read_text()).elements if a.get('role') == 'tab']), 9)
            for backend in ('whisperx', 'mlx'):
                self.assertEqual(app.read_json(cache / f'words-stage-{backend}.json')['settings']['recognizer']['backend'], backend)
            before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in (log, report)]
            extract, cloud, asr, diarize, *_ = self.run_pipeline(source, args)
            for stage in (extract, cloud, asr, diarize):
                stage.assert_not_called()
            self.assertEqual(before, [(p.read_bytes(), p.stat().st_mtime_ns) for p in (log, report)])

    def test_force_reruns_three_recognizers_but_diarizes_only_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, _ = self.setup_case(Path(tmp))
            self.run_pipeline(source, args)
            args.force = True
            _, cloud, asr, diarize, fuse, _ = self.run_pipeline(source, args)
            cloud.assert_called_once(); diarize.assert_called_once(); fuse.assert_not_called()
            self.assertEqual([c.args[-1] for c in asr.call_args_list], ['whisperx', 'mlx'])

    def test_summary_only_keeps_all_sources_without_running_any_recognizer(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, _ = self.setup_case(Path(tmp))
            self.run_pipeline(source, args)
            _, report = app.output_paths(source, args.output_dir)
            original = PanelText(report.read_text()).text
            args.summary_only = True
            args.transcription_model = 'whisperx'
            extract, cloud, asr, diarize, fuse, summary = self.run_pipeline(source, args)
            for stage in (extract, cloud, asr, diarize, fuse):
                stage.assert_not_called()
            self.assertEqual(summary.call_count, 4)
            self.assertEqual(PanelText(report.read_text()).text, original)

    def test_changed_mlx_identity_invalidates_only_mlx_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, _ = self.setup_case(Path(tmp), '--transcribe-only')
            self.run_pipeline(source, args)
            args.output_dir = Path(tmp) / 'new-revision'
            manifest = copy.deepcopy(app.model_manifest())
            manifest['mlx']['identity']['adapter_version'] += 1
            with patch.object(app, 'model_manifest', return_value=manifest):
                _, cloud, asr, diarize, *_ = self.run_pipeline(source, args)
            cloud.assert_not_called(); diarize.assert_not_called()
            self.assertEqual([c.args[-1] for c in asr.call_args_list], ['mlx'])

    def test_both_word_caches_resume_independently_in_new_output_and_single_model_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, args, _ = self.setup_case(root, '--transcribe-only')
            self.run_pipeline(source, args)
            for mode in ('all', 'whisperx', 'mlx'):
                args.transcription_model = mode
                args.output_dir = root / mode
                extract, cloud, asr, diarize, *_ = self.run_pipeline(source, args)
                extract.assert_called_once()
                cloud.assert_not_called(); asr.assert_not_called(); diarize.assert_not_called()

    def test_all_can_reuse_a_compatible_old_single_model_cache(self):
        for backend in ('whisperx', 'mlx'):
            with self.subTest(backend=backend), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source, args, cache = self.setup_case(root, '--transcribe-only')
                args.transcription_model = backend
                self.run_pipeline(source, args)
                old = (cache / 'words-stage.json').read_bytes()
                args.transcription_model = 'all'; args.output_dir = root / 'all'
                _, _, asr, diarize, *_ = self.run_pipeline(source, args)
                self.assertEqual([c.args[-1] for c in asr.call_args_list], ['mlx' if backend == 'whisperx' else 'whisperx'])
                diarize.assert_not_called()
                self.assertEqual((cache / 'words-stage.json').read_bytes(), old)

    def test_failed_cloud_retains_both_local_views_and_retries_only_missing_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, cache = self.setup_case(Path(tmp), '--transcribe-only')
            self.run_pipeline(source, args, fail_cloud=True)
            log, _ = app.output_paths(source, args.output_dir)
            state_path = app.output_state_path(cache, log)
            state = app.read_json(state_path)
            self.assertFalse(state['pipeline_complete'])
            self.assertEqual(state['source_mode'], 'all-local-fallback')
            self.assertEqual([r['id'] for r in app.saved_source_reports(state, log.read_text())],
                             ['whisperx', 'mlx', 'diarization'])
            _, cloud, asr, diarize, *_ = self.run_pipeline(source, args)
            cloud.assert_called_once(); asr.assert_not_called(); diarize.assert_not_called()
            self.assertTrue(app.read_json(state_path)['pipeline_complete'])

    def test_failed_mlx_resumes_cached_gpt_whisperx_and_voice_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, _ = self.setup_case(Path(tmp), '--transcribe-only')
            with self.assertRaisesRegex(app.AppError, 'MLX unavailable'):
                self.run_pipeline(source, args, fail_mlx=True)
            _, cloud, asr, diarize, *_ = self.run_pipeline(source, args)
            cloud.assert_not_called(); diarize.assert_not_called()
            self.assertEqual([c.args[-1] for c in asr.call_args_list], ['mlx'])

    def test_old_all_mode_log_is_protected_from_new_comparison_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, cache = self.setup_case(Path(tmp), '--transcribe-only')
            log, _ = app.output_paths(source, args.output_dir)
            app.atomic_write(log, 'Historical reconciled log')
            settings = app.recognition_settings(source, args)
            settings.pop('additional_recognizers'); settings.pop('recognizer')
            app.save_json(app.output_state_path(cache, log), {'settings': settings,
                'selection': {'transcription_model': 'all'}, 'pipeline_complete': True})
            with self.assertRaisesRegex(app.AppError, 'settings changed'):
                self.run_pipeline(source, args)

    def test_all_setup_prepares_both_asr_models_and_only_the_selected_diarizer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = [{'group': group, 'path': group, 'url': 'https://example.test/' + group,
                      'size': len(group), 'sha256': hashlib.sha256(group.encode()).hexdigest()}
                     for group in ['whisperx', 'mlx', 'nemotron', 'community-1']]
            manifest = {'files': files}
            downloaded = []
            def download(request, **kwargs):
                group = request.full_url.rsplit('/', 1)[-1]
                downloaded.append(group)
                return io.BytesIO(group.encode())
            with patch.object(app, 'model_manifest', return_value=manifest), \
                 patch.object(app.urllib.request, 'urlopen', side_effect=download):
                app.ensure_models(root, transcription_model='all')
            self.assertEqual(set(downloaded), {'whisperx', 'mlx', 'nemotron'})

    def test_all_rejects_unsupported_whisperx_language_before_any_recognition(self):
        with patch.object(app, 'load_env'), patch.object(app, 'ensure_models') as models:
            with self.assertRaisesRegex(app.AppError, 'English and Russian'):
                app.main(['--transcription-model', 'all', '--language', 'de'])
            models.assert_not_called()
