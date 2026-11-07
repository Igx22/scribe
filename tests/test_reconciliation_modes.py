"""Exercise real reconciliation validation across every recognizer with mocked APIs."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import scribe as app


class ReconciliationModeTests(unittest.TestCase):
    def local(self):
        return {'duration': 4, 'words': [], 'voices': [{'start': 0, 'end': 4, 'speaker': 1}],
                'turns': [{'start': 0, 'end': 2, 'speaker': 1, 'text': 'Hello.'},
                          {'start': 2, 'end': 4, 'speaker': 1, 'text': 'My name is Alice.'}]}

    def run_case(self, root, mode, *, offline=False, api_failure=False):
        source = root / '2026-11-07 14-37-07 (1speaker).mkv'
        source.write_bytes(b'fixture')
        args = app.build_parser().parse_args(['--transcription-model', mode,
            '--cache-dir', str(root / 'cache'), '--output-dir', str(root / 'out'),
            '--summarize-model', 'none', *(['--offline'] if offline else [])])
        chunks = [{'index': 0, 'start': 0, 'end': 4, 'text': 'Hello. My name is Alice.'}]
        payloads = []
        def call(key, model, effort, prompt, text, **kwargs):
            if offline:
                raise AssertionError('Offline must never call the text API')
            if api_failure:
                raise app.AppError('Reconciliation unavailable')
            payload = json.loads(text); payloads.append((prompt, payload, model, effort))
            anchors = payload['source_b_fixed_anchors']
            known = [a for a in anchors if a['speaker'] != 'UNKNOWN SPEAKER']
            names = []
            if known:
                introduction = next(a for a in known if 'My name is Alice.' in a['text'])
                names = [dict(speaker_id='A', name='Alice', name_type='human_name',
                    evidence_kind='self_introduction',
                    evidence=[dict(anchor_id=introduction['id'], quote='My name is Alice.')])]
            return json.dumps(dict(turns=[dict(id=a['id'], text=a['text']) for a in anchors],
                                   unassigned_text='', speaker_names=names))
        with patch.object(app, 'extract_audio'), \
                patch.object(app, 'local_recognition', side_effect=lambda *a, **k: copy.deepcopy(self.local())) as local, \
                patch.object(app, 'transcribe_gpt', return_value=chunks) as audio, \
                patch.object(app, 'api_request', side_effect=call) as api:
            app.process_file(source, args, 'fixture-key')
            first_count = api.call_count
            app.process_file(source, args, 'fixture-key')
        return source, args, payloads, first_count, api.call_count, local.call_count, audio.call_count

    def test_all_local_and_combined_modes_apply_names_globally_and_preserve_raw_sources(self):
        for mode in ['all', 'whisperx', 'mlx', app.COMBINED_MODE]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                source, args, payloads, first, repeated, _, audio = self.run_case(Path(tmp), mode)
                log, _ = app.output_paths(source, args.output_dir)
                final = log.read_text()
                self.assertEqual(final.count('] Alice\n'), 2)
                self.assertNotIn('] A\n', final)
                self.assertIn('reconciled by gpt-6.1-sol', final)
                self.assertEqual(app.final_transcript_badge(final), 'GPT-6.1-sol')
                self.assertEqual((first, repeated), (1, 1), 'Resume must not repeat final GPT calls')
                state = app.read_json(next(args.cache_dir.glob('*/outputs/*/state.json')))
                self.assertTrue(state['pipeline_complete'])
                raw = next(r['text'] for r in state['source_reports']['reports'] if r['id'] == ('mlx' if mode == 'mlx' else 'whisperx'))
                self.assertIn('] A\n', raw)
                self.assertNotIn('] Alice\n', raw)
                if mode == 'all':
                    self.assertIn('additional_local_source', payloads[0][1])
                if mode in ['whisperx', 'mlx']:
                    self.assertEqual(audio, 0, 'Local recognition must upload text only')
                    self.assertEqual(payloads[0][0], app.SINGLE_SOURCE_PROMPT)

    def test_api_only_reconciles_without_inventing_speakers_or_loading_local_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, payloads, first, repeated, local, _ = self.run_case(Path(tmp), app.ONLINE_MODE)
            text = app.output_paths(source, args.output_dir)[0].read_text()
            self.assertEqual(local, 0)
            self.assertEqual((first, repeated), (1, 1))
            self.assertIn('GPT-Transcribe only; reconciled by gpt-6.1-sol', text)
            self.assertNotIn('] Alice\n', text)
            self.assertNotIn('] A\n', text)
            self.assertEqual(payloads[0][1]['speaker_context']['speaker_ids'], [])
            self.assertEqual(app.final_transcript_badge(text), 'GPT-6.1-sol')

    def test_explicit_offline_still_skips_gpt_and_name_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, _, first, repeated, _, audio = self.run_case(Path(tmp), 'all', offline=True)
            text = app.output_paths(source, args.output_dir)[0].read_text()
            self.assertEqual((first, repeated, audio), (0, 0, 0))
            self.assertIn('] A\n', text)
            self.assertNotIn('reconciled by', text)

    def test_failed_final_gpt_keeps_raw_text_and_marks_incomplete_for_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args, _, first, repeated, _, _ = self.run_case(Path(tmp), 'whisperx', api_failure=True)
            text = app.output_paths(source, args.output_dir)[0].read_text()
            state = app.read_json(next(args.cache_dir.glob('*/outputs/*/state.json')))
            self.assertIn('] A\n', text)
            self.assertNotIn('reconciled by', text)
            self.assertFalse(state['pipeline_complete'])
            self.assertIn('fusion_error', state)
            self.assertEqual((first, repeated), (1, 2))

    def test_single_source_rejects_removed_uncertainty_empty_anchors_and_invented_speech(self):
        turns = [dict(start=0, end=1, speaker=1, text='[low-confidence speech: Alice]')]
        for replacement, extra in [('', ''), ('Alice', ''), (turns[0]['text'], 'Invented extra speech')]:
            with self.subTest(replacement=replacement, extra=extra), tempfile.TemporaryDirectory() as tmp:
                result = dict(turns=[dict(id=0, text=replacement)], unassigned_text=extra, speaker_names=[])
                with self.assertRaises(app.AppError):
                    app.fuse_transcripts(app.transcript_chunks(turns), turns, Path(tmp), 'key', 'model', 'medium',
                                         single_source=True, call=lambda *a, **k: json.dumps(result))
