"""Transcript menu grouping and provenance must survive every report mode."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import scribe as app
from tests import seed_final
from tests.test_summary_html import Elements


class ReportDropdownTests(unittest.TestCase):
    def render(self, transcript='Final text', **options):
        reports = [dict(id=identifier, label=label, description='Original source', text='Raw & <words>')
                   for identifier, label in [('gpt', 'GPT-Transcribe'), ('whisperx', 'WhisperX Turbo'),
                                              ('mlx', 'MLX Turbo'), ('diarization', 'Nemotron 3')]]
        summaries = {level: 'Summary.' for level in app.summary_levels(options.get('tabs', [1]))}
        return app.summary_html(Path('meeting.mkv'), summaries, transcript=transcript,
                                source_reports=reports, **options)

    def test_menu_keeps_final_and_all_sources_with_processing_badges_and_sections(self):
        content = self.render()
        menu = content.split('id="transcript-options">')[1].split('</div></div>')[0]
        elements = Elements(menu).elements
        self.assertEqual([a['id'] for _, a in elements if a.get('role') == 'tab'],
                         ['tab-transcript', 'tab-source-gpt', 'tab-source-whisperx',
                          'tab-source-mlx', 'tab-source-diarization'])
        self.assertEqual(re.findall(r'class="processing-badge">([^<]+)', menu),
                         ['Online', 'Offline', 'Offline', 'Offline'])
        self.assertLess(menu.index('Source transcripts'), menu.index('tab-source-gpt'))
        self.assertLess(menu.index('Speaker segmentation'), menu.index('tab-source-diarization'))
        self.assertEqual(content.count('id="transcript-toggle"'), 1)
        self.assertIn('aria-controls="transcript-options" hidden', content)
        self.assertIn('Raw &amp; &lt;words&gt;', content)
        self.assertIn('id="transcript-choice-title">Transcript</span>', content)
        self.assertIn('id="transcript-choice-description">Final version</span>', content)
        self.assertEqual([a['data-choice-label'] for _, a in elements if a.get('role') == 'tab'],
                         ['Final version', 'Transcript · GPT-Transcribe', 'Transcript · WhisperX Turbo',
                          'Transcript · MLX Turbo', 'Diarization · Nemotron 3'])

    def test_no_transcript_selection_omits_picker_and_source_text(self):
        content = self.render(tabs=[1])
        elements = Elements(content).elements
        self.assertFalse(any(a.get('id') == 'transcript-toggle' for _, a in elements))
        self.assertNotIn('Raw &amp;', content)

    def test_final_badge_uses_saved_log_instead_of_assuming_gpt(self):
        for provenance, badge in [
            ('WhisperX large-v3-turbo + nemotron voice/time anchors', 'WhisperX Turbo'),
            ('MLX large-v3-turbo + community-1 voice/time anchors', 'MLX Turbo'),
            ('GPT-Transcribe text + WhisperX / nemotron voice/time anchors; reconciled by gpt-6.1-sol', 'GPT-6.1-sol'),
            ('GPT-Transcribe text + WhisperX / community-1 voice/time anchors; reconciled by another-model', 'another-model')]:
            with self.subTest(provenance=provenance):
                log = app.transcript_text(Path('meeting.mkv'), 1, [], provenance=provenance)
                self.assertEqual(app.final_transcript_badge(log), badge)
                self.assertIn(f'class="processing-badge">{badge}</span>', self.render(log))
        cloud = app.gpt_transcript_text(Path('meeting.mkv'), [])
        self.assertEqual(app.final_transcript_badge(cloud), 'GPT-Transcribe')

    def test_unknown_edited_and_dialogue_provenance_does_not_invent_a_model_badge(self):
        for text in ['Reviewed log', 'Sources: GPT-Transcribe only',
                     'DETAILED TRANSCRIPT\nSource file: meeting.mkv\nDuration: 00:01\n\n'
                     'Actual dialogue follows.\n\nSources: GPT-Transcribe only',
                     app.transcript_text(Path('meeting.mkv'), 1, [], provenance='<script>guess</script>')]:
            with self.subTest(text=text):
                self.assertEqual(app.final_transcript_badge(text), '')

    def test_detail_menu_has_only_configured_levels_and_the_actual_summary_model(self):
        log = app.transcript_text(Path('meeting.mkv'), 1, [], provenance=
            'GPT-Transcribe text + WhisperX / nemotron voice/time anchors; reconciled by gpt-6-luna')
        content = app.summary_html(Path('meeting.mkv'), {10: 'Detailed.', 1: 'Brief.', 5: 'Expanded.'},
            transcript=log, tabs=[10, 1, 5, 'transcript'], summary_model='gpt-6.1-sol')
        menu = content.split('id="detail-options">')[1].split('</div></div>')[0]
        elements = Elements(menu).elements
        self.assertEqual([a['id'] for _, a in elements if a.get('role') == 'tab'],
                         ['tab-10', 'tab-1', 'tab-5'])
        self.assertEqual(re.findall(r'class="processing-badge">([^<]+)', menu), ['GPT-6.1-sol'])
        self.assertNotIn('GPT-6-luna', menu)
        self.assertIn('aria-controls="detail-options" hidden', content)
        self.assertEqual(content.count('id="detail-toggle"'), 1)
        trigger = content.split('id="detail-toggle"')[1].split('id="detail-options"')[0]
        self.assertIn('id="detail-choice-title">Summary</span>', trigger)
        self.assertIn('id="detail-choice-description">In depth · 10/10</span>', trigger)
        self.assertIn('<div class="menu-footer"><span class="processing-badge">GPT-6.1-sol</span></div>', content)

    def test_detail_badges_do_not_guess_unknown_provenance_and_escape_model_labels(self):
        for model, expected in [(None, None), ('<img src=x>', '&lt;img src=x&gt;')]:
            content = self.render(tabs=[1], summary_model=model)
            menu = content.split('id="detail-options">')[1].split('</div></div>')[0]
            badges = re.findall(r'class="processing-badge">([^<]+)', menu)
            self.assertEqual(badges, [] if expected is None else [expected])
            self.assertNotIn('<img', content)

    def test_pipeline_passes_the_summary_model_and_grouped_selections_keep_their_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'meeting.mkv'; source.write_bytes(b'fixture')
            args = app.build_parser().parse_args(['--summary-only', '--report-tabs', '10,transcript,1',
                '--summarize-model', 'gpt-6-luna:low', '--output-dir', str(root / 'out')])
            args.cache_dir = root / 'cache'
            log, report = app.output_paths(source, args.output_dir)
            seed_final(source, args, 'Saved final log.')
            with patch.object(app, 'summarize', return_value='Summary.'), \
                    patch.object(app, 'extract_report_metadata', return_value={'topic': 'Meeting', 'roles': {}}):
                app.process_file(source, args, 'fixture-key')
            content = report.read_text()
            elements = Elements(content).elements
            tabs = [a for _, a in elements if a.get('role') == 'tab']
            panels = [a for _, a in elements if a.get('role') == 'tabpanel']
            self.assertEqual([a['id'] for a in tabs], ['tab-10', 'tab-1', 'tab-transcript'])
            self.assertEqual([a['aria-controls'] for a in tabs], [a['id'] for a in panels])
            self.assertEqual(re.findall(r'class="processing-badge">([^<]+)', content), ['GPT-6-luna'])

    @unittest.skipUnless(shutil.which('node'), 'Node.js is optional for offline JavaScript checks')
    def test_keyboard_and_theme_work_for_transcript_first_and_summary_only(self):
        for selection in [['transcript'], ['transcript', 1], [1], [1, 'transcript'],
                          [10, 'transcript', 1, 3, 7, 5]]:
            with self.subTest(selection=selection):
                content = self.render(tabs=selection)
                result = subprocess.run([shutil.which('node'), str(Path(__file__).with_name('report_theme_check.cjs'))],
                                        input=content, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
