"""Actual generation instants, browser-local calendar days and portable fallbacks."""
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

import scribe as app


class GenerationStamp(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.attrs = None
        self.text = ''
        self.inside = False
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        if tag == 'time' and dict(attrs).get('id') == 'generated-at':
            self.attrs = dict(attrs)
            self.inside = True

    def handle_endtag(self, tag):
        if tag == 'time':
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.text += data


class GenerationTimeTests(unittest.TestCase):
    def render(self, generated_at=None):
        return app.summary_html(Path('2026-09-25 16-55-39.mkv'), {1: 'A saved summary.'},
            transcript='DETAILED TRANSCRIPT\nDuration: 01:34\n\nConversation.', generated_at=generated_at)

    def test_timestamp_is_current_render_time_and_not_recording_date(self):
        before = datetime.now(timezone.utc).replace(microsecond=0)
        stamp = GenerationStamp(self.render())
        after = datetime.now(timezone.utc)
        generated = datetime.fromisoformat(stamp.attrs['datetime'])
        self.assertLessEqual(before, generated)
        self.assertLessEqual(generated, after)
        self.assertIn('UTC', stamp.text)

    def test_explicit_generation_instant_is_embedded_in_utc_with_complete_no_js_fallback(self):
        generated = datetime(2026, 11, 7, 17, 34, 56, tzinfo=timezone(timedelta(hours=7)))
        content = self.render(generated)
        stamp = GenerationStamp(content)
        self.assertEqual(stamp.attrs['datetime'], '2026-11-07T10:34:56+00:00')
        self.assertEqual(stamp.text, '2026-11-07 10:34:56 UTC')
        self.assertEqual(stamp.attrs['title'], stamp.text)
        self.assertIn('25 September 2026', content)
        self.assertNotIn('@@GENERATED_', content)
        later = GenerationStamp(self.render(generated + timedelta(hours=1)))
        self.assertNotEqual(later.attrs['datetime'], stamp.attrs['datetime'])
        with self.assertRaisesRegex(app.AppError, 'timezone'):
            self.render(generated.replace(tzinfo=None))

    def check_browser(self, generated, zone, scenarios):
        result = subprocess.run([shutil.which('node'), str(Path(__file__).with_name('report_theme_check.cjs')),
            json.dumps(scenarios)], input=self.render(generated), text=True, capture_output=True,
            env={**os.environ, 'TZ': zone})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node.js is optional for offline JavaScript checks')
    def test_today_time_only_then_full_date_after_browser_local_midnight(self):
        self.check_browser(datetime(2026, 11, 7, 10, 34, tzinfo=timezone.utc), 'Asia/Ho_Chi_Minh', [
            {'now': '2026-11-07T15:00:00Z', 'expected': '17:34', 'titleIncludes': 'GMT+7',
             'advance': '2026-11-07T17:01:00Z', 'afterAdvance': '07 Nov 2026, 17:34'},
            {'now': '2027-11-07T10:00:00Z', 'expected': '07 Nov 2026, 17:34'}])

    @unittest.skipUnless(shutil.which('node'), 'Node.js is optional for offline JavaScript checks')
    def test_day_comparison_uses_browser_timezone_across_utc_year_boundary(self):
        self.check_browser(datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc), 'America/Los_Angeles', [
            {'now': '2025-12-31T22:00:00Z', 'expected': '16:30', 'titleIncludes': '2025',
             'advance': '2026-01-01T08:01:00Z', 'afterAdvance': '31 Dec 2025, 16:30'}])

    @unittest.skipUnless(shutil.which('node'), 'Node.js is optional for offline JavaScript checks')
    def test_daylight_saving_does_not_turn_timestamp_into_a_running_clock(self):
        self.check_browser(datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc), 'America/New_York', [
            {'now': '2026-11-01T05:45:00Z', 'expected': '01:30',
             'advance': '2026-11-01T07:45:00Z', 'afterAdvance': '01:30'}])
