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
- Keep quick start and reference tables in [README.md](README.md), detailed usage
  and recovery in [USAGE.md](docs/USAGE.md), design rationale and important findings
  in [PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md), and working
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
| SCR-038 | Generate tabbed HTML summaries with grounded meeting metadata | Done | 2026-11-07 | 2026-11-07 |
| SCR-039 | Default to summary levels 1, 3, 5, 10 and configure levels through .env | Done | 2026-11-07 | 2026-11-07 |
| SCR-040 | Embed the complete transcript in a standalone HTML Log tab | Done | 2026-11-07 | 2026-11-07 |
| SCR-041 | Clarify the README project data folder and add a direct link to run commands | Done | 2026-11-07 | 2026-11-07 |
| SCR-042 | Include the project data folder in fresh checkouts while excluding private contents | Done | 2026-11-07 | 2026-11-07 |
| SCR-043 | Select report tabs including Transcript and always generate standalone HTML | Done | 2026-11-07 | 2026-11-07 |
| SCR-044 | Add a persistent dark-mode switch to standalone HTML reports | Done | 2026-11-07 | 2026-11-07 |
| SCR-045 | Exclude JetBrains IDE project files from Git | Done | 2026-11-07 | 2026-11-07 |
| SCR-046 | Compare OBS Studio integration options and the recording-to-report user journey | Done | 2026-11-07 | 2026-11-07 |
| SCR-047 | Verify input discovery and --output-dir behavior against the code | Done | 2026-11-07 | 2026-11-07 |
| SCR-048 | Scan MKV recordings from a configurable --input-dir | Done | 2026-11-07 | 2026-11-07 |
| SCR-049 | Monitor growing OBS MKV recordings with --monitor-dir and finalization checks | Done | 2026-11-07 | 2026-11-07 |
| SCR-050 | Rename the shell launcher to scribe.sh throughout the project | Done | 2026-11-07 | 2026-11-07 |
| SCR-051 | Investigate false speaker splitting on the user's single-speaker OBS recording | Done | 2026-11-07 | 2026-11-07 |
| SCR-052 | Research alternative diarization and local transcription models for Scribe | Done | 2026-11-07 | 2026-11-07 |
| SCR-053 | Reprocess the sample with automatic speaker counting and publish a separate (2) HTML report | Done | 2026-11-07 | 2026-11-07 |
| SCR-054 | Test automatic diarization thresholds on the supplied two-speaker recording | Done | 2026-11-07 | 2026-11-07 |
| SCR-055 | Compare isolated WhisperX Russian transcription with cached local and API results on both test recordings | Done | 2026-11-07 | 2026-11-07 |
| SCR-056 | Test WhisperX Community-1 diarization on both recordings without speaker-count hints | Done | 2026-11-07 | 2026-11-07 |
| SCR-057 | Research local GitHub diarization alternatives with evidence for Russian speech | Done | 2026-11-07 | 2026-11-07 |
| SCR-058 | Compare isolated Nemotron 3 automatic diarization with Community-1 and existing Scribe results | Done | 2026-11-07 | 2026-11-07 |
| SCR-059 | Replace local diarization with automatic Nemotron 3 and prepare its public model/runtime during setup | Done | 2026-11-07 | 2026-11-07 |
| SCR-060 | Make Superpowers workflows opt-in through explicit user requests | Done | 2026-11-07 | 2026-11-07 |
| SCR-061 | Default to WhisperX Turbo with four recognition modes and independent diarization selection | Done | 2026-11-07 | 2026-11-07 |
| SCR-062 | Embed final and source transcripts plus diarization in report tabs | Done | 2026-11-07 | 2026-11-07 |
| SCR-063 | Default monitor output to its input folder and allow OS video-folder presets | Done | 2026-11-07 | 2026-11-07 |
| SCR-064 | Run GPT-Transcribe, WhisperX and MLX independently with transcription-model all | Done | 2026-11-07 | 2026-11-07 |
| SCR-065 | Verify force regenerates and replaces existing summary reports | Done | 2026-11-07 | 2026-11-07 |
| SCR-066 | Display report generation time with today-aware date formatting | Done | 2026-11-07 | 2026-11-07 |
| SCR-067 | Compare WhisperX, MLX and GPT transcripts embedded in the two supplied HTML reports | Done | 2026-11-07 | 2026-11-07 |
| SCR-068 | [Preview a Final transcript dropdown for technical report sources](data/comparison/transcript-menu-preview/VERIFICATION.md) | Done | 2026-11-07 | 2026-11-07 |
| SCR-069 | Apply the transcript dropdown, source sections and processing badges to reports | Done | 2026-11-07 | 2026-11-07 |
| SCR-070 | Investigate missing reconciliation and speaker names in the supplied single-speaker report | Done | 2026-11-07 | 2026-11-07 |
| SCR-071 | Parse recording dates from filenames with descriptive text and suffixes | Done | 2026-11-07 | 2026-11-07 |
| SCR-072 | Make GPT reconciliation a common final stage across transcription modes | Done | 2026-11-07 | 2026-11-07 |
| SCR-073 | Evaluate a compact local text model for offline summaries and reconciliation | Planned | 2026-11-07 | — |
| SCR-074 | Group summary detail levels in a dropdown with their generating model badge | Done | 2026-11-07 | 2026-11-07 |
| SCR-075 | Propose clearer summary and transcript menu labels | Done | 2026-11-08 | 2026-11-08 |
| SCR-076 | Generate two visual concepts for summary and transcript menus | Done | 2026-11-08 | 2026-11-08 |
| SCR-077 | [Implement compact Summary and Transcript report menus](data/comparison/menu-naming-preview/IMPLEMENTATION_VERIFICATION.md) | Done | 2026-11-08 | 2026-11-08 |
| SCR-078 | Regenerate the single-speaker recording report and open it in Chrome | In Progress | 2026-11-08 | — |
| SCR-079 | Generate a log and summary report for the supplied July recording | Done | 2026-11-08 | 2026-11-08 |
| SCR-080 | Draft a concise GitHub README and documentation migration plan | Done | 2026-11-08 | 2026-11-08 |
| SCR-081 | Adopt the concise README and detailed usage guide | Done | 2026-11-08 | 2026-11-08 |
| SCR-082 | [Inspect console output and retained reconciliation failure diagnostics](data/comparison/july-recording-run/console-excerpt.txt) | Done | 2026-11-08 | 2026-11-08 |
| SCR-083 | [Investigate English WhisperX output for Russian audio and downstream fallback](data/comparison/july-language-investigation/README.md) | Done | 2026-11-08 | 2026-11-08 |
| SCR-084 | [Make reconciliation resilient to imperfect recognition sources](data/comparison/reconciliation-resilience-preview/VERIFICATION.md) | Done | 2026-11-08 | 2026-11-08 |
| SCR-085 | [Detect WhisperX language from speech instead of leading silence](data/comparison/reconciliation-resilience-preview/VERIFICATION.md) | Done | 2026-11-08 | 2026-11-08 |
| SCR-086 | [Save per-recording processing errors beside the HTML report](data/comparison/reconciliation-resilience-preview/VERIFICATION.md) | Done | 2026-11-08 | 2026-11-08 |
| SCR-087 | [Regenerate the July report after fixes while preserving cloud recognition caches](data/comparison/july-recording-run/rerun-console.log) | Done | 2026-11-08 | 2026-11-08 |
| SCR-088 | [Add local model progress and processing time estimates](data/comparison/progress-preview/VERIFICATION.md) | Done | 2026-11-08 | 2026-11-08 |
| SCR-089 | [Investigate missing speaker names after successful reconciliation](data/comparison/july-speaker-names-investigation/README.md) | In Progress | 2026-11-08 | — |
| SCR-090 | [Save complete console output in daily per-run logs under the launch directory](data/comparison/console-logging-verification/VERIFICATION.md) | Done | 2026-11-08 | 2026-11-08 |
| SCR-091 | Clarify output directory defaults and monitoring documentation | Done | 2026-11-08 | 2026-11-08 |
| SCR-092 | [Audit recognition caches and specify reusable per-model artifacts](docs/PROJECT_CONTEXT.md#recognition-cache-artifacts) | Done | 2026-11-08 | 2026-11-08 |
| SCR-093 | Standardize per-model cache artifacts and allow summaries from cached final transcripts | Planned | 2026-11-08 | — |

### SCR-093

Proposed implementation following the SCR-092 audit. The user requested research
and a task specification; implementation has not yet been assigned.

#### Goal and existing behavior

Make each completed recognition/diarization/reconciliation result an identifiable,
reusable JSON artifact, so downstream work does not depend on the presence of one
exported `.log.md`. Extend existing checkpoints rather than creating a second
unrelated cache. GPT audio, local words and voice intervals already have JSON
checkpoints; `--summary-only` already avoids recognition but currently requires
the exported log. Nemotron supplies speaker intervals, not transcription text.

#### Proposed design

- Keep the application's existing ignored `data/.cache` root. Within each
  recording's cache, use readable artifact names and a small versioned manifest
  identifying the recording and available results. A short configuration ID
  distinguishes model/settings variants; filenames must not be hashes alone.
  Preserve collision safety for recordings with identical basenames. Changing the
  export directory must not require another recognition run.
- Save GPT-Transcribe responses per completed audio chunk, WhisperX ASR segments
  before alignment, alignment results, MLX results, and Nemotron/Community-1
  diarization results at their stage boundaries. Retain the JSON-serializable
  original returned payload and the normalized data actually used downstream,
  without inventing fields the backend did not return. A later alignment or
  reconciliation failure must not discard an already successful upstream result.
- Every artifact needs a schema version, stage/backend/model identity and revision,
  relevant settings, recording signature, dependency identifiers, completion state
  and payload. Preserve timestamps, word/voice uncertainty, language evidence,
  returned usage where available, and exact original text. Diarization metadata
  must distinguish anonymous voice IDs from validated human names.
- Save a complete final-transcript artifact after reconciliation, including the
  exact rendered text, structured turns/validated speaker metadata, supplements,
  provenance, input artifact references and complete/partial/fallback status.
  Preserve existing per-part reconciliation checkpoints and error diagnostics.
  Never present a partial or fallback result as successful full reconciliation.
- Keep recognition settings separate from the text model, reasoning effort,
  reconciliation prompt and summary settings. Changing only the summary model,
  effort, detail levels, prompts, template or output directory must not rerun ASR
  or diarization. Keep multiple compatible model/settings variants rather than
  overwriting another recognizer's only checkpoint. Dependency changes invalidate
  only affected work; preserve existing reuse guarantees for words and voices.
- With `--summary-only`, an existing exported `.log.md` remains authoritative,
  including user edits. Preserve it byte-for-byte. If it is missing, allow a
  validated cached final transcript to supply the report and restore its exact
  export under normal output protection. Select the artifact through matching
  source/provenance and a manifest/output-state reference; ambiguous candidates
  must produce a clear error rather than a guess based on filename or recency.
- `--summary-only` must never extract audio, load recognition/voice models, run
  ASR/diarization, or invoke reconciliation. If neither an exported log nor a
  compatible final cache exists, explain what is missing. Raw model caches alone
  must not trigger hidden audio processing or reconciliation. Normal summary/header
  text requests remain allowed. `--summary-only --force` still bypasses only
  summary/header reuse; ordinary `--force` retains its deliberate reprocessing
  behavior. Existing completed-pair skipping remains intact.
- Read compatible old checkpoints without new inference. Migrate or adapt them
  lazily without deleting old caches/results; record when original backend payloads
  are unavailable in legacy data rather than fabricating them or rerunning models
  just to populate a new schema. Keep incomplete artifacts distinguishable and
  resume GPT chunks and successful reconciliation parts independently.
- Use atomic writes, version/schema validation and appropriate locking for shared
  per-recording artifacts, including concurrent exports to different directories.
  Corrupt/mismatched data must not be silently accepted or damage a valid result.
  Preserve edited-log isolation, frozen report-source snapshots, uncertainty,
  offline guarantees, safe paths and existing ownership/backups. Add no dependencies
  or extra recognition calls merely for cache organization.

Illustrative filenames; the implementation may simplify the layout while keeping
model names readable and configurations distinct:

```text
data/.cache/<recording-id>/
  artifacts.json
  recognition/gpt-transcribe.<config-id>.json
  recognition/whisperx-turbo.<config-id>.json
  alignment/whisperx-turbo.<config-id>.json
  recognition/mlx-turbo.<config-id>.json
  diarization/nemotron-3.<config-id>.json
  diarization/community-1.<config-id>.json
  reconciliation/final-transcript.<config-id>.json
```

#### Acceptance and verification

- Each selected backend produces its own identifiable JSON result. Optional or
  unused backends are not run just to fill the cache. In `all`, each recognizer
  still runs at most once and voice segmentation is shared once.
- A summary-only run with a saved log makes zero extraction/ASR/diarization/fusion
  calls. The same holds with a missing export and a validated cached final result.
  An edited log wins over an older final cache and retains current source-view
  isolation. Missing/ambiguous final caches fail clearly without upstream work.
- Switching recognizers and switching back reuses both stored variants when
  compatible. Changing the summary model/effort/detail or export directory reuses
  upstream results. Source/model/dependency changes invalidate only relevant data.
- Cover legacy migration, stage failures after successful upstream work, partial
  results, corrupt files, interrupted writes, duplicate recording basenames,
  concurrent output directories, force/offline behavior and completed-output
  protection. Preserve the existing source-report and retry tests.
- Run the mocked unit suite without paid calls or model downloads. Update the
  concise README, detailed Usage cache/summary-only rules and Project Context's
  durable cache contract. Keep recordings, artifacts and experiment data ignored.

### SCR-089

Extend the completed cache audit with a bounded live prompt experiment on the
saved opening GPT-Transcribe/WhisperX sources. Repeat the current reconciliation
prompt with gpt-6.1-sol:medium and compare a clearer evidence-focused prompt.
Preserve source data, attribution uncertainty, validation and ordinary outputs.
Record exact prompts/responses, usage and limitations under ignored comparison
data; distinguish proposed name candidates from validated mappings. No full audio
recognition or report regeneration is needed.

### SCR-073

Evaluate compact quantized instruction models for English/Russian summaries on a
MacBook, CPU-only machine or small GPU. Start with Qwen3.5-4B; compare a larger
candidate only if available memory permits. Measure working memory, prompt/output
latency, factual coverage, uncertainty preservation and structured reconciliation
validation on existing cached transcripts against the GPT baseline. Test bounded
context and hierarchical notes rather than assuming the advertised context fits.
Also consider the text-only Qwen3-4B-Instruct-2507 as a non-thinking baseline.
Model selection and implementation are deferred; this ticket authorizes neither
downloads nor integration. Keep strict offline guarantees and original sources.
Candidate references checked on 2026-11-07:
[Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B),
[Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507),
[llama.cpp](https://github.com/ggml-org/llama.cpp).
