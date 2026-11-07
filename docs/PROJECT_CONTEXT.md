# Scribe: durable project context

Reconciled with version 2.3.0 on 2026-11-07. Historical benchmark results below
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
The three prompt constants and their renderers in `src/scribe.py` are canonical.
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
Level 5 was a useful balance for this sample; the default remains level 1.
The log SHA-256 was
`dd08a710329d7aa5fb550cad56e44e387a10292a73581cfb796d8a83112428ad`.
The clean-install and detail-comparison reports/usage records were saved as local
chat artifacts outside this repository and are not fresh-checkout prerequisites.

## Limitations and follow-up

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
