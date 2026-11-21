"""Acquisition, persistence and presentation of public YouTube discussions."""
import json
from html.parser import HTMLParser
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import scribe as app
from tests import runtime_paths, seed_final


VIDEO = "FLoC0dhY4u4"
OTHER = "_EAPUOsb3oQ"


def row(identifier, parent="root", text="Original text"):
    return {"id": identifier, "parent": parent, "author": "@Alice", "text": text}


class ExtractionTests(unittest.TestCase):
    def test_metadata_only_deduplicates_and_preserves_thread_metadata(self):
        entries = [row("one"), {**row("two", "one", "<tag>\nтекст"), "_time_text": "2 days ago"}, row("one")]
        with patch("yt_dlp.YoutubeDL") as client:
            downloader = client.return_value.__enter__.return_value
            downloader.extract_info.return_value = {"id": VIDEO, "comments": entries, "comment_count": 3}
            status, comments = app.media_input.fetch_youtube_comments(
                VIDEO, SimpleNamespace(cookies=None, cookies_from_browser=None), Mock())
        downloader.extract_info.assert_called_once_with(app.media_input.watch_url(VIDEO), download=False)
        self.assertTrue(client.call_args.args[0]["getcomments"])
        self.assertEqual(status, "complete")
        self.assertEqual(comments, [row("one"), {**row("two", "one", "<tag>\nтекст"), "published": "2 days ago"}])

    def test_empty_disabled_interrupted_and_indeterminate_are_distinct(self):
        for fields, expected in (({"comments": [], "comment_count": 0}, "empty"),
                                 ({"comments": None, "comment_count": None}, "disabled"),
                                 ({"comments": None, "comment_count": None}, "unavailable"),
                                 ({"comments": [row("one")], "comment_count": None}, "partial"),
                                 ({"comments": []}, "unavailable"), ({}, "unavailable")):
            with self.subTest(fields=fields), patch("yt_dlp.YoutubeDL") as client:
                def info(*_args, **_kwargs):
                    if expected == "empty":
                        client.call_args.args[0]["logger"].debug("[youtube] Downloading ~0 comments")
                    if expected == "disabled":
                        client.call_args.args[0]["logger"].warning("[youtube] Youtube said: Comments are turned off.")
                    return {"id": VIDEO, **fields}
                client.return_value.__enter__.return_value.extract_info.side_effect = info
                status, _ = app.media_input.fetch_youtube_comments(
                    VIDEO, SimpleNamespace(cookies=None, cookies_from_browser=None), Mock())
                self.assertEqual(status, expected)

    def test_zero_generated_rows_without_youtube_zero_signal_is_indeterminate(self):
        with patch("yt_dlp.YoutubeDL") as client:
            client.return_value.__enter__.return_value.extract_info.return_value = {
                "id": VIDEO, "comments": [], "comment_count": 0}
            result = app.media_input.fetch_youtube_comments(
                VIDEO, SimpleNamespace(cookies=None, cookies_from_browser=None), Mock())
        self.assertEqual(result, ("unavailable", []))

    def test_missing_author_preserves_original_body(self):
        entry = {"id": "one", "parent": "root", "text": "Body"}
        rows, invalid = app.media_input.normalize_youtube_comments([entry])
        self.assertEqual(rows, [{**entry, "author": ""}])
        self.assertFalse(invalid)

    def test_sign_in_retry_uses_only_the_explicit_cookie_source(self):
        with patch("yt_dlp.YoutubeDL") as client:
            downloader = client.return_value.__enter__.return_value

            def extract(*_args, **_kwargs):
                options = client.call_args.args[0]
                if "cookiesfrombrowser" not in options:
                    options["logger"].warning("Youtube said: Sign in to see comments.")
                    return {"id": VIDEO, "comments": None, "comment_count": None}
                return {"id": VIDEO, "comments": [row("one")], "comment_count": 1}

            downloader.extract_info.side_effect = extract
            result = app.media_input.fetch_youtube_comments(
                VIDEO, SimpleNamespace(cookies=None, cookies_from_browser="brave:Profile 1"), Mock())
        self.assertEqual(result, ("complete", [row("one")]))
        anonymous, authenticated = [call.args[0] for call in client.call_args_list]
        self.assertNotIn("cookiesfrombrowser", anonymous)
        self.assertEqual(authenticated["cookiesfrombrowser"][:2], ("brave", "Profile 1"))


