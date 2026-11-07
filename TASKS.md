# Scribe tasks

## Rules and format

- Track each requested feature, fix, investigation, or documentation task once.
  Clarifications of the same task keep the same ID; independently deliverable work
  can have separate tickets. Do not create tickets for routine progress messages.
- Use permanent sequential IDs: `SCR-001`, `SCR-002`, and so on. Append new tickets
  with the next unused number. Never renumber, reuse, or delete historical IDs.
- Use exactly these statuses:
  - `Planned`: recorded, but work has not started.
  - `In Progress`: work has started and is not yet complete.
  - `Done`: the requested work is complete and appropriate verification is recorded
    in its canonical location. For investigations, this means the investigation
    finished; its findings may include failures or unresolved limitations.
  - `Cancelled`: explicitly withdrawn or superseded; retain the ticket for history.
- A listed ticket is context, not an instruction to implement every planned item.
  Work on the task selected by the user. Do not start unrelated tickets or mark
  unfinished work `Done` merely because a chat ends.
- Record dates as `YYYY-MM-DD` using the user's timezone. Set `Created` when the
  request is registered and `Completed` when it becomes `Done`. Leave unknown or
  inapplicable dates as `—`; never infer dates from ticket order or import time.
  Clear `Completed` if a completed ticket is reopened.
- Update the ticket's status and dates together with the corresponding code or
  documentation changes and checks, rather than postponing this to another chat.
- Keep completed tickets to their ID, short English title, status, and dates.
  For an open task that needs detail, add a short `### SCR-NNN` section below the
  register with scope and acceptance criteria. On completion, move durable findings
  to their canonical document and retain only a link here if needed.
- Keep usage and public behavior in [README.md](README.md), design rationale and
  important findings in [PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md), and working
  agreements in [AGENTS.md](AGENTS.md). Do not duplicate those documents, source
  prompts, chat transcripts, or test output here. Never include secrets or private
  recording contents.

New ticket row:

```text
| SCR-NNN | Short task title | Planned | YYYY-MM-DD | — |
```

## Register

The initial history was imported from the development chat on 2026-11-07 and
checked against the current implementation and recorded experiment results.
Repeated requests and clarifications are grouped by deliverable. Historical
request/completion dates were not consistently recorded, so they remain `—`.
Completed investigations do not imply that every tested scenario passed; their
findings and limitations are preserved in `docs/PROJECT_CONTEXT.md`.

| ID | Task | Status | Created | Completed |
| --- | --- | --- | --- | --- |
| SCR-001 | Generate a detailed log and one-page summary of the sample recording | Done | — | — |
| SCR-002 | Add local voice diarization for the two-speaker conversation | Done | — | — |
| SCR-003 | Package the workflow as a Python application with a macOS shell launcher | Done | — | — |
| SCR-004 | Support MKV batches and repeated -f inputs with matching plain-text .md outputs | Done | — | — |
| SCR-005 | Generate summaries through the OpenAI API using explicit editable prompts | Done | — | — |
| SCR-006 | Default input discovery and result output to the working directory's data folder | Done | — | — |
| SCR-007 | Search both ./data and ~/Movies for bare input filenames | Done | — | — |
| SCR-008 | Translate project text to English and consolidate usage documentation in README.md | Done | — | — |
| SCR-009 | Support English/Russian conversations and uppercase Latin speaker labels | Done | — | — |
| SCR-010 | Compare GPT-Transcribe recognition with the local pipeline on the same recording | Done | — | — |
| SCR-011 | Apply speech-confidence and speaker-uncertainty markers only to affected spans | Done | — | — |
| SCR-012 | Add explicit cloud-only and local-only transcription choices | Done | — | — |
| SCR-013 | Reconcile cloud words with local voice/time anchors and preserve a local fallback | Done | — | — |
| SCR-014 | Remove personal home-directory paths from committed code and documentation | Done | — | — |
| SCR-015 | Choose the summary language from the conversation's predominant language | Done | — | — |
| SCR-016 | Rename the project and main Python module to Scribe | Done | — | — |
| SCR-017 | Compare Sol and Luna on identical cached sources while preserving baseline results | Done | — | — |
| SCR-018 | Add strict offline recognition without cloud calls, downloads, or summaries | Done | — | — |
| SCR-019 | Extend transcription selection with an explicit combined all mode | Done | — | — |
| SCR-020 | Combine text-model and reasoning selection in --summarize-model | Done | — | — |
| SCR-021 | Consolidate downloaded assets, the Python environment, and caches under data/ | Done | — | — |
| SCR-022 | Prevent Python bytecode files from cluttering the project root | Done | — | — |
| SCR-023 | Skip recordings that already have both log and summary outputs | Done | — | — |
| SCR-024 | Add summary detail levels from 1 to 10 without padding short conversations | Done | — | — |
| SCR-025 | Regenerate summaries from existing logs without repeating audio processing or fusion | Done | — | — |
| SCR-026 | Organize application code and resources under src/ with separate tests/ | Done | — | — |
| SCR-027 | Bootstrap dependencies and models from a fresh checkout without bundling Python | Done | — | — |
| SCR-028 | Prepare Git exclusions and review GitHub readiness and Docker suitability | Done | — | — |
| SCR-029 | Add the MIT license and document that comparison artifacts remain private | Done | — | — |
| SCR-030 | Publish the source repository to GitHub | Done | — | — |
| SCR-031 | Validate fresh-checkout setup, model downloads, and the real end-to-end workflow | Done | — | — |
| SCR-032 | Compare summary detail levels 1, 3, 5, 7, and 10 using the same saved log | Done | — | — |
| SCR-033 | Preserve verified project decisions and development guidance for future chats | Done | 2026-11-07 | 2026-11-07 |
| SCR-034 | Add a numbered task register and agent rules for maintaining it | Done | 2026-11-07 | 2026-11-07 |
| SCR-035 | Rename the task register to TASKS.md and commit agent/task guidance | Done | 2026-11-07 | 2026-11-07 |
| SCR-036 | Recognize transcript-supported speaker names during fusion | Done | 2026-11-07 | 2026-11-07 |
| SCR-037 | Put English before Russian and use English example names throughout project documentation | Done | 2026-11-07 | 2026-11-07 |
