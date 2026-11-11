"""Finder launcher contracts using synthetic files and isolated native boundaries."""
import json
import os
from pathlib import Path
import select
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / 'macos-register-finder-hooks'


class HookFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='scribe-finder-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.project = self.base / "проект ' \" $() ; space"
        self.project.mkdir()
        self.hook = self.project / HOOK.name
        self.assertTrue(HOOK.is_file(), 'Finder hook implementation is missing')
        shutil.copy2(HOOK, self.hook)
        self.source = self.base / "запись ' \" $(touch INJECTED); [a].MKV"
        self.source.write_bytes(b'synthetic MKV')
        self.report = self.source.with_suffix('.summary.html')
        self.calls = self.project / 'calls.jsonl'
        self.opened = self.project / 'opened.jsonl'
        self.config = self.project / 'fixture.json'
        self.configure()
        fixture = '''import json, pathlib, sys, os
p = pathlib.Path(__file__).resolve().parent
config = json.loads((p / 'fixture.json').read_text())
with (p / 'calls.jsonl').open('a') as out:
    out.write(json.dumps({'argv': sys.argv[1:], 'cwd': os.getcwd()}) + '\\n')
src = pathlib.Path(sys.argv[sys.argv.index('-f') + 1])
if config.get('html', True):
    src.with_suffix('.summary.html').write_text('fixture report')
if config.get('legacy'):
    src.with_suffix('.summary.md').write_text('legacy report')
src.with_suffix('.log.md').write_text('completed output')
print('FIXTURE READY', flush=True)
if config.get('wait'):
    try:
        sys.stdin.readline()
    except KeyboardInterrupt:
        sys.exit(130)
sys.exit(config.get('status', 0))
'''
        (self.project / 'scribe.sh').write_text(f'#!{sys.executable}\n' + fixture)
        (self.project / 'scribe.sh').chmod(0o755)

    def configure(self, **values):
        self.config.write_text(json.dumps(values))

    def records(self, path):
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def boundaries(self):
        return '''native_default_browser() { printf '%s\\n' '/Applications/Chosen Browser.app'; }
native_open_document() { "$FIXTURE_PYTHON" -c 'import json, sys; open(sys.argv[1], "a").write(json.dumps(sys.argv[2:])+"\\n")' "$FIXTURE_OPENED" "$@"; }
'''

    def command(self, args, overrides=''):
        return ['/bin/bash', '-c', 'source "$1" || exit; shift\n' + self.boundaries() + overrides + '\nmain "$@"', 'fixture', str(self.hook), *map(str, args)]

    def environment(self):
        return dict(os.environ, FIXTURE_PYTHON=sys.executable, FIXTURE_OPENED=str(self.opened))

    def run_hook(self, *args, cwd=None, overrides=''):
        return subprocess.run(self.command(args, overrides), cwd=cwd or self.base,
                              env=self.environment(), text=True, capture_output=True, timeout=15)

    def assert_no_work(self):
        self.assertEqual(self.records(self.calls), [])
        self.assertEqual(self.records(self.opened), [])

    def ready_process(self):
        proc = subprocess.Popen(self.command(['--run', self.source]), cwd=self.base,
                                env=self.environment(), text=True, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        def cleanup():
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
        self.addCleanup(cleanup)
        self.assertTrue(select.select([proc.stdout], [], [], 10)[0], 'fixture did not become ready')
        self.assertEqual(proc.stdout.readline().strip(), 'FIXTURE READY')
        return proc


class RunnerTests(HookFixture):
    def test_default_command_preserves_arguments_and_project_cwd(self):
        result = self.run_hook('--run', self.source)
        self.assertEqual(result.returncode, 0, result.stderr)
        call, = self.records(self.calls)
        self.assertEqual(call['argv'], ['-f', str(self.source), '--output-dir', str(self.base)])
        self.assertEqual(call['cwd'], str(self.project))
        self.assertEqual(self.records(self.opened), [['/Applications/Chosen Browser.app', str(self.report)]])
        self.assertFalse((self.base / 'INJECTED').exists())
        self.assertFalse((self.project / 'INJECTED').exists())

    def test_relative_source_and_resolved_symlink_outputs(self):
        target_dir = self.base / 'target'
        target_dir.mkdir()
        target = target_dir / 'real.mkv'
        target.write_bytes(b'x')
        link = self.base / 'alias.mkv'
        link.symlink_to(target)
        result = self.run_hook('--run', './alias.mkv')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.records(self.calls)[0]['argv'], ['-f', str(target), '--output-dir', str(target_dir)])
        self.assertEqual(self.records(self.opened)[0][1], str(target_dir / 'real.summary.html'))

    def test_rejects_invalid_arguments_and_inputs(self):
        invalid = [('--run',), ('--run', self.source, self.source), ('--run', self.base / 'missing.mkv'),
                   ('--run', self.base), ('--run', self.config), ('--unknown',), ('--help', 'extra'), ('--uninstall', 'extra')]
        for args in invalid:
            with self.subTest(args=args):
                result = self.run_hook(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(result.stdout or result.stderr)
                self.assert_no_work()

    def test_waits_for_completion_before_browser(self):
        self.configure(wait=True)
        proc = self.ready_process()
        self.assertTrue(self.report.exists())
        self.assertEqual(self.records(self.opened), [])
        out, err = proc.communicate('finish\n', timeout=10)
        self.assertEqual(proc.returncode, 0, out + err)
        self.assertEqual(len(self.records(self.opened)), 1)

    def test_completed_pair_skip_opens_existing_report_without_force(self):
        self.configure(html=False)
        self.report.write_text('old complete report')
        self.source.with_suffix('.log.md').write_text('old log')
        result = self.run_hook('--run', self.source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.report.read_text(), 'old complete report')
        self.assertEqual(len(self.records(self.calls)), 1)
        self.assertNotIn('--force', self.records(self.calls)[0]['argv'])
        self.assertEqual(len(self.records(self.opened)), 1)

    def test_failure_never_opens_stale_report_and_preserves_status(self):
        self.configure(status=7, html=False)
        self.report.write_bytes(b'old report')
        result = self.run_hook('--run', self.source, overrides='set -e\n')
        self.assertEqual(result.returncode, 7)
        self.assertEqual(self.report.read_bytes(), b'old report')
        self.assertEqual(self.records(self.opened), [])
        self.assertIn('7', result.stderr)

    def test_sigint_keeps_completed_output_and_never_opens_stale_html(self):
        self.configure(wait=True, html=False)
        self.report.write_text('stale')
        proc = self.ready_process()
        os.killpg(proc.pid, signal.SIGINT)
        out, err = proc.communicate(timeout=10)
        self.assertNotEqual(proc.returncode, 0, out + err)
        self.assertEqual(self.records(self.opened), [])
        self.assertEqual(self.report.read_text(), 'stale')
        self.assertEqual(self.source.with_suffix('.log.md').read_text(), 'completed output')

    def test_success_without_html_including_legacy_completion_is_visible_failure(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                self.configure(html=False, legacy=legacy)
                result = self.run_hook('--run', self.source)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(str(self.report), result.stderr)
                self.assertEqual(self.records(self.opened), [])

    def test_browser_lookup_or_open_failure_does_not_repeat_conversion(self):
        for override in ('native_default_browser() { return 3; }', 'native_open_document() { return 4; }'):
            with self.subTest(override=override):
                before = len(self.records(self.calls))
                result = self.run_hook('--run', self.source, overrides=override)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(str(self.report), result.stderr)
                self.assertEqual(len(self.records(self.calls)), before + 1)
                self.assertEqual(self.records(self.opened), [])

    def test_editable_conversion_is_used_on_next_run(self):
        text = self.hook.read_text()
        text = text.replace('"$PROJECT_DIR/scribe.sh" -f "$file" --output-dir "$file_dir"',
                            '"$PROJECT_DIR/scribe.sh" -f "$file" --output-dir "$file_dir" --edited')
        self.hook.write_text(text)
        result = self.run_hook('--run', self.source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.records(self.calls)[0]['argv'][-1], '--edited')

    def test_help_executes_directly_and_sourcing_has_no_side_effects(self):
        result = subprocess.run([str(self.hook), '--help'], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--uninstall', result.stdout)
        self.assertIn('run_conversion', result.stdout)
        result = subprocess.run(['/bin/bash', '-c', 'source "$1"', 'fixture', str(self.hook)], capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assert_no_work()


class RegistrationTests(HookFixture):
    def setUp(self):
        super().setUp()
        self.services = self.base / 'Services'
        self.services.mkdir()
        self.unrelated = self.services / 'unrelated.workflow'
        self.unrelated.write_bytes(b'unrelated service')
        self.bundle = self.services / 'Scribe Local Conversion.workflow'

    def register(self, operation='install_action', overrides='', env=None):
        code = 'source "$1" || exit; native_refresh_services() { :; }; ' + overrides + '\n' + operation + ' "$2"'
        return subprocess.run(['/bin/bash', '-c', code, 'fixture', str(self.hook), str(self.services)],
                              env=env or self.environment(), text=True, capture_output=True, timeout=15)

    def info(self):
        import plistlib
        return plistlib.loads((self.bundle / 'Contents/Info.plist').read_bytes())

    def workflow(self):
        import plistlib
        return plistlib.loads((self.bundle / 'Contents/document.wflow').read_bytes())

    def transport(self):
        return self.workflow()['actions'][0]['action']['ActionParameters']['COMMAND_STRING']

    def test_install_update_rename_and_uninstall_preserve_unrelated_service(self):
        for title in (None, None, 'Renamed & <Scribe>'):
            if title:
                self.hook.write_text(self.hook.read_text().replace('Scribe — Local conversion', title))
            result = self.register()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(sorted(p.name for p in self.services.iterdir()), ['Scribe Local Conversion.workflow', 'unrelated.workflow'])
            self.assertEqual(self.info()['CFBundleIdentifier'], 'org.scribe.finder.local-conversion')
            self.assertEqual(self.info()['NSServices'][0]['NSMenuItem']['default'], title or 'Scribe — Local conversion')
            self.assertEqual(self.unrelated.read_bytes(), b'unrelated service')
            self.assert_no_work()
        for _ in range(2):
            result = self.register('uninstall_action')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(self.bundle.exists())
            self.assertEqual(self.unrelated.read_bytes(), b'unrelated service')

    def test_workflow_advertises_finder_quick_action(self):
        self.assertEqual(self.register().returncode, 0)
        metadata = self.workflow()['workflowMetaData']
        self.assertEqual(metadata['presentationMode'], 15)
        self.assertEqual(metadata['inputTypeIdentifier'], 'com.apple.Automator.fileSystemObject')
        self.assertEqual(metadata['applicationBundleIDsByPath'], {'/System/Library/CoreServices/Finder.app': 'com.apple.finder'})

    def test_workflow_round_trip_and_relocation(self):
        for moved in (False, True):
            if moved:
                dest = self.base / "moved ' \" ; $() проект"
                self.project.rename(dest)
                self.project = dest
                self.hook = dest / HOOK.name
            result = self.register()
            self.assertEqual(result.returncode, 0, result.stderr)
            transport = self.transport()
            # Replace the target only after serializing; execute the actual shell transport.
            original = self.hook.read_bytes()
            self.hook.write_text(f'#!{sys.executable}\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\n')
            # Workflow explicitly uses Bash, so capture shell arguments with a Bash fixture.
            self.hook.write_text('#!/bin/bash\n"' + sys.executable + '" -c \'import json,sys;print(json.dumps(sys.argv[1:]))\' "$@"\n')
            run = subprocess.run(['/bin/bash', '-c', transport, 'workflow', str(self.source)], capture_output=True, text=True)
            self.hook.write_bytes(original)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout), ['--launch', str(self.source)])
            self.assert_no_work()

    def test_missing_installed_target_reports_reregistration(self):
        self.assertEqual(self.register().returncode, 0)
        transport = self.transport()
        self.hook.unlink()
        result = subprocess.run(['/bin/bash', '-c', transport, 'workflow', str(self.source)], text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('register', result.stderr.lower())
        self.assertIn(str(self.project), result.stderr)
        self.assert_no_work()

    def test_foreign_bundle_and_symlink_are_preserved(self):
        self.bundle.mkdir()
        foreign = self.bundle / 'foreign'
        foreign.write_bytes(b'foreign')
        for operation in ('install_action', 'uninstall_action'):
            result = self.register(operation)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(foreign.read_bytes(), b'foreign')
        shutil.rmtree(self.bundle)
        target = self.base / 'foreign directory'
        target.mkdir()
        (target / 'marker').write_bytes(b'protected')
        self.bundle.symlink_to(target, target_is_directory=True)
        for operation in ('install_action', 'uninstall_action'):
            result = self.register(operation)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(self.bundle.is_symlink())
            self.assertEqual((target / 'marker').read_bytes(), b'protected')
        self.assert_no_work()

    def test_unwritable_destination_fails_without_writes(self):
        self.services.chmod(0o555)
        self.addCleanup(self.services.chmod, 0o755)
        result = self.register()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse(self.bundle.exists())
        self.assertEqual(self.unrelated.read_bytes(), b'unrelated service')
        self.assert_no_work()

    def test_invalid_replacement_keeps_previous_owned_workflow(self):
        self.assertEqual(self.register().returncode, 0)
        before = {str(p.relative_to(self.bundle)): p.read_bytes() for p in self.bundle.rglob('*') if p.is_file()}
        result = self.register(overrides="MENU_TITLE=$'bad\\001title'")
        self.assertNotEqual(result.returncode, 0)
        after = {str(p.relative_to(self.bundle)): p.read_bytes() for p in self.bundle.rglob('*') if p.is_file()}
        self.assertEqual(after, before)
        self.assert_no_work()

    def test_prepared_runtime_with_minimal_path_and_missing_python(self):
        minimal = self.base / 'minimal-bin'
        minimal.mkdir()
        for command in ('dirname', 'basename'):
            (minimal / command).symlink_to('/usr/bin/' + command)
        runtime = self.project / 'data/.venv/bin/python3'
        runtime.parent.mkdir(parents=True)
        runtime.symlink_to(sys.executable)
        env = dict(self.environment(), PATH=str(minimal))
        result = self.register(env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        runtime.unlink()
        # Model a host with no absolute fallback interpreter installed.
        text = self.hook.read_text()
        for command in ('/opt/homebrew/bin/python3', '/usr/local/bin/python3', '/usr/bin/python3'):
            text = text.replace(command, str(self.base / 'absent-python'))
        self.hook.write_text(text)
        result = self.register(env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Python 3', result.stderr)
        self.assert_no_work()


class LaunchTests(HookFixture):
    def launch_override(self):
        return 'native_terminal_do_script() { printf "%s" "$1" > "$FIXTURE_COMMAND"; }\n'

    def environment(self):
        return dict(super().environment(), FIXTURE_COMMAND=str(self.base / 'terminal-command'))

    def test_terminal_command_round_trip_is_foreground_and_returns_to_shell(self):
        result = self.run_hook('--launch', self.source.name, overrides=self.launch_override())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_no_work()
        command = (self.base / 'terminal-command').read_text()
        # Capture the arguments received by the child script, then prove shell control returns.
        self.hook.write_text('#!/bin/bash\n"$FIXTURE_PYTHON" -c \'import json,sys; open(sys.argv[1], "w").write(json.dumps(sys.argv[2:]))\' "$FIXTURE_OPENED" "$@"\n')
        run = subprocess.run(['/bin/bash', '-c', command + '\nprintf "SHELL RETURNED\\n"'], env=self.environment(), cwd=self.base, text=True, capture_output=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('SHELL RETURNED', run.stdout)
        self.assertEqual(json.loads(self.opened.read_text()), ['--run', str(self.source)])
        self.assertEqual(self.records(self.calls), [])

    def test_invalid_selection_never_launches_terminal(self):
        for args in [('--launch',), ('--launch', self.source, self.source), ('--launch', self.base), ('--launch', self.config)]:
            result = self.run_hook(*args, overrides=self.launch_override())
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((self.base / 'terminal-command').exists())
            self.assert_no_work()

    def test_denied_terminal_automation_is_reported(self):
        result = self.run_hook('--launch', self.source, overrides='native_terminal_do_script() { echo "Not authorized (-1743)" >&2; return 1; }')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Terminal', result.stderr)
        self.assertIn('1743', result.stderr)
        self.assert_no_work()
