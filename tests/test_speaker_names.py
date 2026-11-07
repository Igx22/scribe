"""Name evidence, fixed voices, cross-chunk resolution, caching, and final outputs."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import scribe as app


class SpeakerNameTests(unittest.TestCase):
    def setUp(self):
        metadata = patch.object(app, "extract_report_metadata", return_value={"topic": "Test conversation.", "roles": {}})
        metadata.start()
        self.addCleanup(metadata.stop)

    def turn(self, start, speaker, text):
        return {"start": start, "end": start + 1, "speaker": speaker, "text": text}

    def claim(self, speaker, name, *evidence, kind="self_introduction", name_type="human_name"):
        return {"speaker_id": speaker, "name": name, "name_type": name_type, "evidence_kind": kind,
                "evidence": [{"anchor_id": i, "quote": quote} for i, quote in evidence]}

    def fuse(self, turns, names, cloud=None, corrected=None, seen=None):
        chunks = [{"index": 0, "start": 0, "end": 60,
                   "text": cloud or " ".join(t["text"] for t in turns)}]
        response = {"turns": [{"id": i, "text": (corrected or {}).get(i, t["text"])}
                              for i, t in enumerate(turns)],
                    "unassigned_text": "Unplaced speech.", "speaker_names": names}
        def reply(key, model, effort, prompt, data, **kwargs):
            if seen is not None:
                seen.append(json.loads(data))
            return json.dumps(response)
        with tempfile.TemporaryDirectory() as tmp:
            return app.fuse_transcripts(chunks, turns, Path(tmp), "key", "model", "medium",
                                        call=reply)

    def test_two_person_reciprocal_address_needs_no_self_introductions(self):
        turns = [self.turn(0, 1, "Bob, please send the report."),
                 self.turn(2, 2, "Alice, thanks. I'll send it now.")]
        evidence = [(0, turns[0]["text"]), (1, turns[1]["text"])]
        seen = []
        fused, _ = self.fuse(turns, [self.claim("A", "Alice", *evidence, kind="address_response"),
                                   self.claim("B", "Bob", *evidence, kind="address_response")], seen=seen)
        self.assertEqual([t["speaker_name"] for t in fused], ["Alice", "Bob"])
        self.assertEqual(seen[0]["speaker_context"], {"speaker_ids": ["A", "B"],
            "observed_speaker_count": 2, "has_unattributed_speech": False})
        self.assertEqual(seen[0]["established_speaker_names"], {})

    def test_neutral_nickname_is_allowed_when_no_human_name_is_established(self):
        turns = [self.turn(0, 1, "Call me Rocket.")]
        nickname = self.claim("A", "Rocket", (0, "Call me Rocket."), name_type="nickname")
        fused, _ = self.fuse(turns, [nickname])
        self.assertEqual(fused[0]["speaker_name"], "Rocket")
        turns.append(self.turn(2, 1, "My name is Bob."))
        human = self.claim("A", "Bob", (1, "My name is Bob."))
        fused, _ = self.fuse(turns, [nickname, human])
        self.assertEqual([t["speaker_name"] for t in fused], ["Bob", "Bob"])
        turns.append(self.turn(4, 1, "Call me Rocket."))
        later_nickname = self.claim("A", "Rocket", (2, "Call me Rocket."),
                                    kind="self_correction", name_type="nickname")
        fused, _ = self.fuse(turns, [nickname, human, later_nickname])
        self.assertEqual([t["speaker_name"] for t in fused], ["Bob"] * 3)

    def test_whole_recording_roster_includes_a_later_third_voice_and_unknown_speech(self):
        turns = [self.turn(0, 1, "Bob, please send the report."),
                 self.turn(2, 2, "Alice, I'll send it now."), self.turn(22, 3, "Can I help?"),
                 self.turn(24, None, "Overlapping speech.")]
        chunks = [{"index": i, "start": i * 10, "end": (i + 1) * 10, "text": "Dialogue."}
                  for i in range(3)]
        seen = []
        def reply(key, model, effort, prompt, data, **kwargs):
            payload = json.loads(data); seen.append(payload)
            return json.dumps({"turns": [{"id": a["id"], "text": a["text"]}
                                         for a in payload["source_b_fixed_anchors"]],
                               "unassigned_text": "", "speaker_names": []})
        with tempfile.TemporaryDirectory() as tmp:
            fused, _ = app.fuse_transcripts(chunks, turns, Path(tmp), "k", "m", "medium", call=reply)
        self.assertEqual(len(seen), 3)
        for payload in seen:
            self.assertEqual(payload["speaker_context"], {"speaker_ids": ["A", "B", "C"],
                "observed_speaker_count": 3, "has_unattributed_speech": True})
        self.assertTrue(all("speaker_name" not in t for t in fused))

    def test_three_person_address_requires_the_target_voice_in_evidence(self):
        turns = [self.turn(0, 1, "Bob, please send the report."),
                 self.turn(2, 3, "I'll check the chart."), self.turn(4, 2, "I'll send the report now.")]
        valid = self.claim("B", "Bob", (0, turns[0]["text"]), (2, turns[2]["text"]), kind="address_response")
        fused, _ = self.fuse(turns, [valid])
        self.assertEqual([t.get("speaker_name") for t in fused], [None, None, "Bob"])
        invalid = self.claim("B", "Bob", (0, turns[0]["text"]), (1, turns[1]["text"]), kind="address_response")
        fused, _ = self.fuse(turns, [invalid])
        self.assertTrue(all("speaker_name" not in t for t in fused))

    def test_self_introductions_apply_to_earlier_turns_without_changing_voices(self):
        turns = [self.turn(0, 1, "Hello."), self.turn(2, 2, "I'm Bob."),
                 self.turn(4, 1, "My name is Alice."), self.turn(6, 3, "Let's start.")]
        original = copy.deepcopy(turns)
        fused, extra = self.fuse(turns, [self.claim("A", "Alice", (2, "My name is Alice.")),
                                       self.claim("B", "Bob", (1, "I'm Bob."))])
        self.assertEqual(turns, original)
        self.assertEqual([(t["speaker"], t["start"], t["end"]) for t in fused],
                         [(t["speaker"], t["start"], t["end"]) for t in turns])
        self.assertEqual([t.get("speaker_name") for t in fused], ["Alice", "Bob", "Alice", None])
        log = app.transcript_text(Path("meeting.mkv"), 8, fused, supplements=extra)
        self.assertIn("] Alice\nHello.", log)
        self.assertIn("] Bob\nI'm Bob.", log)
        self.assertIn("] C\nLet's start.", log)
        self.assertIn("A = Alice; B = Bob", log)
        self.assertIn("EXACT TIME AND SPEAKER UNRESOLVED", log)

    def test_shared_names_keep_distinct_ids_and_unknown_speech_stays_unknown(self):
        turns = [self.turn(0, 1, "I'm Alice."), self.turn(2, 2, "My name is Alice."),
                 self.turn(4, None, "Overlapping speech.")]
        fused, _ = self.fuse(turns, [self.claim("A", "Alice", (0, "I'm Alice.")),
                                   self.claim("B", "Alice", (1, "My name is Alice."))])
        log = app.transcript_text(Path("meeting.mkv"), 6, fused)
        self.assertIn("] Alice (A)\n", log)
        self.assertIn("] Alice (B)\n", log)
        self.assertIn("] UNKNOWN SPEAKER\n", log)

    def test_cross_boundary_address_and_confirmation_reuse_cache(self):
        turns = [self.turn(0, 2, "Hello."), self.turn(8, 1, "Bob, can you introduce yourself?"),
                 self.turn(10, 2, "Yes, I'm Bob."), self.turn(22, 2, "Let's proceed.")]
        chunks = [{"index": i, "start": i * 10, "end": (i + 1) * 10, "text": "Dialogue."}
                  for i in range(3)]
        calls = []
        def fake(key, model, effort, prompt, data, **kwargs):
            payload = json.loads(data)
            calls.append(payload)
            primary = payload["source_b_fixed_anchors"]
            claims = [self.claim("B", "Bob", (1, "Bob, can you introduce yourself?"),
                                 (2, "Yes, I'm Bob."), kind="address_response")] if primary[0]["id"] == 0 else []
            return json.dumps({"turns": [{"id": a["id"], "text": a["text"]} for a in primary],
                               "unassigned_text": "", "speaker_names": claims})
        with tempfile.TemporaryDirectory() as tmp:
            for _ in range(2):
                fused, _ = app.fuse_transcripts(chunks, turns, Path(tmp), "k", "m", "medium", call=fake)
                self.assertEqual([t.get("speaker_name") for t in fused], ["Bob", None, "Bob", "Bob"])
        self.assertEqual(len(calls), 3)
        self.assertIn(2, [a["id"] for a in calls[0]["source_b_context_anchors"]])
        self.assertEqual(calls[1]["established_speaker_names"], {"B": "Bob"})

    def test_conflicts_keep_letters_unless_a_later_explicit_correction_resolves_them(self):
        turns = [self.turn(0, 1, "I'm Alice."), self.turn(2, 1, "Actually, my name is Bob.")]
        first = self.claim("A", "Alice", (0, "I'm Alice."))
        second = self.claim("A", "Bob", (1, "Actually, my name is Bob."))
        fused, _ = self.fuse(turns, [first, second])
        self.assertNotIn("speaker_name", fused[0])
        second["evidence_kind"] = "self_correction"
        fused, _ = self.fuse(turns, [first, second])
        self.assertEqual([t["speaker_name"] for t in fused], ["Bob", "Bob"])
        turns.append(self.turn(4, 1, "Again, I'm Bob."))
        later = self.claim("A", "Bob", (2, "Again, I'm Bob."))
        fused, _ = self.fuse(turns, [first, second, later])
        self.assertEqual([t["speaker_name"] for t in fused], ["Bob"] * 3)
        turns.append(self.turn(6, 1, "I'm Alice."))
        conflict = self.claim("A", "Alice", (3, "I'm Alice."))
        fused, _ = self.fuse(turns, [first, second, later, conflict])
        self.assertTrue(all("speaker_name" not in t for t in fused))

    def test_unsupported_evidence_does_not_discard_a_usable_fusion(self):
        turns = [self.turn(0, 1, "Bob, are you ready?"), self.turn(2, 2, "Yes."),
                 self.turn(4, None, "I'm Alice."),
                 self.turn(6, 1, "[speaker uncertain: I'm Alice.]"),
                 self.turn(8, 1, "[low-confidence speech: I'm Alice.]")]
        bad = [self.claim("Z", "Alice", (0, "Bob, are you ready?")),
               self.claim("UNKNOWN SPEAKER", "Alice", (2, "I'm Alice.")),
               self.claim("A", "Alice", (999, "I'm Alice.")),
               self.claim("A", "Alice", (0, "I'm Alice.")),
               self.claim("A", "Alice\nInjected header", (0, "Bob, are you ready?")),
               self.claim("B", "Bob", (0, "Bob, are you ready?"), kind="address_response"),
               self.claim("A", "Alice", (2, "I'm Alice.")),
               self.claim("A", "Alice", (3, "I'm Alice.")),
               self.claim("A", "Alice", (4, "I'm Alice."))]
        fused, _ = self.fuse(turns, bad)
        self.assertTrue(all("speaker_name" not in t for t in fused))
        self.assertEqual([t["text"] for t in fused], [t["text"] for t in turns])

    def test_corrected_evidence_requires_support_in_the_cloud_source(self):
        turns = [self.turn(0, 1, "I'm Alise.")]
        claim = self.claim("A", "Alice", (0, "I'm Alice."))
        fused, _ = self.fuse(turns, [claim], cloud="I'm Alice.", corrected={0: "I'm Alice."})
        self.assertEqual(fused[0]["speaker_name"], "Alice")
        fused, _ = self.fuse(turns, [claim], cloud="I'm Alise.", corrected={0: "I'm Alice."})
        self.assertNotIn("speaker_name", fused[0])

    def test_confirmed_introduction_requires_the_named_persons_reply(self):
        turns = [self.turn(0, 1, "I'm Alice, and this is Bob."),
                 self.turn(2, 2, "Yes, I'm Bob.")]
        name = self.claim("B", "Bob", (0, "I'm Alice, and this is Bob."),
                          (1, "Yes, I'm Bob."), kind="confirmed_introduction")
        fused, _ = self.fuse(turns, [name])
        self.assertEqual(fused[1]["speaker_name"], "Bob")
        name["evidence"] = name["evidence"][:1]
        fused, _ = self.fuse(turns, [name])
        self.assertNotIn("speaker_name", fused[1])

    def test_names_reach_saved_log_and_summary_with_one_fusion_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "meeting.mkv"; source.write_bytes(b"input")
            args = app.build_parser().parse_args(["--transcription-model", app.COMBINED_MODE, "--output-dir", str(root / "data"),
                                                 "--cache-dir", str(root / "cache"), "--report-tabs", "1"])
            turns = [self.turn(0, 1, "I'm Alice."), self.turn(2, 2, "I'm Bob.")]
            local = {"duration": 4, "turns": turns, "voices": [
                {"start": t["start"], "end": t["end"], "speaker": t["speaker"]} for t in turns]}
            chunks = [{"index": 0, "start": 0, "end": 4, "text": "I'm Alice. I'm Bob."}]
            response = {"turns": [{"id": i, "text": t["text"]} for i, t in enumerate(turns)],
                        "unassigned_text": "", "speaker_names": [
                            self.claim("A", "Alice", (0, "I'm Alice.")),
                            self.claim("B", "Bob", (1, "I'm Bob."))]}
            with patch.object(app, "extract_audio"), patch.object(app, "local_recognition", return_value=local), \
                    patch.object(app, "transcribe_gpt", return_value=chunks), \
                    patch.object(app, "api_request", return_value=json.dumps(response)) as fusion, \
                    patch.object(app, "summarize", return_value="Alice and Bob discussed the plan.") as summary:
                app.process_file(source, args, "key")
                log, summary_path = app.output_paths(source, args.output_dir)
                self.assertIn("] Alice\n", log.read_text())
                self.assertIn("] Bob\n", summary.call_args.args[0])
                self.assertIn("Alice and Bob", summary_path.read_text())
                app.process_file(source, args, "key")
                fusion.assert_called_once(); summary.assert_called_once()
            schema = fusion.call_args.kwargs["schema"]
            self.assertIn("speaker_names", schema["required"])
            self.assertFalse(schema["properties"]["speaker_names"]["items"]["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
