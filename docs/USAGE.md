# Scribe usage guide

Detailed setup, runtime behaviour and recovery instructions.
For the first run, model tables and all CLI options, see the [README](../README.md).

## Setup from GitHub: start here

Scribe requires macOS 14+ on Apple Silicon (M1 or newer) and an installed ARM64
Python 3.12 or 3.13 (WhisperX does not support 3.14). The Git repository contains source code and setup
instructions, **not a downloaded Python distribution or model weights**.

### 1. Install Python and Git once

If a suitable Python and Git are already installed, skip this step. With Homebrew:

```bash
brew install python@3.13 git
```

If Homebrew is missing, install it using the command from its
[official site](https://brew.sh/), then load its Apple Silicon shell environment:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
eval "$(/opt/homebrew/bin/brew shellenv)"
brew install python@3.13 git
```

Follow the installer's prompts, including Apple's Command Line Tools if requested.
Homebrew has its own supported macOS versions; if it does not support your macOS,
install Python 3.12–3.13 using the [official macOS installer](https://www.python.org/downloads/macos/)
and use GitHub's Download ZIP option if Git is unavailable. The remaining setup is
the same. [Python formula details](https://formulae.brew.sh/formula/python@3.13).

### 2. Clone and configure Scribe

Clone the Scribe repository. For a downloaded ZIP, extract it and change into
its directory instead.

```bash
git clone https://github.com/Igx22/scribe.git scribe
cd scribe
cp -n .env.example .env
open -e .env
```

Set `OPENAI_API_KEY` in `.env` and save it for API recognition, fusion, or summaries.
Do not copy `.env.example` over an existing configured `.env`. Fully offline
recognition needs no API key; online downloads are still needed to prepare it once.

### 3. Prepare dependencies and models

Default setup prepares:

- Python environment in `data/.venv`, required libraries and FFmpeg.
- **WhisperX Turbo**, English and Russian word-alignment models, and tokenizer data.
- **Nemotron 3** and its native runtime for speaker segmentation.

See the [table in the README](../README.md#install).

Models go into `data/models`; sizes exclude Python packages. GPT stays online.
Default setup requires no recording or API/Hugging Face credentials and makes
no paid API calls.

To replace Nemotron with Community-1, use
`./scribe.sh --setup --diarization-model community-1`. First download requires
accepting the [model conditions](https://huggingface.co/pyannote/speaker-diarization-community-1)
and `HF_TOKEN` in `.env`.

Repeated setup reuses valid files; `--verify-models` checks hashes.
Prepare selected models online before using `--offline`.

### 4. Transcribe recordings

Open Terminal in the Scribe project folder (the folder containing `scribe.sh`).
The checkout already includes a `data` subfolder. Put your MKV files there, for example
`scribe/data/recording.mkv`, then run:

```bash
./scribe.sh
./scribe.sh -f "recording.mkv"
./scribe.sh -f "first.mkv" -f "second.mkv"
```

After setup, fully local recognition is available with `./scribe.sh --offline`.
There is no need to ship or commit a separate Python installation in `data/runtime`.

Without `-f`, Scribe scans `--input-dir DIR`, or `./data` in the Terminal's current
working directory when that option is omitted. Scanning is non-recursive. When
you run from the project folder, the default is the project's `data` subfolder.
To process all MKV recordings in `~/Movies` and save their logs and HTML reports
in the same folder:

```bash
./scribe.sh --input-dir ~/Movies --output-dir ~/Movies
```

`--input-dir` and `--output-dir` are independent: changing the input folder alone
still saves results in `./data`. Both accept absolute paths, relative paths from
the Terminal working directory, and `~` home paths. `--input-dir` selects a batch
and cannot be combined with `-f`, which selects individual recordings. Generated
logs and reports are ignored when scanning for MKV files. Existing completed
recordings are skipped as described below. This is a one-time scan, not a folder
watcher; wait until recording has finished before running it.

You can also select a recording by its explicit path:

```bash
./scribe.sh -f "./data/recording.mkv"
./scribe.sh -f "./recording.mkv"
./scribe.sh -f "/absolute/path/recording.mkv"
python3 src/scribe.py -f "recording.mkv"
```

An explicit relative path is relative to the Terminal working directory. The
launcher preserves that directory. Only MKV files are accepted; `.MKV` also works.
Missing inputs, empty input directories, and output-name collisions are reported.
Repeated references or symlinks to the same resolved file are processed once.

## Monitor growing OBS recordings

Start Scribe before or during an OBS recording:

```bash
./scribe.sh --monitor-dir
./scribe.sh --monitor-dir ~/Movies --output-dir ./reports
```

Without a path, Scribe watches `~/Movies` on macOS. The folder must already exist;
use an explicit path for custom locations. Monitoring stays in the foreground,
checks `.mkv` files every five seconds, and ignores subfolders. Logs and reports
are saved beside recordings unless `--output-dir` is supplied.

A file qualifies only after observed size growth, including recordings already
in progress at startup. Scribe then waits for 30 seconds of stability and checks
for OBS-style MKV finalization before processing. This is a readiness heuristic,
not a universal completion or corruption check. Stationary files, completed copies
and very short recordings can be missed; process them manually with `-f`.

Files are processed one at a time with normal completion skipping, caches and
output protection. An unchanged failed file is not retried automatically; use
`-f` to retry. There is no persistent queue, and restarting requires fresh observed
growth. Monitoring itself makes no API calls; normal processing may. `--offline`
produces local logs only.

Stop with Ctrl+C; completed outputs are preserved. Monitor mode cannot be combined
with `-f`, `--input-dir`, `--force`, `--summary-only`, setup or prompt-preview options.

## Outputs and completed recordings

For `meeting.mkv`, outputs are plain-text `meeting.log.md` and standalone
`meeting.summary.html`. They go to `./data`, the watched folder in monitor mode,
or `--output-dir`. With reports disabled, only the log is written.

A log plus HTML or legacy Markdown summary counts as complete: processing skips
it without API calls or file changes, even after source/settings change. Ordinary
resume of a lone log requires matching cached source/settings and ownership.

`--force` replaces the log and report, backs up previous results, and may repeat
paid requests. `--summary-only` preserves the log and regenerates the report
without recognition or reconciliation; add `--force` to bypass summary/header
checkpoints:

```bash
./scribe.sh -f "recording.mkv" --force
./scribe.sh -f "recording.mkv" --summary-only --force
```

## Transcription modes

The default combination is `--transcription-model whisperx --diarization-model nemotron`.
`--transcription-model` accepts five values:

See the [table in the README](../README.md#transcription-modes).

Online/Offline describes recognition after model setup. Initial model downloads
need internet access; summaries and report headers also use the text API unless
report generation is disabled. Use `--offline` for a run without network requests.

`all` runs GPT-Transcribe Online, WhisperX Turbo and MLX Turbo once each,
sequentially, with one shared diarization pass. GPT then reconciles the cloud and
WhisperX text, with MLX as additional comparison evidence, while preserving fixed
WhisperX voice/time anchors. The final reconciled log supplies summaries. All
three original texts and the shared diarization remain available as source views.

Every non-offline mode runs final GPT text reconciliation, including when reports
are disabled with `--summarize-model none` or `--transcribe-only`. WhisperX/MLX-only
recognition sends only text to GPT, never audio; one-source review preserves
uncertain speech instead of treating duplicated text as independent evidence.
API-only mode reviews GPT-Transcribe text but keeps chunk timing and unknown
speakers; it does not load local models or invent voice labels. `--offline` is the
explicit exception: no GPT calls, reconciliation or automatic name discovery.

WhisperX and MLX have independent word checkpoints in `all`, so repeated runs
or new output folders can reuse both without alternating one shared cache.
Compatible single-model word checkpoints remain reusable. `--force` reruns
all three recognizers and one diarization pass. A failed cloud stage leaves both
local sources and a clearly reported local fallback; without a completed report
pair, retrying reuses local stages and retries the missing cloud result. A failed
local recognizer reports an error, preserving completed stage caches for retry.
As with other modes, a completed log/report pair still skips on the next launch.
`--offline` retains its existing priority: with `all`, it selects only WhisperX,
disables summaries and makes no cloud requests.

The default `whisperx` uses CPU int8, batch four, four threads and beam five,
with local pyannote VAD and forced word alignment. English, Russian and mixed
speech are supported; auto language detection runs per recording. Alignment
assets are prepared for English and Russian; choose `mlx` or API-only recognition
for other languages. MLX uses Apple Silicon acceleration and per-chunk detection.
WhisperX alignment scores are not ASR confidence; low-confidence speech is marked
from source-segment recognition scores. Words without precise alignment are
retained with approximate neighboring bounds and speaker-uncertainty markers.

In combined mode, GPT-Transcribe runs first and WhisperX supplies local word/time
anchors, using the selected diarizer's fixed voice IDs. Text reconciliation combines
these sources; the MKV container/video itself is never uploaded. The summary is
made from the final log. If cloud audio recognition fails, GPT text reconciliation
is still attempted using the local text. Failed reconciliation retains the raw
source log, reports the failure and leaves its stage incomplete for a later retry. An API-only failure
is reported without falling back to local recognition.

**Local recognition does not mean a fully offline run.** Ordinary runs use
`--summarize-model gpt-6.1-sol:medium` for final text reconciliation and reports.
`none` disables reports but leaves final reconciliation on `gpt-6.1-sol:medium`.
Use `--offline` to disable every cloud request. A fallback log plus a successful
report still counts as a completed pair on the next run; it is not silently
replaced. Existing completed reports retain their previous final text until
explicitly reprocessed. `--summary-only` keeps the saved log and does not add
reconciliation to it.

## Diarization models

`--diarization-model` selects the voice model independently of the recognizer:

See the [table in the README](../README.md#diarization-models).

Both models run locally and determine the number of voices automatically;
Nemotron supports up to eight voices. No exact/minimum/maximum count hints are
supplied. After setup, neither model needs network access or a token for inference.
API-only recognition ignores this option and does not load or prepare local
recognition/voice models.

## Speaker names from the conversation

In non-offline modes with local voice anchors, GPT reconciliation can identify
speakers from supported introductions or clear named exchanges, without a separate
API request. It checks quoted evidence and resolves names across the recording;
ambiguous or conflicting claims retain anonymous labels. Supported human names
take precedence over nicknames. These checks cannot guarantee correct interpretation
or diarization.

Confirmed names retain their original language and script and apply throughout
the final log and summaries; internal voice IDs and timestamps stay unchanged.
Unnamed voices keep letters, unassigned speech stays unknown, and shared names
include the voice label, such as `Alice (A)`. Offline and failed-reconciliation
fallback logs keep anonymous labels; API-only mode cannot assign speaker names.
Existing outputs are not renamed automatically, and `--summary-only` preserves
the log without discovering names.

## Summary and fusion model

Choose the text model and reasoning effort:

```bash
./scribe.sh --summarize-model gpt-6.1-sol:medium
./scribe.sh --summarize-model gpt-6-luna:medium
./scribe.sh --summarize-model none
```

Format: `MODEL[:EFFORT]` or `none`. A bare model ID uses `medium`. Supported effort
values are `low`, `medium`, `high`, `xhigh`, and `max`; the chosen API model must
support the requested effort. The default is `gpt-6.1-sol:medium`.

This selection controls final summaries and final text reconciliation in every
ordinary mode. `none` disables reports only: reconciliation still uses
`gpt-6.1-sol:medium`. Use `--offline` to avoid all text-model and cloud-audio calls.

The summary follows the predominant language of the conversation: mostly English
speech produces an English summary; mostly Russian speech produces a Russian one.
If neither language clearly predominates, both may be used as appropriate to the
topics. Names and technical terms can retain their original language. Intermediate
notes preserve the source languages and their approximate proportions. Application
headings do not determine the summary language. Recognition detects the language
automatically; summaries are not forced into English.

Summaries distinguish decisions from proposals and open questions, and include
owners and deadlines only when explicitly present.

## Report tabs and summary detail

Summary detail ranges from 1 to 10; the default levels are 1, 3, 5 and 10.
The report's **Summary** menu names these levels **Key points**, **Overview**,
**Expanded** and **In depth**, with the selected name and depth (for example,
`Overview · 3/10`) below the fixed menu title. Other configured levels show
`Summary · N/10`. Depth describes retained information, not a percentage of the
original text. The **Transcript** menu has a decorative outline microphone and
shows `Final version` or the selected source below its title; source transcripts
and speaker segmentation remain available when included. Both menus remember
their own selection while the report stays open. The Summary model badge applies
to all its levels; transcript badges retain their separate provenance.

Level 1 captures the essentials, while higher levels retain more discussion,
reasoning, alternatives and technical nuance. Detail controls coverage independently
of the model's reasoning effort. The table gives approximate lengths for long,
information-dense discussions, assuming roughly 400-450 words per page.

See the [table in the README](../README.md#summary-detail).

These lengths are guides, not minimum quotas: short conversations stay short even
at level 10, without padding or invented background. Each level is generated
independently from the same final log, so additional levels increase text API work.
Use `--summary-only` to regenerate an existing HTML report without repeating audio
processing or reconciliation; the saved log is preserved.

```bash
./scribe.sh -f "recording.mkv" --summary-only
```

## Fully offline mode

```bash
./scribe.sh --offline
./scribe.sh -f "recording.mkv" --offline
```

`--offline` takes priority over transcription and summary selections. It retains an explicit
`mlx` selection and otherwise uses `whisperx`, disables summary generation and fusion, and prohibits model
downloads. No audio or text is sent to OpenAI. There is no local LLM summary.
The prepared `data/.venv` and the selected local models must already be present; missing
or outdated dependencies produce an error instead of a network bootstrap. Run
`./scribe.sh --setup` online once before offline use. `--offline --summary-only` is
rejected because offline mode does not generate summaries.

`--transcription-model mlx` by itself can still send the final text for
the default API summary. Add `--summarize-model none`, or use `--offline`, for a
local log without cloud text processing.

## API key and configuration

Copy `.env.example` to `.env` and set `OPENAI_API_KEY`. The existing key remains
valid after resource relocation. Do not share the real `.env` file. Environment
variables take priority over `.env`; the file is parsed as data and never executed.

```text
OPENAI_API_KEY=your-api-key
SCRIBE_SUMMARIZE_MODEL=gpt-6.1-sol:medium
SCRIBE_REPORT_TABS=1,3,5,10,transcript
```

`SCRIBE_SUMMARIZE_MODEL` supplies the default for `--summarize-model`.
`SCRIBE_REPORT_TABS` supplies the default for `--report-tabs`; it accepts
commas or spaces, for example `SCRIBE_REPORT_TABS="1, 5, 10, transcript"`.
`.env.example` and the built-in fallback both use `1,3,5,10,transcript`.
A single value such as `SCRIBE_REPORT_TABS=5` still creates HTML; `transcript`
can be selected alone or with summaries. The old `SCRIBE_SUMMARY_DETAIL` key is
unused; rename it and add `transcript` if the full conversation should be included.
The precedence is explicit CLI option, process environment, `.env`, then built-in
fallback. Invalid configured tabs produce an error unless a valid CLI value
overrides them. The old `OPENAI_MODEL` and `OPENAI_REASONING` settings are no longer
used. No API key is required to skip completed pairs or run offline.
API requests consume the account's API credits/billing; do not infer available
API balance from a ChatGPT subscription. See the account's API Billing page.

## Complete command-line reference

Language detection is automatic. Models and caches use the application's
`data/models` and `data/.cache` folders.

See the [complete option table in the README](../README.md#options).

`--transcribe-only` and `--summary-only` are mutually exclusive.
Long options must be written in full.

For implementation details, additional examples and test instructions, see the
[development context](PROJECT_CONTEXT.md).

## License

Scribe's source code is licensed under the MIT License; see [LICENSE](../LICENSE).
Third-party libraries and downloaded models retain their respective licenses.
Nemotron 3 weights use [OpenMDW-1.1](https://huggingface.co/nvidia/Nemotron-3-Diarization);
the [NeMo-Speech.cpp runtime](https://github.com/NVIDIA/NeMo-Speech.cpp/releases/tag/v0.3.0)
includes Apache-2.0 code and bundled third-party notices retained during setup.
