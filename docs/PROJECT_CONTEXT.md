# Scribe: development context

Keep this file focused on architectural decisions and unresolved limitations.
[README](../README.md) owns quick start and reference tables;
[Usage](USAGE.md) owns detailed setup, public behavior and recovery;
[AGENTS](../AGENTS.md) owns development agreements;
[src/scribe.py](../src/scribe.py) owns prompts, schemas and implementation.

## Structure and runtime

Keep the application portable and simple: `scribe.sh` prepares the isolated
Python environment and launches `src/scribe.py`; `src/console_log.py` is the
standard-library console supervisor shared by both CLI entry points. Static
resources live in `src/resources`, with mocked tests in `tests`. Current native support is macOS
Apple Silicon with Python 3.12-3.13. Cross-platform folder presets do not imply
cross-platform model/runtime support. Docker integration is deferred.

## Data, models, Python environment, and caches

Downloaded assets, the Python environment and default caches live under the
application's `data/`. Only `data/.gitkeep` is tracked; recordings, generated
results and optional private experiments under `data/comparison/` stay outside Git.

```text
scribe/
  scribe.sh, requirements.txt, .env, .env.example
  README.md, AGENTS.md, TASKS.md, LICENSE, .gitignore
  src/
    scribe.py
    console_log.py
    resources/models-manifest.json
    resources/summary.html
  tests/
  docs/PROJECT_CONTEXT.md
  data/
    .gitkeep
    models/
    .venv/
    .cache/
    comparison/
    recording.mkv, recording.log.md, recording.summary.html
```

The launcher installs pinned requirements into `data/.venv`, never globally.
A successful-install stamp records the SHA-256 of `requirements.txt`; unchanged
requirements reuse the environment without pip, while changed or interrupted
installations are retried online. Ordinary source updates do not require new
model downloads unless the manifest changes. Tests import `src` through
`tests/__init__.py`, without installing Scribe as a package; they still need their
Python dependencies.

The environment refers to a separately installed Python and is disposable, not
a bundled Python distribution. Recreate it after moving the application or
changing Python, while preserving models, recordings, results and API caches:

```bash
rm -rf data/.venv
./scribe.sh --setup
```

Legacy `data/runtime/python` is a launcher compatibility fallback when no new
environment exists. Setup uses the separately installed Python; after successful
migration, the old runtime is no longer required.

Application-relative paths hold `.env`, the environment, models and caches.
Ordinary input/output `./data` is instead relative to the launch working directory;
monitor outputs default to the watched folder. Only `--output-dir` relocates results; models and caches stay in the application's
`data/models` and `data/.cache`. The environment stays in `data/.venv`.