class SnapshotTests(unittest.TestCase):
    def test_failed_pointer_publication_still_returns_the_fetched_discussion(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            pointer = cache / f"youtube.comments.{VIDEO.encode().hex()}.selected.json"
            pointer.mkdir()
            args = SimpleNamespace(force=False, summary_only=True)
            with patch.object(app.media_input, "fetch_youtube_comments", return_value=("complete", [row("one")])):
                snapshot = app.youtube_comments_snapshot(cache, VIDEO, args)
            self.assertEqual(snapshot["comments"], [row("one")])
            self.assertTrue(pointer.is_dir())

    def test_cache_reuse_refresh_and_validation_are_scoped_by_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            args = SimpleNamespace(force=False, summary_only=False)
            with patch.object(app.media_input, "fetch_youtube_comments",
                              side_effect=[("complete", [row("one")]), ("complete", [row("other")]),
                                           ("partial", [row("incomplete")]), ("empty", [])]) as fetch:
                first = app.youtube_comments_snapshot(cache, VIDEO, args)
                other = app.youtube_comments_snapshot(cache, OTHER, args)
                args.summary_only = args.force = True
                self.assertEqual(first, app.youtube_comments_snapshot(cache, VIDEO, args))
                args.summary_only = False
                stale = app.youtube_comments_snapshot(cache, VIDEO, args)
                self.assertEqual(stale["comments"], first["comments"])
                self.assertTrue(stale["refresh_failed"])
                args.force = False
                self.assertEqual(other, app.youtube_comments_snapshot(cache, OTHER, args))
                path = next(cache.glob(f"youtube.comments.{VIDEO.encode().hex()}.selected.json"))
                pointer = json.loads(path.read_text())
                (cache / pointer["file"]).write_text("{}")
                self.assertEqual(app.youtube_comments_snapshot(cache, VIDEO, args)["status"], "empty")
            self.assertEqual(fetch.call_count, 4)


class CommentRenderingTests(unittest.TestCase):
    def test_comments_menu_has_its_own_levels_and_one_escaped_raw_view(self):
        rows = [row("a", text="Top & <markup>\n🙂"), row("b", "a", "Same reply"),
                row("c", "b", "Same reply"), row("orphan", "missing", "Last reply")]
        discussion = {"comments": rows, "status": "partial", "top_level": 1, "replies": 3,
                      "captured_at": "2026-11-21T07:13:00+00:00"}
        report = app.summary_html(Path("video.webm"), {1: "Video brief", 5: "Video expanded"},
                                  transcript="Final words", youtube={"id": VIDEO}, discussion=discussion,
                                  comment_digests={1: [{"title": "", "text": "Brief discussion"}],
                                                   5: [{"title": "Theme", "text": "Expanded <discussion>"}]},
                                  best_comments=[{"author": "@Alice <viewer>", "title": "Experience & detail",
                                                  "text": "An account of working with <equipment>."}])
        summary = report.split('id="panel-1"', 1)[1].split('</section>', 1)[0]
        brief = report.split('id="panel-comments-1"', 1)[1].split('</section>', 1)[0]
        expanded = report.split('id="panel-comments-5"', 1)[1].split('</section>', 1)[0]
        self.assertIn("Video brief", summary)
        self.assertNotIn("Brief discussion", summary)
        self.assertIn("Brief discussion", brief)
        self.assertNotIn("Video brief", brief)
        self.assertIn("Expanded &lt;discussion&gt;", expanded)
        self.assertLess(report.index('id="detail-picker"'), report.index('id="comments-picker"'))
        self.assertLess(report.index('id="comments-picker"'), report.index('id="transcript-picker"'))
        comments_menu = report.split('id="comments-options">')[1].split('</div></div>', 1)[0]
        self.assertLess(comments_menu.index('id="tab-comments-1"'), comments_menu.index('id="tab-comments-5"'))
        self.assertLess(comments_menu.index('id="tab-comments-5"'), comments_menu.index('id="tab-best-comments"'))
        self.assertLess(comments_menu.index('id="tab-best-comments"'), comments_menu.index('id="tab-full-comments"'))
        best = report.split('id="panel-best-comments"', 1)[1].split("</section>", 1)[0]
        self.assertIn("@Alice &lt;viewer&gt;", best)
        self.assertIn("Experience &amp; detail", best)
        self.assertIn("&lt;equipment&gt;", best)
        self.assertNotIn("Same reply", best)
        transcript_menu = report.split('id="transcript-options">')[1].split('</div></div>', 1)[0]
        self.assertNotIn('id="tab-full-comments"', transcript_menu)
        self.assertEqual(report.count('id="panel-full-comments"'), 1)
        self.assertIn('data-choice-label="Full comments"', report)
        self.assertEqual(report.count("Top &amp; &lt;markup&gt;\n🙂"), 1)
        self.assertEqual(report.count("Same reply"), 2)
        self.assertIn("Parent comment unavailable", report)
        self.assertIn("Partial discussion", report)
        for html_tag, record in zip(self.comment_elements(report), rows, strict=True):
            self.assertEqual(html_tag, record["id"])

    def test_youtube_transcript_only_has_full_comments_and_no_ai_levels(self):
        report = app.summary_html(Path("video.webm"), {}, transcript="Final words", youtube={"id": VIDEO})
        self.assertIn('id="comments-choice-description">Full comments</span>', report)
        self.assertIn('id="panel-full-comments"', report)
        self.assertNotIn('id="tab-comments-1"', report)
        self.assertNotIn('id="tab-best-comments"', report)
        self.assertNotIn('id="detail-picker"', report)

    @staticmethod
    def comment_elements(report):
        class Elements(HTMLParser):
            def handle_starttag(self, tag, attrs):
                if tag == "li" and (identifier := dict(attrs).get("data-comment-id")):
                    self.ids.append(identifier)
        elements = Elements()
        elements.ids = []
        elements.feed(report)
        return elements.ids


class CommentDigestTests(unittest.TestCase):
    @staticmethod
    def answer(*ids, text="Supported viewpoint."):
        return json.dumps({"themes": [{"title": "", "text": text, "comment_ids": list(ids)}]})

    def test_detail_language_and_source_identity_drive_comment_cache(self):
        snapshot = {"video_id": VIDEO, "comments": [row("a"), row("b", "a")], "status": "complete"}
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "api_request", return_value=self.answer("a")) as api:
            cache = Path(tmp)
            first = app.youtube_comment_digest(cache, snapshot, "Russian", 3, "key", "model", "medium")
            args = api.call_args.args
            self.assertIn("Russian", args[3])
            self.assertIn("3/10", args[3])
            self.assertEqual([r["id"] for r in json.loads(args[4])["comments"]], ["a", "b"])
            snapshot["captured_at"] = "new time"
            self.assertEqual(first, app.youtube_comment_digest(cache, snapshot, "Russian", 3, "key", "model", "medium"))
            self.assertEqual(api.call_count, 1)
            app.youtube_comment_digest(cache, snapshot, "Russian", 5, "key", "model", "medium")
            snapshot["comments"][1]["text"] += " changed"
            app.youtube_comment_digest(cache, snapshot, "Russian", 3, "key", "model", "medium")
            self.assertEqual(api.call_count, 3)

    def test_oversized_reply_is_covered_and_successful_notes_resume(self):
        text = "first-" + "ё" * 1500 + "-last"
        snapshot = {"video_id": VIDEO, "comments": [row("a", text="Parent"), row("b", "a", text)]}
        inputs = []

        def request(_key, _model, _effort, instructions, prompt_input, **_kwargs):
            payload = json.loads(prompt_input)
            self.assertLessEqual(len(prompt_input.encode()), 1200)
            if "comments" in payload:
                inputs.append(payload)
                return self.answer(payload["comments"][-1]["id"])
            return self.answer(payload["notes"][-1]["comment_ids"][0])

        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "COMMENT_INPUT_BYTES", 1200), \
                patch.object(app, "api_request", side_effect=request):
            cache = Path(tmp)
            app.youtube_comment_digest(cache, snapshot, "English", 1, "key", "model", "medium")
            self.assertGreater(len(inputs), 2)
            self.assertEqual("".join(r["text"] for p in inputs for r in p["comments"] if r["id"] == "b"), text)
            self.assertTrue(any(p.get("parent_context") for p in inputs))
            count = len(inputs)
            app.youtube_comment_digest(cache, snapshot, "English", 5, "key", "model", "medium")
            self.assertEqual(len(inputs), count)

    def test_fabricated_ids_do_not_enter_cache(self):
        snapshot = {"video_id": VIDEO, "comments": [row("a")]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "api_request", return_value=self.answer("invented")):
            with self.assertRaisesRegex(app.AppError, "support"):
                app.youtube_comment_digest(Path(tmp), snapshot, "English", 1, "key", "model", "medium")
            self.assertFalse(list(Path(tmp).glob("*.json")))

    def test_empty_reduction_cannot_silently_erase_successful_reviewed_batches(self):
        snapshot = {"video_id": VIDEO,
                    "comments": [row(str(i), text="Large comment " + "x" * 550) for i in range(10)]}
        seen = []

        def answer(_key, _model, _effort, _prompt, raw, **_kwargs):
            payload = json.loads(raw)
            if "notes" in payload:
                return '{"themes":[]}'
            seen.extend(row["id"] for row in payload["comments"])
            return self.answer(payload["comments"][0]["id"], text="Specific discussion " + "x" * 150)

        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "COMMENT_INPUT_BYTES", 1200), \
                patch.object(app, "api_request", side_effect=answer):
            cache = Path(tmp)
            with self.assertRaisesRegex(app.AppError, "discarded all"):
                app.youtube_comment_digest(cache, snapshot, "English", 1, "key", "model", "medium")
            self.assertEqual(seen, [str(i) for i in range(10)])
            self.assertEqual(len(list(cache.glob("youtube.comment-notes.*.json"))), 10)
            self.assertFalse(list(cache.glob("youtube.comment-summary.*.json")))
            with self.assertRaisesRegex(app.AppError, "discarded all"):
                app.youtube_comment_digest(cache, snapshot, "English", 1, "key", "model", "medium")
            self.assertEqual(len(seen), 10)


