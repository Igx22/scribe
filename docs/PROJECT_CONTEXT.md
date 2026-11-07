# Scribe: durable project context

Reconciled with version 2.16.0 on 2026-11-07. Historical benchmark results below
refer to version 2.2.0 at commit `034b1a9616f6c152995e6950442e9670c87be08f`.
This document preserves rationale and important evidence from the original
development chat. [README](../README.md) owns setup, options, paths, output
formats, and operational behavior; do not duplicate its reference material here.

## Decisions and their reasons

### Recognition and voices solve different problems

The original local-only results contained too much unclear speech and uncertain
speaker attribution, especially in Russian technical discussion. A live comparison
led the user to prefer cloud recognition for clearer words, while retaining local
voice/time anchors. The resulting combined mode uses two sources and text
reconciliation, rather than asking a text model to infer who spoke from meaning.
SCR-061 later selected WhisperX Turbo as the local default while preserving the
combined option.

Whisper recognizes words. Nemotron 3 establishes voices independently, through
the pinned NeMo-Speech.cpp 0.3.0 CPU runtime and Q8_0 model. It automatically
detects up to eight voices with the tested `v3-offline` stateful chunk preset;
`--speakers N` has been removed. Reconciliation may correct words
but cannot move anchors or change their speaker/time assignments. Speech that
cannot be placed confidently must remain unassigned. Thus clearer recognition
does not establish more accurate speaker attribution.

The five recognition choices are API-only, default local WhisperX Turbo,
local MLX Turbo, API + WhisperX reconciliation, and independent three-source
comparison through `all`. Diarization is independently
selectable between default Nemotron and optional Community-1. A failed cloud
stage in combined mode must still leave a usable local
log; API-only mode must not silently load or substitute local models. See
`configure_mode()`, `_process_file()`, and `fuse_transcripts()` in
[src/scribe.py](../src/scribe.py), with regression coverage in
[test_modes.py](../tests/test_modes.py) and [test_backends.py](../tests/test_backends.py).

The SCR-051 single-speaker investigation found that the default `--speakers 2`
forces two clusters, rather than estimating their count. Repeating diarization
on the user's 94.25-second monologue reproduced the cached false split exactly.
With the same segmentation/embedding models, automatic clustering at thresholds
0.4–0.7 returned one voice; 0.3 returned two. Fixed-one also returned one, but
that is an imposed count. Seven local diarization runs took about 14 seconds each;
rerunning MLX Whisper large-v3-turbo took 11.44 seconds and repeated the cached
text exactly (156 word items). No cloud calls or fusion validation were repeated;
all 12 baseline recording/output/cache files retained their hashes and mtimes.
The user's statement supplies the single-speaker reference, not a full accuracy
benchmark. These measurements predate the SCR-059 Nemotron replacement.
Private evidence: [investigation](../data/comparison/single-speaker-obs-20261107/REPORT.txt).

SCR-054 tested automatic clustering (`num_clusters=-1`, no count hints) on the
user's 425.05-second two-participant recording with unchanged models. Thresholds
0.3/0.4/0.5/0.6/0.7/0.8/0.9/1.0 produced 32/20/14/7/4/3/2/1 voices respectively.
At 0.9 the intervals exactly matched the cached fixed-two baseline; this is a
consistency check, not independently annotated diarization accuracy. Each run
took 63–68 seconds on CPU. Cached Whisper words were reused; no API calls or
fusion validation ran, and all 15 baseline files retained their hashes/mtimes.
Thus 0.5 fails the two-person control despite working for the monologue; 0.9 is
sample-specific evidence, not a validated replacement default. A follow-up
monologue control at 0.9 also returned one voice (13.70 seconds). Private evidence:
[sweep](../data/comparison/two-speaker-auto-thresholds/results.json).

SCR-053 then ran the ordinary manual all-mode pipeline with experimental automatic
clustering (-1, threshold 0.5) in isolated caches/results. Local recognition was
rerun; cached cloud audio transcription was reused, then fusion, four summary
levels, and header were regenerated with `gpt-6.1-sol:medium`. All six text calls
completed, returning 8,396 input / 1,459 output tokens (0 reported reasoning tokens),
without fusion validation failures. The log and header contain only the one
supported participant name throughout. Separate `(2)` HTML/log copies were
published beside the recording, preserving all 12 baseline files by hash/mtime.
Local and report passes took 24.76 and 24.57 seconds respectively on this sample;
this is not a general latency or accuracy benchmark. Markers and approximate
timings remain. Evidence: [report](../data/comparison/single-speaker-report-2/REPORT.txt).