SCR-090 console logs instead always follow the caller cwd: `data/log/` contains
exclusive UTF-8 files named by local date and a stable start-time/PID/random run
identifier. Midnight rotates on the next write, retaining that identifier; there
is no retention/deletion policy. A supervisor mirrors stdout/stderr descriptors,
using PTYs only for original TTY outputs to preserve progress detection and
terminal dimensions. The launcher starts it before setup checks; a parent-PID
marker prevents a second log across exec into Python. Direct CLI uses the same
helper, with no import side effects or extra dependencies. File copies clean
terminal controls and redact configured credentials; optional logging failures
warn and preserve console operation/worker status. Original stream ordering is
preserved within each descriptor; scheduling between stdout and stderr is not a
global chronology. See [console behavior](USAGE.md#console-logs) and
[isolated logging checks](../tests/test_console_log.py).

Keep both static resources with the source when copying the application:
`summary.html` is the standalone report template; `models-manifest.json` defines
model paths, pinned URLs/revisions, sizes, hashes and archive extraction rules,
including offline verification. Downloads and the native runtime live in
`data/models`, with runtime libraries and license notices under `diarization/`.
Installation allowlists archive members and always checks executable/library
hashes. Online runtime repair preserves the previous directory as `.previous-*`.
No separate NVIDIA toolkit, compiler or global runtime is required.

Setup prepares only selected assets without paid API calls. Default assets are
public; optional Community-1 needs HF authorization for its initial download.
Scope credentials to gated requests and strip them on redirects. Prepare each
machine online before offline use. Weights can be copied and checked with
`--verify-models`; recreate the Python environment on each machine. API-only
recognition does not need local weights. Old ONNX assets are preserved but unused;
old diarizer intervals cannot satisfy Nemotron checkpoints.

### Recognition cache artifacts

SCR-093 uses `data/.cache/<full-source-sha256>/`, hashing every source byte once
per stable invocation needing cache access. Names/stat timestamps are metadata,
not identity; renamed/copied identical recordings reuse work. There is no global
run-folder search index. Stage keys canonically include model/settings and relevant
upstream payload identities; variants coexist in flat JSON files. Envelopes validate
schema, settings/key and payload hash. The manifest inventories stages and explicitly
selects finals globally and per export location. Output ownership/backups remain
under output-scoped state; content and output locks prevent concurrent duplicate
processing/publication. Source-change guards precede inference and publication.

Recognition retains backend payloads and normalized data, GPT chunks, raw WhisperX
ASR before alignment, raw alignment/words, independent MLX results and shared
Nemotron/Community-1 intervals. Reconciliation parts remain independently resumable.
Final JSON keeps turns/names/uncertainty/supplements, frozen sources, dependencies
and complete/partial/fallback/offline status. Materialization is also JSON, with text
and a validated final reference. Summary levels/header responses are flat and
reusable after publication; renderer/tab/output changes do not invalidate ASR.
Library/model/environment caches, timings, console logs and temporary audio keep
their separate roles. Application bytecode stays disabled; dependency bytecode stays
in `data/.venv`. See [layout and recovery](USAGE.md#processing-cache-and-exports).

Exported `.log.md` and HTML are never pipeline inputs. Summary-only uses selected
internal final JSON, even with absent or edited logs; it never extracts audio or
runs ASR, diarization or reconciliation. It preserves existing log bytes and may
recreate a missing export. Summary-only force refreshes summary/header only; changing
its model does not select another reconciliation result. Missing/ambiguous/invalid
final JSON fails clearly. Completed-pair skips and edited/unknown-output protection
remain. This deliberately supersedes the old edited-log/log-only summary contract.

Legacy JSON migrates lazily through direct old path lookup, without deleting originals
or inventing raw responses. Historical edge hashes remain explicitly weaker provenance,
not retroactive full-file proofs. Final reconstruction requires compatible upstream
JSON, cached validated reconciliation, frozen snapshots and reproduced transcript hash;
insufficient state/log-only results fail without reading exported logs. Legacy
rename lookup and missing raw/duration/final checkpoints are recovery limitations;
[Usage](USAGE.md#older-json-checkpoints) owns detailed prerequisites.

The CLI uses automatic language detection and no custom vocabulary prompt. Internal
backend fields retain those default values and the existing checkpoint schema,
so removing their CLI overrides does not invalidate default recognition caches.
WhisperX language detection now probes speech selected from existing voice intervals,
merging overlaps and bounding work to three disjoint 30-second speech probes. A
first probe with at least ten seconds, top probability >=0.8 and margin >=0.2 ends
selection early; otherwise duration-weighted probabilities select the language.
These are operational heuristics, not calibrated accuracy guarantees. Weak or mixed
results are reported. The original waveform is retained for ASR/alignment; explicit
internal language selections bypass probing. Word checkpoints retain probe evidence.
The WhisperX adapter identity changed to 2, invalidating old words but preserving
compatible cloud/voice stages. Completed output pairs still skip unchanged.

SCR-083 established that raw-first-30-second detection chose English on digital
silence; a later speech window selected Russian. SCR-085's production detector was
also checked locally on speech from the cached July-recording intervals: Russian
0.9989 on 27.08 seconds of speech within the first 100 seconds of audio. This is
one language-selection smoke check, not a full-recording accuracy benchmark.
Private evidence: [investigation](../data/comparison/july-language-investigation/README.md)
and [implementation checks](../data/comparison/reconciliation-resilience-preview/VERIFICATION.md).
Tests and isolated experiments may set `args.cache_dir` and `args.models_dir` on
the parsed namespace; CLI path overrides are no longer accepted. Main-entry tests
use `tests.runtime_paths()` to keep temporary paths isolated while loading `.env`
before building the parser. Reuse compatible stages rather than deleting caches.
`--setup` is the single preparation command; its former download alias is removed.

## Pipeline contracts

Recognition supplies words; independent diarization supplies voice/time anchors.
WhisperX Turbo is the default recognizer, with MLX and cloud alternatives.
WhisperX uses CPU int8, batch four, four threads and beam five, with local pyannote
VAD and forced alignment. Language detection runs per recording; MLX uses Apple
Silicon acceleration and detects language per chunk.
Nemotron 3 is the default diarizer, using pinned NeMo-Speech.cpp and automatic
speaker counting; Community-1 remains optional. The pinned CPU runtime uses Q8_0
weights and the `v3-offline` stateful chunk preset, with capacity for eight voices.
It sends no audio to NVIDIA or Hugging Face. Forced speaker counts and
sample-specific clustering thresholds are not the production design.

Every ordinary recognition mode runs final GPT text reconciliation. `all` runs
three recognizers independently, shares one diarization pass, and keeps WhisperX
voice/time anchors. Local-only recognition modes send text, not audio, to GPT.
API-only mode must not load local models or invent speaker assignments from its
chunk text/timing. Explicit `--offline` prohibits API calls and downloads and
produces no report. Disabling reports alone does not disable reconciliation;
the configured report model/effort controls both, with the default used when
reports are disabled. Summary-only processing uses selected internal final JSON and
never repeats recognition or reconciliation.

Reconciliation cannot move anchors, change voice assignments or omit/duplicate
anchors. Single-source review cannot erase speech/recognition uncertainty or invent
unassigned speech. Speaker-only annotation loss is recoverable: retain corrected
words, conservatively mark the whole affected turn uncertain, and keep the exact
original in raw sources. Corrected uncertain spans cannot establish names alone.

Returned-content validation failures receive two corrective retries per part.
Transport/authentication/quota errors retain their own retry policy. Rejected
responses and precise errors are saved before retry; successful parts are cached.
After exhausted recovery, retain only the unresolved part's primary-source text
and continue later parts. Partial logs list unresolved ranges, HTML shows a notice,
and state remains incomplete. Accepted parts can supply citation-validated names.
Summaries read this explicit partial log. API-only mode never substitutes local
recognition or invents speakers. Original sources remain available.

Output-scoped `meeting.summary.err` is an atomic JSON history containing failed and
recovered attempts, diagnostics, rejected responses and available API usage. No
sidecar is created on a clean first run; a clean rerun records completion in existing
history. Completed-pair skips change nothing. Ownership and output locks protect
history; unknown/symlink sidecars stay untouched. Credentials are redacted, but
transcript excerpts remain private data. Recording-stage failures, including model
preparation, are recorded; unassigned CLI/configuration errors stay on the console.

Speaker names are display metadata, resolved across the whole recording from
validated evidence attached to fixed voices. Supported introductions and coherent
address/response exchanges can establish names; conflicting unresolved claims
retain anonymous Latin labels. Established human names take precedence over
casual nicknames. Citation validation does not prove correct social interpretation
or diarization. Keep speech confidence and voice uncertainty on affected spans.
Preserve actual participant names and the conversation's predominant language;
never use external knowledge to guess identities or repair the apparent quality.

SCR-089's successful Russian rerun had `speaker_names: []` in all 16 matching
responses: no candidates reached validation/resolution, and saved log/HTML agreed.
Opening name/reply quotes lay inside uncertain attribution spans; the existing
naming policy excludes them. Six unrelated unattributed fragments also set the
whole-recording context flag; this does not prove an additional participant.
The model's exact reason for abstaining is unavailable: empty name lists carry no
reason/status, and reports currently give no explicit explanation for anonymous
labels. Successful reconciliation does not guarantee name discovery. No naming
fix is implemented; see private [SCR-089 evidence](../data/comparison/july-speaker-names-investigation/README.md).

The SCR-089 investigation is complete. A later proposed prompt experiment was not
performed: a possible follow-up could compare the current prompt with a clearer
evidence-focused variant on saved opening GPT-Transcribe/WhisperX sources using
`gpt-6.1-sol:medium`. Such an experiment would preserve source data, uncertainty,
validation and ordinary outputs, retain exact prompts/responses and returned usage
under ignored comparison data, and distinguish candidates from validated names.
It would not require full audio recognition or report regeneration; no improved
name recovery has been established by this unperformed proposal.

## Resume behavior and failures

Word, voice, cloud-audio and final reconciliation checkpoints have independent
identities. Changing only the recognizer can reuse compatible voices; changing
only the diarizer can reuse compatible words. Backend revisions, presets, source
signatures, model/effort and prompts must invalidate the appropriate stages.
Legacy backend caches cannot satisfy a different engine's signature.

Keep `data/.cache` to retain resumability and output ownership. Changed source
bytes have a different cache identity; identical bytes after a move retain it. Unknown partial outputs stay protected. Summary-only preserves edited
exports while using internal JSON; ordinary force deliberately replaces exports.

Completion skipping deliberately depends on an existing log plus either current
HTML or legacy Markdown summary, even after settings change. Incomplete outputs
require matching ownership/settings; edited logs are protected. State is scoped
to each output location. Writes are atomic and output locks prevent concurrent
processing of the same result. Replacement backs up logs and summaries; transcript
changes must not leave an old summary presented as current. Summary/header work
is checkpointed and publishes the report only after all selected levels succeed;
failed regeneration preserves existing reports. See `_process_file()` and the
mode, source-report and summary tests before changing these contracts.

Completed pairs remain untouched by ordinary runs even if their state is missing.
Failures for one recording are reported and processing continues with other inputs.
Authentication, unavailable models, quota limits, refusals and incomplete responses
are errors. Quota errors are not retried; transient HTTP 429/500/502/503/504 errors
receive at most two retries. Credentials are redacted from caught errors.
Ctrl+C preserves completed files.

Exit codes: `0` for success/skipped inputs, `1` for per-recording failures, `2` for
input/configuration errors, and `130` for interruption.

Source views freeze successful raw inputs before reconciliation and bind them to
the source signature and final-log hash. Summary-only rendering uses the selected
final JSON and its frozen sources, never unrelated shared checkpoints or edited
exports. Raw sources remain unchanged by reconciliation.

## Editable prompts and long recordings

The actual instructions are constants near the top of `src/scribe.py`:

- `FUSION_PROMPT` and `SINGLE_SOURCE_PROMPT`: reconcile combined or single-source
  text while preserving fixed voice/time anchors.
- `SUMMARIZATION_PROMPT`: final summary template, including language and detail rules.
- `PART_NOTES_PROMPT`: detail-aware factual notes template for long transcripts.
- `REPORT_HEADER_PROMPT`: grounded topic and role extraction for the HTML header.
- `REPORT_TOPIC_PROMPT`: combine supported topics from every part of a long log.

`summary_prompt()` fills `{summary_detail}`, `{summary_min_words}`, and
`{summary_max_words}` in the final template. `notes_prompt()` fills
`{summary_detail}` and `{notes_word_limit}` in the notes template. The selected
detail is also recorded in the summary cache settings.

Transcript content is treated as untrusted data, never executable instructions.
The prompts prohibit invented facts, speech, speakers, decisions, and deadlines.
Fusion can change text but cannot change anchor IDs, internal speaker IDs, or times.
Transcript-supported display names are returned separately as `speaker_names`;
the caller applies them to the fixed voices after resolving the whole recording.
The application rejects responses that omit or duplicate anchors; bounded recovery
retains source text for unresolved parts. Speaker-marker loss is repaired conservatively
without discarding corrected words.

Transcripts over 180,000 characters are processed into notes for every part, with
further reduction layers if necessary. The end of a long recording is not simply
truncated. Long recordings may need additional paid calls. The summary cache tracks
both summary and notes prompts, detail, model, effort, and final log content, but a completed
pair is still skipped unless explicitly regenerated.

Audio is converted to mono 16 kHz PCM and divided into non-overlapping chunks of
at most 10 minutes, below a conservative 24 MB upload limit. Successful GPT chunks
are checkpointed immediately. Fusion processes every primary chunk, using adjacent
chunks only as context. Responses API calls use `store=false`, no tools/web search,
and strict JSON output for fusion. Audio and text are subject to the API account's
applicable data policies.

## Reports and text processing

Each summary level reads the same final log independently; detail controls retained
information, separately from reasoning effort. Page guidance is not a padding quota.

Reports are standalone HTML with inline CSS/JavaScript and escaped model text and
filenames. Transcript selection includes the complete internal transcript and
available raw sources; omitting it excludes both. Summary and Transcript dropdowns have fixed
titles, independent last choices on their second lines, and stable item order.
Summary levels use readable names and separate N/10 depth labels, never percentages;
non-default levels retain a generic Summary label and their numeric depth. Inline
decorative SVG icons require no external assets. Model badges reflect actual provenance:
one shared footer badge from summary configuration, saved-log provenance for Final transcript;
unknown provenance omits the badge. Existing HTML needs explicit regeneration
for renderer changes. Browser storage failures must not break navigation/theme
controls; file-origin theme persistence across paths is browser-dependent.

Header roles require supported evidence; conflicts or missing facts stay unknown.
Names come from final-log turn labels. Duration and recording date come from log
metadata or a valid, unambiguous ISO date/time embedded in the filename, never
filesystem timestamps or model guesses. The separate Generated stamp stores an
aware UTC rendering instant and is formatted in the viewer's timezone.

## Local progress and timing

Local progress/ETA (SCR-088) uses optional bounded `data/.cache/timings.json`,
grouped by stage, model/runtime settings, machine fingerprint, Python/requirements.
Only successful computed stages teach rates; cached work adds no forecast time.
Median rates/pairwise slopes and conservative ranges model loading overhead when
supported. Startup forecasts follow extraction and exclude setup, extraction and
unmeasured API/report work. Missing history is explicit; the first Nemotron run
can have no numeric ETA. WhisperX recognition/alignment callbacks supply segment
progress; elapsed-time heartbeats never imply inference progress. Nemotron uses
one stateful process with streamed bounded diagnostics, no inferred percentage,
and terminate/kill/reap cleanup. Optional history is atomic, bounded-lock merged,
and never required for success. No recognition identities/settings changed.
See [usage](USAGE.md#progress-and-time-estimates) and private
[verification/example](../data/comparison/progress-preview/VERIFICATION.md).

## Recording monitor

The foreground monitor selects observed size growth and processes serially through
the ordinary pipeline. Stationary files and timestamp-only changes do not qualify;
short recordings can finish between polls. There is no durable queue, background
service or automatic retry of unchanged failed files; manual processing is the
recovery path. Monitor outputs default to the watched folder, unlike batch output.

MKV has no mandatory EOF marker. `obs_mkv_readiness()` checks stability, a finite
Segment ending at the file boundary, and bounded metadata/audio structure while
skipping media payloads. Recheck source snapshots around inspection/extraction.
This is an OBS finalization heuristic, not a full integrity check: recovered or
streaming MKVs can fail it and later reopening by a writer cannot be ruled out.
Only the first audio stream is extracted; it must contain all required voices.
Video is not analyzed. OBS scripting/WebSocket bridges are not implemented.

## Experiments behind the current decisions

WhisperX Turbo retained more technical terms and disagreed less with cached GPT
text than MLX on two recordings. Full large-v3 improved the longer recording but
was slower and still introduced name errors. These observations support Turbo as
the routine recognizer with optional cloud recognition/reconciliation; they do
not isolate model weights from runtime, VAD, decoding or alignment differences.

A fixed two-speaker setting split a known monologue. Automatic clustering could
recover one voice, but a threshold that worked there over-split the two-person
control. Community-1 and native Nemotron both returned the expected one/two counts
without hints. Nemotron ran substantially faster in those deployment checks and
needed no gated download, motivating its default status. Precision and threading
differed, so this was not a controlled speed or speaker-accuracy benchmark.

Sol reconciliation passed validation on identical cached sources; Luna failed
twice by removing required uncertainty markers. On the accepted Sol log, Luna's
summary also missed a substantive correction. Keep Sol as the default and preserve
strict validation; cheaper tokens did not establish equivalent quality. This is
sample-specific evidence, not a universal model ranking.

Detailed private evidence, when available, remains under ignored
`data/comparison/whisperx-comparison/`, `diarization-comparison/` and `luna-vs-sol/`.
It is not required for a fresh checkout.

## Quality and validation limits

These comparisons use a few recordings without independent human-reference
transcripts or speaker annotations. Agreement with another model is not WER/DER
or proof of correctness; better words cannot fix wrong voice anchors.
Overlaps, technical names and untimed words remain error sources. Untimed words
must be retained with approximate bounds and uncertainty; alignment scores are
separate from recognition confidence. WhisperX currently prepares English/Russian
alignment, not arbitrary detected languages.

Mocked tests cover contracts, not multi-hour accuracy or universal latency. Real
OBS active/paused/stopped/crashed scenarios and long mixed-language recordings
still need representative manual validation. Text requests have a 600-second
timeout; transport timeouts are not retried by the transient HTTP retry loop.
Missing returned usage does not establish zero billing. Reuse cached sources for
experiments and preserve ordinary outputs; the mocked test command is below.

## Examples

```bash
# Default: WhisperX Turbo + Nemotron voices, Sol reconciliation and summaries
./scribe.sh

# API transcription and summary, without local voice models
./scribe.sh -f "recording.mkv" --transcription-model gpt-transcribe-online

# MLX alternative, followed by an API summary
./scribe.sh --transcription-model mlx

# Cloud audio recognition and final GPT reconciliation, without reports
./scribe.sh --transcription-model gpt-transcribe-online --summarize-model none

# Strictly local log; no network calls or summary
./scribe.sh --offline

# Luna for fusion and summary on an unfinished recording
./scribe.sh --transcription-model gpt-transcribe+whisperx --summarize-model gpt-6-luna:medium

# Compare all three recognizers; GPT reconciles text with fixed WhisperX anchors
./scribe.sh --transcription-model all

# Deliberately replace only an existing summary using Luna
./scribe.sh -f "recording.mkv" --summary-only --summarize-model gpt-6-luna:medium
```

## Validation and comparison

```bash
./data/.venv/bin/python3 -I -B -m unittest discover -s tests -t . -v
```

Run this command from the project root. The explicit top-level directory (`-t .`)
loads the test package and its source-path setup before collecting the tests.

The checks use mocks and local fixtures, without paid API calls. They cover input
paths, voice labels, uncertainty spans, all modes, offline isolation, completed-pair
skipping, API failures, ownership, retries, cache reuse, prompt chunk coverage,
model verification, detail propagation, output budgets, and detail-aware long-input
notes. Native diarization checks cover automatic counts, first-appearance voice
IDs, overlaps, invalid output rejection, checked anonymous runtime downloads,
archive/link safety, offline integrity checks and repair, legacy voice-cache
invalidation with Whisper-word reuse, and protected old local/API-only outputs.
WhisperX checks cover selected assets, scoped gated authentication, tokenizer
integrity, local CPU ASR/alignment, independent recognizer/voice cache identities,
retention of untimed words, and separation of alignment scores from ASR confidence.
Configuration checks cover the four default summary tabs, `.env` lists, environment
and CLI precedence, single-tab HTML overrides and transcript-only selections, and invalid defaults. HTML
checks cover multi-level parsing, escaping, tab associations, completed
output protection in either format, interrupted-level reuse, invalidation, and
preservation of existing results on failure. Transcript checks cover exact embedded text,
per-output source snapshots, raw inputs after fusion/fallback, mode-specific source
tabs, edited/legacy-log isolation, and source-tab keyboard/theme interactions,
three-recognizer comparison with final GPT reconciliation, independent local word checkpoints,
one shared forced diarization, retry of missing stages and historical-all protection,
long-log completeness, escaped markup, the inline icon, and copying the HTML
without its source log. Header checks cover role citations,
unknown participants, date/duration provenance, long-log coverage, conflicting
roles, escaped metadata, checkpoint revalidation, and preservation after header
failures. Name checks cover introductions, cross-chunk address/response evidence,
conflicts and corrections, invalid citations, shared names, checkpoint reuse, and
two-/three-person address evidence, human-name preference over nicknames, and names
reaching the final log and summary. Setup checks cover a ready virtual
environment without a bundled runtime, offline rejection of outdated dependencies,
the data-folder placeholder in a fresh checkout, and Git exclusions for private
and generated files. Menu checks cover names and numeric depth for all ten levels,
fixed titles, the decorative microphone, and separate summary/transcript provenance.
When Node.js is available, an optional offline JavaScript check executes the actual
report script for theme restoration/toggling, cookie fallback, blocked storage,
and tab navigation; it is skipped otherwise. Node.js is not required to run Scribe.
Input-directory checks cover relative and home paths, uppercase extensions,
non-recursive scanning, symlink deduplication, invalid folders, exclusive `-f`
selection, independent batch output defaults, and same-folder HTML generation with
completed-result preservation.
Monitor checks cover monitor-folder output defaults, OS-specific bare monitor
presets, explicit output precedence, growth selection among stationary files,
existing active recordings, empty folders, new recordings,
pause-like stability with unknown Segment size, metadata-only changes, malformed
or truncated containers, missing audio, source-change guards, failure isolation,
output collisions, and the normal processing path. They use simulated time and
local fixtures, without waiting 30 seconds or making paid requests.
The original seven-minute recording has also been used
for real API comparisons. In the original local installation, preserved Sol
results, controlled Sol/Luna outputs, rejected candidate diagnostics, and usage/cost
estimates are stored under `data/comparison/luna-vs-sol/`. These are local experiment
artifacts and are **not included in the Git repository**. A fresh GitHub checkout
does not contain the recordings, comparison transcripts, summaries, reports, or
usage logs. Except for `data/.gitkeep`, the contents of `data/`, including
`data/comparison/`, are excluded by `.gitignore`; setup does not download or
recreate those private comparison files.
If you have the local comparison report, consult it before choosing Luna for
fusion: a lower token price does not establish equivalent transcript quality.

Official references: [API pricing](https://developers.openai.com/api/docs/pricing),
[GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol), and
[GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna).

SCR-084–086 checks additionally cover leading silence, overlapping/short speech
probes, language voting and explicit decoding, bounded part retries and resume,
nonfatal speaker-marker recovery, partial report notices/source snapshots, and
error-file history, early failures, ownership/symlink protection and redaction.

SCR-093 verification on 2026-11-08: the full mocked suite passed 244 tests without
paid calls or model downloads. [Content-cache checks](../tests/test_content_cache.py)
cover full-file/middle-byte identity, rename/output reuse, flat variants, selected
finals with edited/missing exports, corrupt references, source changes, atomic
writes/content locks, raw ASR/alignment resume, batch preparation, offline reuse
and legacy final/summary/header adapters that preserve original JSON. Live model
accuracy and historical full-file identity of legacy edge-hash data are not
established by these mocked checks.

## Finder hooks (SCR-097)

`macos-register-finder-hooks` is a separate Bash 3.2 launcher. Its top-of-file
`MENU_TITLE` and `run_conversion(file, file_dir)` are the only editable behavior
configuration. The ordinary command adds only absolute `-f` and `--output-dir`,
preserving WhisperX/GPT defaults and configuration precedence. It resolves input
symlinks before deriving outputs, changes to the project root for console logs,
waits synchronously, and opens HTML only after exit 0. It preserves normal skip,
cache, lock and resume behavior. It never prepares Python/models during registration.

The generated `Scribe Local Conversion.workflow` has stable identity
`org.scribe.finder.local-conversion`; the editable display title is separate.
Plist serialization escapes dynamic values. Replacements are prepared and parsed
before replacing an owned bundle, with rollback on rename failure. Foreign or
symlink destinations are refused. The workflow contains only delegation to the
installed script path, not the conversion function. Re-register after a project
move or title change. Terminal receives a quoted foreground `/bin/bash SCRIPT
--run FILE` child through AppleScript argv; its interactive parent remains open.
NSWorkspace resolves the HTTPS handler without navigation; `open -a` explicitly
uses it for HTML. [Apple's lookup contract](https://developer.apple.com/documentation/appkit/nsworkspace/urlforapplication(toopen:)-7qkzf).

Verification on 2026-11-12, macOS 14.5 (23F79), system Bash 3.2.57:

- Full suite after review fixes: **267 tests passed** (244 existing + 23 hook tests), using
  `/opt/projects26/scribe/data/.venv/bin/python3 -I -B -m unittest discover -s tests -t . -v`.
  No real recordings, model downloads or paid API calls. Hook fixtures cover
  literal special-character paths, relative paths/symlinks, synchronous completion,
  normal skips, failure/SIGINT/stale HTML, missing HTML/legacy Markdown, browser
  errors, edited conversion functions, CLI validation, interpreter discovery,
  ownership/symlink/write failures, safe replacement, rename and relocation.
- `/bin/bash -n` passed. Generated `Info.plist` and `document.wflow` passed native
  `plutil -lint`; Terminal AppleScript passed `osacompile`. Native `automator -i`
  executed a temporary workflow and delivered exact `--launch` argv to a harmless
  target with Cyrillic, quotes, spaces and shell metacharacters.
- A temporary project under `/tmp/scr097-ui` registered a harmless action in the
  real Services directory. There was no preexisting Scribe installation. Finder
  exposed it in **Finder → Services** and directly in the MKV context menu.
  Initial invocation displayed native error **-1743** and the launcher's
  permission guidance. After the user enabled Terminal automation, Finder launched
  a distinct Terminal window (7208); fixture progress and final output were visible.
  A completion gate proved no browser dispatch while conversion remained active.
  The prompt returned, `busy=false`, and a subsequent `printf` executed in the shell.
- Real failure 7 (window 7215) and physical Ctrl+C (7220) retained diagnostics,
  output bytes and interactive prompts. Neither opened old HTML. Synthetic TXT
  was offered the service but rejected at runtime without conversion. Action title
  rename and project relocation were exercised through Finder, retaining one bundle;
  the relocated command executed from the moved project (window 7231).
- Native HTTPS and HTML associations both resolved `/Applications/Velja.app`.
  Actual `open -a` dispatch opened the first fixture report in Firefox, whose window
  title matched the synthetic report. Velja may show its browser/profile selector;
  the launcher leaves that policy to the system handler. A deliberately differing
  HTML-editor association was **not** configured or tested natively; adapter tests
  cover that routing decision. Completed-pair skipping was fixture-tested, without
  running the real ASR pipeline.
- The real **Quick Actions** submenu showed only **Customize…**, while the Scribe
  service worked from the context menu/Services. Modern Quick Action metadata, including standard service icon/background fields,
  is included, but discovery/enabling of Scribe inside that submenu and invocation
  through that exact route remain **unverified**. No unrelated extension setting
  was changed. SCR-097 stays **In Progress** until that acceptance check is resolved.
- The temporary workflow was removed twice; later diagnostics found that
  `pbs -update` retained its deleted discovery entry. Refresh now uses `pbs -flush`
  followed by `-update`. Native install/removal with the corrected script passed,
  `pbs -dump` no longer listed Scribe, and `NSServicesStatus` before/after snapshots
  compared byte-for-byte equal. No production action or discovery entry was left
  pointing to the temporary project; unrelated services and source-checkout
  changes were preserved. Private data, `.env`, caches and reports were untouched.

The Python `-I` named-module unittest command in the plan cannot import the local
`tests` package on this runtime. Discovery with explicit `-t .` is the verified
command and provides the same test package setup used by the existing suite.

Final independent review (fresh `gpt-6-astra/high`) ran the full 266-test suite
and found no additional runner/registration defect. It flagged the unqualified
Quick Actions instructions as Important; README, usage and installer now describe
the verified Services route and explicit Quick Actions enablement. The user
chose to defer exact-submenu acceptance, so SCR-097 remains In Progress. The single
fix pass added standard `NSIconName`/`NSBackgroundColorName` metadata and corrected
stale cache refresh; both regression contracts were observed RED → GREEN, with
267/267 tests and native plist/removal checks green afterward. No second review
was dispatched. A Minor task-table formatting finding was deferred: SCR-097's row
is separated from the existing table by a blank line.

The user also reported **Settings Error: Extension process Extensions exited**.
Crash reports `Extensions-2026-11-12-004204.ips`, `004634.ips` and `004901.ips`
show EXC_BAD_ACCESS/SIGSEGV in the macOS Extensions host; the first includes
`NSQuickActionGetIcon`/NSImage drawing. This is a different failure from Terminal
permission denial and does not show conversion terminating early. A control
attempt without the workflow file was inconclusive because its cached discovery
entry still existed. The test entry was then removed with the corrected cache
refresh. The cause of the Settings host crash and a checkbox/submenu retest remain
unverified; no extra permission or unrelated setting was changed as a workaround.

Execution decisions: the plan's isolated named unittest import was replaced by
explicit-top-level discovery (cost: changed collection scope, recorded counts).
Exact Quick Actions acceptance was deferred at the user's request (cost: further
native integration work may remain). Code and documented evidence are committed;
private source-checkout data and unrelated task edits were not copied or modified.