class BestCommentsTests(unittest.TestCase):
    def test_rank_uses_own_words_and_keeps_snapshot_order_on_ties(self):
        comments = [row("first", text="example " * 70), row("longest", text="example " * 90),
                    row("second", "first", "example " * 70), row("below-cutoff", text="example " * 70)]
        comments.extend(row(str(i), text="example " * 59 + "🙂 " * 100) for i in range(5))
        self.assertEqual([item["id"] for item in app.best_comment_candidates(comments)], ["longest", "first", "second"])
        self.assertEqual(app.best_comment_candidates(comments[4:]), [])

    def test_experience_selection_uses_best_candidates_context_order_and_cache(self):
        phrase_a = "I have lived here for seven years."
        phrase_b = "I worked with the equipment for a decade."
        comments = [{**row("a", "parent", phrase_a + " observation" * 70), "author": "@resident"},
                    {**row("b", text=phrase_b + " example" * 65), "author": "@operator"},
                    row("parent", text="This is what the resident replied to.")]
        comments.extend(row(str(i), text="lower ranked " * 16) for i in range(2))
        snapshot = {"video_id": VIDEO, "comments": comments}
        answer = {"themes": [
            {"title": "Field use", "text": "The operator reports working with the equipment for ten years.",
             "comment_ids": ["b"], "experience_evidence": phrase_b},
            {"title": "Local account", "text": "The resident reports seven years of living here.",
             "comment_ids": ["a"], "experience_evidence": phrase_a},
        ]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "api_request", return_value=json.dumps(answer)) as api:
            args = (Path(tmp), snapshot, "The video compares two observations.", "English", "key", "model", "medium")
            result = app.youtube_best_comments(*args)
            self.assertEqual([item["author"] for item in result], ["@resident", "@operator"])
            self.assertEqual(result, app.youtube_best_comments(*args))
            api.assert_called_once()
            request = json.loads(api.call_args.args[4])
            self.assertIn("video compares", request["video_context"])
            self.assertEqual([record["id"] for record in request["comments"]], ["a", "b"])
            self.assertIn("resident replied", request["comments"][0]["parent_context"])
            instructions = " ".join(api.call_args.args[3].lower().split())
            self.assertIn("weight to experience", instructions)
            self.assertIn("practical familiarity", instructions)
            self.assertIn("qualifies without a biographical statement", instructions)
            self.assertIn("concrete insight", instructions)
            self.assertIn("overlooked perspective", instructions)
            fields = api.call_args.kwargs["schema"]["properties"]["themes"]["items"]["required"]
            self.assertIn("experience_evidence", fields)

    def test_parent_evidence_and_fabricated_quotes_are_rejected(self):
        comments = [row("reply", "parent", "This reply describes specific outcomes. " + "example " * 66),
                    row("parent", text="I have worked on this for fifteen years.")]
        for quote in ("I have worked on this for fifteen years.", "I have worked on this for ten years.",
                      ".", "his reply describes", "specific outcomes"):
            model_answer = {"themes": [{"title": "Reply", "text": "Experience claim.",
                                        "comment_ids": ["reply"], "experience_evidence": quote}]}
            with self.subTest(quote=quote), tempfile.TemporaryDirectory() as tmp, \
                    patch.object(app, "api_request", return_value=json.dumps(model_answer)):
                with self.assertRaisesRegex(app.AppError, "invalid experience evidence"):
                    app.youtube_best_comments(Path(tmp), {"video_id": VIDEO, "comments": comments},
                                              "context", "English", "key", "model", "medium")
                self.assertFalse(list(Path(tmp).glob("*.json")))

    def test_short_discussion_makes_no_requests(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "api_request") as api:
            result = app.youtube_best_comments(Path(tmp), {"video_id": VIDEO, "comments": [row("short")]},
                                               "context", "English", "key", "model", "medium")
        self.assertEqual(result, [])
        api.assert_not_called()


