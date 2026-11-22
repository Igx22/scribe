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
        self.assertEqual(client.call_args.args[0]["extractor_args"]["youtube"]["comment_sort"], ["new"])
        self.assertEqual(status, "complete")
        self.assertEqual(comments, [row("one"), {**row("two", "one", "<tag>\nтекст"), "published": "2 days ago"}])

    def test_top_requests_only_100_parents_in_youtube_order(self):
        entries = [row(str(i), text=f"{i}: <original>\n🙂") for i in reversed(range(102))]
        with patch("yt_dlp.YoutubeDL") as client:
            downloader = client.return_value.__enter__.return_value
            downloader.extract_info.return_value = {"id": VIDEO, "comments": entries, "comment_count": len(entries)}
            status, comments = app.media_input.fetch_youtube_comments(
                VIDEO, SimpleNamespace(cookies=None, cookies_from_browser=None), Mock(), top=True)
        downloader.extract_info.assert_called_once_with(app.media_input.watch_url(VIDEO), download=False)
        options = client.call_args.args[0]["extractor_args"]["youtube"]
        self.assertEqual(options["comment_sort"], ["top"])
        self.assertEqual(options["max_comments"], ["100", "100", "0", "0"])
        self.assertEqual((status, comments), ("complete", entries[:100]))

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

    def test_ranked_snapshot_is_independent_and_cannot_replace_full_discussion(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            args = SimpleNamespace(force=False, summary_only=True)
            full_rows = [row("new"), row("reply", "new"), row("popular")]
            top_rows = [row("popular"), row("new")]
            with patch.object(app.media_input, "fetch_youtube_comments",
                              side_effect=[("complete", full_rows), ("complete", top_rows)]) as fetch:
                full = app.youtube_comments_snapshot(cache, VIDEO, args)
                top = app.youtube_comments_snapshot(cache, VIDEO, args, top=True)
                self.assertEqual(full["comments"], full_rows)
                self.assertEqual(top["comments"], top_rows)
                self.assertEqual(app.youtube_comments_snapshot(cache, VIDEO, args), full)
                self.assertEqual(app.youtube_comments_snapshot(cache, VIDEO, args, top=True), top)
                self.assertFalse(app.valid_comment_snapshot(full, VIDEO, top=True))
            self.assertEqual([call.kwargs["top"] for call in fetch.call_args_list], [False, True])


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
                                  best_comments=[{"comment_id": "a", "author": "@Alice <viewer>", "title": "Experience & detail",
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
        self.assertLess(comments_menu.index('id="tab-comments-5"'), comments_menu.index('id="tab-smartest-comments"'))
        best = report.split('id="panel-smartest-comments"', 1)[1].split("</section>", 1)[0]
        self.assertIn("@Alice &lt;viewer&gt;", best)
        self.assertIn("Experience &amp; detail", best)
        self.assertIn("&lt;equipment&gt;", best)
        self.assertIn('data-original-comment="a" aria-haspopup="dialog" aria-controls="original-comment-dialog"', best)
        self.assertIn('aria-label="Show original comment by @Alice &lt;viewer&gt;"', best)
        self.assertIn('<dialog id="original-comment-dialog" aria-labelledby="original-comment-title">', best)
        self.assertIn('id="original-comment-text" dir="auto" tabindex="0"></div>', best)
        self.assertNotIn("Top &amp;", best)
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
        self.assertIn('id="tab-top-comments"', report)
        self.assertNotIn('id="tab-smartest-comments"', report)
        self.assertNotIn('id="detail-picker"', report)

    def test_ranked_comments_keep_original_text_and_raw_views_have_no_model_labels(self):
        ranked = [row("z", text="A <tag> & line\n" + "🙂 " * 500), row("a", text="Second")]
        top = {"comments": ranked, "status": "complete", "top_level": 2, "replies": 0,
               "captured_at": "2026-11-21T07:13:00+00:00"}
        report = app.summary_html(
            Path("video.webm"), {1: "Video brief"}, transcript="Final words", youtube={"id": VIDEO},
            top_comments=top, comment_filter_models=["GPT-6 Luna Fast · no reasoning"],
            comment_summary_models=["GPT-6 Luna · medium reasoning"])
        menu = report.split('id="comments-options">')[1].split('</div></div>', 1)[0]
        labels = ["Smartest comments", "Top 100 YouTube comments", "Full comments"]
        self.assertEqual(sorted(labels, key=lambda label: menu.index(f'>{label}</span>')), labels)
        self.assertEqual(menu.count('class="comment-option-icon"'), 3)
        self.assertGreater(menu.index('class="menu-footer"'), menu.index('>Full comments</span>'))
        self.assertIn('>Filter</span><span class="processing-badge">GPT-6 Luna Fast · no reasoning', menu)
        self.assertIn('>Summaries</span><span class="processing-badge">GPT-6 Luna · medium reasoning', menu)
        top_panel = report.split('id="panel-top-comments"', 1)[1].split('</section>', 1)[0]
        self.assertEqual(self.comment_elements(top_panel), ['z', 'a'])
        self.assertIn('A &lt;tag&gt; &amp; line\n' + '🙂 ' * 500, top_panel)
        self.assertIn('2 top-level · YouTube order', top_panel)
        full_panel = report.split('id="panel-full-comments"', 1)[1].split('</section>', 1)[0]
        self.assertNotIn('processing-badge', top_panel + full_panel)

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

    def test_request_local_support_ids_round_trip_to_youtube_ids(self):
        parent = "A-comment-id-that-is-too-long-to-repeat"
        reply = "B-comment-id-that-is-too-long-to-repeat"
        snapshot = {"video_id": VIDEO, "comments": [row(parent), row(reply, parent, "A specific reply.")]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "api_request",
                return_value=self.answer("c2")) as api:
            cache = Path(tmp)
            args = (cache, snapshot, "English", 1, "key", app.COMMENT_SUMMARY_MODEL, "medium")
            digest = app.youtube_comment_digest(*args)
            self.assertEqual(digest[0]["comment_ids"], [reply])
            request = json.loads(api.call_args.args[4])["comments"]
            self.assertEqual([r["id"] for r in request], ["c1", "c2"])
            self.assertEqual(request[1]["parent"], "c1")
            fields = api.call_args.kwargs["schema"]["properties"]["themes"]["items"]["properties"]
            self.assertEqual(fields["comment_ids"]["items"]["enum"], ["c1", "c2"])
            self.assertEqual(digest, app.youtube_comment_digest(*args))
            api.assert_called_once()

    def test_oversize_notes_split_preserves_batch_support_and_resumes_across_levels(self):
        snapshot = {"video_id": VIDEO, "comments": [row(str(i), text="x" * 300) for i in range(5)]}
        seen = []

        def request(_key, _model, _effort, instructions, raw, **_kwargs):
            payload = json.loads(raw)
            if "comments" in payload:
                ids = [item["id"] for item in payload["comments"]]
                seen.append(ids)
                return self.answer(*ids, text="Oversized " + "x" * 300 if len(ids) > 1 else "A point")
            return self.answer(*(note["comment_ids"][0] for note in payload["notes"]))

        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "COMMENT_INPUT_BYTES", 1200), \
                patch.object(app, "api_request", side_effect=request):
            cache = Path(tmp)
            first = app.youtube_comment_digest(cache, snapshot, "English", 1, "key", "model", "medium")
            self.assertEqual(first[0]["comment_ids"], ["0", "1", "2", "3", "4"])
            self.assertEqual(seen, [["0", "1"], ["0"], ["1"], ["2", "3"], ["2"], ["3"], ["4"]])
            calls = len(seen)
            app.youtube_comment_digest(cache, snapshot, "English", 5, "key", "model", "medium")
            self.assertEqual(len(seen), calls)

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
            self.assertEqual([item["comment_id"] for item in result], ["a", "b"])
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

    def test_long_comments_request_detailed_retellings_without_a_length_cap(self):
        source = (
            "I worked at the dock for eight winters. At first, I thought the new ramp had fixed "
            "the problem because loading sped up before dawn. Then a storm changed the current "
            "and we waited two hours for the tug. We kept the ramp, but put back the old signal "
            "bell so the drivers could hear the crew. My impression is that it made the west "
            "dock safer, though I never worked the east dock and cannot compare."
        )
        answer = {"themes": [{"title": "Dock safety", "text": source, "comment_ids": ["dock"],
                             "experience_evidence": "I worked at the dock"}]}
        snapshot = {"video_id": VIDEO, "comments": [row("dock", text=source)]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "api_request", return_value=json.dumps(answer)) as api:
            result = app.youtube_best_comments(Path(tmp), snapshot, "Dock design", "English", "key", "model", "medium")
        self.assertEqual(result[0]["text"], source)
        instructions = " ".join(api.call_args.args[3].lower().split())
        self.assertIn("sequence of events", instructions)
        self.assertIn("reservations, changes of mind, and shifts in tone", instructions)
        self.assertIn("close to the original length", instructions)
        self.assertEqual(json.loads(api.call_args.args[4])["comments"], [{"id": "dock", "text": source}])

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


class CommentFilterTests(unittest.TestCase):
    def test_serialized_utf8_budget_splits_batches_and_keeps_an_oversized_comment(self):
        original = [row("a", text="é" * 18), row("b", text="ё" * 80), row("c", text="я" * 18)]
        snapshot = {"video_id": VIDEO, "comments": original}
        sent = []

        def request(_key, _model, _effort, _prompt, raw, **_kwargs):
            self.assertLessEqual(len(raw.encode("utf-8")), 120)
            sent.extend(json.loads(raw)["comments"].values())
            return '{"1":true}'

        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "COMMENT_FILTER_BATCH_BYTES", 120), \
                patch.object(app, "api_request", side_effect=request) as api:
            selected, stats = app.filter_youtube_comments(Path(tmp), snapshot, "Title", "key")
        self.assertEqual(api.call_count, 2)
        self.assertCountEqual([entry["text"] for entry in sent], [original[0]["text"], original[2]["text"]])
        self.assertEqual(selected, snapshot)
        self.assertEqual(stats, {"kept": 3, "unfiltered": 1})

    def test_filter_uses_luna_fast_and_keeps_omitted_parent_context_for_a_reply(self):
        original = [row("a", text="Parent question?"), row("b", "a", "Concrete reply."),
                    row("c", text="Generic praise")]
        snapshot = {"video_id": VIDEO, "comments": original}
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "api_request",
                return_value='{"1":false,"2":true,"3":false}') as api:
            cache = Path(tmp)
            selected, stats = app.filter_youtube_comments(cache, snapshot, "Title", "key")
            self.assertEqual(stats, {"kept": 1, "unfiltered": 0})
            self.assertEqual(selected["comments"], [{**original[1], "parent_context": "Parent question?"}])
            self.assertEqual(snapshot["comments"], original)
            args, kwargs = api.call_args
            self.assertEqual(args[1:3], ("gpt-6-luna", "none"))
            self.assertEqual(kwargs["service_tier"], "priority")
            self.assertEqual(json.loads(args[4])["comments"]["2"]["parent_context"], "Parent question?")
            self.assertEqual(app.filter_youtube_comments(cache, snapshot, "Title", "key"), (selected, stats))
            api.assert_called_once()

    def test_incomplete_verdict_retains_batch_and_is_retried_instead_of_cached(self):
        snapshot = {"video_id": VIDEO, "comments": [row("a"), row("b")]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "api_request",
                side_effect=['{"1":false}', '{"1":false,"2":true}']):
            cache = Path(tmp)
            kept, stats = app.filter_youtube_comments(cache, snapshot, "Title", "key")
            self.assertEqual(kept, snapshot)
            self.assertEqual(stats, {"kept": 2, "unfiltered": 2})
            self.assertFalse(list(cache.glob("*.json")))
            kept, stats = app.filter_youtube_comments(cache, snapshot, "Title", "key")
            self.assertEqual([row["id"] for row in kept["comments"]], ["b"])
            self.assertEqual(stats, {"kept": 1, "unfiltered": 0})


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

            def answer(_key, model, effort, prompt, raw, **kwargs):
                responses = app.CURRENT_RESPONSES.get()
                if kwargs.get("service_tier") == "priority":
                    self.assertEqual((model, effort), ("gpt-6-luna", "none"))
                    self.assertIn("Excluded reaction", raw)
                    responses.append({"status": "completed", "model": model, "service_tier": "fast",
                                      "reasoning": {"effort": effort}})
                    return '{"1":true,"2":false}'
                self.assertEqual((model, effort), ("gpt-6-luna", "medium"))
                calls.append(prompt)
                self.assertIn("Viewer evidence", raw)
                self.assertNotIn("Excluded reaction", raw)
                if len(calls) == 2:
                    raise app.AppError("Temporary failure.")
                responses.append({"status": "completed", "model": "gpt-6-luna-snapshot",
                                  "service_tier": "default", "reasoning": {"effort": effort}})
                return CommentDigestTests.answer("one", text=f"Discussion answer {len(calls)}")

            def fetch_comments(_video_id, _args, _say, *, top):
                if top:
                    return "complete", [row("top", text="Ranked original")]
                return "complete", [row("one", text="Viewer evidence"), row("two", text="Excluded reaction")]

            with runtime_paths(cache_dir=args.cache_dir), patch.object(app, "load_env"), \
                    patch.object(app.media_input, "obtain_youtube", return_value=(source, {"id": VIDEO})), \
                    patch.object(app.media_input, "fetch_youtube_comments",
                                 side_effect=fetch_comments) as fetch, \
                    patch.object(app, "summarize", side_effect=lambda *a, detail: f"Video detail {detail}") as video, \
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
                self.assertIn("Smartest comments unavailable.", first)
                self.assertIn("Ranked original", first)
                self.assertIn("Viewer evidence", first)
                self.assertIn("Excluded reaction", first)
                self.assertIn("1 of 2 comments retained for review", first)
                self.assertEqual(app.main(regen), 0)
                second = report.read_text()
                self.assertIn("Discussion answer 1", second)
                self.assertIn("Discussion answer 3", second)
                self.assertNotIn("Comment summary unavailable.", second)
                self.assertIn("Relevant firsthand details.", second)
                self.assertIn("GPT-6 Luna Fast · no reasoning", second)
                self.assertIn("GPT-6-luna-snapshot · medium reasoning", second)
                self.assertEqual([call.kwargs["top"] for call in fetch.call_args_list], [False, True])
                audio.assert_not_called()
                self.assertEqual(video.call_count, 2)
            self.assertEqual(["1/10" in p for p in calls], [True, False, False])
            self.assertEqual(log.read_text(), "Hand-edited export.")
