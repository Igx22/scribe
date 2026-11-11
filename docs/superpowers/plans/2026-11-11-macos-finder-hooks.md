# macOS Finder Hooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` (recommended for this plan) or `superpowers:subagent-driven-development`, according to the user's execution choice, to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an editable root script that registers a Finder action, runs Scribe in a persistent Terminal window, and opens its HTML report in the default browser.

**Architecture:** One Bash script owns the editable menu title, conversion command, CLI dispatch, and user-level workflow installation. The generated Automator Quick Action delegates to that script; its launch mode opens Terminal, whose interactive shell invokes the script's run mode. Run mode executes the configured command synchronously and opens the expected report only after a successful result.

**Tech Stack:** macOS 14+, system Bash 3.2, Automator, AppleScript/JXA, an already available Python 3 for standard-library plist/path handling, and the repository's Python `unittest` suite. No new packages or model preparation.

**Spec:** [Approved Finder hooks design](../specs/2026-11-11-macos-finder-hooks-design.md), approved by the user on 2026-11-11. The spec is authoritative.

**Task:** SCR-097. **Plan approval:** Approved by the user on 2026-11-12. **Execution method:** `superpowers:executing-plans`, selected by the user. **Requested model:** `gpt-6.1-sol`, reasoning effort `high`. **Handoff target:** `программер сеньор 2` (thread `01a1cb9b-774e-70f3-92bb-30f6283a30c2`). Dispatched on 2026-11-12; the programmer chat has acknowledged the assignment and started execution.

## Global Constraints

- Add an executable script named `macos-register-finder-hooks` at the repository root. Keep installation separate from `scribe.sh` and normal processing.
- The menu title is `Scribe — Local conversion`.
- Put the visible menu title and the actual conversion command together near the beginning of that script, with clear comments so the user can edit them.
- Use `"$PROJECT_DIR/scribe.sh" -f "$file" --output-dir "$file_dir"`; preserve normal configuration precedence and the existing default WhisperX pipeline. Do not add `--offline`.
- Run the conversion from `PROJECT_DIR`, keeping console logs in project `data/log/`.
- Terminal must remain open after success, failure, or interruption.
- Wait for the command to finish before opening its report. Do not watch for file creation as the completion signal.
- Keep the existing cache, locking, resume, partial-report, and error-history semantics. Do not add `--force` or automatic retries in this wrapper.
- Use a stable action identity independent of the editable display name. Repeated registration updates one action; renaming must not leave duplicates.
- Registration does not process a recording, prepare models, or call an API.
- Initial scope is one selected MKV per invocation. Multiple inputs must be rejected explicitly; accept `.mkv` case-insensitively.
- Keep user-facing script help and repository documentation in English. Preserve private data, existing configuration, results, and unrelated working-tree changes.

## Review Focus

1. Filenames and project locations containing spaces, Cyrillic, quotes, or shell metacharacters must survive both shell and AppleScript transport literally; relative inputs must be resolved before changing directories. Exercise in Task 1 runner tests and Task 2 launch round-trip tests.
2. Failure, SIGINT, stale HTML, success without HTML, and browser-open failure must retain diagnostics and never cause stale-report opening or another conversion. Exercise in Task 1 outcome tests and Task 3 manual Terminal checks.
3. Menu rename, reinstall, project relocation, and a foreign/symlink destination must preserve one owned action and unrelated files. Exercise in Task 2 registration tests.
4. Finder discovery, denied automation permission, a missing installed target, and a default browser differing from the HTML file association need explicit handling. Exercise adapter errors in Task 2 and verify actual UI/native behavior in Task 3.
5. Registration under a minimal GUI environment, absent prepared Python, and extra/unsupported arguments must not fall through to Scribe or setup. Exercise interpreter/CLI tests in Tasks 1–2; report unavailable prerequisites without installing them.

## Files and preparation

Paths below are repository-relative. The current source checkout is `/opt/projects26/scribe`; the desktop project card may still point to a removed checkout. Set the actual working directory explicitly.

