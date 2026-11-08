# scribe

Turn MKV recordings into speaker-labelled transcripts and standalone HTML summaries.
Supports English, Russian, and mixed conversations. Uses the first audio track only.

## Requirements

macOS 14+, Apple Silicon, Python 3.12–3.13.
An OpenAI API key is required for GPT processing; `--offline` needs no key.

## Pipeline

capture MKV data ⇒
extract 1st audio track ⇒
transcribe and detect speakers (multiple formats)  ⇒
aggregate using GPT 6 API ⇒ clean transcription with speakers
⇒ summarize using GPT6 API (multiple formats)


If this is your first installation, follow the setup steps below.

## Quick Example

Process all MKV recordings in `./data` and save logs and `.summary.html` reports
to the same folder:

```bash
./scribe.sh
```

Process all MKV recordings in `~/my-recordings` and save results to `~/my-summaries`:

```bash
./scribe.sh --input-dir ~/my-recordings --output-dir ~/my-summaries
```

Process one recording by filename. Scribe searches `./data` and `~/Movies`;
results are saved to `./data`:

```bash
./scribe.sh -f "recording.mkv"
```

Process two recordings and save results to `./data`:

```bash
./scribe.sh -f "first.mkv" -f "second.mkv"
```

Monitor growing OBS Studio MKV recordings in `~/my-meetings`. Once a recording
stops growing and passes the finalization checks, process it and save results
to the same folder:

```bash
./scribe.sh --monitor-dir ~/my-meetings
```

Monitor the OS-specific default video folder and save results there:

```bash
./scribe.sh --monitor-dir
```

Normal quality is achieved by using WhisperX Turbo + Nemotron 3 (local model, default option).
A bit higher quality can be achieved with paid GPT transcribe api.
```bash
./scribe.sh --monitor-dir --transcription-model gpt-transcribe+whisperx
```

## Install

