# Scribe: durable project context

Reconciled with version 2.9.0 on 2026-11-07. Historical benchmark results below
refer to version 2.2.0 at commit `034b1a9616f6c152995e6950442e9670c87be08f`.
This document preserves rationale and important evidence from the original
development chat. [README](../README.md) owns setup, options, paths, output
formats, and operational behavior; do not duplicate its reference material here.

## Decisions and their reasons

### Recognition and voices solve different problems

The original local-only results contained too much unclear speech and uncertain
speaker attribution, especially in Russian technical discussion. A live comparison
led the user to prefer cloud recognition for clearer words, while retaining local
voice/time anchors. The resulting design uses two sources and text reconciliation,
rather than asking a text model to infer who spoke from meaning.

Whisper recognizes words. Separate pyannote segmentation and WeSpeaker ResNet-34
embeddings, through sherpa-onnx, establish voices. Reconciliation may correct words
but cannot move anchors or change their speaker/time assignments. Speech that
cannot be placed confidently must remain unassigned. Thus clearer recognition
does not establish more accurate speaker attribution.

The user explicitly retained API-only and local-only choices alongside the combined
default. A failed cloud stage in combined mode must still leave a usable local
log; API-only mode must not silently load or substitute local models. See
`configure_mode()`, `_process_file()`, and `fuse_transcripts()` in
[src/scribe.py](../src/scribe.py), with regression coverage in
[test_modes.py](../tests/test_modes.py) and [test_backends.py](../tests/test_backends.py).

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
changing default behavior or adding a watcher. Completed-pair protection still
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
the four summary levels and Transcript tab. Each summary level uses
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

When selected, Transcript embeds the entire saved final log as escaped text;
the default puts it after all Detail tabs. A decorative document icon is drawn in
the inline CSS. The transcript
is inserted as escaped text with whitespace preserved; it is neither truncated nor
loaded from the separate `.log.md`. This makes the HTML sufficient for sharing as
one file. The separate log remains part of local output/resume behavior. Embedding
adds no model call. Markdown summary generation has been removed; existing legacy
Markdown files remain recognized for completion skipping, protection, and backups.
The separate `.log.md` output and offline/disabled-report boundaries are preserved.

The report's Dark Mode switch uses inline CSS and JavaScript, with theme setup in
the head before rendering. A saved explicit choice overrides the system preference;
printing resets to light. Browser localStorage remembers the preference when
available; HTTP(S) also uses a shared site-wide cookie. Local files cannot reliably
share a preference across different paths because file-origin storage behavior is
browser-dependent. Storage errors must not break switching or tab navigation.
There is no server, external asset, or transcript data in preference storage.

### OBS integration investigation (SCR-046)

The user prefers a watched recording folder: after OBS finishes writing an MKV,
Scribe would queue it and open the successfully generated HTML in the default
browser. This is a proposed user journey, not implemented behavior. The current
scope is research only; there was no live OBS integration or timing experiment.

OBS supports [launch parameters](https://obsproject.com/kb/launch-parameters),
[Lua/Python scripts](https://docs.obsproject.com/scripting), and a
[built-in WebSocket interface](https://obsproject.com/kb/remote-control-guide).
Its [protocol](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md)
provides RecordStateChanged with the saved path on stop. These are alternatives
to a native plugin; launch parameters alone do not configure capture devices or
provide the complete post-recording workflow.

The follow-up also considers an OBS stop event as a primary trigger. An in-OBS
Lua bridge is a candidate for a small OBS-only integration: it would handle
RECORDING_STOPPED, obtain the last recording path (frontend API, OBS 29+), and hand
work to an independent process or persistent queue without blocking OBS. Python
scripting adds OBS-specific interpreter/architecture configuration; Scribe's own
Python environment would remain separate. A WebSocket listener instead needs
one-time authenticated local connection setup and reconnection handling. Live
event delivery must not be treated as a durable job queue: missed stops need a
recovery policy, and GetRecordStatus does not return the last recording path.
Both candidates need path-safe launching with an explicit output directory,
deduplication, bounded retries, and opening only the intended completed report.
Folder recovery can complement an event trigger, but is not an approved design
requirement. No integration approach has been finally selected or implemented.

For a macOS folder watcher, file notifications and stable size/mtime alone do not
establish completion. Apple's documented [kqueue vnode events](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/kqueue.2.html)
do not provide a close-write event. A candidate design combines a settling period,
writer-descriptor inspection, media checks, and a final source-change check before
paid processing. Writer-inspection errors must remain unknown, not mean ready.
These checks need testing with pause/resume, copies, sleep, crashes, and file splits;
they cannot prove that a closed segment represents the entire meeting. OBS notes
that [unfinished MKV files can remain playable](https://obsproject.com/kb/audio-video-formats-guide),
so successful decoding alone is not proof of a complete recording. A persistent
queue, explicit backlog policy, and bounded retries would be needed for unattended
use. No new dependency or background service has been selected or installed.

Matroska/EBML has no mandatory fixed EOF byte marker. The
[EBML specification](https://www.rfc-editor.org/rfc/rfc8794.html#section-6.2)
allows unknown-sized elements ending at EOF; the
[Matroska index](https://www.rfc-editor.org/rfc/rfc9559.html#section-6.4)
is recommended rather than mandatory and need not be at the end. OBS's FFmpeg
mux helper calls av_write_trailer; FFmpeg's
[Matroska trailer](https://github.com/FFmpeg/FFmpeg/blob/master/libavformat/matroskaenc.c)
can write Cues and patch Segment size, SeekHead, and Duration at earlier offsets.
For a tested OBS recording configuration, a finite Segment size matching the
file boundary plus stable size/mtime is a candidate finalization signal. It is
not a general integrity check or proof of a complete meeting. This could simplify
an OBS-focused watcher, but needs validation on the installed version with active,
paused, stopped, crashed, and copied files; no such experiment has been run.

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