| File | Responsibility |
| --- | --- |
| `macos-register-finder-hooks` | New executable script; configuration, registration, launch, run, and uninstall |
| `tests/test_finder_hooks.py` | New fixture-based subprocess, filesystem, and native-adapter tests |
| `README.md` | Short Finder entry point linking to detailed usage |
| `docs/USAGE.md` | Installation, editing, relocation, execution, removal, and troubleshooting |
| `docs/PROJECT_CONTEXT.md` | Verified design choices, test evidence, and actual macOS UI results/limitations |
| `TASKS.md` | SCR-097 status and links; preserve unrelated entries and edits |

Before Task 1, use `superpowers:using-git-worktrees` to establish an isolated workspace. Ensure this plan and its approved spec are present there: uncommitted/untracked planning artifacts do not automatically appear in a new worktree. Copy only these approved documents if needed; do not copy private `data`, `.env`, or other chats' changes. Read `README.md`, `docs/USAGE.md`, and `docs/PROJECT_CONTEXT.md`; historical AGENTS instructions were explicitly revoked by the user.

Use the existing test runtime without bootstrapping a new environment. From the implementation worktree, set a task-specific shell variable:

```bash
SCRIBE_TEST_PYTHON=/opt/projects26/scribe/data/.venv/bin/python3
```

The production hook must find an available interpreter independently: try the project venv, the existing legacy runtime, then available Python 3 commands. Use only standard-library operations and fail clearly if none works. Never call `scribe.sh` to discover or prepare Python.

### Task 1: Editable command and synchronous recording runner

**Files:** Create `macos-register-finder-hooks` and `tests/test_finder_hooks.py`.

**Interfaces:**
- Public root CLI: no arguments installs/updates; `--uninstall` removes; `--help` describes usage. Unknown flags and unexpected argument counts return nonzero without side effects.
- Shell dispatcher `main(argv...)` implements the CLI; invoke it only when the script is executed directly.
- Editable configuration: `MENU_TITLE` and Bash function `run_conversion(file, file_dir)` near the beginning; the default body is the command in Global Constraints.
- Produce internal CLI `--run FILE` and shell function `run_file(file)`, which normalizes/validates one source, derives its directory/report, changes to the project root, runs the configured command once, and applies report-opening rules.
- Produce native boundary functions `native_default_browser()` (prints an application path) and `native_open_document(application, report)` (returns native open status). Keep ordinary routing/report decisions outside these boundaries.
- Keep the script sourceable without executing CLI dispatch: use a normal Bash entry-point guard. Tests may substitute native boundary functions after sourcing; no production `--test` switch or test environment mode.

- [x] **Step 1: Write runner tests before implementation.** Build temporary project/recording directories, copy the hook under test, and supply an executable fixture `scribe.sh` that records exact argv/cwd, writes a small HTML when requested, and returns controlled exit codes. Keep native browser operations isolated at the boundary functions. Define test helper `run_hook(*args, cwd=None, overrides="") -> subprocess.CompletedProcess[str]`; it sources the copied script, applies only explicit fixture boundary overrides, and invokes its real CLI dispatcher. Directly execute `--help` too, to cover the executable entry point.

  `RunnerTests.test_default_command_preserves_arguments_and_project_cwd` must assert:

  ```python
  self.assertEqual(call["argv"], ["-f", str(source.resolve()), "--output-dir", str(source.resolve().parent)])
  self.assertEqual(call["cwd"], str(project.resolve()))
  self.assertEqual(result.returncode, 0)
  self.assertEqual(opened_reports, [str(report)])
  ```

  Also add outcome cases with explicit observable assertions:

  | Test case | Expected result |
  | --- | --- |
  | Relative source; `.MKV`; special characters in source/project path | Correct literal arguments; no shell-expanded marker file; correct report path |
  | Input symlink whose name differs from its target | Resolve consistently with Scribe's `collect_files()` before deriving directory/stem; locate the actual generated HTML |
  | Zero/two inputs, missing file, directory, non-MKV, unknown flag | Nonzero; zero conversion/browser calls; explanatory output |
  | Fixture creates HTML but remains running | No browser call until its completion, coordinated by process/pipe events rather than arbitrary sleeps |
  | Successful fixture representing a normal completed-pair skip | Existing HTML opens once; one configured-command invocation; no forced flags |
  | Exit 7 with an old report present | Return 7; preserve old report bytes; zero browser calls |
  | SIGINT sent to an isolated fixture process group | Interrupted/nonzero result; zero browser calls; completed output bytes retained |
  | Exit 0 without HTML, including legacy Markdown-only completion | Explanatory output and no browser call |
  | Chosen browser differs from an HTML editor association | Pass the resolved browser application and report to the open adapter |
  | Browser lookup/open fails | Visible report path and error; conversion count stays one |
  | Edit `run_conversion` in the temporary project copy | Next run executes the edited function, with no workflow reinstall |

  This covers Review Focus 1, 2, and runner portions of 4–5. Use real fixture processes/files; substitute only native OS side effects. Do not import the ASR pipeline or use real recordings.

