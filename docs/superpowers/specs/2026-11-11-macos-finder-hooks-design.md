# macOS Finder hooks design

Date: 2026-11-11
Task: SCR-097
Status: Approved by the user on 2026-11-11. Implementation delivered on branch
`codex/scr-097-finder-hooks`; native acceptance is partial (see PROJECT_CONTEXT.md).

## Intent

Start the existing Scribe recording-to-report workflow from a selected MKV in
Finder. The user should see processing in Terminal, receive the report beside
the recording, and have that report open automatically in the default browser.
Terminal must remain open after success, failure, or interruption.

## Agreed requirements

- Add an executable script named `macos-register-finder-hooks` at the repository
  root. Keep installation separate from `scribe.sh` and normal processing.
- Put the visible menu title and the actual conversion command together near
  the beginning of that script, with clear comments so the user can edit them.
- The menu title is `Scribe — Local conversion`.
- Use the ordinary Scribe command with the selected file's absolute path and its
  containing directory as the output directory:

  ```bash
  "$PROJECT_DIR/scribe.sh" -f "$file" --output-dir "$file_dir"
  ```

- `Local conversion` means the existing default local WhisperX recognition
  pipeline, including its normal diarization, GPT text processing, and HTML
  generation. Do not add `--offline`. Preserve normal configuration precedence;
  the menu does not introduce a separate transcription mode.
- Open a separate Terminal window for the invocation and show Scribe's console
  output and progress there. Return control to its interactive shell when done.
- Save `recording.log.md` and `recording.summary.html` beside `recording.mkv`.
- After successful completion, open the available HTML in the browser selected
  as the system's default web browser.

## Approaches

1. **Automator Quick Action plus a project script — selected.** Uses the native
   Finder Quick Actions mechanism and keeps the editable command in the project.
   Requires a one-time registration for the current macOS user.
2. **Shortcuts Quick Action — considered.** Also integrates with Finder, but adds
   a shortcut import/configuration surface for a workflow already handled by CLI.
3. **Dedicated application or Finder extension — not selected.** Adds application
   packaging and lifecycle work beyond this small launcher feature.

The standard entry point is Finder's file context menu, then **Quick Actions**,
then **Scribe — Local conversion**. A top-level context-menu item is not required.

## Script interface and configuration

- `./macos-register-finder-hooks`: install or update this user's Scribe action.
- `./macos-register-finder-hooks --uninstall`: remove only the Scribe action.
- Provide `--help` describing these operations and the editable configuration.
- The installed action calls this same project script in an internal run mode,
  passing the selected path as data. Do not embed a second conversion command
  in the installed workflow.
- Determine `PROJECT_DIR` from the script's location. Registration stores the
  actual location at installation time. Moving the project requires running
  registration again, which updates the existing action.
- Command edits take effect on the next menu invocation. Menu-title edits take
  effect after registration is run again.

Suggested configuration shape (illustrative, not implemented):

```bash
MENU_TITLE="Scribe — Local conversion"

run_conversion() {
    local file="$1"
    local file_dir="$2"
    "$PROJECT_DIR/scribe.sh" -f "$file" --output-dir "$file_dir"
}
```

Use a function or argument array rather than a command string evaluated with
`eval`. A configurable conversion command must retain the documented Scribe
output naming so the launcher can locate its HTML result.

## Registration and execution behavior

- Register a user-owned Automator workflow using the normal user Services
  location. Installation and removal need no administrator privileges.
- Use a stable action identity independent of the editable display name.
  Repeated registration updates one action; renaming must not leave duplicates.
- Registration does not process a recording, prepare models, or call an API.
- Preserve other services and user settings. If Finder has disabled the action,
  explain how to enable it instead of changing unrelated extensions.
- Resolve the input to an absolute path before changing directories. Run the
  conversion from `PROJECT_DIR`, keeping console logs in project `data/log/`.
- Accept existing `.mkv` files case-insensitively. Validate input at runtime even
  if Finder's file-type configuration limits when the action appears. Visibility
  exclusively for MKV needs actual macOS verification and must not be assumed.
- Quote paths across the shell/AppleScript boundary. Spaces, Cyrillic, quotes,
  and shell metacharacters in filenames must be passed literally.
- Wait for the command to finish before opening its report. Do not watch for
  file creation as the completion signal.
- A successful run with the expected HTML opens that HTML. A normal skip of an
  already completed recording also opens the existing HTML without forced work.
- Nonzero exit or cancellation leaves diagnostics visible in Terminal and does
  not open an old report. Success without HTML prints a clear explanation.
- A browser-launch failure leaves the report path visible; it must not trigger
  another conversion. Respect the system web-browser choice independently of
  a possible editor association for `.html` files.
- Keep the existing cache, locking, resume, partial-report, and error-history
  semantics. Do not add `--force` or automatic retries in this wrapper.

## Proposed implementation defaults

These are implementation judgments, not additional user requests:

- Target Scribe's existing macOS 14+ environment and use system facilities and
  existing project dependencies; add no package installation to registration.
- Initial scope is one selected MKV per invocation. If Finder supplies multiple
  inputs, report that limitation clearly instead of silently taking the first.
  Batch support can be specified separately.
- Use AppleScript to launch the command inside Terminal's interactive shell.
  Do not require the user to change global Terminal exit settings.
- Report denied automation permission or a missing project path visibly.
- Keep user-facing script help and repository documentation in English.

The implementer chooses workflow serialization, internal run-mode naming, and
the system API used to identify the default web browser.

## Acceptance and verification

1. Installing twice produces one action; changing the title and reinstalling
   updates it. Uninstall removes only this action. Registration invokes no
   conversion or model/API work.
2. A selected MKV outside the project, including a path with spaces, Cyrillic,
   quotes, or shell metacharacters, reaches the configured command literally,
   with the correct output directory and project working directory.
3. A successful conversion opens the expected HTML in the default browser and
   leaves Terminal open with the output available and shell control restored.
4. An already completed recording opens its existing HTML without repeating
   processing. Failure, interruption, or a missing HTML does not open a stale
   report; Terminal stays open and explains the outcome.
5. Editing the command changes the next invocation without copying that command
   into the workflow. Re-registering after a project move updates its target.
6. Runtime rejection of unsupported inputs is explicit. Verify actual Finder
   visibility, Terminal behavior, and browser selection on macOS; syntax checks
   or mocked commands alone do not establish these UI behaviors.

Use throwaway command fixtures and isolated service/output locations for
automated checks. A manual UI check can use a harmless fixture that writes a
small HTML file; running paid processing is not needed to verify the hook.
Document real UI checks separately from syntax and fixture checks.

## Delivery boundary

This document specifies the feature. The executable script, workflow generation,
tests, and usage documentation belong to the subsequent implementation task.
This design work does not install a Finder action or start recording processing.

## Reference

[Apple: Use Quick Action workflows on Mac](https://support.apple.com/en-gb/guide/automator/aut73234890a/2.10/mac/15.0)
describes creating a file-receiving Quick Action and exposing it in Finder.
