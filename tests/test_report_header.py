"""Grounded report topics, fixed participant labels, role evidence, dates, and resume."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import scribe as app


class ReportHeaderTests(unittest.TestCase):
    def log(self):
        return ("DETAILED TRANSCRIPT\nSource file: 2026-09-25 16-55-39.mkv\nDuration: 01:24:05\n\n"
                "[00:00–00:04] Alice\nI'm the product manager. We should plan the deployment.\n\n"
                "[00:04–00:09] Bob\nI'm a platform engineer. Let's check rollback procedures.\n\n"
                "[00:09–00:10] UNKNOWN SPEAKER\nOverlapping speech.\n")

    def response(self):
        return {"topic": "Plan the deployment and rollback procedures.",
                "topic_evidence": [{"turn_id": 0, "quote": "We should plan the deployment."},
                                   {"turn_id": 1, "quote": "Let's check rollback procedures."}],
                "participant_roles": [
                    {"speaker": "Alice", "role": "product manager", "evidence": [
                        {"turn_id": 0, "quote": "I'm the product manager."}]},
                    {"speaker": "Bob", "role": "platform engineer", "evidence": [
                        {"turn_id": 1, "quote": "I'm a platform engineer."}]}]}

    def test_turn_labels_and_unassigned_speech_are_kept_separate(self):
        transcript = self.log() + "\nADDITIONAL SPEECH — EXACT TIME AND SPEAKER UNRESOLVED\nAudio chunk: 00:00–01:00\nExtra words.\n"
        turns = app.report_turns(transcript)
        self.assertEqual(app.report_roster(turns), ["Alice", "Bob"])
        self.assertEqual(turns[-1]["speaker"], "UNKNOWN SPEAKER")
        self.assertEqual(turns[-1]["text"], "Extra words.")
        self.assertNotIn("Extra words", turns[-2]["text"])

    def test_role_citations_keep_supplied_names_without_identifying_people_anew(self):
        turns = app.report_turns(self.log())
        result = app.validate_report_metadata(self.response(), turns, app.report_roster(turns))
        self.assertEqual(result["roles"], [{"speaker": "Alice", "role": "product manager"},
                                          {"speaker": "Bob", "role": "platform engineer"}])
        header = app.report_header(Path("different-name.mkv"), self.log(), {
            "topic": result["topic"], "roles": {row["speaker"]: row["role"] for row in result["roles"]}})
        self.assertEqual(header["participants"], [{"name": "Alice", "role": "product manager"},
                                                 {"name": "Bob", "role": "platform engineer"}])
        self.assertEqual(header["duration"], "1 hr 24 min 5 sec")
        self.assertEqual(header["date"], "25 September 2026 · 16:55")
        self.assertIn("filename", header["date_note"])

    def test_unknown_wrong_voice_uncertain_and_invented_role_evidence_is_ignored(self):
        transcript = self.log() + "\n[00:10–00:13] Alice\n[speaker uncertain: I'm a director.]\n"
        turns = app.report_turns(transcript)
        response = self.response()
        base = response["participant_roles"][0]
        wrong = []
        for speaker in ("Carol", "UNKNOWN SPEAKER", "Bob"):
            wrong.append({**base, "speaker": speaker})
        wrong.extend([
            {**base, "role": "director", "evidence": [{"turn_id": 3, "quote": "I'm a director."}]},
            {**base, "role": "director"},
            {**base, "evidence": [{"turn_id": 0, "quote": "I'm the chief executive."}]},
            {**base, "evidence": [{"turn_id": 999, "quote": "I'm the product manager."}]},
            {**base, "evidence": [{"turn_id": True, "quote": "I'm a platform engineer."}]}])
        response["participant_roles"] = wrong
        self.assertEqual(app.validate_report_metadata(response, turns, app.report_roster(turns))["roles"], [])

    def test_unsupported_topic_or_malformed_metadata_fails_instead_of_publishing(self):
        for result in (None, {}, {**self.response(), "topic": "An invented topic.", "topic_evidence": []},
                       {**self.response(), "topic": "Two\nlines."},
                       {**self.response(), "topic_evidence": [{"turn_id": 0, "quote": "Not in this log."}]}):
            with self.subTest(result=result), self.assertRaises(app.AppError):
                app.validate_report_metadata(result, app.report_turns(self.log()), ["Alice", "Bob"])

    def test_dates_are_never_taken_from_spoken_text_or_filesystem_timestamps(self):
        transcript = "DETAILED TRANSCRIPT\nDuration: 07:05\n\n[00:00–00:01] A\nDate: 2026-09-25\n"
        header = app.report_header(Path("meeting.mkv"), transcript, {})
        self.assertEqual(header["duration"], "7 min 5 sec")
        self.assertEqual(header["date"], "Not recorded")
        self.assertEqual(header["participants"], [{"name": "A", "role": ""}])
        self.assertEqual(header["topic"], "Not established")
        transcript = transcript.replace("Duration: 07:05", "Duration: 07:05\nDate: 2026-11-06 10:30")
        header = app.report_header(Path("2026-09-25 16-55-39.mkv"), transcript, {})
        self.assertEqual(header["date"], "6 November 2026 · 10:30")
        self.assertIn("transcript", header["date_note"])
        for name in ("2026-02-30.mkv", "2026-09-25 24-01-00.mkv", "meeting.mkv"):
            self.assertEqual(app.report_header(Path(name), "", {})["date"], "Not recorded")

    def test_api_only_log_has_duration_but_does_not_invent_participants(self):
        transcript = app.gpt_transcript_text(Path("meeting.mkv"), [
            {"start": 0, "end": 425, "text": "Alice was mentioned; she may not be present."}])
        header = app.report_header(Path("meeting.mkv"), transcript, {})
        self.assertEqual(header["duration"], "7 min 5 sec")
        self.assertEqual(header["participants"], [])
        self.assertEqual(app.report_turns(transcript)[0]["speaker"], "UNKNOWN SPEAKER")

    def test_cached_metadata_is_revalidated_and_force_bypasses_it(self):
        calls = []
        def call(*args, **kwargs):
            calls.append(json.loads(args[4]))
            return json.dumps(self.response())
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            for _ in range(2):
                result = app.extract_report_metadata(self.log(), "key", "model", "medium", cache, call=call)
                self.assertEqual(result["roles"], {"Alice": "product manager", "Bob": "platform engineer"})
            self.assertEqual(len(calls), 1)
            app.extract_report_metadata(self.log(), "key", "model", "medium", cache, force=True, call=call)
            self.assertEqual(len(calls), 2)
            path = next((cache / "report-header").glob("*.json"))
            saved = json.loads(path.read_text()); saved["result"]["topic_evidence"] = []
            app.save_json(path, saved)
            with self.assertRaisesRegex(app.AppError, "unsupported evidence"):
                app.extract_report_metadata(self.log(), "key", "model", "medium", cache, call=call)

    def test_long_log_covers_final_turns_and_conflicting_roles_remain_absent(self):
        transcript = ("[00:00–00:01] Alice\nI'm a product manager. We discussed deployment. " + "word " * 14000 +
                      "\n\n[00:01–00:02] Alice\nI'm a platform engineer. Security was discussed at the end.\n")
        payloads = []
        def call(key, model, effort, prompt, text, **kwargs):
            payload = json.loads(text); payloads.append(payload)
            if prompt == app.REPORT_TOPIC_PROMPT:
                self.assertTrue(any("Security" in topic for topic in payload["topics"]))
                return json.dumps({"topic": "Deployment and security planning."})
            roles = []
            topic = "Deployment discussion."
            evidence = [{"turn_id": payload["turns"][0]["id"], "quote": "word"}]
            for turn in payload["turns"]:
                for role in ("product manager", "platform engineer"):
                    if "I'm a " + role in turn["text"]:
                        quote = "I'm a " + role + "."
                        roles.append({"speaker": "Alice", "role": role, "evidence": [{"turn_id": turn["id"], "quote": quote}]})
                        evidence = [{"turn_id": turn["id"], "quote": quote}]
                if "Security" in turn["text"]:
                    topic = "Security was discussed at the end."
                    evidence = [{"turn_id": turn["id"], "quote": topic}]
            return json.dumps({"topic": topic, "topic_evidence": evidence, "participant_roles": roles})
        with tempfile.TemporaryDirectory() as tmp:
            result = app.extract_report_metadata(transcript, "key", "model", "medium", Path(tmp), call=call)
        self.assertEqual(result["topic"], "Deployment and security planning.")
        self.assertEqual(result["roles"], {})
        self.assertGreater(sum("turns" in payload for payload in payloads), 1)

    def test_header_values_are_escaped_and_fields_keep_the_approved_order(self):
        metadata = {"topic": '<script>alert("topic")</script>',
                    "participants": [{"name": "Alice & Bob", "role": "<img src=x>"}],
                    "duration": "1 hr 24 min", "date": "25 September 2026", "date_note": "Date from recording filename"}
        result = app.summary_html(Path("meeting.mkv"), {1: "Brief.", 5: "Expanded."}, metadata, transcript=self.log())
        self.assertIn("&lt;script&gt;", result)
        self.assertIn("Alice &amp; Bob", result)
        self.assertIn("&lt;img src=x&gt;", result)
        self.assertNotIn("<img", result)
        offsets = [result.index(f"<dt>{field}:</dt>") for field in ("Topic", "Participants", "Duration", "Date")]
        self.assertEqual(offsets, sorted(offsets))

    def test_confirmed_introduction_can_use_neighboring_turns_across_parts(self):
        transcript = ("[00:00–00:01] Alice\nWe discussed deployment. " + "word " * 12000 +
                      "Bob is our platform engineer.\n\n[00:01–00:02] Bob\nYes, that's my role.\n")
        parts = []
        def call(key, model, effort, prompt, text, **kwargs):
            payload = json.loads(text)
            if "topics" in payload:
                return json.dumps({"topic": "Deployment planning."})
            parts.append(payload)
            primary = payload["turns"][0]
            return json.dumps({"topic": "Deployment planning.",
                "topic_evidence": [{"turn_id": primary["id"], "quote": primary["text"][:30].strip()}],
                "participant_roles": [{"speaker": "Bob", "role": "platform engineer", "evidence": [
                    {"turn_id": 0, "quote": "Bob is our platform engineer."},
                    {"turn_id": 1, "quote": "Yes, that's my role."}]}]})
        with tempfile.TemporaryDirectory() as tmp:
            result = app.extract_report_metadata(transcript, "key", "model", "medium", Path(tmp), call=call)
        self.assertGreater(len(parts), 1)
        self.assertTrue(parts[0]["context_turns"])
        self.assertEqual(result["roles"], {"Bob": "platform engineer"})

    def test_metadata_failure_preserves_report_and_reuses_completed_summaries_on_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "meeting.mkv"; source.write_bytes(b"fixture")
            args = app.build_parser().parse_args(["--summary-only", "--report-tabs", "1,5",
                "--output-dir", str(root / "output"), "--cache-dir", str(root / "cache")])
            log, report = app.output_paths(source, args.output_dir)
            app.atomic_write(log, self.log()); app.atomic_write(report, "Reviewed report")
            before = (report.read_bytes(), report.stat().st_mtime_ns)
            with patch.object(app, "summarize", return_value="New summary.") as summaries, \
                    patch.object(app, "extract_report_metadata", side_effect=app.AppError("Invalid topic")):
                with self.assertRaises(app.AppError):
                    app.process_file(source, args, "key")
            self.assertEqual(summaries.call_count, 2)
            self.assertEqual(before, (report.read_bytes(), report.stat().st_mtime_ns))
            with patch.object(app, "summarize") as summaries, patch.object(app, "extract_report_metadata",
                    return_value={"topic": "Deployment planning.", "roles": {"Bob": "platform engineer"}}):
                app.process_file(source, args, "key")
            summaries.assert_not_called()
            self.assertIn("Deployment planning.", report.read_text())
            self.assertIn("platform engineer", report.read_text())

    def test_single_level_html_includes_grounded_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "meeting.mkv"; source.write_bytes(b"fixture")
            args = app.build_parser().parse_args(["--summary-only", "--report-tabs", "1",
                "--output-dir", str(root / "output"), "--cache-dir", str(root / "cache")])
            log, summary = app.output_paths(source, args.output_dir)
            app.atomic_write(log, self.log())
            with patch.object(app, "summarize", return_value="Plain summary."), \
                    patch.object(app, "extract_report_metadata", return_value={"topic": "Deployment planning.", "roles": {}}) as metadata:
                app.process_file(source, args, "key")
            metadata.assert_called_once()
            self.assertEqual(summary.suffix, ".html")
            self.assertIn("Deployment planning.", summary.read_text())
            self.assertIn("Plain summary.", summary.read_text())

    def test_single_summary_survives_header_failure_and_is_reused_on_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "meeting.mkv"; source.write_bytes(b"fixture")
            args = app.build_parser().parse_args(["--summary-only", "--report-tabs", "5",
                "--output-dir", str(root / "output"), "--cache-dir", str(root / "cache")])
            log, report = app.output_paths(source, args.output_dir)
            app.atomic_write(log, self.log()); app.atomic_write(report, "Previous report")
            before = (report.read_bytes(), report.stat().st_mtime_ns)
            with patch.object(app, "summarize", return_value="Completed summary.") as summary, \
                    patch.object(app, "extract_report_metadata", side_effect=app.AppError("header failed")):
                with self.assertRaisesRegex(app.AppError, "header failed"):
                    app.process_file(source, args, "key")
            summary.assert_called_once()
            self.assertEqual(before, (report.read_bytes(), report.stat().st_mtime_ns))
            with patch.object(app, "summarize") as summary, patch.object(app, "extract_report_metadata",
                    return_value={"topic": "Deployment planning.", "roles": {}}):
                app.process_file(source, args, "key")
            summary.assert_not_called()
            self.assertIn("Completed summary.", report.read_text())
            self.assertFalse(report.with_suffix(".md").exists())


if __name__ == "__main__":
    unittest.main()