- [x] **Step 2: Run RED.** Run `"$SCRIBE_TEST_PYTHON" -I -B -m unittest tests.test_finder_hooks.RunnerTests -v`. Verify failures concern the absent hook/behavior, not broken test fixtures.
- [x] **Step 3: Implement the runner and configuration.** Use system Bash-compatible syntax and quoted arguments; avoid `eval`. Resolve project/input locations consistently with `src/scribe.py:collect_files` and `output_paths`, then derive `<source-stem>.summary.html`. Capture conversion status explicitly so failure handling survives shell error settings. Return the conversion's failure status; treat missing HTML/native-open failure as a visible failure of the launcher. Do not swallow SIGINT.
- [x] **Step 4: Implement native browser boundaries.** Query the system's handler for a synthetic HTTPS URL through `NSWorkspace` using JXA, without navigating to that URL, then explicitly open the HTML with that application. Do not infer the browser from the HTML association. Keep missing-handler/open failures visible and leave the report intact.
- [x] **Step 5: Run GREEN and syntax checks.** Rerun `RunnerTests`; run `/bin/bash -n macos-register-finder-hooks`. Expected: every runner case passes and Bash syntax succeeds. The script must have its executable bit set. These checks do not prove Terminal window lifetime.
- [x] **Step 6: Commit this task's script and tests.** Suggested message: `feat: add configurable Finder recording runner`. Stage only the named implementation/test files.

### Task 2: User workflow registration and Terminal launch

**Files:** Modify `macos-register-finder-hooks` and `tests/test_finder_hooks.py`.

**Interfaces:**
- Consume Task 1's configuration, native browser boundaries, and `--run FILE` contract.
- Add internal CLI `--launch FILE`, which validates a single input and asks a new Terminal window to run the same root script's `--run` mode, then returns promptly.
- Add shell function `native_terminal_do_script(command)`, the native Terminal boundary; failures must remain observable to Automator/the caller.
- Add `install_action(services_dir)` and `uninstall_action(services_dir)`. Public CLI supplies the real user's `Library/Services`; tests call these functions with a temporary services directory. Do not repurpose `HOME` or add a test-only CLI flag.
- If native service discovery needs refreshing, isolate that operation in `native_refresh_services()` so tests can substitute it without touching the real user's registry.
- Stable bundle basename: `Scribe Local Conversion.workflow`; ownership identifier: `org.scribe.finder.local-conversion`. The editable display title comes from `MENU_TITLE`, never from the stable basename.

