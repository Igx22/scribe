"""Console mirroring without models, downloads, paid APIs or real-time waits."""
from datetime import datetime
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock

import console_log as console
import scribe as app


class DailyLogTests(unittest.TestCase):
    def test_same_day_exclusive_names_collision_and_simulated_midnight(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = Mock(return_value=datetime(2026, 11, 8, 23, 59, 59))
            logs = [console.DailyRunLog(tmp, clock=now) for _ in range(3)]
            paths = [log.path for log in logs]
            self.assertEqual(len(set(paths)), 3)
            first = logs[0]
            first.write("before midnight\n")
            before = first.file
            now.return_value = datetime(2026, 11, 9)
            first.write("after midnight\n")
            self.assertTrue(before.closed)
            self.assertIn(first.run_id, first.path.name)
            self.assertTrue(first.path.name.startswith("2026-11-09_"))
            self.assertEqual(paths[0].read_text(), "before midnight\n")
            self.assertEqual(first.path.read_text(), "after midnight\n")
            collision = console.DailyRunLog(tmp, clock=now, run_id=first.run_id)
            self.assertNotEqual(first.path, collision.path)
            self.assertIn(first.run_id, collision.path.name)
            self.assertEqual(first.path.read_text(), "after midnight\n")
            for log in [*logs, collision]:
                log.finish()
            self.assertEqual(first.path.stat().st_mode & 0o777, 0o600)

    def test_init_write_and_close_failures_are_nonfatal_and_warn_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocked = Path(tmp) / "not-a-directory"
            blocked.write_text("preserved")
            warning = Mock()
            log = console.DailyRunLog(blocked / "log", warning=warning)
            log.write("ignored"); log.finish()
            warning.assert_called_once()
            self.assertEqual(blocked.read_text(), "preserved")
            warning.reset_mock()
            log = console.DailyRunLog(Path(tmp) / "valid", warning=warning)
            real = log.file
            log.file = Mock()
            log.file.write.side_effect = OSError("disk full")
            log.file.close.side_effect = OSError("close failed")
            log.write("message"); log.write("next"); log.finish()
            self.assertTrue(log.failed)
            warning.assert_called_once()
            self.assertIn("disk full", warning.call_args.args[0])
            real.close()

    def test_unicode_ansi_cr_partial_utf8_and_credentials_split_across_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            secret = "test-secret-value"
            log = console.DailyRunLog(tmp, secrets=[secret])
            stream = console.LogStream(log)
            data = ("\r\x1b[2KProgress 10%\r\x1b[2KProgress 20%\r\n"
                    "\x1b]0;window title\x07Привет café\n"
                    f"{secret} sk-exampleabcdef123 hf_exampleabcdef456\nend").encode()
            for byte in data:
                stream.feed(bytes([byte]))
            stream.feed(b"", final=True)
            text = log.path.read_text()
            self.assertIn("Progress 10%\nProgress 20%\n", text)
            self.assertIn("Привет café\n", text)
            self.assertTrue(text.endswith("end\n"))
            self.assertNotIn(secret, text)
            self.assertNotIn("sk-example", text)
            self.assertNotIn("hf_example", text)
            self.assertNotIn("\x1b", text)
            self.assertNotIn("\r", text)
            self.assertNotIn("window title", text)
            log.finish()

    def test_partial_flush_keeps_secrets_at_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            secret = "a-credential-with-a-long-tail"
            log = console.DailyRunLog(tmp, secrets=[secret])
            stream = console.LogStream(log)
            stream.feed(("x" * 200 + secret[:12]).encode())
            stream.flush_partial()
            self.assertEqual(log.path.read_text(), "x" * 200)
            stream.feed((secret[12:] + "\n").encode())
            self.assertEqual(log.path.read_text(), "x" * 200 + "[redacted]\n")
            log.finish()

    def test_unterminated_messages_flush_and_long_key_does_not_grow_buffer(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = console.DailyRunLog(tmp)
            stream = console.LogStream(log)
            stream.feed(b"Live message without newline.")
            stream.flush_partial()
            self.assertEqual(log.path.read_text(), "Live message without newline.")
            stream.feed(b"\nsk-" + b"a" * 70000)
            self.assertLess(len(stream.pending), 65536)
            stream.feed(b"b" * 10000 + b"\nDone\n", final=True)
            self.assertTrue(log.path.read_text().endswith("[redacted]\nDone\n"))
            self.assertNotIn("sk-", log.path.read_text())
            log.finish()

    def test_env_credentials_are_read_as_data_and_environment_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text('OPENAI_API_KEY="file-key"\nexport HF_TOKEN=hf_filevalue\n'
                            'SOMETHING=$(do-not-execute)\n# COMMENT=secret\n')
            values = console.credential_values({"OPENAI_API_KEY": "env-key"}, path)
            self.assertIn("env-key", values)
            self.assertIn("hf_filevalue", values)
            self.assertNotIn("file-key", values)
            self.assertNotIn("$(do-not-execute)", values)


class ConsoleIntegrationTests(unittest.TestCase):
    helper = app.SOURCE_DIR / "console_log.py"

    def run_script(self, cwd, script, **kwargs):
        return subprocess.run([sys.executable, "-I", "-B", str(self.helper),
                               sys.executable, "-I", "-B", "-c", script], cwd=cwd,
                              capture_output=True, text=True, timeout=20, **kwargs)

    def log_text(self, cwd):
        logs = list((Path(cwd) / "data/log").glob("*.log"))
        self.assertEqual(len(logs), 1)
        return logs[0].read_text()

    def test_fd_stdout_stderr_logging_warnings_subprocess_traceback_and_status(self):
        script = '''import logging, os, subprocess, sys, warnings
print("python stdout", flush=True)
print("python stderr", file=sys.stderr, flush=True)
logging.warning("logging warning")
warnings.warn("dependency warning")
os.write(1, "native Привет\\n".encode())
os.write(2, b"native stderr\\n")
subprocess.run([sys.executable, "-c", "print('subprocess stdout'); import sys; print('subprocess stderr', file=sys.stderr)"])
print("tty", sys.stdout.isatty(), sys.stderr.isatty(), flush=True)
raise RuntimeError("fixture traceback")
'''
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_script(tmp, script)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("python stdout", result.stdout)
            self.assertNotIn("python stderr", result.stdout)
            self.assertIn("python stderr", result.stderr)
            self.assertNotIn("python stdout", result.stderr)
            self.assertIn("tty False False", result.stdout)
            text = self.log_text(tmp)
            for line in ("python stdout", "python stderr", "logging warning", "UserWarning: dependency warning",
                         "native Привет", "native stderr", "subprocess stdout", "subprocess stderr",
                         "RuntimeError: fixture traceback"):
                self.assertEqual(text.count(line), 1, text)

    def test_failed_log_initialization_keeps_console_exit_code_without_recursion(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "data").write_text("blocked")
            result = self.run_script(tmp, 'import sys; print("STILL WORKS"); sys.exit(7)')
            self.assertEqual(result.returncode, 7, result.stderr)
            self.assertEqual(result.stdout, "STILL WORKS\n")
            self.assertEqual(result.stderr.count("WARNING: Console file logging disabled:"), 1)

    def test_disk_write_failure_keeps_worker_output_and_exit_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = f'''import runpy, sys
from pathlib import Path
api = runpy.run_path({str(self.helper)!r})
log = api['DailyRunLog'](Path.cwd() / 'data/log')
log.file.close()
class FullDisk:
    def write(self, text): raise OSError('fixture disk full')
    def close(self): pass
log.file = FullDisk()
raise SystemExit(api['mirror']([sys.executable, '-c', 'import sys; print("CONTINUES"); sys.exit(8)'], log))
'''
            result = subprocess.run([sys.executable, "-I", "-B", "-c", script], cwd=tmp,
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 8, result.stderr)
            self.assertEqual(result.stdout, "CONTINUES\n")
            self.assertEqual(result.stderr.count("WARNING: Console file logging disabled:"), 1)
            self.assertIn("fixture disk full", result.stderr)

    def test_concurrent_invocations_keep_separate_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            commands = [[sys.executable, "-I", "-B", str(self.helper), sys.executable, "-c",
                         f"print('run {index}')"] for index in range(3)]
            processes = [subprocess.Popen(command, cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                         for command in commands]
            for index, process in enumerate(processes):
                stdout, stderr = process.communicate(timeout=20)
                self.assertEqual(process.returncode, 0, stderr)
                self.assertEqual(stdout.decode(), f"run {index}\n")
            logs = list((Path(tmp) / "data/log").glob("*.log"))
            self.assertEqual(len(logs), 3)
            self.assertEqual({p.read_text() for p in logs}, {f"run {i}\n" for i in range(3)})

    def test_tty_live_output_window_size_and_readable_progress(self):
        import fcntl
        import struct
        import termios
        with tempfile.TemporaryDirectory() as tmp:
            reader, writer = os.openpty()
            fcntl.ioctl(writer, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 110, 0, 0))
            script = ('import os, sys; print("TTY", sys.stdout.isatty(), sys.stderr.isatty(), '
                      'os.get_terminal_size().columns, flush=True); '
                      'sys.stdout.write("\\r\\033[2KProgress 10%\\r\\033[2KProgress 20%\\n"); '
                      'sys.stdout.flush(); input(); print("FINISHED", flush=True)')
            process = subprocess.Popen([sys.executable, "-I", "-B", str(self.helper),
                                        sys.executable, "-c", script], cwd=tmp,
                                       stdin=subprocess.PIPE, stdout=writer, stderr=writer)
            os.close(writer)
            selector = selectors.DefaultSelector()
            selector.register(reader, selectors.EVENT_READ)
            try:
                initial = b""
                deadline = time.monotonic() + 10
                while b"\n" not in initial:
                    self.assertTrue(selector.select(max(0, deadline - time.monotonic())), "Output was not live")
                    data = os.read(reader, 65536)
                    self.assertTrue(data, "Terminal closed before its first line")
                    initial += data
                self.assertIn(b"TTY True True 110", initial)
                self.assertIsNone(process.poll())
                process.communicate(b"\n", timeout=10)
                self.assertEqual(process.returncode, 0)
                text = self.log_text(tmp)
                self.assertIn("Progress 10%\nProgress 20%\n", text)
                self.assertIn("FINISHED\n", text)
                self.assertNotIn("\x1b", text)
                self.assertNotIn("\r", text)
            finally:
                if process.poll() is None:
                    process.kill(); process.wait()
                selector.close(); os.close(reader)

    def test_sigint_drains_orderly_cleanup_and_returns_130(self):
        script = ('import sys, time; print("READY", flush=True)\n'
                  'try: time.sleep(60)\n'
                  'except KeyboardInterrupt: print("CLEANUP", file=sys.stderr, flush=True); sys.exit(130)')
        with tempfile.TemporaryDirectory() as tmp:
            process = subprocess.Popen([sys.executable, "-I", "-B", str(self.helper),
                                        sys.executable, "-c", script], cwd=tmp,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            try:
                selector = selectors.DefaultSelector()
                selector.register(process.stdout, selectors.EVENT_READ)
                self.assertTrue(selector.select(10), "Worker did not start")
                self.assertEqual(process.stdout.readline(), b"READY\n")
                os.killpg(process.pid, signal.SIGINT)
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 130, stderr)
                self.assertEqual(stderr, b"CLEANUP\n")
                self.assertEqual(self.log_text(tmp).count("CLEANUP"), 1)
            finally:
                selector.close()
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL); process.wait()

    def test_import_has_no_file_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([sys.executable, "-I", "-B", "-c",
                                     f"import runpy; runpy.run_path({str(app.SOURCE_DIR / 'scribe.py')!r})"],
                                    cwd=tmp, capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((Path(tmp) / "data").exists())


class LauncherLogTests(unittest.TestCase):
    def fixture(self, root):
        checkout = root / "app"
        (checkout / "src").mkdir(parents=True)
        shutil.copy2(app.APP_DIR / "scribe.sh", checkout / "scribe.sh")
        shutil.copy2(app.SOURCE_DIR / "console_log.py", checkout / "src/console_log.py")
        # An existing legacy environment avoids any bootstrap or downloads.
        python = checkout / "data/runtime/python/bin/python3"
        python.parent.mkdir(parents=True)
        python.symlink_to(sys.executable)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        for name, script in (("uname", 'if [ "$1" = -s ]; then echo Darwin; else echo arm64; fi'),
                             ("sw_vers", "echo 14.0")):
            path = bin_dir / name
            path.write_text("#!/bin/bash\n" + script + "\n"); path.chmod(0o755)
        env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]}
        cwd = root / "caller"
        cwd.mkdir()
        return checkout, cwd, env

    def test_early_launcher_errors_and_legacy_handoff_share_one_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkout, cwd, env = self.fixture(root)
            (checkout / "src/scribe.py").write_text('import sys; print("APP OUTPUT"); print("APP ERROR", file=sys.stderr)')
            result = subprocess.run(["/bin/bash", str(checkout / "scribe.sh"), "--offline"], cwd=cwd,
                                    env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "APP OUTPUT\n")
            self.assertEqual(result.stderr, "APP ERROR\n")
            logs = list((cwd / "data/log").glob("*.log"))
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].read_text().count("APP OUTPUT"), 1)
            self.assertFalse((checkout / "data/log").exists())
            (root / "bin/sw_vers").write_text("#!/bin/bash\necho 13.0\n")
            result = subprocess.run(["/bin/bash", str(checkout / "scribe.sh")], cwd=cwd,
                                    env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 2)
            self.assertIn("macOS 14 or newer", result.stderr)
            logs = list((cwd / "data/log").glob("*.log"))
            self.assertEqual(len(logs), 2)
            self.assertEqual(sum("macOS 14 or newer" in p.read_text() for p in logs), 1)

    def test_direct_entry_help_version_config_error_and_setup_output_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkout, cwd, env = self.fixture(Path(tmp))
            # Exercise the real direct-entry guard without bootstrapping a venv.
            source = (app.SOURCE_DIR / "scribe.py").read_text()
            source = source.replace('managed = {APP_DATA / ".venv", APP_DATA / "runtime/python", APP_DATA / "runtime/venv"}',
                                    'managed = {Path(sys.prefix)}')
            # Setup uses fake model preparation while retaining the real CLI.
            source = source.replace('raise SystemExit(main())',
                                    'ensure_models = lambda *a, **k: print("FAKE SETUP")\n'
                                    '        process_files = lambda *a: print("FAKE BATCH") or 0\n'
                                    '        monitor_directory = lambda *a: print("FAKE MONITOR") or 0\n'
                                    '        raise SystemExit(main())')
            (checkout / "src/scribe.py").write_text(source)
            (checkout / "src/resources").mkdir()
            shutil.copy2(app.RESOURCE_DIR / "models-manifest.json", checkout / "src/resources/models-manifest.json")
            inputs = cwd / "inputs"
            inputs.mkdir()
            (inputs / "meeting.mkv").write_bytes(b"fixture")
            for arguments, status, expected in ((["--help"], 0, "usage:"), (["--version"], 0, app.VERSION),
                                                (["--bad-option"], 2, "unrecognized arguments"),
                                                (["--setup", "--offline", "--output-dir", str(cwd / "elsewhere")],
                                                 0, "FAKE SETUP"),
                                                (["--input-dir", str(inputs), "--output-dir", str(cwd / "elsewhere")],
                                                 0, "FAKE BATCH"),
                                                (["--monitor-dir", str(inputs), "--output-dir", str(cwd / "elsewhere")],
                                                 0, "FAKE MONITOR")):
                with self.subTest(arguments=arguments):
                    result = subprocess.run([sys.executable, "-I", "-B", str(checkout / "src/scribe.py"), *arguments],
                                            cwd=cwd, env=env, capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, status, result.stderr)
                    self.assertIn(expected, result.stdout + result.stderr)
            logs = list((cwd / "data/log").glob("*.log"))
            self.assertEqual(len(logs), 6)
            self.assertEqual(sum("FAKE SETUP" in p.read_text() for p in logs), 1)
            self.assertFalse((cwd / "elsewhere").exists())
            self.assertFalse((checkout / "data/log").exists())

    def test_direct_unmanaged_entry_through_launcher_and_failed_log_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkout, cwd, env = self.fixture(Path(tmp))
            source = (app.SOURCE_DIR / "scribe.py").read_text().replace(
                'managed = {APP_DATA / ".venv", APP_DATA / "runtime/python", APP_DATA / "runtime/venv"}',
                'managed = {Path(sys.prefix)} if os.getenv("_TEST_READY") else set()')
            (checkout / "src/scribe.py").write_text(source)
            (checkout / "src/resources").mkdir()
            shutil.copy2(app.RESOURCE_DIR / "models-manifest.json", checkout / "src/resources/models-manifest.json")
            python = checkout / "data/runtime/python/bin/python3"
            python.unlink()
            python.write_text(f'#!/bin/bash\nexport _TEST_READY=1\nexec {sys.executable!r} "$@"\n')
            python.chmod(0o755)
            command = [sys.executable, "-I", "-B", str(checkout / "src/scribe.py"), "--version"]
            result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            logs = list((cwd / "data/log").glob("*.log"))
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].read_text(), app.VERSION + "\n")
            # The fallback exec must carry a valid marker through all three
            # entry points as well, or an unwritable log could recurse forever.
            blocked = cwd / "blocked"
            blocked.mkdir()
            (blocked / "data").write_text("not a directory")
            result = subprocess.run(command, cwd=blocked, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, app.VERSION + "\n")
            self.assertEqual(result.stderr.count("WARNING: Console file logging disabled:"), 1)

    def test_bootstrap_stdout_stderr_and_error_before_main_python_are_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkout, cwd, env = self.fixture(Path(tmp))
            python = checkout / "data/.venv/bin/python3"
            python.parent.mkdir(parents=True)
            python.write_text(f'''#!/bin/bash
if [[ "$3" == -c ]]; then
    exit 0
elif [[ "$3" == -m && "$4" == pip ]]; then
    echo "SETUP OUTPUT"
    echo "SETUP ERROR" >&2
    exit 9
fi
exec {sys.executable!r} "$@"
''')
            python.chmod(0o755)
            result = subprocess.run(["/bin/bash", str(checkout / "scribe.sh"), "--setup"], cwd=cwd,
                                    env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 9, result.stderr)
            self.assertIn("Installing Scribe dependencies", result.stdout)
            self.assertIn("SETUP OUTPUT", result.stdout)
            self.assertEqual(result.stderr, "SETUP ERROR\n")
            logs = list((cwd / "data/log").glob("*.log"))
            self.assertEqual(len(logs), 1)
            text = logs[0].read_text()
            for line in ("Installing Scribe dependencies", "SETUP OUTPUT", "SETUP ERROR"):
                self.assertEqual(text.count(line), 1)


if __name__ == "__main__":
    unittest.main()
