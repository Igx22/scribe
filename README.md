# scribe

macOS command-line tool for detailed conversation logs and summaries with selectable
detail. It accepts MKV recordings, extracts the first audio track, and supports
Russian, English, and mixed conversations. Input recordings are never modified.

## Setup from GitHub: start here

Scribe requires macOS 14+ on Apple Silicon (M1 or newer) and an installed ARM64
Python 3.12, 3.13, or 3.14. The Git repository contains source code and setup
instructions, **not a downloaded Python distribution or model weights**.

### 1. Install Python and Git once

If a suitable Python and Git are already installed, skip this step. With Homebrew:

```bash
brew install python@3.14 git
```

If Homebrew is missing, install it using the command from its
[official site](https://brew.sh/), then load its Apple Silicon shell environment:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
eval "$(/opt/homebrew/bin/brew shellenv)"
brew install python@3.14 git
```

Follow the installer's prompts, including Apple's Command Line Tools if requested.
Homebrew has its own supported macOS versions; if it does not support your macOS,
install Python 3.12–3.14 using the [official macOS installer](https://www.python.org/downloads/macos/)
and use GitHub's Download ZIP option if Git is unavailable. The remaining setup is
the same. [Python formula details](https://formulae.brew.sh/formula/python@3.14).

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

```bash
./run.sh --setup
```

This command automatically creates `data/.venv` using the installed Python,
installs the libraries from `requirements.txt` into that isolated environment,
and downloads Whisper plus the local speaker-segmentation and embedding models
into `data/models`. Model downloads total approximately 1.65 GB. File sizes and
SHA-256 hashes are checked during download. FFmpeg is provided by the Python
dependency `imageio-ffmpeg`; a separate `brew install ffmpeg` is not required.
No MKV file or API key is needed for this setup command, and no paid transcription
or summary request is made. You do not need to run pip or activate the environment
manually.

The explicit setup step is convenient but optional: an ordinary first launch
also prepares its Python environment, and local/combined recognition downloads
missing models when needed. API-only mode does not download local model weights.
`--setup` deliberately prepares all local models, regardless of the transcription
mode. Existing verified-size files are reused; repeated setup does not download
them again. Use `--verify-models` to recheck existing model hashes too.

### 4. Transcribe recordings

Put MKV files into `data`, or select a recording from `~/Movies`:

```bash
./run.sh
./run.sh -f "recording.mkv"
./run.sh -f "first.mkv" -f "second.mkv"
```

After setup, fully local recognition is available with `./run.sh --offline`.
There is no need to ship or commit a separate Python installation in `data/runtime`.

Without `-f`, scan the lowercase `data` directory in the current working directory,
non-recursively. A bare filename searches both `./data` and `~/Movies`. `~/Movies`
uses the current user's home directory and capital-M `Movies`, via `Path.home()`.
If distinct files with that name exist in both locations, pass an explicit path.
Repeated references or symlinks to the same resolved file are processed once.

```bash
./run.sh -f "~/Movies/recording.mkv"
./run.sh -f "./recording.mkv"
./run.sh -f "/absolute/path/recording.mkv"
python3 src/scribe.py -f "recording.mkv"
```

An explicit relative path is relative to the Terminal working directory. The
launcher preserves that directory. Only MKV files are accepted; `.MKV` also works.
Missing inputs, empty input directories, and output-name collisions are reported.

## Outputs and completed recordings

For `meeting.mkv`, the default outputs are:

- `./data/meeting.log.md`: detailed conversation log.
- `./data/meeting.summary.md`: summary at the selected detail level, when enabled.

Both contain plain text despite the `.md` extension. There are no Markdown
headings, tables, emphasis, or code fences. Speaker labels and approximate times
are available in local and combined modes. API-only logs have chunk time ranges
and no invented A/B speaker labels.

If **both files already exist**, ordinary processing skips the recording, even
if the model, prompt, source, or settings have changed. Existing results are not
validated as a condition of this check. Skipping happens before model preparation,
API-key validation, audio extraction, or API calls. File contents and modification
times are preserved. This also applies to files selected with `-f` and results in
an explicit `--output-dir`.

To deliberately replace a completed result, use `--force`. This bypasses caches
and can repeat paid requests. To replace only its summary, use `--summary-only`;
that preserves the log and does not repeat recognition or fusion. A lone log file
does not count as a completed pair, but can be resumed if its cache proves ownership.
With summaries disabled, only the log is created; repeated runs reuse it when its
source/settings match.

## Transcription modes

`--transcription-model` accepts exactly three values:

| Value | Recognition and final log | Local voice labels | Audio uploaded |
| --- | --- | --- | --- |
| `gpt-transcribe` | OpenAI GPT-Transcribe only | No | Yes, extracted audio |
| `whisper-local` | Local Whisper and local diarization only | A, B, C, D, etc. | No |
| `all` (default) | GPT-Transcribe + local Whisper/voices + GPT text reconciliation | A, B, C, D, etc. | Yes, extracted audio |

The default `all` preserves the earlier two-source pipeline. GPT-Transcribe runs
first, local recognition supplies voice/time anchors, and a text model combines
the sources into the final log. The MKV container/video itself is not uploaded.
The summary is generated from that final log.

API-only mode does not load, prepare, or fall back to local recognition models.
An API failure is reported. In `all`, failed cloud transcription falls back to the
local log and skips reconciliation; a failed reconciliation retains the local log.
If summaries are enabled, the text model then summarizes that available log.
The source transcripts and error state remain cached for inspection and retries.
A fallback log plus a successful summary counts as a completed pair on the next
ordinary run; use explicit regeneration if you want another attempt at fusion.

## Summary and fusion model

One option replaces the former `--model` and `--reasoning` options:

```bash
./run.sh --summarize-model gpt-6.1-sol:medium
./run.sh --summarize-model gpt-6-luna:medium
./run.sh --summarize-model none
```

Format: `MODEL[:EFFORT]` or `none`. A bare model ID uses `medium`. Supported effort
values are `low`, `medium`, `high`, `xhigh`, and `max`; the chosen API model must
support the requested effort. The default is `gpt-6.1-sol:medium`.

This selection controls final summaries and, in `all`, the text reconciliation.
`none` disables the summary only: `all` still needs GPT reconciliation and uses
`gpt-6.1-sol:medium` for it. To avoid all text-model calls while using cloud audio
recognition, choose `gpt-transcribe --summarize-model none`. To avoid every cloud
call, use `--offline`.

The summary follows the predominant language of the conversation: mostly Russian
speech produces a Russian summary; mostly English speech produces an English one.
If neither language clearly predominates, both may be used as appropriate to the
topics. Names and technical terms can retain their original language. Intermediate
notes preserve the source languages and their approximate proportions. Application
headings do not determine the summary language. `--language` guides recognition
and does not force or translate the summary language.

Summaries distinguish decisions from proposals and open questions, and include
owners and deadlines only when explicitly present.

## Summary detail: 1–10

`--summary-detail N` controls how much substantive information the summary retains.
The default is `1`, preserving the earlier brief-summary style. This option is
independent of the model's reasoning effort: higher detail requests more coverage,
not a different reasoning setting.

| Level | Approximate length for long, information-dense discussions | Word guide |
| --- | --- | --- |
| `1` | Half a page to one page: main points, outcome, decisions, and actions | 200–450 |
| `5` | Roughly 3–5 pages: key discussion threads, positions, reasoning, alternatives, and constraints | 1,200–2,250 |
| `10` | Up to roughly 10 pages: a detailed, compressed account of every substantive thread | 2,400–4,500 |

Levels in between progressively increase coverage. The word ceiling is `450 × N`;
the lower word guide is 200 at level 1 and `240 × N` at other levels. These are
guides and ceilings, **not minimum quotas**. Page estimates assume roughly 400–450
words per page; actual pagination depends on font, spacing, and editor.

A short or repetitive conversation should stay short even at level 10. The prompt
asks for a result substantially shorter than the original speech, normally no more
than half its words and often much less. It forbids padding, added background,
duplicated facts, and a turn-by-turn retelling. Key decisions, consequential facts,
corrections, qualifications, unresolved disagreements, and explicit actions matter
at every level. Higher levels retain more reasoning, alternatives, dependencies,
relevant examples, and technical nuance; they do not fill pages with quotations.

```bash
# Select the detail for unfinished recordings
./run.sh --summary-detail 5

# Regenerate only an existing summary, preserving the log and recognition caches
./run.sh -f "recording.mkv" --summary-only --summary-detail 10

# Inspect the actual rendered prompt without making an API call
./run.sh --show-prompt --summary-detail 5
```

Changing detail does not override completed-pair skipping. Use `--summary-only`
to change a finished summary without repeating transcription or fusion. Offline
mode and `--summarize-model none` still disable summaries at every detail level.

One shortening request is made if the answer exceeds the selected word ceiling;
there is no fixed one-page clamp at higher levels. This remains a model-guided
length target, not a guaranteed printed layout. Long-recording notes also retain
more information at higher levels: their word limit grows from 600 to 2,400 per
part. Output token budgets grow to accommodate longer text and reasoning. Higher
detail can therefore increase summary API cost, including intermediate note calls.

## Fully offline mode

```bash
./run.sh --offline
./run.sh -f "recording.mkv" --offline
```

`--offline` takes priority over transcription and summary selections. It forces
`whisper-local`, disables summary generation and fusion, and prohibits model
downloads. No audio or text is sent to OpenAI. There is no local LLM summary.
The prepared `data/.venv` and all local models must already be present; missing
or outdated dependencies produce an error instead of a network bootstrap. Run
`./run.sh --setup` online once before offline use. `--offline --summary-only` is
rejected because offline mode does not generate summaries.

`--transcription-model whisper-local` by itself can still send the final text for
the default API summary. Add `--summarize-model none`, or use `--offline`, for a
local log without cloud text processing.

## What belongs in Git, and what is created locally

| Commit to Git | Keep local; excluded by `.gitignore` |
| --- | --- |
| `src/`, including the small model manifest | The entire `data/` directory |
| `tests/`, `run.sh`, `requirements.txt` | `data/.venv`, downloaded model weights, pip/library/API caches |
| `README.md`, `LICENSE`, `.gitignore`, `.env.example` | Recordings, generated logs/summaries, comparisons, and `.env` |

A fresh checkout has no `data` directory or `.env`. Copy `.env.example` when API
features are needed; `run.sh` creates `data` and the environment automatically.
For a source checkout on another machine, follow the setup commands rather than
copying the virtual environment. Python virtual environments depend on their base
Python installation and location; they should be recreated after moving the
project or removing/upgrading the base Python.

## Data, models, Python environment, and caches

Downloaded models, the isolated Python environment, and default caches live inside the
**project's** `data` directory. Source code and its static resources live in `src`,
while tests live in the separate root-level `tests` directory:

```text
scribe/
  run.sh
  README.md
  LICENSE
  .env
  .env.example
  .gitignore
  requirements.txt
  src/
    scribe.py
    resources/
      models-manifest.json
  tests/
    __init__.py
    test_scribe.py
    test_backends.py
    test_modes.py
    test_summary_detail.py
    test_setup.py
  data/
    recording.mkv
    recording.log.md
    recording.summary.md
    models/
    .venv/
    .cache/
    comparison/
```

`requirements.txt` pins the declared library versions installed into `data/.venv`.
The launcher compares its SHA-256 with the last successful dependency installation;
unchanged requirements reuse the environment without invoking pip. Changed
requirements are installed on the next online launch. An interrupted installation
has no success stamp and is retried. Normal source updates do not require model
downloads unless the model manifest changes. No packages are installed globally.

`data/.venv` refers to the separately installed Python and contains Scribe's
libraries; it is not a copied standalone Python distribution. It is disposable
and excluded from Git. To recreate it after moving the project or changing Python,
run these commands from the Scribe project directory, without deleting models,
recordings, results, or API caches:

```bash
rm -rf data/.venv
./run.sh --setup
```

Older prepared installations may still have `data/runtime/python`. The launcher
can use that only for compatibility when no new environment exists. `--setup`
always creates the new environment from a separately installed Python. Once the
new setup succeeds, `data/runtime` is no longer required and need not be retained.

`src/resources/models-manifest.json` is static application metadata: model-relative
paths, download URLs, file sizes, SHA-256 checksums, and archive extraction details.
It is required for model preparation and verification, including offline checks;
the actual downloaded model files belong in `data/models`. Keep this resource
with the source code when copying or restoring the application.

The project root remains the base for `.env`, `data`, and `run.sh` regardless of
the source file's location. Tests add `src` to their import path through
`tests/__init__.py`, so testing the portable application requires no package
installation or additional dependencies.

The input/output `./data` directory is relative to the Terminal working directory.
Persistent resources use the application directory so that the launcher can find
its environment even when launched from elsewhere. In the usual case these are the
same `data` directory. `--output-dir`, `--models-dir`, and `--cache-dir` explicitly
override their respective defaults; they do not relocate `data/.venv`.

`data/.cache` includes GPT audio responses, voice intervals, Whisper words, source
transcripts, fusion responses, output ownership, locks, previous generated results,
library caches, and temporary extracted/chunk audio. Temporary audio directories
are removed normally; forced process termination can leave temporary files there.
The two raw sources are `<source-cache>/sources/gpt-transcribe.txt` and
`<source-cache>/sources/local.log.md`. Output filenames keep the recording's stem.

Application bytecode generation is disabled with Python `-B` and
`sys.dont_write_bytecode`. No root-level `__pycache__` is needed. Existing dependency
bytecode is inside `data/.venv`; it is safe to retain there.

Whisper uses the downloaded MLX large-v3-turbo model. Voice separation uses local
pyannote segmentation and WeSpeaker ResNet-34 embeddings through sherpa-onnx; it
is a separate stage from Whisper. The default known speaker count is two. Labels
follow first voice appearance and never guess real names. Overlapping speech can
still have uncertain attribution. `[speaker uncertain: words]` and
`[low-confidence speech: words]` apply only to the affected span; one uncertain
word does not mark an entire turn. `[unintelligible]` means no words were recognized.
Cloud transcription alone does not supply the local A/B labels in this tool.

The model manifest records sizes and SHA-256 hashes. Missing local models can be
downloaded automatically in online local/combined mode. `--download-models` prepares
them explicitly, and `--verify-models` also checks their hashes. No Hugging Face login
is required. Prepare each machine online with `./run.sh --setup` before using it
offline. Downloaded weights can be copied into `data/models` and checked with
`--verify-models`; the Python environment should be recreated on each machine.
Pip's cache is `data/.cache/pip`. No root-level models, runtime, virtual environment,
or application cache is used. Model weights are needed for local/combined modes;
API-only recognition does not use them. API caches are optional for a fresh setup
but preserve resumability and avoid repeating paid recognition calls.

## API key and configuration

Copy `.env.example` to `.env` and set `OPENAI_API_KEY`. The existing key remains
valid after resource relocation. Do not share the real `.env` file. Environment
variables take priority over `.env`; the file is parsed as data and never executed.

```text
OPENAI_API_KEY=your-api-key
SCRIBE_SUMMARIZE_MODEL=gpt-6.1-sol:medium
```

`SCRIBE_SUMMARIZE_MODEL` supplies the default for `--summarize-model`; the explicit
CLI option wins. The old `OPENAI_MODEL` and `OPENAI_REASONING` settings are no longer
used. No API key is required to skip completed pairs or run offline.
API requests consume the account's API credits/billing; do not infer available
API balance from a ChatGPT subscription. See the account's API Billing page.

## Complete command-line reference

| Option | Default | Behavior |
| --- | --- | --- |
| `-h`, `--help` | — | Show English help. |
| `-f FILE`, `--file FILE` | Scan `./data` | Repeat to select several files; bare names search `./data` and `~/Movies`. |
| `--transcription-model gpt-transcribe\|whisper-local\|all` | `all` | API only, local only, or both plus reconciliation. |
| `--summarize-model MODEL[:EFFORT]\|none` | `gpt-6.1-sol:medium` | Summary model/effort; also controls all-mode fusion. |
| `--summary-detail 1..10` | `1` | How much substantive detail to retain; guides range from half a page to up to ten pages, subject to the source content. |
| `--offline` | Off | Force local recognition, no summary, no API calls or downloads. |
| `--output-dir DIR` | Working directory's `data` | Destination for logs and summaries. |
| `--speakers N` | `2` | Positive known speaker count for local diarization. |
| `--language CODE` | `auto` | Local per-chunk detection; GPT receives Russian/English hints. An explicit code guides either recognizer. |
| `--vocabulary TEXT` | Empty | Domain terms/names for local Whisper and GPT keyword hints. |
| `--models-dir DIR` | Application's `data/models` | Explicit local model directory. |
| `--cache-dir DIR` | Application's `data/.cache` | Explicit checkpoint/library/temp cache directory. |
| `--force` | Off | Bypass completion skipping and recognition/API caches; may repeat paid calls. |
| `--transcribe-only` | Off | Alias for disabling final summaries. Combined-mode fusion still uses the API. |
| `--summary-only` | Off | Explicitly regenerate summary from an existing log, without recognition/fusion. |
| `--download-models` | Off | Prepare/verify local models and exit. Offline mode only checks existing files. |
| `--verify-models` | Off | Verify SHA-256 hashes as well as sizes when preparing local models. |
| `--show-prompt` | Off | Print the rendered final summary prompt for the selected detail, without processing or API calls. |
| `--version` | — | Print the version. |
| `--setup` | Off | Prepare the isolated Python environment through the launcher, prepare local models, and exit without recordings or paid API calls. |

`--transcribe-only` and `--summary-only` are mutually exclusive. Long options must
be written in full. The removed `--model`, `--reasoning`, and transcription value
`whisper` are rejected; use the new options above.

## Editable prompts and long recordings

The actual instructions are constants near the top of `src/scribe.py`:

- `FUSION_PROMPT`: combine clear GPT words with fixed local voice/time anchors.
- `SUMMARIZATION_PROMPT`: final summary template, including language and detail rules.
- `PART_NOTES_PROMPT`: detail-aware factual notes template for long transcripts.

`summary_prompt()` fills `{summary_detail}`, `{summary_min_words}`, and
`{summary_max_words}` in the final template. `notes_prompt()` fills
`{summary_detail}` and `{notes_word_limit}` in the notes template. The selected
detail is also recorded in the summary cache settings.

Transcript content is treated as untrusted data, never executable instructions.
The prompts prohibit invented facts, speech, speakers, decisions, and deadlines.
Fusion can change text but cannot change anchor IDs, speaker labels, or times.
The application rejects responses that omit or duplicate anchors or remove existing
speaker-uncertainty markers; it saves the usable local log instead.

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

## Resume behavior and failures

Keep `data/.cache` if you want resume information and inexpensive retries. Voice,
word, cloud-audio, and fusion checkpoints are separate. Removing the cache loses
both resumability and existing-output ownership. A changed or moved source can
have a different cache identity. Unknown existing partial outputs are protected;
use `--summary-only` for an edited log or deliberately choose `--force`.

Previous generated logs are backed up in the output's cache before replacement.
Previous summaries are backed up before forced replacement or removal after a log
change, so a failed summary call cannot leave an old summary beside a changed log.
Completed pairs are never touched by an ordinary run, even if their state is missing.

Output writes are atomic. Per-output locks prevent two instances sharing a cache
from processing the same result simultaneously. Per-output state prevents accidental
reuse across different output directories. Failures for one recording are reported
and processing continues with the remaining selected inputs. Authentication,
unavailable models, quota limits, refusals, and incomplete responses are errors;
quota errors are not retried. Transient HTTP 429/500/502/503/504 errors receive at
most two retries. Credentials are never intentionally logged and are redacted from
caught errors. Ctrl+C preserves completed files.

Exit codes: `0` for success/skipped inputs, `1` for per-recording failures, `2` for
input/configuration errors, and `130` for interruption.

## Examples

```bash
# Default: both recognizers, fusion, and a Sol medium summary
./run.sh

# API transcription and summary, without local voice models
./run.sh -f "recording.mkv" --transcription-model gpt-transcribe

# Local recognition, followed by an API summary
./run.sh --transcription-model whisper-local

# Cloud audio recognition only; no text-model calls
./run.sh --transcription-model gpt-transcribe --summarize-model none

# Strictly local log; no network calls or summary
./run.sh --offline

# Luna for fusion and summary on an unfinished recording
./run.sh --transcription-model all --summarize-model gpt-6-luna:medium

# Deliberately replace only an existing summary using Luna
./run.sh -f "recording.mkv" --summary-only --summarize-model gpt-6-luna:medium
```

## License

Scribe's source code is licensed under the MIT License; see [LICENSE](LICENSE).
Third-party libraries and downloaded models retain their respective licenses.

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
notes. Setup checks cover a ready virtual environment without a bundled runtime,
offline rejection of outdated dependencies, and Git exclusions for generated files.
The original seven-minute recording has also been used
for real API comparisons. In the original local installation, preserved Sol
results, controlled Sol/Luna outputs, rejected candidate diagnostics, and usage/cost
estimates are stored under `data/comparison/luna-vs-sol/`. These are local experiment
artifacts and are **not included in the Git repository**. A fresh GitHub checkout
does not contain the recordings, comparison transcripts, summaries, reports, or
usage logs. The entire `data/` directory, including `data/comparison/`, is excluded
by `.gitignore`; setup does not download or recreate those private comparison files.
If you have the local comparison report, consult it before choosing Luna for
fusion: a lower token price does not establish equivalent transcript quality.

Official references: [API pricing](https://developers.openai.com/api/docs/pricing),
[GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol), and
[GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna).