- [x] **Step 1: Write `RegistrationTests` and `LaunchTests` before their implementation.** Parse generated plists with `plistlib`, and execute generated shell transport/captured Terminal command text against harmless fixtures to verify the round trip. Do not assert merely that a quoted path appears in source text. The registry/native GUI boundaries must not affect the real user during automated tests.

  Required registration assertions include:

  ```python
  self.assertEqual(sorted(path.name for path in services_dir.iterdir()), ["Scribe Local Conversion.workflow", "unrelated.workflow"])
  self.assertEqual(unrelated.read_bytes(), original_unrelated_bytes)
  self.assertEqual(conversion_calls, [])
  ```

  Add these behaviors:

  | Case | Observable assertion |
  | --- | --- |
  | Install twice; edit title and reinstall | One owned bundle; service metadata exposes current title; no obsolete bundle |
  | Move temporary project and register again | Generated delegation resolves to the new script; literal argv reaches its `--launch` mode |
  | Uninstall twice | Owned action absent; unrelated bytes preserved; missing owned action handled explicitly/idempotently |
  | Foreign bundle or symlink at the owned path; unwritable target | Clear failure; preserve existing data; no writes through symlinks |
  | Failure while preparing replacement workflow | Previous valid owned installation remains usable |
  | Available interpreter only in prepared project runtime; none available | First installs without bootstrap; second reports prerequisite and performs no conversion/setup |
  | Filenames/root path containing quotes/metacharacters | Actual captured command round trip passes exactly one absolute file to `--run` |
  | Invalid/multiple inputs | No Terminal launch; clear error |
  | Native Terminal adapter reports denied permission | Nonzero/visible error, no conversion and no silent success |
  | Installed target no longer exists | Workflow surfaces a useful missing-project/re-registration error |

  This covers Review Focus 1 and 3–5. Check actual default-browser query availability on macOS without opening a document; UI opening remains Task 3.

- [x] **Step 2: Run RED.** Run `"$SCRIBE_TEST_PYTHON" -I -B -m unittest tests.test_finder_hooks.RegistrationTests tests.test_finder_hooks.LaunchTests -v`. Confirm failures demonstrate missing registration/launch behavior.
- [x] **Step 3: Implement install/update/removal.** Generate valid `Contents/Info.plist` and `Contents/document.wflow`, using standard-library plist encoding for dynamic strings. Configure file input for Finder; validate MKV in the script regardless of menu visibility. Workflow delegates to the root script's `--launch` mode with input as arguments; it contains no copied conversion command. Prepare/validate replacements before replacing an owned bundle, checking its ownership marker. Handle Finder service refresh only as narrowly needed; do not reset unrelated service settings.
- [x] **Step 4: Implement Terminal dispatch.** Pass input data to AppleScript as arguments rather than injecting it into AppleScript source. Quote each argument for the receiving shell; explicitly invoke `/bin/bash` with the root script and `--run`. Submit a foreground child command to a new interactive Terminal session: no parent-shell `exec` or `exit`, no background conversion, and no global Terminal preference changes. Native permission errors and missing installed targets must surface visibly.
- [x] **Step 5: Run GREEN and native format checks.** Run the entire `tests.test_finder_hooks` module, Bash syntax validation, and macOS plist/AppleScript compilation validation of generated fixture artifacts. Expected: valid native artifact formats; all hook tests pass; the real Services directory, Terminal, and browser remain untouched by automation tests. Report the exact tests/checks run.
- [x] **Step 6: Commit this task's script and tests.** Suggested message: `feat: register Scribe Finder quick action`.

### Task 3: Actual macOS acceptance, documentation, and completion

**Files:** Modify `README.md`, `docs/USAGE.md`, `docs/PROJECT_CONTEXT.md`, and the SCR-097 record in `TASKS.md`.

**Interfaces:** Consume the finished CLI and workflow from Tasks 1–2. Produce user instructions and honest verification evidence for all six acceptance points in the spec.

