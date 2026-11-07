"""Git-checkout setup, reusable venvs, and generated-file exclusions."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import scribe as app


class SetupTests(unittest.TestCase):
    def test_setup_prepares_models_without_recordings_or_an_api_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            models = Path(temporary) / "models"
            for option, offline in (("--setup", False), ("--setup", True), ("--download-models", False)):
                with self.subTest(option=option, offline=offline), \
                        patch.object(app, "load_env"), patch.dict(os.environ, {}, clear=True), \
                        patch.object(app, "ensure_models") as prepare, \
                        patch.object(app, "process_file") as process, \
                        patch.object(app.urllib.request, "urlopen", side_effect=AssertionError("Network forbidden")):
                    arguments = [option, "--models-dir", str(models)]
                    if offline:
                        arguments.append("--offline")
                    self.assertEqual(app.main(arguments), 0)
                    prepare.assert_called_once_with(models.resolve(), offline, False)
                    process.assert_not_called()

    def test_ready_venv_runs_without_a_bundled_python_or_pip_and_stale_one_is_rejected_offline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "src").mkdir()
            (root / "src/scribe.py").write_text('import os\nprint("READY " + os.getcwd())\n')
            requirements = root / "requirements.txt"
            requirements.write_text("")
            launcher = root / "scribe.sh"
            shutil.copy2(app.APP_DIR / "scribe.sh", launcher)
            environment = root / "data/.venv"
            subprocess.run([sys._base_executable, "-I", "-B", "-m", "venv", "--without-pip", "--symlinks",
                            str(environment)], check=True, capture_output=True)
            (environment / ".requirements-sha256").write_text(hashlib.sha256(requirements.read_bytes()).hexdigest())
            cwd = root / "elsewhere"
            cwd.mkdir()
            result = subprocess.run(["/bin/bash", str(launcher), "--offline"], cwd=cwd, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "READY " + str(cwd.resolve()))
            self.assertFalse((root / "data/runtime").exists())
            requirements.write_text("package-not-installed\n")
            result = subprocess.run(["/bin/bash", str(launcher), "--offline"], cwd=cwd, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("READY", result.stdout)
            self.assertNotIn("Installing", result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("git"), "Git is needed to verify Git exclusions")
    def test_git_excludes_private_and_generated_files_but_keeps_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copy2(app.APP_DIR / ".gitignore", root / ".gitignore")
            subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
            for name in (".env", "data/.venv/lib/dependency.py", "data/models/weights.safetensors",
                         "data/.cache/stage.json", "data/recording.mkv", "data/comparison/usage.json",
                         "data/notes.txt", "data/.env", "data/.gitkeep.copy", "exports/meeting.summary.html"):
                self.assertEqual(subprocess.run(["git", "check-ignore", "-q", name], cwd=root).returncode, 0, name)
            for name in (".env.example", "requirements.txt", "scribe.sh", "src/scribe.py",
                         "src/resources/models-manifest.json", "src/resources/summary.html", "tests/test_setup.py",
                         "data/.gitkeep"):
                self.assertEqual(subprocess.run(["git", "check-ignore", "-q", name], cwd=root).returncode, 1, name)

    @unittest.skipUnless(shutil.which("git"), "Git is needed to verify fresh checkout contents")
    def test_checkout_contains_data_before_any_launch_but_no_private_contents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, checkout = root / "repo", root / "checkout"
            repo.mkdir(); checkout.mkdir()
            shutil.copy2(app.APP_DIR / ".gitignore", repo / ".gitignore")
            (repo / "data").mkdir()
            shutil.copy2(app.APP_DIR / "data/.gitkeep", repo / "data/.gitkeep")
            for name in ("recording.mkv", "notes.txt", "models/model.bin", ".cache/stage.json"):
                path = repo / "data" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"private fixture")
            subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
            subprocess.run(["git", "add", "--all"], cwd=repo, check=True, capture_output=True)
            tracked = subprocess.run(["git", "ls-files"], cwd=repo, check=True, capture_output=True, text=True)
            self.assertEqual(tracked.stdout.splitlines(), [".gitignore", "data/.gitkeep"])
            subprocess.run(["git", "checkout-index", "--all", "--prefix", str(checkout) + os.sep],
                           cwd=repo, check=True, capture_output=True)
            self.assertTrue((checkout / "data").is_dir())
            self.assertEqual([path.name for path in (checkout / "data").iterdir()], [".gitkeep"])


if __name__ == "__main__":
    unittest.main()
