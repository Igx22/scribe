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
            launcher = root / "run.sh"
            shutil.copy2(app.APP_DIR / "run.sh", launcher)
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
                         "data/.cache/stage.json", "data/recording.mkv", "data/comparison/usage.json"):
                self.assertEqual(subprocess.run(["git", "check-ignore", "-q", name], cwd=root).returncode, 0, name)
            for name in (".env.example", "requirements.txt", "run.sh", "src/scribe.py",
                         "src/resources/models-manifest.json", "tests/test_setup.py"):
                self.assertEqual(subprocess.run(["git", "check-ignore", "-q", name], cwd=root).returncode, 1, name)


if __name__ == "__main__":
    unittest.main()
