"""Transcript menu grouping and provenance must survive every report mode."""
from pathlib import Path
import re
import shutil
import subprocess
import unittest

import scribe as app
from tests.test_summary_html import Elements


class ReportDropdownTests(unittest.TestCase):
    def render(self, transcript='Final text', **options):
        reports = [dict(id=identifier, label=label, description='Original source', text='Raw & <words>')
                   for identifier, label in [('gpt', 'GPT-Transcribe'), ('whisperx', 'WhisperX Turbo'),
                                              ('mlx', 'MLX Turbo'), ('diarization', 'Nemotron 3')]]
        return app.summary_html(Path('meeting.mkv'), {1: 'Brief'}, transcript=transcript,
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

    @unittest.skipUnless(shutil.which('node'), 'Node.js is optional for offline JavaScript checks')
    def test_keyboard_and_theme_work_for_transcript_first_and_summary_only(self):
        for selection in [['transcript'], ['transcript', 1], [1]]:
            with self.subTest(selection=selection):
                content = self.render(tabs=selection)
                result = subprocess.run([shutil.which('node'), str(Path(__file__).with_name('report_theme_check.cjs'))],
                                        input=content, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