class CommentPipelineTests(unittest.TestCase):
    def test_log_only_url_run_caches_comments_without_any_report_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "video.webm"
            source.write_bytes(b"media fixture")
            args = app.build_parser().parse_args(["--output-dir", str(root), "--transcribe-only"])
            args.cache_dir = root / "cache"
            args.youtube_metadata = {"id": VIDEO}
            app.configure_mode(args)
            seed_final(source, args, "Original speech words.")
            with patch.object(app.media_input, "fetch_youtube_comments", return_value=("complete", [row("one")])) as fetch, \
                    patch.object(app, "api_request") as ai:
                app.process_file(source, args, "key")
            fetch.assert_called_once()
            ai.assert_not_called()
            self.assertFalse(app.output_paths(source, root)[1].exists())
            self.assertEqual(len(list(args.cache_dir.glob("*/youtube.comments.*.selected.json"))), 1)

    def test_url_regeneration_reuses_snapshot_recovers_one_depth_and_preserves_edit(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"OPENAI_API_KEY": "test"}, clear=True):
            root = Path(tmp)
            source = root / "video.webm"
            source.write_bytes(b"media fixture")
            args = app.build_parser().parse_args(["--output-dir", str(root)])
            args.cache_dir = root / "cache"
            seed_final(source, args, "Original speech words.")
            log, report = app.output_paths(source, root)
            log.write_text("Hand-edited export.")
            report.write_text("Old report with a single detail.")
            request = ["--youtube", app.media_input.watch_url(VIDEO), "--output-dir", str(root)]
            calls = []

            def answer(_key, _model, _effort, prompt, raw, **_kwargs):
                calls.append(prompt)
                self.assertIn("Viewer evidence", raw)
                if len(calls) == 2:
                    raise app.AppError("Temporary failure.")
                return CommentDigestTests.answer("one", text=f"Discussion answer {len(calls)}")

            with runtime_paths(cache_dir=args.cache_dir), patch.object(app, "load_env"), \
                    patch.object(app.media_input, "obtain_youtube", return_value=(source, {"id": VIDEO})), \
                    patch.object(app.media_input, "fetch_youtube_comments",
                                 return_value=("complete", [row("one", text="Viewer evidence")])) as fetch, \
                    patch.object(app, "summarize", side_effect=lambda *a, detail: f"Video detail {detail}") as video, \
                    patch.object(app, "extract_report_metadata", return_value={}), \
                    patch.object(app, "youtube_best_comments", side_effect=[app.AppError("Best digest failure."),
                                 [{"author": "@Author", "title": "Experience", "text": "Relevant firsthand details."}]]), \
                    patch.object(app, "extract_audio") as audio, patch.object(app, "api_request", side_effect=answer), \
                    patch.object(app.subprocess, "run"):
                self.assertEqual(app.main(request), 0)
                fetch.assert_not_called()
                regen = [*request, "--summary-only", "--report-tabs", "1", "5"]
                self.assertEqual(app.main(regen), 0)
                first = report.read_text()
                self.assertIn("Video detail 5", first)
                self.assertIn("Comment summary unavailable.", first)
                self.assertIn("Best comments unavailable.", first)
                self.assertIn("Viewer evidence", first)
                self.assertEqual(app.main(regen), 0)
                second = report.read_text()
                self.assertIn("Discussion answer 1", second)
                self.assertIn("Discussion answer 3", second)
                self.assertNotIn("Comment summary unavailable.", second)
                self.assertIn("Relevant firsthand details.", second)
                fetch.assert_called_once()
                audio.assert_not_called()
                self.assertEqual(video.call_count, 2)
            self.assertEqual(["1/10" in p for p in calls], [True, False, False])
            self.assertEqual(log.read_text(), "Hand-edited export.")
