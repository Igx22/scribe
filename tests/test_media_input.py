"""Contracts for explicit media inputs and completed YouTube downloads."""
from contextlib import redirect_stderr
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import scribe as app


ID = "FLoC0dhY4u4"
URL = f"https://www.youtube.com/watch?v={ID}"


class MediaCLITests(unittest.TestCase):
    def test_explicit_formats_do_not_expand_directory_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            data = root / "data"
            data.mkdir()
            paths = [data / f"input.{ext}" for ext in ("mkv", "MP4", "webm")]
            for path in paths:
                path.touch()
            self.assertEqual(app.collect_files([p.name for p in paths], root), paths)
            self.assertEqual(app.collect_files([], root), paths[:1])

    def test_invalid_option_combinations_fail_before_processing(self):
        for flags in (["--youtube", URL, "--offline"], ["--youtube", URL, "--youtube", URL],
                      ["--youtube", URL, "-f", "input.mp4"], ["--youtube", URL, "--input-dir", "."],
                      ["--youtube", URL, "--monitor-dir"], ["--cookies", "cookies.txt"],
                      ["--youtube", URL, "--cookies", "a", "--cookies-from-browser", "brave"]):
            with self.subTest(flags=flags), patch.object(app, "load_env"), \
                    patch.object(app, "process_youtube") as download, patch.object(app, "process_files") as process:
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    app.main(flags)
                download.assert_not_called()
                process.assert_not_called()

    def test_download_source_title_and_link_are_escaped(self):
        transcript = "DETAILED TRANSCRIPT\n\n[00:00] SPEAKER A: Test."
        rendered = app.summary_html(Path("video.webm"), {1: "Summary"}, transcript=transcript,
                                    youtube={"id": ID, "title": 'A <video> & "title"'})
        self.assertIn(f'href="{URL}"', rendered)
        self.assertIn("A &lt;video&gt; &amp; &quot;title&quot;", rendered)
        self.assertNotIn("A <video>", rendered)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        self.args = SimpleNamespace(cookies=None, cookies_from_browser=None)
        self.media = app.media_input
        self.say = Mock()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.output = self.root / "exports"
        self.output.mkdir()
        self.state = self.output / ".scribe-youtube"
        self.state.mkdir()

    def obtain(self, video_id=ID):
        return self.media.obtain_youtube(video_id, self.output, self.state, self.args, say=self.say,
                                         read_json=app.read_json, save_json=app.save_json, digest_file=app.digest_file)

    def downloaded(self, url, stage, say, **credentials):
        source = stage / "video.webm"
        source.write_bytes(b"valid audio and video")
        return {"id": self.media.youtube_id(url), "title": "Clip / test", "channel": "Test channel",
                "upload_date": "20261120",
                "duration": 132, "requested_formats": [{"vcodec": "av1", "url": "https://secret"},
                                                       {"acodec": "opus", "http_headers": {"Cookie": "secret"}}],
                "requested_downloads": [{"filepath": str(source)}]}

    def playable(self, path, duration=None):
        return path.suffix == ".webm" and path.is_file() and path.read_bytes() == b"valid audio and video"

    def test_url_parses_without_youtube_contact(self):
        forms = [URL, URL + "&list=PL123", f"https://youtu.be/{ID}?si=tracking", f"https://m.youtube.com/shorts/{ID}"]
        for url in forms:
            self.assertEqual(self.media.youtube_id(url), ID)
        for url in ("https://www.youtube.com/playlist?list=PL123", f"https://www.youtube.com.bad/watch?v={ID}",
                    URL + f"&v={ID}", f"{URL} {URL}"):
            with self.subTest(url=url), self.assertRaisesRegex(self.media.MediaError, "one YouTube video URL"):
                self.media.youtube_id(url)

    def test_verified_publication_reused_by_id_and_corruption_rejected(self):
        self.args.cookies = self.root / "missing.cookies"
        (self.output / f"{ID}.webm.part").write_bytes(b"partial")
        with patch.object(self.media, "verify_video", side_effect=self.playable), \
                patch.object(self.media, "download_attempt", side_effect=self.downloaded) as download:
            source, metadata = self.obtain()
            self.assertEqual(source.name, f"Clip test [{ID}].webm")
            self.assertEqual(source.read_bytes(), b"valid audio and video")
            self.assertEqual(metadata["streams"], [{"vcodec": "av1"}, {"acodec": "opus"}])
            self.assertEqual(metadata["url"], URL)
            self.assertEqual(metadata["publication_date"], "2026-11-20")
            self.assertEqual(app.read_json(self.state / f"{ID.encode().hex()}.json")["publication_date"],
                             "2026-11-20")
            self.assertEqual(download.call_args.kwargs, {"cookie_file": None, "browser": None})
            renamed = source.with_name(f"New title [{ID}].webm")
            source.rename(renamed)
            self.assertEqual(self.obtain()[0], renamed)
            self.assertEqual(download.call_count, 1)
            renamed.write_bytes(b"corrupt")
            self.assertNotEqual(self.obtain()[0], renamed)
            self.assertEqual(renamed.read_bytes(), b"corrupt")
            other = self.obtain(ID.swapcase())[0]
            self.assertNotEqual(other, source)
            self.assertEqual(download.call_count, 3)
            self.assertEqual(len(list(self.state.glob("*.json"))), 2)
            self.assertFalse(list(self.state.glob("*-*")))

    def test_interrupted_or_unplayable_file_never_published(self):
        with patch.object(self.media, "download_attempt", side_effect=self.downloaded), \
                patch.object(self.media, "verify_video", return_value=False):
            with self.assertRaisesRegex(self.media.MediaError, "readable video and audio"):
                self.obtain()
        self.assertEqual(list(self.output.iterdir()), [self.state])
        self.assertEqual(list(self.state.iterdir()), [])

    def test_selected_cookie_source_read_only_after_sign_in(self):
        with patch.object(self.media, "verify_video", side_effect=self.playable):
            for cookie_file, browser, video_id in ((self.root / "cookies", None, "abcdefghijk"),
                                                   (None, "brave:Profile 1", "bcdefghijkl")):
                self.args.cookies, self.args.cookies_from_browser = cookie_file, browser
                attempts = [self.media.SignInRequired("Use cookies"), self.downloaded]

                def download(*args, **kwargs):
                    result = attempts.pop(0)
                    if isinstance(result, Exception):
                        raise result
                    return result(*args, **kwargs)

                with self.subTest(browser=browser), patch.object(self.media, "download_attempt", side_effect=download) as run:
                    self.obtain(video_id)
                    self.assertEqual([call.kwargs for call in run.call_args_list],
                                     [{"cookie_file": None, "browser": None}, {"cookie_file": cookie_file, "browser": browser}])

    def test_sign_in_with_no_credentials_and_non_authentication_fail_once(self):
        for error, with_browser in ((self.media.SignInRequired("Use cookies"), None),
                                    (self.media.MediaError("HTTP 403"), "brave")):
            self.args.cookies_from_browser = with_browser
            with patch.object(self.media, "download_attempt", side_effect=error) as download:
                with self.assertRaisesRegex(self.media.MediaError, str(error)):
                    self.obtain()
                download.assert_called_once()
                self.assertIsNone(download.call_args.kwargs["browser"])

    def test_extractor_errors_are_classified_and_cookie_values_stay_private(self):
        import sys
        from yt_dlp.cookies import CookieLoadError
        from yt_dlp.utils import DownloadError

        for error, browser, expected in (
            (DownloadError("Sign in to confirm you’re not a bot. secret-value"), None, "requires sign-in"),
            (DownloadError("HTTP Error 403: Forbidden secret-value"), None, "HTTP 403"),
            (DownloadError("Unable to open for writing: '/path/sign-in/403/video.part' secret-value"), None, "Could not write"),
            (DownloadError("No supported JavaScript runtime secret-value"), None, "JavaScript"),
            (DownloadError("supplied cookies are no longer valid secret-value"), "brave", "expired"),
            (DownloadError("This video is private. Sign in secret-value"), "brave", "lacks access"),
            (CookieLoadError("permission denied secret-value"), "brave", "could not read"),
        ):
            with self.subTest(expected=expected), patch("yt_dlp.YoutubeDL") as ydl, \
                    patch.object(self.media, "deno_executable", return_value=Path(sys.executable)), \
                    patch.object(self.media, "ffmpeg_executable", return_value="unused-ffmpeg"):
                ydl.return_value.__enter__.return_value.extract_info.side_effect = error
                with self.assertRaisesRegex(self.media.MediaError, expected) as caught:
                    self.media.download_attempt(URL, self.state, self.say, browser=browser)
                self.assertNotIn("secret-value", str(caught.exception))
                self.assertNotIn("format", ydl.call_args.args[0])
                if browser:
                    self.assertEqual(ydl.call_args.args[0]["cookiesfrombrowser"][0], browser)

    def test_equivalent_url_uses_shared_pipeline_and_opens_only_new_report(self):
        def publish(source, args, key, *, prepare_models):
            self.assertEqual(source.suffix, ".webm")
            self.assertEqual(args.output_dir, self.output)
            self.assertEqual(args.youtube_metadata["id"], ID)
            for path in app.output_paths(source, self.output):
                path.write_text("finished")

        flags = ["--output-dir", str(self.output), "--transcription-model", "gpt-transcribe-online"]
        with patch.object(app, "load_env"), patch.dict(app.os.environ, {}), \
                patch.object(self.media, "verify_video", side_effect=self.playable), \
                patch.object(self.media, "download_attempt", side_effect=self.downloaded) as download, \
                patch.object(app, "process_file", side_effect=publish) as process, \
                patch.object(app.subprocess, "run") as open_report:
            self.assertEqual(app.main(["--youtube", URL + "&list=PL123", *flags]), 0)
            self.assertEqual(app.main(["--youtube", f"https://youtu.be/{ID}", "--cookies", "missing", *flags]), 0)
        download.assert_called_once()
        process.assert_called_once()
        open_report.assert_called_once()
        self.assertEqual(open_report.call_args.args[0][0], "/usr/bin/open")

    def test_concurrent_runs_share_one_verified_download(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        first_started, waiting, release = Event(), Event(), Event()

        def note(message):
            if message.startswith("Waiting for the active YouTube run"):
                waiting.set()

        self.say.side_effect = note

        def download(*args, **kwargs):
            first_started.set()
            if not release.wait(5):
                raise AssertionError("Second request did not start")
            return self.downloaded(*args, **kwargs)

        def run():
            with self.media.youtube_lock(self.output, ID, self.say):
                return self.obtain()[0]

        with patch.object(self.media, "verify_video", side_effect=self.playable), \
                patch.object(self.media, "download_attempt", side_effect=download) as request, \
                ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(run)
            self.assertTrue(first_started.wait(5))
            second = pool.submit(run)
            try:
                self.assertTrue(waiting.wait(5))
            finally:
                release.set()
            self.assertEqual(first.result(timeout=5), second.result(timeout=5))
        request.assert_called_once()

    def test_youtube_header_inference_failure_still_publishes_transcript(self):
        from tests import seed_final
        source = self.output / f"A talk [{ID}].webm"
        source.write_bytes(b"verified media fixture")
        args = app.build_parser().parse_args(["--summary-only", "--report-tabs", "transcript"])
        args.output_dir = self.output
        args.cache_dir = self.root / "cache"
        args.youtube_metadata = {"id": ID, "title": "Title from YouTube", "publication_date": "2026-11-20"}
        seed_final(source, args, "[00:00–00:02] A\nThe final words are still here.")
        with patch.object(app, "extract_report_metadata", side_effect=app.AppError("Topic evidence rejected")), \
                patch.object(self.media, "fetch_youtube_comments", return_value=("empty", [])):
            app.process_file(source, args, "example-key")
        report = app.output_paths(source, self.output)[1].read_text()
        self.assertIn("The final words are still here.", report)
        self.assertIn("Title from YouTube", report)
        self.assertIn(f'href="{URL}"', report)
        self.assertIn("20 November 2026", report)
        self.assertIn("Published on YouTube", report)

    def test_explicit_regeneration_backfills_publication_date_without_redownloading(self):
        source = self.output / f"Old clip [{ID}].webm"
        source.write_bytes(b"verified media")
        manifest = self.state / f"{ID.encode().hex()}.json"
        metadata = {"id": ID, "sha256": app.digest_file(source), "filename": source.name, "media_path": str(source)}
        app.save_json(manifest, metadata)
        self.args.cookies = self.root / "missing.cookies"
        with patch.object(self.media, "download_attempt") as download, patch("yt_dlp.YoutubeDL") as extractor:
            self.assertEqual(self.obtain(), (source, metadata))
            extractor.assert_not_called()
            self.args.summary_only = True
            extract = extractor.return_value.__enter__.return_value.extract_info
            extract.return_value = {"id": ID, "upload_date": "20261120"}
            self.assertEqual(self.obtain()[1]["publication_date"], "2026-11-20")
            self.assertEqual(self.obtain()[1]["publication_date"], "2026-11-20")
        extract.assert_called_once_with(URL, download=False)
        self.assertNotIn("cookiefile", extractor.call_args.args[0])
        self.assertFalse(extractor.call_args.args[0].get("getcomments", False))
        download.assert_not_called()
        self.assertEqual(app.read_json(manifest)["publication_date"], "2026-11-20")

    def test_failed_date_lookup_leaves_verified_media_available(self):
        source = self.output / f"{ID}.webm"
        source.write_bytes(b"verified media")
        manifest = self.state / f"{ID.encode().hex()}.json"
        metadata = {"id": ID, "sha256": app.digest_file(source), "filename": source.name, "media_path": str(source)}
        app.save_json(manifest, metadata)
        self.args.summary_only = True
        with patch.object(self.media, "download_attempt") as download, patch("yt_dlp.YoutubeDL") as extractor:
            extract = extractor.return_value.__enter__.return_value.extract_info
            for result in (OSError("network unavailable"), {"id": ID, "upload_date": "20260229"},
                           {"id": ID.swapcase(), "upload_date": "20261120"}):
                if isinstance(result, Exception):
                    extract.side_effect = result
                else:
                    extract.side_effect = None
                    extract.return_value = result
                self.assertEqual(self.obtain(), (source, metadata))
        self.assertEqual(app.read_json(manifest), metadata)
        download.assert_not_called()

    def test_terminal_cache_miss_does_not_download_for_summary_only(self):
        self.args.summary_only = True
        with patch.object(self.media, "download_attempt") as download:
            with self.assertRaisesRegex(self.media.MediaError, "verified local YouTube download"):
                self.obtain()
        download.assert_not_called()

    def test_corrupted_or_truncated_download_rejected_before_publication(self):
        import subprocess
        source = self.output / "video.webm"
        source.touch()
        for stdout, stderr, return_code in (("out_time_us=70000000\n", "", 0),
                                            ("out_time_us=132000000\n", "corrupt packet", 0),
                                            ("out_time_us=132000000\n", "", 1)):
            result = subprocess.CompletedProcess([], return_code, stdout, stderr)
            with patch.object(self.media, "ffmpeg_executable", return_value="ffmpeg"), \
                    patch.object(self.media.subprocess, "run", return_value=result):
                self.assertFalse(self.media.verify_video(source, 132))

    def test_untracked_media_and_existing_exports_are_preserved(self):
        unrelated = self.output / f"Clip test [{ID}].webm"
        unrelated.write_bytes(b"valid audio and video")
        with patch.object(self.media, "verify_video", side_effect=self.playable), \
                patch.object(self.media, "download_attempt", side_effect=self.downloaded) as download:
            source, _ = self.obtain()
        self.assertNotEqual(source, unrelated)
        self.assertEqual(unrelated.read_bytes(), b"valid audio and video")
        download.assert_called_once()

    def test_netscape_cookie_parse_errors_never_echo_values(self):
        path = self.root / "cookies.txt"
        path.write_text("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t12000.0\tTEST\tsecret-value\n")
        self.assertEqual(self.media.read_cookie_file(path).read(), path.read_text())
        path.write_text(path.read_text() + "malformed secret-value\n")
        with self.assertRaisesRegex(self.media.MediaError, "malformed entry") as caught:
            self.media.read_cookie_file(path)
        self.assertNotIn("secret-value", str(caught.exception))

    def test_progress_has_download_statistics_and_merge_heartbeat(self):
        progress = self.media.DownloadProgress(self.say)
        progress.finished.wait = Mock(side_effect=[False, True])
        progress.stage("YouTube download")
        progress.transfer({"status": "downloading", "downloaded_bytes": 500000, "total_bytes": 1000000,
                           "speed": 250000, "eta": 2})
        progress.heartbeat()
        self.assertIn("0.5 MB (50%)", self.say.call_args.args[0])
        self.assertIn("ETA 2s", self.say.call_args.args[0])
        progress.finished.wait.side_effect = [False, True]
        progress.postprocess({"status": "started", "postprocessor": "Merger"})
        progress.heartbeat()
        self.assertIn("FFmpeg merge · elapsed", self.say.call_args.args[0])


class FFmpegSetupTests(unittest.TestCase):
    def test_compatible_system_ffmpeg_is_remembered_for_limited_path(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            prefix = root / "venv"
            prefix.mkdir()
            binary = root / "ffmpeg"
            binary.write_text('#!/bin/sh\nprintf "ffmpeg version 7.1\\n"\n')
            binary.chmod(0o755)
            with patch.object(app.media_input.sys, "prefix", str(prefix)), patch.dict(os.environ, {"PATH": str(root)}, clear=True):
                self.assertTrue(app.media_input.prepare_ffmpeg())
                self.assertEqual(app.media_input.system_ffmpeg(), str(binary))
                with patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}, clear=True):
                    self.assertEqual(app.media_input.system_ffmpeg(), str(binary))

    def test_older_system_ffmpeg_is_ineligible_and_bundle_is_used(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            binary = root / "ffmpeg"
            binary.write_text('#!/bin/sh\nprintf "ffmpeg version 5.1\\n"\n')
            binary.chmod(0o755)
            with patch.object(app.media_input.sys, "prefix", str(root)), patch.dict(os.environ, {"PATH": str(root)}, clear=True), \
                    patch.object(app.media_input, "bundled_ffmpeg", return_value="/bundle/ffmpeg"):
                self.assertIsNone(app.media_input.system_ffmpeg())
                self.assertTrue(app.media_input.prepare_ffmpeg())
                self.assertFalse((root / ".scribe-ffmpeg").exists())
                self.assertEqual(app.media_input.ffmpeg_executable(), "/bundle/ffmpeg")
