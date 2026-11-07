# Scribe: development context

Keep this file focused on architectural decisions and unresolved limitations.
[README](../README.md) owns setup and public behavior;
[AGENTS](../AGENTS.md) owns development agreements;
[src/scribe.py](../src/scribe.py) owns prompts, schemas and implementation.

## Structure and runtime

Keep the application portable and simple: `scribe.sh` prepares the isolated
Python environment and launches `src/scribe.py`; static resources live in
`src/resources`, with mocked tests in `tests`. Current native support is macOS
Apple Silicon with Python 3.12-3.13. Cross-platform folder presets do not imply
cross-platform model/runtime support. Docker integration is deferred.

Dependencies, pinned model assets, native runtime and checkpoints live under
ignored `data/`; only `data/.gitkeep` is tracked. Private experiment artifacts
under `data/comparison/` are optional local evidence, never checkout prerequisites.
Setup prepares selected assets without paid API calls. Default assets are public;
optional Community-1 requires HF authorization for its initial download. Scope
credentials to those gated requests and strip them on redirects. Native runtime
installation allowlists archive members, always verifies executable/library
hashes, and stages repairs without destroying the previous runtime.

## Pipeline contracts

Recognition supplies words; independent diarization supplies voice/time anchors.
WhisperX Turbo is the default recognizer, with MLX and cloud alternatives.
Nemotron 3 is the default diarizer, using pinned NeMo-Speech.cpp and automatic
speaker counting; Community-1 remains optional. Forced speaker counts and
sample-specific clustering thresholds are not the production design.

Every ordinary recognition mode runs final GPT text reconciliation. `all` runs
three recognizers independently, shares one diarization pass, and keeps WhisperX
voice/time anchors. Local-only recognition modes send text, not audio, to GPT.
API-only mode must not load local models or invent speaker assignments from its
chunk text/timing. Explicit `--offline` prohibits API calls and downloads and
produces no report. Disabling reports alone does not disable reconciliation;
the configured report model/effort controls both, with the default used when
reports are disabled. Summary-only processing preserves the saved final log and
never repeats recognition or reconciliation.

Reconciliation cannot move anchors, change voice assignments, omit/duplicate
anchors or erase uncertainty markers. Single-source review cannot invent
unassigned speech. Preserve the usable source log before text API calls; failed
reconciliation leaves an explicit fallback and an incomplete final stage for
retry. Combined recognition can fall back to local text if cloud recognition
fails; API-only recognition must not silently substitute a local model.

Speaker names are display metadata, resolved across the whole recording from
validated evidence attached to fixed voices. Supported introductions and coherent
address/response exchanges can establish names; conflicting unresolved claims
retain anonymous Latin labels. Established human names take precedence over
casual nicknames. Citation validation does not prove correct social interpretation
or diarization. Keep speech confidence and voice uncertainty on affected spans.
Preserve actual participant names and the conversation's predominant language;
never use external knowledge to guess identities or repair the apparent quality.

## Checkpoints and output protection

Word, voice, cloud-audio and final reconciliation checkpoints have independent
identities. Changing only the recognizer can reuse compatible voices; changing
only the diarizer can reuse compatible words. Backend revisions, presets, source
signatures, model/effort and prompts must invalidate the appropriate stages.
Legacy backend caches cannot satisfy a different engine's signature.

Completion skipping deliberately depends on an existing log plus either current
HTML or legacy Markdown summary, even after settings change. Incomplete outputs
require matching ownership/settings; edited logs are protected. State is scoped
to each output location. Writes are atomic and output locks prevent concurrent
processing of the same result. Replacement backs up logs and summaries; transcript
changes must not leave an old summary presented as current. Summary/header work
is checkpointed and publishes the report only after all selected levels succeed;
failed regeneration preserves existing reports. See `_process_file()` and the
mode, source-report and summary tests before changing these contracts.

Source views freeze successful raw inputs before reconciliation and bind them to
the source signature and final-log hash. Summary-only rendering must not borrow
unrelated shared checkpoints. Edited or legacy logs without compatible snapshots
show only their final view. Raw sources remain unchanged by reconciliation.

## Reports and text processing

Each summary level reads the same final log independently; detail controls retained
information, separately from reasoning effort. Long inputs use notes covering every
part, with further reduction as needed, rather than truncating the end. Prompt
constants in `src/scribe.py` remain canonical; page guidance is not a padding quota.

Reports are standalone HTML with inline CSS/JavaScript and escaped model text and
filenames. Transcript selection includes the complete saved log and available raw
sources; omitting it excludes both. Detail and Transcript dropdowns keep independent
last choices and stable item order. Model badges must reflect actual provenance:
summary configuration for Detail, saved-log provenance for Final transcript;
unknown provenance omits the badge. Existing HTML needs explicit regeneration
for renderer changes. Browser storage failures must not break navigation/theme
controls; file-origin theme persistence across paths is browser-dependent.

Header roles require supported evidence; conflicts or missing facts stay unknown.
Names come from final-log turn labels. Duration and recording date come from log
metadata or a valid, unambiguous ISO date/time embedded in the filename, never
filesystem timestamps or model guesses. The separate Generated stamp stores an
aware UTC rendering instant and is formatted in the viewer's timezone.

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
experiments and preserve ordinary outputs; README documents the mocked test command.
