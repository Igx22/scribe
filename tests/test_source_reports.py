"""Source snapshots, truthful provenance, self-contained rendering and resume."""
import copy
import hashlib
from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import scribe as app
from tests.test_summary_html import Elements


class PanelText(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.panel = None
        self.in_text = False
        self.text = {}
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'section':
            self.panel = attrs.get('id')
        if tag == 'div' and attrs.get('class') == 'transcript-content':
            self.in_text = True
            self.text[self.panel] = ''

    def handle_endtag(self, tag):
        if tag == 'div':
            self.in_text = False

    def handle_data(self, text):
        if self.in_text:
            self.text[self.panel] += text


class SourceReportTests(unittest.TestCase):
    def local(self):
        return {'duration': 4, 'words': [], 'voices': [
            {'start': .125, 'end': 2.375, 'speaker': 1},
            {'start': 1.75, 'end': 3.875, 'speaker': 2}],
            'turns': [{'start': .125, 'end': 2.375, 'speaker': 1,
                       'uncertain': False, 'text': 'LOCAL_UNRECONCILED & words.'}]}

    def chunks(self):
        return [{'index': 0, 'start': 0, 'end': 4, 'text': 'GPT_ORIGINAL & words.'}]

    def pipeline(self, root, mode=app.COMBINED_MODE):
        source = root / 'meeting.mkv'
        source.write_bytes(b'recording')
        args = app.build_parser().parse_args(['--transcription-model', mode,
            '--output-dir', str(root / 'out'),
            '--report-tabs', '1,3,5,10,transcript'])
        args.cache_dir = root / 'cache'
        return source, args

    def run_pipeline(self, source, args, *, cloud_failure=False, fusion_failure=False):
        local = self.local()
        fused = [{**local['turns'][0], 'text': 'FINAL_RECONCILED words.'}]
        with patch.object(app, 'extract_audio'), patch.object(app, 'local_recognition', return_value=local), \
             patch.object(app, 'transcribe_gpt', side_effect=app.AppError('Audio unavailable') if cloud_failure else None,
                          return_value=self.chunks()) as cloud, \
             patch.object(app, 'fuse_transcripts', side_effect=app.AppError('Invalid anchors') if fusion_failure else None,
                          return_value=(fused, [])) as fusion, \
             patch.object(app, 'summarize', side_effect=lambda *a, detail: f'Summary {detail}') as summary, \
             patch.object(app, 'extract_report_metadata', return_value={'topic': 'Test conversation', 'roles': {}}):
            app.process_file(source, args, 'fixture-key')
        return cloud.call_count, fusion.call_count, summary.call_count

    def test_combined_report_embeds_both_original_sources_and_fixed_voice_intervals(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args = self.pipeline(Path(tmp))
            self.assertEqual(self.run_pipeline(source, args), (1, 1, 4))
            log, report = app.output_paths(source, args.output_dir)
            content = report.read_text()
            panels = PanelText(content).text
            self.assertEqual(panels['panel-transcript'], log.read_text())
            self.assertIn('FINAL_RECONCILED', panels['panel-transcript'])
            self.assertIn('GPT_ORIGINAL', panels['panel-source-gpt'])
            self.assertNotIn('FINAL_RECONCILED', panels['panel-source-gpt'])
            self.assertIn('LOCAL_UNRECONCILED', panels['panel-source-whisperx'])
            self.assertNotIn('FINAL_RECONCILED', panels['panel-source-whisperx'])
            self.assertIn('[0.125–2.375] A', panels['panel-source-diarization'])
            self.assertIn('[1.750–3.875] B', panels['panel-source-diarization'])
            self.assertIn('Detected voices: 2', panels['panel-source-diarization'])
            self.assertIn('Final transcript', content)
            tabs = [a for t, a in Elements(content).elements if a.get('role') == 'tab']
            self.assertEqual([a['id'] for a in tabs], ['tab-1', 'tab-3', 'tab-5', 'tab-10',
                'tab-transcript', 'tab-source-gpt', 'tab-source-whisperx', 'tab-source-diarization'])
            self.assertTrue(all(a.get('class') == 'source-tab' for a in tabs[-3:]))

    def test_only_models_used_by_the_selected_mode_are_displayed(self):
        for mode, expected in [(app.ONLINE_MODE, ['gpt']), ('whisperx', ['whisperx', 'diarization']),
                               ('mlx', ['mlx', 'diarization'])]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                source, args = self.pipeline(Path(tmp), mode)
                self.run_pipeline(source, args)
                _, report = app.output_paths(source, args.output_dir)
                panels = PanelText(report.read_text()).text
                self.assertEqual([p for p in panels if p.startswith('panel-source-')],
                                 ['panel-source-' + key for key in expected])

    def test_fallback_preserves_actual_inputs_without_presenting_failed_cloud_as_success(self):
        for failed_cloud, expected in [(True, ['whisperx', 'diarization']),
                                       (False, ['gpt', 'whisperx', 'diarization'])]:
            with self.subTest(cloud_failure=failed_cloud), tempfile.TemporaryDirectory() as tmp:
                source, args = self.pipeline(Path(tmp))
                self.run_pipeline(source, args, cloud_failure=failed_cloud, fusion_failure=True)
                log, report = app.output_paths(source, args.output_dir)
                panels = PanelText(report.read_text()).text
                self.assertIn('LOCAL_UNRECONCILED', panels['panel-transcript'])
                self.assertEqual([p for p in panels if p.startswith('panel-source-')],
                                 ['panel-source-' + key for key in expected])
                self.assertNotIn('FINAL_RECONCILED', log.read_text())

    def test_summary_only_reuses_frozen_sources_despite_different_current_options_and_cache_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, args = self.pipeline(Path(tmp))
            self.run_pipeline(source, args)
            log, report = app.output_paths(source, args.output_dir)
            original = PanelText(report.read_text()).text
            before = log.read_bytes(), log.stat().st_mtime_ns
            cache = args.cache_dir / hashlib.sha256(str(source).encode()).hexdigest()[:16]
            app.atomic_write(cache / 'sources/local.log.md', 'STALE_OTHER_RUN')
            app.save_json(cache / 'voices-stage.json', {'intervals': [{'speaker': 99}]})
            args.summary_only = True
            args.transcription_model = 'mlx'
            args.diarization_model = 'community-1'
            with patch.object(app, 'extract_audio', side_effect=AssertionError('No extraction')), \
                 patch.object(app, 'local_recognition', side_effect=AssertionError('No inference')), \
                 patch.object(app, 'transcribe_gpt', side_effect=AssertionError('No audio API')), \
                 patch.object(app, 'fuse_transcripts', side_effect=AssertionError('No fusion')), \
                 patch.object(app, 'summarize', return_value='Updated summary'), \
                 patch.object(app, 'extract_report_metadata', return_value={'topic': 'Test conversation', 'roles': {}}):
                app.process_file(source, args, 'fixture-key')
            self.assertEqual(PanelText(report.read_text()).text, original)
            self.assertEqual((log.read_bytes(), log.stat().st_mtime_ns), before)
            self.assertNotIn('STALE_OTHER_RUN', report.read_text())

    def test_old_or_edited_logs_do_not_borrow_unproven_source_outputs(self):
        transcript = 'Final log'
        reports = app.recognition_source_reports(Path('meeting.mkv'), local=self.local())
        snapshot = {'version': 1, 'source': {'size': 1}, 'reports': reports,
                    'transcript_sha256': hashlib.sha256(transcript.encode()).hexdigest()}
        state = {'settings': {'source': {'size': 1}}, 'source_reports': snapshot}
        self.assertEqual(app.saved_source_reports(state, transcript), reports)
        self.assertEqual(app.saved_source_reports(state, transcript + ' edited'), [])
        self.assertEqual(app.saved_source_reports({}, transcript), [])
        invalid = copy.deepcopy(state)
        invalid['source_reports']['source']['size'] = 2
        self.assertEqual(app.saved_source_reports(invalid, transcript), [])
        invalid = copy.deepcopy(state)
        invalid['source_reports']['reports'].append(reports[0])
        self.assertEqual(app.saved_source_reports(invalid, transcript), [])

    def test_sources_are_escaped_complete_portable_and_omitted_without_transcript_selection(self):
        text = '\nRAW_BEGIN\n' + '<script>example</script> & @@PANELS@@\n' * 10000 + 'RAW_END\n'
        reports = [{'id': 'gpt', 'label': '<GPT>', 'description': 'Original & raw', 'text': text}]
        rendered = app.summary_html(Path('meeting.mkv'), {1: 'Brief'}, transcript='Final', source_reports=reports)
        self.assertEqual(PanelText(rendered).text['panel-source-gpt'], text)
        elements = Elements(rendered).elements
        self.assertEqual(sum(tag == 'script' for tag, _ in elements), 1)
        self.assertFalse(any(key in attrs for _, attrs in elements for key in ('src', 'href', 'srcset')))
        self.assertIn('&lt;GPT&gt;', rendered)
        self.assertNotIn('RAW_BEGIN', app.summary_html(Path('meeting.mkv'), {1: 'Brief'},
            transcript='Final', source_reports=reports, tabs=[1]))
        with tempfile.TemporaryDirectory() as tmp:
            standalone = Path(tmp) / 'report.html'
            standalone.write_text(rendered)
            self.assertEqual(list(Path(tmp).iterdir()), [standalone])
            self.assertEqual(PanelText(standalone.read_text()).text['panel-source-gpt'], text)

    @unittest.skipUnless(shutil.which('node'), 'Node.js is optional for offline JavaScript checks')
    def test_all_source_tabs_support_theme_clicks_and_keyboard_navigation(self):
        reports = app.recognition_source_reports(Path('meeting.mkv'), local=self.local(), gpt_chunks=self.chunks())
        content = app.summary_html(Path('meeting.mkv'), {1: 'Brief'}, transcript='Final', source_reports=reports)
        result = subprocess.run([shutil.which('node'), str(Path(__file__).with_name('report_theme_check.cjs'))],
                                input=content, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
