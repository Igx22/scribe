"""Native automatic diarization, checked setup, and independent cache migration."""
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import wave

import scribe as app


def wav(path, seconds=4):
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(16000)
        out.writeframes(b"\0\0" * 16000 * seconds)


class NemotronTests(unittest.TestCase):
    def setUp(self):
        final = patch.object(app, "fuse_transcripts", side_effect=lambda chunks, turns, *a, **k: (turns, []))
        final.start()
        self.addCleanup(final.stop)

    def runtime_fixture(self, root, link="libfake.1.dylib", member_data=b"binary fixture"):
        resources = root / "resources"
        archive_path = root / "runtime.tar.gz"
        entries = [{"path": "bin/nemo-speech", "size": len(member_data),
                    "sha256": hashlib.sha256(member_data).hexdigest(), "executable": True},
                   {"path": "lib/libfake.1.dylib", "size": 3,
                    "sha256": hashlib.sha256(b"lib").hexdigest()},
                   {"path": "lib/libfake.dylib", "symlink": "libfake.1.dylib"}]
        with tarfile.open(archive_path, "w:gz") as archive:
            for name, data in (("bin/nemo-speech", member_data), ("lib/libfake.1.dylib", b"lib")):
                member = tarfile.TarInfo("runtime/" + name); member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
            member = tarfile.TarInfo("runtime/lib/libfake.dylib")
            member.type = tarfile.SYMTYPE; member.linkname = link
            archive.addfile(member)
            # Neither an unlisted traversal entry nor a device is extracted.
            member = tarfile.TarInfo("../../outside"); member.size = 3
            archive.addfile(member, io.BytesIO(b"bad"))
        files = [{"path": "diarization/runtime.tar.gz", "size": archive_path.stat().st_size,
                  "sha256": app.digest_file(archive_path), "url": "https://example.test/runtime.tar.gz"}]
        manifest = {"files": files, "diarization": {"runtime": {
            "archive": files[0]["path"], "directory": "diarization/runtime", "archive_root": "runtime",
            "executable": "bin/nemo-speech", "members": entries}}}
        app.save_json(resources / "models-manifest.json", manifest)
        return resources, archive_path, manifest

    def test_setup_downloads_anonymously_and_offline_checks_runtime_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resources, archive, manifest = self.runtime_fixture(root)
            requests = []
            def download(request, **kwargs):
                requests.append(request)
                return io.BytesIO(archive.read_bytes())
            models = root / "models"
            with patch.object(app, "RESOURCE_DIR", resources), \
                    patch.dict(os.environ, {"HF_TOKEN": "secret-fixture"}), \
                    patch.object(app.urllib.request, "urlopen", download):
                app.ensure_models(models)
            self.assertEqual(len(requests), 1)
            self.assertIsNone(requests[0].get_header("Authorization"))
            runtime = models / "diarization/runtime"
            binary = runtime / "bin/nemo-speech"
            self.assertTrue(os.access(binary, os.X_OK))
            self.assertTrue((runtime / "lib/libfake.dylib").is_symlink())
            self.assertFalse((root / "outside").exists())
            before = binary.read_bytes(), binary.stat().st_mtime_ns
            with patch.object(app, "RESOURCE_DIR", resources), \
                    patch.object(app.urllib.request, "urlopen", side_effect=AssertionError("Network forbidden")):
                app.ensure_models(models, offline=True, verify=True)
                self.assertEqual(before, (binary.read_bytes(), binary.stat().st_mtime_ns))
                binary.write_bytes(b"x" * binary.stat().st_size)
                with self.assertRaisesRegex(app.AppError, "runtime is missing or damaged"):
                    app.ensure_models(models, offline=True)
                app.ensure_models(models)  # Repair from the already checked local archive.
            self.assertEqual(binary.read_bytes(), b"binary fixture")
            previous = list(runtime.parent.glob("runtime.previous-*"))
            self.assertEqual(len(previous), 1)
            self.assertEqual((previous[0] / "bin/nemo-speech").read_bytes(), b"x" * len(b"binary fixture"))

    def test_runtime_archive_link_escape_is_rejected_before_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resources, archive, _ = self.runtime_fixture(root, link="../../outside")
            with patch.object(app, "RESOURCE_DIR", resources), \
                    patch.object(app.urllib.request, "urlopen", return_value=io.BytesIO(archive.read_bytes())):
                with self.assertRaisesRegex(app.AppError, "archive link"):
                    app.ensure_models(root / "models")
            self.assertFalse((root / "models/diarization/runtime").exists())
            self.assertFalse((root / "outside").exists())

    def test_runtime_checksum_failure_preserves_existing_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resources, archive, manifest = self.runtime_fixture(root)
            manifest["diarization"]["runtime"]["members"][0]["sha256"] = "0" * 64
            app.save_json(resources / "models-manifest.json", manifest)
            target = root / "models/diarization/runtime"
            target.mkdir(parents=True); (target / "user-note").write_text("preserve")
            with patch.object(app, "RESOURCE_DIR", resources), \
                    patch.object(app.urllib.request, "urlopen", return_value=io.BytesIO(archive.read_bytes())):
                with self.assertRaisesRegex(app.AppError, "runtime SHA-256"):
                    app.ensure_models(root / "models")
            self.assertEqual((target / "user-note").read_text(), "preserve")

    def native_fixture(self, root):
        audio = root / "audio with spaces.wav"
        wav(audio)
        spec = app.model_manifest()["diarization"]
        models = root / "models with spaces"
        binary = models / spec["runtime"]["directory"] / spec["runtime"]["executable"]
        binary.parent.mkdir(parents=True); binary.write_bytes(b"fixture"); binary.chmod(0o755)
        weights = models / spec["model"]
        weights.parent.mkdir(parents=True, exist_ok=True); weights.write_bytes(b"fixture")
        return audio, models

    def native_response(self, payload, seen=None):
        def run(command, **kwargs):
            if seen is not None:
                seen.append((command, kwargs))
            result = Path(command[command.index("--output") + 1])
            result.write_text(json.dumps(payload))
            return subprocess.CompletedProcess(command, 0, "", "")
        return run

    def test_native_command_is_local_automatic_and_retains_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio, models = self.native_fixture(Path(tmp))
            raw = {"segments": [{"start": 2, "end": 3, "speaker": 3},
                                {"start": .5, "end": 2.5, "speaker": 7}]}
            seen = []
            with patch.dict(os.environ, {"HF_TOKEN": "secret", "OPENAI_API_KEY": "secret"}), \
                    patch.object(app, "run_native", self.native_response(raw, seen)), \
                    patch.object(app.urllib.request, "urlopen", side_effect=AssertionError("Network forbidden")):
                intervals = app.diarize(audio, models)
            self.assertEqual(intervals, [{"start": .5, "end": 2.5, "speaker": 1},
                                         {"start": 2., "end": 3., "speaker": 2}])
            cmd, kw = seen[0]
            self.assertEqual(cmd[cmd.index("--model")+1], str((models / app.model_manifest()["diarization"]["model"]).resolve()))
            self.assertIn("v3-offline", cmd); self.assertIn("cpu", cmd)
            self.assertNotIn("--offline", cmd)
            self.assertFalse(any("speakers" in arg for arg in cmd))
            self.assertNotIn("HF_TOKEN", kw["env"]); self.assertNotIn("OPENAI_API_KEY", kw["env"])
            self.assertFalse(Path(cmd[cmd.index("--output")+1]).exists())

    def test_native_silence_and_invalid_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio, models = self.native_fixture(Path(tmp))
            with patch.object(app, "run_native", self.native_response({"segments": []})):
                self.assertEqual(app.diarize(audio, models), [])
            invalid = [None, {}, {"segments": "bad"}, {"segments": [None]}]
            for values in ((-1,1,1), (0,0,1), (0,5,1), (float("nan"),1,1),
                           (0,float("inf"),1), (True,1,1), (0,1,9), (0,1,True)):
                invalid.append({"segments": [dict(zip(("start","end","speaker"), values))]})
            for payload in invalid:
                with self.subTest(payload=payload), patch.object(app, "run_native", self.native_response(payload)):
                    with self.assertRaisesRegex(app.AppError, "invalid"):
                        app.diarize(audio, models)
            with patch.object(app, "run_native", return_value=subprocess.CompletedProcess([], 1, "", "bad weights")):
                with self.assertRaisesRegex(app.AppError, "bad weights"):
                    app.diarize(audio, models)

    def test_old_voice_cache_is_invalidated_while_words_and_new_voices_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "meeting.mkv"; source.write_bytes(b"source")
            audio = root / "audio.wav"; wav(audio)
            args = app.build_parser().parse_args(["--offline", "--transcription-model", "mlx"])
            app.configure_mode(args)
            settings = app.recognition_settings(source, args)
            legacy = {k:v for k,v in settings.items() if k not in ("diarization", "recognizer")}
            legacy["speakers"] = 2
            cache = root / "cache"
            words = [{"start": .5,"end": 1.,"text":" Hello","unclear":False}]
            app.save_json(cache / "words-stage.json", {"settings":legacy,"duration":4,"words":words})
            app.save_json(cache / "voices-stage.json", {"settings":legacy,"intervals":[
                {"start":0,"end":2,"speaker":1},{"start":2,"end":4,"speaker":2}]})
            before = (cache / "words-stage.json").read_bytes()
            with patch.object(app, "diarize", return_value=[{"start":0,"end":4,"speaker":1}]) as voice, \
                    patch.object(app, "recognize") as recognize:
                first = app.local_recognition(audio, cache, settings, args)
                second = app.local_recognition(audio, cache, settings, args)
                voice.assert_called_once_with(audio, args.models_dir, "nemotron"); recognize.assert_not_called()
            self.assertEqual(len({i['speaker'] for i in first['voices']}), 1)
            self.assertEqual(first, second)
            self.assertEqual((cache / "words-stage.json").read_bytes(), before)
            # A voice-engine update needs new voices, but still not new words.
            changed = copy.deepcopy(settings); changed["diarization"]["adapter_version"] += 1
            with patch.object(app, "diarize", return_value=first["voices"]) as voice, \
                    patch.object(app, "recognize") as recognize:
                app.local_recognition(audio, cache, changed, args)
                voice.assert_called_once(); recognize.assert_not_called()
            # A recognition language change must not redo the unchanged voice stage.
            changed["language"] = args.language = "en"
            with patch.object(app, "diarize") as voice, patch.object(app, "recognize", return_value=words) as recognize:
                app.local_recognition(audio, cache, changed, args)
                voice.assert_not_called(); recognize.assert_called_once()
            args.force = True
            with patch.object(app, "diarize", return_value=first["voices"]) as voice, \
                    patch.object(app, "recognize", return_value=words) as recognize:
                app.local_recognition(audio, cache, changed, args)
                voice.assert_called_once(); recognize.assert_called_once()

    def test_previous_api_only_log_resumes_despite_irrelevant_legacy_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "meeting.mkv"; source.write_bytes(b"source")
            args = app.build_parser().parse_args(["--transcription-model", "gpt-transcribe-online", "--summarize-model", "none",
                 "--output-dir", str(root/"out")])
            args.cache_dir = root/"cache"
            chunks=[{"index":0,"start":0,"end":4,"text":"Saved cloud words"}]
            with patch.object(app, "extract_audio"), patch.object(app, "transcribe_gpt", return_value=chunks):
                app.process_file(source,args,"key")
            log,_=app.output_paths(source,args.output_dir)
            before=log.read_bytes(),log.stat().st_mtime_ns
            state_path=next(args.cache_dir.glob("*/outputs/*/state.json"))
            state=app.read_json(state_path)
            state['settings']['speakers']=2
            state['selection']['transcription_model']='gpt-transcribe'
            app.save_json(state_path,state)
            with patch.object(app, "extract_audio") as extract, patch.object(app, "transcribe_gpt") as cloud, \
                    patch.object(app, "diarize") as voice:
                app.process_file(source,args,"key")
                extract.assert_not_called(); cloud.assert_not_called(); voice.assert_not_called()
            self.assertEqual((log.read_bytes(),log.stat().st_mtime_ns),before)

    def test_old_partial_local_log_is_protected_after_backend_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "meeting.mkv"; source.write_bytes(b"source")
            args = app.build_parser().parse_args(["--offline",
                                                 "--output-dir", str(root/"out")])
            args.cache_dir = root/"cache"
            app.configure_mode(args)
            log,_ = app.output_paths(source,args.output_dir)
            app.atomic_write(log,"Previously generated or reviewed log")
            settings = app.recognition_settings(source,args)
            settings.pop('diarization'); settings.pop('recognizer'); settings['speakers']=2
            cache=args.cache_dir/hashlib.sha256(str(source).encode()).hexdigest()[:16]
            app.save_json(app.output_state_path(cache,log),{'settings':settings,
                'selection':{'transcription_model':'whisper-local'},'pipeline_complete':True})
            before=log.read_bytes(),log.stat().st_mtime_ns
            with patch.object(app,'extract_audio') as extract, patch.object(app,'diarize') as voice:
                with self.assertRaisesRegex(app.AppError,'settings changed'):
                    app.process_file(source,args,'')
                extract.assert_not_called(); voice.assert_not_called()
            self.assertEqual((log.read_bytes(),log.stat().st_mtime_ns),before)

    def test_fixed_count_option_is_removed(self):
        self.assertNotIn("--speakers", app.build_parser().format_help())
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            app.build_parser().parse_args(["--speakers", "2"])


if __name__ == "__main__":
    unittest.main()