SCR-052 identified [pyannote Community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)
and [NVIDIA's native diarization runtime](https://github.com/NVIDIA/NeMo-Speech.cpp)
as candidates for a measured replacement comparison; subsequent tests are below.
WhisperX adds alignment and pyannote diarization; a different Whisper runtime alone
does not fix fixed-count voice clustering. Full large-v3 is a separate word-quality
experiment. This motivated multi-speaker controls before selecting a replacement,
rather than selecting a threshold from the monologue alone.

SCR-055 ran isolated WhisperX 3.8.6 on both byte-identical test-recording copies,
without changing production code/dependencies. CPU int8, four threads, batch four,
beam five, explicit `ru`, bundled pyannote VAD, and no vocabulary prompts produced
new large-v3-turbo and full large-v3 texts. Existing MLX turbo and cloud
`gpt-transcribe` text were reused. Normalized word edit distances against the API
text were respectively 12.0%/7.3%/12.0% (Scribe/WhisperX turbo/full, monologue)
and 30.9%/21.6%/17.5% (two-person discussion). These measure disagreement with an
automatic reference, not human-reference WER or general accuracy. Turbo improved
technical spellings on these samples; full large-v3 improved the longer text but
also turned Scribe into `skype` in the monologue. Runtime, VAD/chunking, decoding,
language hints, and full-model weights are confounded; no isolated causal claim.

WhisperX ASR took 17.96/85.42 seconds (turbo) and 29.37/150.98 seconds (full).
Russian [wav2vec2 alignment](https://github.com/m-bain/whisperX/blob/main/whisperx/alignment.py)
also completed for all four outputs, with no missing word times or invalid bounds;
timing accuracy lacks human annotation. During SCR-055, Community-1 diarization
was not run because Hugging Face authorization/token was unavailable then.
No audio was uploaded, no new API usage or fusion validation occurred, and all
31 baseline files retained hashes/mtimes. Private texts, revisions, timings, and
checks: [comparison](../data/comparison/whisperx-comparison/comparison.html),
[evidence](../data/comparison/whisperx-comparison/REPORT.txt).

SCR-057 clarified that local inference and gated weight distribution are separate:
WhisperX ASR needs no HF account with its public weights; default Community-1
diarization needs account acceptance/token for download, then runs locally.
[NeMo-Speech.cpp](https://github.com/NVIDIA/NeMo-Speech.cpp) with ungated Nemotron 3
is a CPU/Metal candidate with independent Russian-use evidence: BMeet reports
correct counts on 4/5 hand-corrected Russian podcasts in its own NPU/postprocessed
pipeline. This is not a raw-model or Scribe benchmark. Polyvoice offers ungated
small native CPU models and Mac support; Russian-specific quality remains unverified.
DiariZen and SUPlime have ungated weights but declare non-commercial weight
licenses. That research did not run the alternatives or select a product default;
correct counts alone do not validate turn attribution.
Sources and limitations: [research](../data/comparison/diarization-candidates-20261107/REPORT.txt).

SCR-056/SCR-058 subsequently tested default Community-1 through WhisperX 3.8.6 /
pyannote.audio 4.0.7, plus Nemotron 3 through NeMo-Speech.cpp 0.3.0 CPU Q8_0
(`v3-offline` stateful chunks). Both returned one/two voices on the monologue /
discussion with no exact/min/max count hints. No threshold tuning, voice merging,
ASR, alignment, fusion, or paid API calls were repeated. Community-1 CPU four-thread
passes took 69.51/356.09 seconds, excluding initial 0.99-second model loading;
native Nemotron took 1.65/7.21 seconds including per-process loading, with runtime
thread defaults. These are single-run deployment observations, not a controlled
speed benchmark across equivalent precision/thread settings.

On identical cached WhisperX Turbo words, both new models assigned all 150
monologue items to one voice. For the discussion, they disagreed on 38/785 jointly
assigned word items; Community-1 left three of 788 unassigned, Nemotron zero.
After label permutation, agreement on common single-voice 10-ms frames was 97.42%;
old Scribe fixed-two / automatic-0.9 agreed with Community-1 on 89.74%, differing
on 99/785 jointly assigned word items. These compare model consistency, not human
accuracy or DER. Different silence/overlap coverage remains visible for review.
All 59 baseline files retained hashes/mtimes. Production code/dependencies were
preserved; no default replacement was selected during that experiment. The local HTML has two primary
model columns, two recording choices, optional old Scribe baselines, highlighted
label differences, and local audio seeking. Text/structure and JavaScript syntax
checks passed; browser visual QA was blocked by its file-URL policy. Exact model
revisions, parameters, intervals and checks: [comparison](../data/comparison/diarization-comparison/comparison.html),
[report](../data/comparison/diarization-comparison/REPORT.txt).

SCR-059 selected Nemotron 3 for production. Setup anonymously downloads pinned
public model weights and NVIDIA's macOS ARM64 CPU release, verifies hashes, and
installs only allowlisted archive members with bundled libraries/licenses under
`data/models`. Executable/library hashes are always checked; model hashes remain
controlled by `--verify-models`. Damaged runtime repair stages a checked replacement
and preserves the prior directory. No HF account, GPU toolkit, global runtime,
or native compilation is needed. The old sherpa dependency and ONNX manifest
entries are removed; previously downloaded ONNX files are preserved but unused.

Voice checkpoints now identify the pinned backend/revisions/preset; old sherpa
intervals cannot satisfy them. Compatible legacy Whisper words and GPT audio
responses remain reusable. Completed pairs still skip, old partial local outputs
remain protected against a backend change, and existing API-only logs can resume
despite their obsolete unused speaker-count setting. README owns the migration
and removed-option instructions. These decisions follow two controls, not a
general accuracy benchmark or a claim that eight voices always separate correctly.

SCR-061 makes recognizer identity part of word checkpoints, independently of voice
checkpoints. MLX words cannot stand in for WhisperX; changing only the diarizer
reuses compatible words. Legacy MLX word caches remain reusable with explicit MLX.
Completed pairs still skip, partial outputs with changed settings remain protected,
and summary-only regeneration keeps the final log. API service IDs and cached audio
responses retain `gpt-transcribe`; the renamed public option is `gpt-transcribe-online`.

WhisperX 3.8.6 runs Turbo on CPU int8 with four threads, batch four and beam five,
using local pyannote VAD and prepared English/Russian wav2vec2 word alignment.
Automatic language detection is per recording; MLX retains per-chunk detection.
Other alignment languages are not prepared; unsupported detection fails clearly.
Alignment scores are retained separately from ASR segment confidence. Untimed
words are retained with approximate neighboring bounds and uncertain voice markers.
The default recognizer supplies anonymous labels, without text reconciliation or
name discovery; ordinary summaries still send text unless disabled/offline.

Setup prepares only the selected assets, including local NLTK tokenizers for
WhisperX. Public pinned default assets need no HF account. Optional Community-1
uses a token only for initial gated HF requests, strips it on redirects, and runs
locally after download. Python support is 3.12–3.13 because this WhisperX release
excludes 3.14. The shared environment keeps both recognizers; unused weights and
all existing private outputs are preserved. README owns migration commands.

SCR-064 reintroduces `all` with a new meaning: run GPT-Transcribe, WhisperX Turbo
and MLX Turbo independently, sharing one diarization pass. WhisperX remains the
final log/summary source; all successful raw texts and one shared diarization
are snapshotted into report source tabs. There is no implicit combined-mode,
fusion or name-identification call. Setup prepares both local recognizers and
the selected diarizer. Per-backend word/result checkpoints preserve both local
outputs; compatible shared single-model checkpoints still work in either direction.
The extra MLX identity is part of final-output ownership, but excluded from WhisperX
word/voice cache identity. Force reruns each recognizer and one shared diarization.
Cloud failure leaves local comparison sources; local ASR failure reports an error
and retry reuses completed stages. Offline still forces only WhisperX unless MLX
was explicitly selected. The historical combined `all` is not reused as this new
comparison mode; completed-pair protection and summary-only behavior are unchanged.

### Honest uncertainty and language preservation

Anonymous Latin speaker IDs avoid invented identities and language-specific labels.
The user rejected marking a whole turn because one word was doubtful: recognition
confidence and uncertain voice attribution must stay attached to affected spans.
Fusion's marker checks are deliberate safeguards, not cosmetic restrictions.
See `assign_speakers()`, `fuse_transcripts()`, and
[test_scribe.py](../tests/test_scribe.py).

The tool must support English, Russian, and mixed speech without forcing the
summary into a fixed language. Summary detail controls retained information,
independently of reasoning effort; page counts are guidance, never padding quotas.
The prompt constants and their renderers in `src/scribe.py` are canonical.
`PART_NOTES_PROMPT` is for covering every part of long input, not reconciling the
two recognizers. `FUSION_PROMPT` owns reconciliation.

### Transcript-supported names are display metadata

The user subsequently approved replacing displayed letters with names established
in the conversation. This extends the original anonymous-label requirement without
allowing a text model to change voice assignments. Evidence is returned separately
in the existing fusion response, so no extra naming call is needed. The application
checks quoted anchor references and resolves claims globally before rendering;
contradictory unresolved names retain letters. Citation validation is not proof
that an introduction was interpreted correctly. The prompt, schema, and processing
in `src/scribe.py` own this contract; [name tests](../tests/test_speaker_names.py)
exercise the boundaries. Summaries/notes preserve supplied names rather than
independently guessing identities.

The follow-up clarification accepts coherent named request/response exchanges
without self-introductions or a host: two voices can identify each other through
reciprocal address, while three voices require a clear response/handoff link.
The whole-recording roster is supplied automatically, rather than assuming two
participants from a short chunk. Established human names take precedence over
later casual nicknames; neutral stable handles are allowed when no human name is
supported. The model classifies labels, while the resolver enforces that priority.
These heuristics do not independently validate diarization or social meaning.

Documentation and prompt examples use conventional English names such as Alice
and Bob, and language lists put English before Russian. This presentation rule
does not translate participant names or change summary-language selection.

### Preserve work and avoid unnecessary repeat charges

The user wanted finished recordings left alone and summary experiments to reuse
the final log. Completion skipping is intentionally based on the presence of the
output pair, not automatic validation against changed settings. Explicit summary
regeneration is the economical way to compare summarizers; force regeneration can
repeat recognition charges. This is a deliberate tradeoff, including when the
saved log came from a fallback. Consult README before changing resume semantics.

SCR-065 confirmed the existing force behavior without production-code changes:
normal forced processing regenerates the selected summaries and replaces the
existing HTML, backing up previous logs/HTML/legacy Markdown. Summary-only plus
force regenerates the report while preserving the log and skipping recognition
and fusion. Dedicated mocked CLI/success-path checks cover both cases; all 158
tests passed without model inference or paid API requests. The existing failure
checks continue to cover backups and preservation during interrupted generation.

The public shell launcher is `scribe.sh`; source invocation through `src/scribe.py`
delegates to it when environment preparation is needed. Launcher naming does not
change working-directory handling, model locations, or resume behavior.
The rename passed the 113 mocked tests, shell syntax validation, launcher help/version,
and direct source-invocation delegation, without API calls or model downloads.

The source repository must stay small and portable: downloaded assets and private
experiment files stay outside Git. A separately installed Python plus a disposable
virtual environment replaced distributing an entire Python runtime. The launcher
still has a legacy-runtime compatibility path; it is not the new-install design.
Docker was considered and explicitly deferred. MIT covers Scribe's own source;
third-party assets keep their own licenses.

Fresh checkouts now include `data/` before any launcher invocation, using the sole
tracked placeholder `data/.gitkeep`. The root ignore rules exclude every other
file and subdirectory under `data/`, preserving private recordings, generated
results, weights, caches, and environments outside Git. This replaces the earlier
first-run-only creation behavior; the launcher still recreates a missing folder
when bootstrapping online. Checkout and ignore behavior have regression coverage.

Input discovery and result placement are independent. `--input-dir` selects a
non-recursive MKV batch, while `--output-dir` selects where its logs and reports
are written; both default to the working directory's `data` folder. Explicit `-f`
selection is mutually exclusive with `--input-dir` and retains its existing name
search rules. This supports keeping OBS recordings and results together without
changing default batch behavior. Completed-pair protection still
applies when input and output folders coincide. README owns the usage details.

### Multiple reading depths share one report

Report generation always produces standalone HTML, even with one selected tab.
The default selection is 1, 3, 5, 10, and transcript. `SCRIBE_REPORT_TABS` in `.env`
configures the contents; `--report-tabs` replaces the former summary-detail option
and selects summary levels and/or transcript in the requested order. A transcript-only
selection skips summarization, but retains grounded header extraction. Omitting
transcript excludes its content from the report. An explicit CLI value
takes precedence, and exported environment values retain precedence over `.env`.
The built-in fallback matches `.env.example`, so absent configuration still yields
the four summary levels and Final transcript tab. Each summary level uses
the same saved final log independently, rather than using another summary as its
source. This preserves the existing detail guidance and language/identity rules,
at the cost of one summarization pipeline per level. The inline template lives in
`src/resources/summary.html`; model text and filenames are escaped before insertion.
Detail tabs use the approved decorative dot indicators: exactly N dots for level
N, with subdued colors and at most five dots per row. All ten levels are supported.
These indicators and the Transcript document icon use inline markup/CSS without assets.

An existing log plus either summary format still counts as completed, regardless
of a changed selection. Explicit summary-only generation is required to change a
finished result. Requests checkpoint completed summary levels, including a single
level, and publish only after all summaries and the header succeed; failed
regeneration preserves the old report. Pending
results are invalidated by changed inputs or settings. Forced transcript changes
archive both summary formats to avoid leaving stale results beside a new log.
After successful summary-only generation for an edited log, a known stale summary
in the other format is also archived. Failed generation preserves existing reports.

The approved header adds a common topic, participants with supported roles,
duration, and date. Names are reused from the final log's turn labels rather than
rediscovered during summary generation. Structured role claims require quoted
reliable evidence, including the participant's own turn and the role phrase;
conflicting or unsupported roles are omitted. Semantic attribution still depends
on the model. This avoids inferring a person's job from technical expertise or a
reference to an absent administrator. Long logs are covered in parts with boundary
context, then their supported topics are combined. Independent validated checkpoints
avoid repeating successful header extraction on unchanged inputs.

Duration is parsed from log metadata. Date is parsed from explicit log metadata
or a recognized recording filename, with provenance visible in the report. Neither
is guessed by a text model or taken from filesystem timestamps. Missing facts stay
unestablished. Header extraction now applies to every selection, including one
summary level or transcript alone; README owns the exact formats and request/resume details.

When selected, Final transcript embeds the entire saved final log as escaped text;
the default puts it after all Detail tabs. A decorative document icon is drawn in
the inline CSS. The transcript
is inserted as escaped text with whitespace preserved; it is neither truncated nor
loaded from the separate `.log.md`. This makes the HTML sufficient for sharing as
one file. The separate log remains part of local output/resume behavior. Embedding
adds no model call. Markdown summary generation has been removed; existing legacy
Markdown files remain recognized for completion skipping, protection, and backups.
The separate `.log.md` output and offline/disabled-report boundaries are preserved.

SCR-062 adds smaller gray source views after the main tabs: original GPT audio
text, pre-reconciliation WhisperX/MLX voice/word text, and the selected diarizer's
anonymous intervals/count. Only sources actually produced in that run are shown;
failed fusion retains both successful inputs alongside the local final fallback.
The final label does not claim successful reconciliation or greater accuracy.
The existing `transcript` selection controls final and source views together.

Each output ownership state freezes its source texts before reconciliation and
binds them to the source signature and final-log hash. Summary-only regeneration
never borrows current shared checkpoints or reruns recognition to populate tabs.
Old logs without snapshots and edited final logs retain final-only views. This
avoids displaying incompatible upstream results after changing models or output
locations. Raw views remain escaped, complete HTML body text with no external
dependencies or additional model calls; summary/header prompts are unchanged.

The report's Dark Mode switch uses inline CSS and JavaScript, with theme setup in
the head before rendering. A saved explicit choice overrides the system preference;
printing resets to light. Browser localStorage remembers the preference when
available; HTTP(S) also uses a shared site-wide cookie. Local files cannot reliably
share a preference across different paths because file-origin storage behavior is
browser-dependent. Storage errors must not break switching or tab navigation.
There is no server, external asset, or transcript data in preference storage.

SCR-066 adds a bottom-right Generated stamp, separate from the recording's Date.
Rendering embeds an aware UTC instant in a time element plus a full UTC fallback.
The browser displays HH:MM for its current local calendar day, otherwise a full
day/month/year/time, and exposes the local timezone in a tooltip. A minute timer
updates only the presentation across midnight; opening/copying a report does not
alter its stored generation instant. Successful regeneration stamps the new HTML;
completion skipping preserves old timestamps. No model, network or filesystem
creation/mtime inference is involved. Without JavaScript the full UTC text stays
readable. Printing retains the existing hidden-footer behavior.

### OBS integration and folder monitoring (SCR-046, SCR-049)

The user selected `--monitor-dir` as a separate foreground mode, independent of
batch `--input-dir`. Its selection criterion is observed size growth, regardless
of whether the MKV existed at startup. Stationary files never enter readiness
checks; a timestamp change or a newly appearing complete file alone is insufficient.
Very short recordings can finish between polls without observed growth. Polling
uses the standard library without filesystem hooks or new dependencies. Processing
is serial, with the existing batch pipeline and protection rules. There is no
persistent queue, automatic browser opening, or automatic retry of unchanged failed
files. Manual `-f` processing remains the recovery path; restarting the monitor
requires fresh observed growth. README owns exact options and timing.

SCR-063 makes monitor-mode outputs default to the monitored folder; explicit
output paths still take precedence and ordinary batch/`-f` defaults stay `./data`.
The monitor flag now accepts an optional path. A bare flag lazily selects fixed
home-directory presets: Movies on macOS, Videos on Linux/Windows. These are simple
conventional paths, not localized XDG/Windows Known Folder resolution; custom or
redirected folders require an explicit path. Missing folders still fail rather
than being created silently. Presets do not extend the current macOS ARM64 runtime
support or change growth/stability/readiness criteria.

OBS supports [launch parameters](https://obsproject.com/kb/launch-parameters),
[Lua/Python scripts](https://docs.obsproject.com/scripting), and a
[built-in WebSocket interface](https://obsproject.com/kb/remote-control-guide).
Its [protocol](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md)
provides RecordStateChanged with the saved path on stop. These are alternatives
to a native plugin; launch parameters alone do not configure capture devices or
provide the complete post-recording workflow.

Lua and WebSocket triggers remain unimplemented alternatives. A Lua bridge would
hand work to an independent process; Python scripting needs OBS-specific interpreter
configuration. A WebSocket listener needs authentication and reconnection, and its
live events would still need durable recovery if missed. GetRecordStatus does not
return the last recording path. No background service has been installed.

Matroska/EBML has no mandatory fixed EOF byte marker. The
[EBML specification](https://www.rfc-editor.org/rfc/rfc8794.html#section-6.2)
allows unknown-sized elements ending at EOF; the
[Matroska index](https://www.rfc-editor.org/rfc/rfc9559.html#section-6.4)
is recommended rather than mandatory and need not be at the end. OBS's FFmpeg
mux helper calls av_write_trailer; FFmpeg's
[Matroska trailer](https://github.com/FFmpeg/FFmpeg/blob/master/libavformat/matroskaenc.c)
can write Cues and patch Segment size, SeekHead, and Duration at earlier offsets.
`obs_mkv_readiness()` combines observed metadata stability with a finite Segment
matching the file boundary and bounded metadata, Duration, Cluster, and audio
CodecID checks. It skips media payloads rather than claiming full integrity.
Source snapshots are checked around inspection and audio extraction. This is an
OBS-oriented finalization heuristic: valid recovered/streaming MKVs can fail it,
file splits are not joined, and a later writer reopening cannot be ruled out.
Synthetic FFmpeg writing/finalization has been checked; real OBS active, paused,
stopped, crashed, and copied-file scenarios still need manual validation.

Scribe currently extracts only the first audio stream (`extract_audio()`). OBS
must include both microphone and remote audio in that stream; its
[multi-track guide](https://obsproject.com/kb/multiple-audio-track-recording-guide/)
describes a combined track 1 plus optional isolated tracks. Video content is not
analyzed by Scribe. Existing measured runtimes do not support a universal
60-second recording-to-report promise.

## Important observed results

These are historical measurements, not latency guarantees or current price quotes.
The live experiments used the same approximately seven-minute, two-speaker
recording. No human reference transcript or independent speaker-accuracy benchmark
was produced.

### Sol versus Luna, medium reasoning

The controlled comparison reused identical cached cloud words/local anchors and
identical prompts. Sol fusion passed validation. Luna fusion failed twice by
removing required speaker-uncertainty markers. The retained second candidate kept
all 33 anchor IDs but only 29 of 38 required markers. Validation was not relaxed;
the published Luna-path log was the local fallback, not accepted fused text.

With the same accepted Sol log as summary input, Luna preserved the broad topics
but lost the explicit `managed` versus `manageable self-hosted` correction. The
isolated summary estimates were $0.000690 for Luna and $0.011871 for Sol. Cheaper
tokens did not establish equivalent quality, and Luna fusion was slower in this
sample. This supports retaining Sol as the default; it does not prove Luna fails
on every conversation. Detailed local evidence, when present:
[comparison report](../data/comparison/luna-vs-sol/REPORT.md). That ignored report
and its private inputs are intentionally absent from a fresh checkout.

### Fresh checkout on this Mac

At the baseline commit, a separate native checkout with private Python 3.14.7
created its own environment and downloaded all four manifest assets; no prior
model weights, recognition results, or API caches were copied into it. Setup took
557 seconds, downloaded 1,646,501,343 bytes, and passed dependency consistency and
repeat SHA-256 verification. The real default pipeline took 173.5 seconds and
produced accepted fused A/B text plus a Russian summary.

Additional guarded checks confirmed offline isolation, cached API-only reuse,
completed-pair preservation, and ambiguous bare-filename handling. The 44 mocked
unit tests passed before and after dependency installation, and were rerun
successfully in the main project when these context files were created.
This was a clean application setup on an existing macOS host, not a fresh OS or
Homebrew installation, a Docker test, or evidence of cross-platform support.

### Summary detail on the same saved log

Five subsequent calls used `gpt-6.1-sol:medium`, the existing `summarize()` function,
and the unchanged 6,980-character final log. No audio, diarization, fusion, or
intermediate notes were repeated. Calls ran concurrently, one per level:

| Detail | Summary words | Per-call seconds | Estimated USD |
| --- | ---: | ---: | ---: |
| 1 | 161 | 7.93 | 0.00970 |
| 3 | 233 | 9.92 | 0.01086 |
| 5 | 389 | 14.35 | 0.01340 |
| 7 | 437 | 16.61 | 0.01490 |
| 10 | 524 | 18.02 | 0.01679 |

Total estimate: $0.065640 from returned usage, not an invoice. Increased detail
retained more technical nuance without expanding this short source to ten pages.
Level 5 was a useful balance for this sample; the default at the time was level 1.
The log SHA-256 was
`dd08a710329d7aa5fb550cad56e44e387a10292a73581cfb796d8a83112428ad`.
The clean-install and detail-comparison reports/usage records were saved as local
chat artifacts outside this repository and are not fresh-checkout prerequisites.

### First multi-level HTML run

Version 2.4.0 passed 67 mocked unit tests, plus offline JavaScript checks for tab
selection, keyboard navigation, wrapping, and focus. A user-authorized live run
generated levels 1, 5, and 10 with `gpt-6.1-sol:medium`, using the same saved short
log for each level. It reused the final transcript without audio, diarization,
fusion, or intermediate notes. All three requests completed; returned usage totaled
8,505 input and 2,065 output tokens (76 reasoning tokens), in 38.0 seconds. No
fusion validation was run because fusion was not repeated. This is a functionality
check on one short source, not an independent summary-accuracy benchmark.

The HTML, copied source log, returned usage, and preservation checks are local-only
under `data/comparison/summary-tabs-preview/`. The HTML contains all three populated
tabs and no external assets. Structural and offline interaction checks passed;
browser visual verification was unavailable because the browser tool rejected
local-file navigation. The actual result was selected in Finder for user review.

### Header on the saved real log

Version 2.5.0 passed 83 mocked unit tests, including citation rejection, cross-part
role evidence, conflicting roles, date/duration provenance, and retry preservation.
A separate user-authorized example regenerated levels 1, 3, 5, and 10 plus the
header with `gpt-6.1-sol:medium`. It reused the final log without audio, diarization,
fusion, or intermediate notes. All five requests completed without validation
failures in 51.4 seconds; returned usage totaled 13,990 input and 2,802 output
tokens, including 217 reasoning tokens. The log establishes only A/B labels and
no participant roles, so the header retains A and B. Duration is 7 min 5 sec;
the displayed date comes from the recording filename and is marked accordingly.

The actual HTML and usage/preservation evidence are local-only under
`data/comparison/report-header-preview/`. Original log and summary bytes and
modification times were unchanged. The file was selected in Finder; header
structure was checked, while browser visual verification remains unavailable.
This verifies one short example, not independent metadata or summary accuracy.

## Limitations and follow-up

- Version 2.16.0 passed 163 mocked tests and launcher syntax/version checks.
  Timestamp checks execute the actual inline script with fixed clocks/timezones:
  time-only today, full date/year on older days, midnight while open, UTC/local
  year boundaries, and daylight-saving changes. The stored UTC instant, full
  no-JavaScript fallback and separate recording Date are checked independently.
  A real four-summary/source-view preview reused saved text without new model,
  API, fusion or header-model calls; all 59 current baseline files retained
  hashes/mtimes. HTML and inline theme/navigation checks passed; browser visual
  QA remains unavailable under its local-file policy. Evidence:
  [preview](../data/comparison/generated-time-preview/verification.json).
- Version 2.15.0 passed 156 mocked tests covering three recognizers without fusion,
  one diarization even with force, independent word-cache resume and model-identity
  invalidation, cloud/local failure recovery, summary-only snapshots and historical
  `all` protection. A fresh monologue run executed WhisperX 3.8.6 Turbo CPU int8
  and MLX Whisper 0.4.3 Turbo Metal in the same process, with Nemotron 3 Q8_0 CPU
  once: 150/156 words, one voice, 54.30 s including imports/model loading. GPT audio
  text was cached. Both recordings also completed all-mode integration from cached
  GPT/WhisperX/MLX/voice sources, preserving one/two voices and producing four source
  views beside the unchanged WhisperX final. HTML/script checks and completed-pair
  preservation passed; browser visual QA remains unavailable. Model hashes and
  launcher syntax/help/version passed. No new paid API calls, returned usage,
  fusion, summary or header-model validation occurred. All 59 baseline files kept
  their current hashes/mtimes. These are integration observations, not independent
  accuracy or latency benchmarks. Evidence: [integration](../data/comparison/all-mode-integration/verification.json),
  [fresh local run](../data/comparison/all-mode-integration/fresh-local.json).
- Version 2.14.0 passed 145 mocked tests and launcher syntax/help/version checks.
  New checks cover bare/explicit monitor paths, macOS/Linux/Windows home-folder
  presets, explicit output precedence, resolved relative paths, unchanged batch
  defaults, missing folders without creation, unsupported-platform preset errors,
  bare-flag conflicts and dispatch of a growing finalized MKV into the monitored
  output folder. Linux/Windows selection was mocked on macOS, not native runtime
  validation. No downloads, model inference or paid API calls were needed.
- Version 2.13.0 passed 140 mocked tests, including all recognition modes,
  fusion/cloud fallback, exact raw/final separation, escaped long source text,
  per-output snapshots, legacy/edited-log isolation, and actual inline-script
  keyboard/theme checks across source tabs. Two real transcript-only HTML previews
  reused cached WhisperX Turbo words and Nemotron intervals, preserving one/two
  voices; no new inference, API requests, usage, fusion, summaries or header-model
  validation ran. Preview rendering used a local descriptive header. Both reports
  retained all text and passed script checks/completed-pair skipping. Browser
  visual QA remains unavailable under its local-file policy. Seven two-speaker
  cache/output files had been refreshed concurrently since the prior experiment;
  all 59 files were unchanged against a new pre-check snapshot, without restoring
  older user results. Evidence: [previews](../data/comparison/source-tabs-preview/verification.json).
- Version 2.12.0 passed 133 mocked tests, dependency consistency, launcher
  syntax/help/version, selected online setup, and offline hash verification for
  the default, MLX and Community-1 selections. Fresh production WhisperX Turbo
  ASR/alignment plus Nemotron detected one/two voices and produced 150/788 word
  items on the two controls, with automatic Russian detection, no count hints,
  missing word times or invalid bounds. Repeated runs reused final logs without
  extraction/inference. Switching to Community-1 on the monologue detected one
  voice in 72.47 s while reusing WhisperX words; API-only mode reused cached GPT
  audio text without local models. English alignment weights loaded locally,
  but English/mixed speech and fresh MLX inference were not retested. No new API
  calls, returned API usage, fusion or summary validation occurred; 59 private
  baseline files retained hashes/mtimes. A verification-script field typo and a
  unit fixture's trailing-newline expectation were corrected without changing
  model outputs. These checks establish integration, not independent accuracy.
  Evidence: [integration](../data/comparison/whisperx-integration/REPORT.txt).
- Version 2.11.0 passed 122 mocked tests and dependency consistency, launcher
  syntax/help/version, live setup downloads (113,908,104 new bytes; existing
  Whisper reused), and offline full model/runtime verification. An isolated
  integrated offline batch reused cached MLX words, detected one/two voices,
  and exactly reproduced the prior native experiment's intervals in 10.48 s.
  The next batch reused final logs without extraction/diarization. No API calls,
  returned API usage, fusion validation, or fresh Whisper inference occurred;
  all 59 private baseline files retained hashes/mtimes. A first test correctly
  refused word-cache reuse for a copied file with a 311-ns mtime difference;
  only the isolated fixture cache was rebound after full SHA equality checks.
  Production source-signature checks remain strict. Evidence:
  [integration](../data/comparison/nemotron3-integration/REPORT.txt).
- Version 2.10.0 passed 113 mocked tests, including selection of an existing growing
  recording among 100 stationary files, two growing recordings, rejection of new
  stationary files and timestamp-only changes, reset on truncation/replacement,
  simulated stability/finalization, error isolation, offline boundaries, and normal
  output generation. A synthetic three-second FFmpeg video with AAC audio was
  rejected while writing (unknown Segment size) and accepted after finalization
  (29,537 bytes). That structural smoke check supplied the elapsed-stability value;
  it did not wait 30 seconds or run recognition, fusion, or text API calls. Real
  OBS compatibility remains a manual validation item, not a measured result.
- Version 2.9.0 passed 97 mocked tests, including custom input-folder discovery,
  same-folder log/HTML generation, and completed-pair preservation on a repeated
  batch scan. No live audio or API processing was needed for this change.
- Version 2.8.0 passed 92 mocked tests, including the optional Node.js check of
  the actual inline theme/navigation script with saved, invalid, or blocked
  storage and HTTP(S) cookie fallback. Three real-data examples under ignored
  `data/comparison/dark-mode-preview/` reuse prior outputs without API/audio calls.
  Offline script checks passed for all three; calculated text contrast exceeded
  4.5:1 in both palettes. Browser visual verification remains unavailable, so
  actual browser persistence is subject to the documented file-origin limits.
- Version 2.7.0 passed 91 mocked tests covering tab configuration/precedence,
  optional Transcript inclusion/order, HTML for single tabs, and summary reuse
  after header failure. Default, single-summary, and transcript-only examples in
  ignored `data/comparison/report-tabs-preview/` reuse saved real summaries/log and
  revalidated header metadata from `gpt-6.1-sol:medium`; no new API or audio calls.
  Structural and offline JavaScript navigation checks passed for all three.
  Browser visual verification remains unavailable.
- The detail indicators and tracked data-folder placeholder passed 88 mocked
  unit tests, including all ten dot counts and checkout-before-launch behavior.
  The existing real HTML example was rendered again from cached results without
  additional API or audio processing.
- Version 2.6.0 passed 86 mocked unit tests plus offline checks of actual-report
  Log clicks, Home/End navigation, arrow wrapping, and focus. A real example was
  rendered under ignored `data/comparison/log-tab-preview/` from the previous
  saved log, all four summaries, and revalidated header cache. No new API or audio
  calls were made. The embedded text exactly matched the complete saved log, and
  no external resource references were present. Browser visual verification
  remains unavailable; these checks cover content, structure, and interaction.
- The configurable default selection passed 71 mocked unit tests, including
  end-to-end HTML generation with no detail flag, `.env` lists, and single-level
  CLI overrides. This configuration change required no new paid API requests;
  the live HTML evidence above remains the earlier three-level run.
- Version 2.3.0 name recognition passed 56 mocked unit tests (including the prior
  44 tests). Its live model behavior has not yet been evaluated on an independently
  reviewed recording; the historical live benchmarks above predate this feature.
- Two earlier detail-5 summary-only requests timed out after about 600 seconds;
  the existing log and summary survived. The later five-level experiment succeeded
  without changing application code or token budgets. The cause remains unknown:
  neither claim all live scenarios always pass nor diagnose a detail/token-limit
  bug from these observations alone. `api_request()` still uses a 600-second
  timeout; transport timeouts are not retried by its transient-HTTP retry loop.
- The word-quality improvement does not repair wrong local voice anchors.
  Overlaps and technical names remain error sources; saved examples include
  inconsistent product-name spellings. Do not silently replace them with external
  knowledge or hard-code this recording's vocabulary into the general pipeline.
- Prompt and contract tests cover long-input note handling, but the live sample
  does not validate multi-hour recordings or every language mixture. New model,
  diarization, or transport changes need evidence appropriate to their scope.
- Failed or timed-out requests may lack returned usage. Their billed cost cannot
  be inferred as zero from missing response metadata.
