"""Whole-recording context, output budgets, coverage, and resumable JSON parts."""
import copy
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import scribe as app


class ReconciliationBudgetTests(unittest.TestCase):
    def sources(self, count=3, width=10):
        turns = [dict(start=i * 600, end=i * 600 + 2, speaker=1,
                      text=f'Original {i} ' + 'x' * width) for i in range(count)]
        return turns, app.transcript_chunks(turns)

    def echo(self, calls):
        def reply(*args, **kwargs):
            payload = json.loads(args[4])
            calls.append((payload, kwargs))
            return json.dumps(dict(turns=[dict(id=a['id'], text=a['text'])
                                         for a in payload['source_b_fixed_anchors']],
                                   unassigned_text='', speaker_names=[]))
        return reply

    def test_eight_audio_windows_fit_one_request_with_fixed_voices_and_times(self):
        turns, chunks = self.sources(8)
        original = copy.deepcopy(turns)
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            result, extra = app.fuse_transcripts(chunks, turns, Path(tmp), '', app.DEFAULT_MODEL,
                                                'medium', call=self.echo(calls), single_source=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual([a['id'] for a in calls[0][0]['source_b_fixed_anchors']], list(range(8)))
        self.assertEqual(len(calls[0][0]['source_a_chunks']), 8)
        self.assertTrue(all(c['primary'] for c in calls[0][0]['source_a_chunks']))
        self.assertGreater(calls[0][1]['max_output_tokens'], 20000)
        self.assertEqual(result, original)
        self.assertEqual(turns, original)
        self.assertEqual(extra, [])

    def test_output_parts_each_receive_every_source_and_cover_anchors_once(self):
        turns, chunks = self.sources(width=1000)
        calls = []
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(app, 'reconciliation_model_limits', return_value=(1050000, 2500)):
            result, _ = app.fuse_transcripts(chunks, turns, Path(tmp), '', app.DEFAULT_MODEL, 'medium',
                                            additional_turns=turns, call=self.echo(calls))
        self.assertEqual(len(calls), 3)
        returned = []
        for i, (payload, options) in enumerate(calls):
            ids = [a['id'] for a in payload['source_b_fixed_anchors']]
            returned.extend(ids)
            self.assertEqual(ids, [i])
            self.assertEqual({a['id'] for a in payload['source_b_context_anchors']}, {0, 1, 2} - {i})
            self.assertEqual([c['text'] for c in payload['source_a_chunks']], [c['text'] for c in chunks])
            self.assertEqual([c['primary'] for c in payload['source_a_chunks']], [j == i for j in range(3)])
            self.assertEqual(payload['additional_local_source'], turns)
            self.assertLessEqual(options['max_output_tokens'], 2500)
        self.assertEqual(returned, [0, 1, 2])
        self.assertEqual(result, turns)

    def test_context_budget_includes_reserved_answer_not_just_input(self):
        turns, chunks = self.sources(6, 3000)
        prompt = app.FUSION_PROMPT + app.FULL_CONTEXT_PROMPT
        whole = app.plan_reconciliation(chunks, turns, None, app.DEFAULT_MODEL, prompt)[0]
        context = whole['input_tokens'] + whole['max_output_tokens'] + 8192 - 1
        with patch.object(app, 'reconciliation_model_limits', return_value=(context, 128000)):
            parts = app.plan_reconciliation(chunks, turns, None, app.DEFAULT_MODEL, prompt)
        self.assertGreater(len(parts), 1)
        for part in parts:
            self.assertLessEqual(part['input_tokens'] + part['max_output_tokens']
                                 + part['policy']['context_reserve'], context)
            self.assertLessEqual(part['max_output_tokens'], 128000)

    def test_context_overflow_and_unsplittable_output_make_no_api_call(self):
        turns, chunks = self.sources(width=3000)
        for limits, message in [((5000, 128000), 'context is too large'),
                                ((1050000, 1000), 'output window cannot fit')]:
            with self.subTest(limits=limits), tempfile.TemporaryDirectory() as tmp, \
                    patch.object(app, 'reconciliation_model_limits', return_value=limits):
                call = Mock()
                with self.assertRaisesRegex(app.AppError, message):
                    app.fuse_transcripts(chunks, turns, Path(tmp), '', app.DEFAULT_MODEL, 'medium', call=call)
                call.assert_not_called()

    def test_late_context_and_budget_changes_invalidate_cached_parts(self):
        turns, chunks = self.sources(width=1000)
        calls = []
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(app, 'reconciliation_model_limits', return_value=(1050000, 2500)):
            cache = Path(tmp)
            for _ in range(2):
                app.fuse_transcripts(chunks, turns, cache, '', app.DEFAULT_MODEL, 'medium', call=self.echo(calls))
            self.assertEqual(len(calls), 3)
            originals = {p: p.read_bytes() for p in cache.glob('reconciliation.part-*.json')}
            turns[-1]['text'] += ' Later clarification.'
            chunks[-1]['text'] = turns[-1]['text']
            app.fuse_transcripts(chunks, turns, cache, '', app.DEFAULT_MODEL, 'medium', call=self.echo(calls))
            self.assertEqual(len(calls), 6)
            for path, data in originals.items():
                self.assertEqual(path.read_bytes(), data)
            with patch.object(app, 'reconciliation_model_limits', return_value=(1050000, 2600)):
                app.fuse_transcripts(chunks, turns, cache, '', app.DEFAULT_MODEL, 'medium', call=self.echo(calls))
            self.assertEqual(len(calls), 9)

    def test_name_evidence_can_come_from_the_far_end_of_the_recording(self):
        turns, chunks = self.sources(width=1000)
        turns[2]['text'] += ' My name is Alice.'
        chunks[2]['text'] = turns[2]['text']
        calls = []
        echo = self.echo(calls)
        def reply(*args, **kwargs):
            result = json.loads(echo(*args, **kwargs))
            if len(calls) == 1:
                result['speaker_names'] = [dict(speaker_id='A', name='Alice', name_type='human_name',
                    evidence_kind='self_introduction', evidence=[dict(anchor_id=2, quote='My name is Alice.')])]
            return json.dumps(result)
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(app, 'reconciliation_model_limits', return_value=(1050000, 2500)):
            result, _ = app.fuse_transcripts(chunks, turns, Path(tmp), '', app.DEFAULT_MODEL, 'medium', call=reply)
        self.assertEqual([t['speaker_name'] for t in result], ['Alice'] * 3)
        self.assertEqual(calls[1][0]['established_speaker_names'], {'A': 'Alice'})

    def test_all_failed_whole_recording_request_has_no_reconciled_badge(self):
        turns, chunks = self.sources(8)
        local = dict(duration=4800, turns=turns, words=[], voices=[])
        args = SimpleNamespace(transcription_model='whisperx', diarization_model='nemotron', offline=False, force=False)
        selection = {'fusion': {'model': app.DEFAULT_MODEL, 'effort': 'medium'}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'api_request', side_effect=app.AppError('Network unavailable')) as call:
            result = app.reconcile_final(Path('meeting.mkv'), args, '', Path(tmp), selection, local, None)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(result['status'], 'fallback')
        self.assertEqual(result['source_mode'], 'unreconciled-fallback')
        self.assertFalse(result['pipeline_complete'])
        self.assertNotIn('reconciled_by', result)
        self.assertEqual(result['turns'], turns)

    def test_profiles_and_non_ascii_budget_use_local_conservative_estimates(self):
        self.assertEqual(app.reconciliation_model_limits('gpt-6.1-sol'), (1050000, 128000))
        self.assertEqual(app.reconciliation_model_limits('gpt-6.1-sol-2026-11-12'), (1050000, 128000))
        self.assertEqual(app.reconciliation_model_limits('custom-model'), (128000, 16000))
        payload = {'text': 'Привет 🌍'}
        with patch.object(app.urllib.request, 'urlopen', side_effect=AssertionError('No network allowed')):
            size = app.reconciliation_input_tokens(payload, 'Instructions')
        self.assertGreaterEqual(size, len(app.reconciliation_json(payload).encode('utf-8')))

    def test_large_answer_budget_increases_http_timeout_without_changing_small_requests(self):
        response = dict(status='completed', output=[dict(type='message',
            content=[dict(type='output_text', text='Reviewed')])])
        for budget in (12000, 128000):
            with self.subTest(budget=budget), \
                    patch.object(app.urllib.request, 'urlopen', return_value=io.StringIO(json.dumps(response))) as request, \
                    patch.object(app, 'ssl_context', return_value=None):
                answer = app.api_request('fixture-key', app.DEFAULT_MODEL, 'medium', 'Prompt', 'Text', max_output_tokens=budget)
            self.assertEqual(answer, 'Reviewed')
            timeout = request.call_args.kwargs['timeout']
            if budget == 12000:
                self.assertEqual(timeout, 600)
            else:
                self.assertGreater(timeout, 600)
                self.assertLessEqual(timeout, 3600)