With [Homebrew](https://brew.sh/) installed:

```bash
brew install python@3.13 git
git clone https://github.com/Igx22/scribe.git scribe
cd scribe
cp -n .env.example .env
```

Set `OPENAI_API_KEY` in `.env`, then prepare the environment and default models:

```bash
./scribe.sh --setup
```

| Command | Models prepared (approximate download) |
| --- | --- |
| `./scribe.sh --setup` | WhisperX Turbo + Nemotron 3 (**3.38 GB**) |
| `./scribe.sh --setup --transcription-model mlx` | MLX Turbo + Nemotron 3 (**1.73 GB**) |
| `./scribe.sh --setup --transcription-model all` | WhisperX Turbo + MLX Turbo + Nemotron 3 (**4.99 GB**) |

Models are saved to `data/models`; sizes exclude Python packages.
Setup makes no paid API calls. Repeated setup reuses valid downloads.
For other installation paths and Community-1 setup, see [the usage guide](docs/USAGE.md#setup-from-github-start-here).

## Outputs

For `meeting.mkv`, Scribe writes `meeting.log.md` and `meeting.summary.html`.
Reports include summary levels, the final transcript, available source views, and a dark theme.
Input recordings are never modified.

Each invocation also saves console stdout/stderr to `./data/log/` in the launch
directory. Runs have separate UTF-8 files and rotate at local midnight, regardless
of `--output-dir`. [Console log details](docs/USAGE.md#console-logs).

Processing errors and recovery warnings are saved beside the report in
`meeting.summary.err`, with attempt history and credentials redacted. Reconciliation
retries invalid parts up to twice, then retains their source text and continues;
partial results are marked in the log and HTML. A changed speaker-uncertainty
annotation alone does not cancel reconciliation.

Local processing shows phases, elapsed time and approximate remaining time.
WhisperX reports recognition/alignment progress; Nemotron shows activity without
invented percentages. Before inference, a local-only time range uses comparable
successful runs and excludes reused checkpoints. The first run explicitly reports
missing history; API/report time is not included. [Progress and estimate details](docs/USAGE.md#progress-and-time-estimates).

`--output-dir DIR` sets where recording transcripts, reports and error files are saved.
Without it, results go to `./data` in the current directory, or to the watched folder
when `--monitor-dir` is used. Monitoring is enabled by `--monitor-dir`.

A log plus a summary counts as complete and is skipped, even if settings change.
A lone log resumes only with matching cached source/settings and ownership.
Processing results live in `data/.cache/<full-source-sha256>/` as flat JSON stage
artifacts. Identical recording bytes reuse them after a rename or output move;
different model/settings variants coexist. Logs and HTML are exports: manual log
edits are preserved but never imported into processing or summaries.

```bash
# Replace the report from internal final JSON; preserve an existing log export
./scribe.sh -f "meeting.mkv" --summary-only

# Replace the report and bypass summary/header reuse; preserve an existing log
./scribe.sh -f "meeting.mkv" --summary-only --force

# Reprocess the recording and replace both outputs
./scribe.sh -f "meeting.mkv" --force
```

Summary-only needs a valid selected internal final result, even if a `.log.md`
exists. A missing log export can be recreated from that JSON. Old JSON checkpoints
migrate only when they contain enough verifiable data; an old log alone cannot.
Replacement backs up previous results and may repeat paid requests.
See [resume and failure details](docs/USAGE.md#outputs-and-completed-recordings).

## Transcription modes

Default: WhisperX Turbo recognition + Nemotron 3 speaker segmentation.

| Value | Internet during recognition | Recognition and final log | Local voice labels | Audio uploaded |
| --- | --- | --- | --- | --- |
| `gpt-transcribe-online` | Online | OpenAI GPT-Transcribe, then GPT text reconciliation | No | Yes, extracted audio |
| `whisperx` (default) | Offline | Local WhisperX words/voices, then GPT text reconciliation | Supported names or A, B, C, etc. | No |
| `mlx` | Offline | Local MLX words/voices, then GPT text reconciliation | Supported names or A, B, C, etc. | No |
| `gpt-transcribe+whisperx` | Online | GPT-Transcribe + WhisperX/voices + GPT text reconciliation | A, B, C, etc.; supported names when available | Yes, extracted audio |
| `all` | Online | GPT-Transcribe, WhisperX and MLX; GPT reconciles the final log | Supported names or A, B, C, etc. | Yes, extracted audio |

Online/Offline in the table describes recognition after setup.
**Every ordinary mode also sends text to GPT for final reconciliation**, including
`--transcribe-only` and `--summarize-model none`. Local recognizers never upload audio.

For a fully local run after setup:

```bash
./scribe.sh --offline
```

Offline mode writes a log only. It makes no API calls or downloads and creates no
HTML summary. It keeps an explicit `mlx` selection; otherwise it uses `whisperx`.
See [mode and fallback details](docs/USAGE.md#transcription-modes).

## Diarization models

Choose speaker segmentation independently with `--diarization-model`.

| Value | Model | Internet during diarization | Initial model download |
| --- | --- | --- | --- |
| `nemotron` (default) | Nemotron 3 | Offline | Public download; no Hugging Face account or token required |
| `community-1` | pyannote Community-1 | Offline | Hugging Face account, acceptance of model conditions, and `HF_TOKEN` required |

Both models detect voice counts automatically; Nemotron supports up to eight voices.
API-only recognition does not use a local diarizer.
Names are assigned only from supported conversation evidence; uncertain speakers keep
anonymous labels. See [speaker naming](docs/USAGE.md#speaker-names-from-the-conversation).

## Configuration

Set defaults in `.env`:

```dotenv
OPENAI_API_KEY=your-api-key
SCRIBE_SUMMARIZE_MODEL=gpt-6.1-sol:medium
SCRIBE_REPORT_TABS=1,3,5,10,transcript
```

CLI options override environment variables, then `.env`, then built-in defaults.

`--summarize-model MODEL[:EFFORT]` selects the model for reconciliation and reports.
A bare model uses `medium`; supported effort values are `low`, `medium`, `high`,
`xhigh`, and `max`, subject to model support. `none` disables reports while
reconciliation still uses `gpt-6.1-sol:medium`.

Summaries follow the conversation's predominant language.
See [configuration details](docs/USAGE.md#api-key-and-configuration) and
[summary behaviour](docs/USAGE.md#summary-and-fusion-model).

## Summary detail

The **Summary** menu offers **Key points** (1), **Overview** (3), **Expanded** (5),
and **In depth** (10). **Transcript** contains the final text and available source views.

Detail controls retained information, independently of reasoning effort.
Lengths below are guides for long discussions at roughly 400–450 words per page;
short recordings stay short.

| Level | Approximate length for long, information-dense discussions | Word guide |
| --- | --- | --- |
| `1` | Half a page to one page: main points, outcome, decisions, and actions | 200–450 |
| `3` | Roughly 2–3 pages: main discussion threads, decisions, actions, and supporting context | 720–1,350 |
| `5` | Roughly 3–5 pages: key discussion threads, positions, reasoning, alternatives, and constraints | 1,200–2,250 |
| `10` | Up to roughly 10 pages: a detailed, compressed account of every substantive thread | 2,400–4,500 |

Each level is generated separately, so more levels mean more text API work.

```bash
./scribe.sh -f "meeting.mkv" --summary-only --report-tabs 1 5 10 transcript
```

Existing completed reports are skipped on an ordinary run.
Use `--summary-only` to apply a different tab selection without repeating recognition.
See [report details](docs/USAGE.md#report-tabs-and-summary-detail).

## Options

| Option | Default | Behavior |
| --- | --- | --- |
| `-h`, `--help` | — | Show English help. |
| `-f FILE`, `--file FILE` | Scan `--input-dir` or `./data` | Repeat to select several files; bare names search `./data` and `~/Movies`. Cannot combine with `--input-dir`. |
| `--input-dir DIR` | Working directory's `data` | Scan all MKV files in this folder, without subfolders. Cannot combine with `-f`; does not change the output directory. |
| `--monitor-dir [DIR]` | Off | Watch growing MKVs and wait for 30 seconds of stability plus OBS-style finalization checks. Omit DIR for `~/Movies` on macOS or `~/Videos` on Linux/Windows. Outputs default to this folder. Alternative to `-f` and `--input-dir`. |
| `--transcription-model gpt-transcribe-online\|whisperx\|mlx\|gpt-transcribe+whisperx\|all` | `whisperx` | API only, WhisperX Turbo, MLX Turbo, GPT + WhisperX with reconciliation, or all three recognizers; every ordinary mode then runs GPT text reconciliation. |
| `--diarization-model nemotron\|community-1` | `nemotron` | Independent automatic local diarizer. Community-1 download needs HF access; ignored for API-only recognition. |
| `--summarize-model MODEL[:EFFORT]\|none` | `gpt-6.1-sol:medium` | Report and final GPT reconciliation model/effort; none disables reports, not reconciliation. |
| `--report-tabs TAB [TAB ...]` | `SCRIBE_REPORT_TABS`, or `1,3,5,10,transcript` | Summary levels 1–10 and/or `transcript`, separated by spaces or commas. CLI replaces the selection; levels keep their order within the Summary menu. Always writes standalone HTML. |
| `--offline` | Off | Force local recognition, no summary, no API calls or downloads. |
| `--output-dir DIR` | `./data`; with `--monitor-dir`: the watched folder | Write recording transcripts, reports and error files to DIR. Does not enable monitoring. |
| `--force` | Off | Bypass completion skipping and recognition/API caches; may repeat paid calls. |
| `--transcribe-only` | Off | Create only the log; equivalent to `--summarize-model none`. Final GPT reconciliation still runs unless offline. |
| `--summary-only` | Off | Regenerate HTML from validated internal final JSON, without audio processing/reconciliation; a log export is optional. |
| `--verify-models` | Off | Verify SHA-256 hashes as well as sizes when preparing local models. |
| `--show-prompt` | Off | Print the rendered final summary prompt for the selected detail, without processing or API calls. |
| `--version` | — | Print the version. |
| `--setup` | Off | Prepare the isolated Python environment through the launcher, prepare selected models, and exit without recordings or paid API calls. |

`--transcribe-only` and `--summary-only` are mutually exclusive.
Monitor mode also excludes `-f`, `--input-dir`, `--force`, `--summary-only`,
setup and prompt preview. Long options must be written in full.

Monitoring uses observed growth, 30 seconds of stability and OBS finalization checks;
stationary or very short recordings may need `-f`.
See [monitor behaviour](docs/USAGE.md#monitor-growing-obs-recordings).

## Documentation

- [Usage guide](docs/USAGE.md): installation alternatives, paths, monitoring, retries and configuration.
- [Project context](docs/PROJECT_CONTEXT.md): design decisions, experiments, limitations and mocked tests.
- [Tasks](TASKS.md): requested and completed work.

## License

[MIT](LICENSE). Downloaded models and runtimes have [their own licenses](docs/USAGE.md#license).