- [x] **Step 1: Run the full repository suite from the implementation worktree.** Command: `"$SCRIBE_TEST_PYTHON" -I -B -m unittest discover -s tests -t . -v`. Expected: all tests pass, without model downloads or paid requests. Record failures by name, including unrelated failures; do not describe a targeted green module as a green full suite.
- [x] **Step 2: Verify the real Finder → Terminal → browser path.** Use a temporary project copy whose visible configuration calls a harmless fixture, and synthetic MKVs. Register only that fixture's Scribe action, preserving any preexisting owned installation so it can be restored. From Finder, invoke the action and verify a separate Terminal window, visible fixture progress, the correct output folder, browser opening only after completion, and an interactive shell still usable afterward. Repeat failure and Ctrl+C with old HTML present; neither should open that HTML. Verify the current system browser resolves correctly; if safely testing a differing HTML association is impractical, record that specific scenario as unverified rather than changing the user's defaults.
- [ ] **Step 3: Verify real registration lifecycle.** Reinstall with another title, move the fixture project and re-register, check Finder shows the updated action, then remove the fixture action and restore any previous owned installation. Record actual Finder visibility for MKV and other file types. A broad file action with runtime MKV validation must be documented accurately. If a GUI session or permission is unavailable, record the outstanding acceptance item and leave SCR-097 `In Progress`; simulated boundaries do not satisfy native UI acceptance.
- [x] **Step 4: Document the delivered behavior.** Add a short Finder feature link to `README.md`. In `docs/USAGE.md`, document registration/removal commands, the editable top-of-script title/function, ordinary local WhisperX plus GPT semantics, one-file scope, project relocation, configuration precedence, log/output locations, completion/error/browser behavior, and enabling the action or allowing Terminal automation. Keep current macOS menu paths accurate for the version actually checked. Put durable rationale and precise test/UI evidence in `docs/PROJECT_CONTEXT.md`.
- [x] **Step 5: Self-review the delivered scope against the spec.** Check documentation, executable mode, generated-artifact isolation, and every spec acceptance point. Record actual test/UI outcomes and remaining checks; preserve the original Scribe pipeline and user data. Independent whole-branch review follows the completed task sequence below.
- [x] **Step 6: Commit documentation and evidence.** Keep SCR-097 `In Progress` pending final review. Stage only this task's documentation/ticket changes, excluding preexisting unrelated register edits. Suggested message: `docs: document and verify Scribe Finder integration`.

## Final review and delivery

- [x] Run the selected execution skill's single final independent whole-branch review after Tasks 1–3, including their committed documentation. This section records that required review; it does not request an additional duplicate review. Fix material findings and rerun checks affected by those changes.
- [x] Use `superpowers:verification-before-completion`. Mark SCR-097 `Done` with the actual user-local completion date only when code, required tests, native UI acceptance, and final review are complete. Otherwise retain `In Progress` with explicit remaining checks. Commit the final ticket/evidence update separately from unrelated edits.
- [ ] Use `superpowers:finishing-a-development-branch`. Present the verified result and integration choices to the user; preserve the worktree until the chosen integration is complete. Provide the branch/commits, tests, native UI evidence, and any remaining limitations in the programmer chat's final report.

## Plan self-review and handoff

The approved requirements map to Tasks 1–3: editable command and processing outcomes (1), stable registration/delegation and Terminal transport (2), actual UI/browser behavior, documentation, and integration evidence (3). Each Review Focus item has an explicit test/check owner above. Review is performed on this plan without spawning an implementation agent.

The user approved this plan and explicitly authorized handoff for implementation on 2026-11-12, choosing `superpowers:executing-plans` and `gpt-6.1-sol` with reasoning effort `high`. After the user explicitly requested creation of the new chat, both document paths and the implementation instruction were delivered to `программер сеньор 2` (thread `01a1cb9b-774e-70f3-92bb-30f6283a30c2`); its active turn acknowledged `superpowers:executing-plans`. Do not request plan or execution-method approval again. Implementation belongs to that programmer chat; no service installation or recording processing was performed by the analyst.

## Primary platform references

- [Apple: Use Quick Action workflows on Mac](https://support.apple.com/en-gb/guide/automator/aut73234890a/2.10/mac/15.0).
- [Apple: NSWorkspace URL-based default application lookup](https://developer.apple.com/documentation/appkit/nsworkspace/urlforapplication%28toopen%3A%29-7qkzf). Using a synthetic HTTPS URL to resolve its handler is the chosen browser-selection approach; no network navigation is required.

## Execution evidence (2026-11-12)

Tasks 1–2 implemented and committed; Task 3 records native acceptance and
remaining limits in [project context](../../PROJECT_CONTEXT.md#finder-hooks-scr-097).
267 tests pass after review fixes; native plist, AppleScript and Automator checks pass. Finder Services
success/failure/Ctrl+C and rename/relocation were verified using harmless fixtures.
The exact Quick Actions submenu route remains unverified: the session showed only
Customize there, although Scribe appeared directly in the context menu/Services.
SCR-097 remains In Progress. A differing HTML association was not changed natively.
Final independent review completed; inaccurate route claims, standard service icon metadata
and stale discovery cache refresh were corrected in one verified fix pass.
The user explicitly deferred Quick Actions acceptance; SCR-097 remains In Progress.
