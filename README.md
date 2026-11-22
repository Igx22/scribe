# scribe

Turn YouTube videos and MKV, MP4 or WebM recordings into speaker-labelled transcripts and standalone HTML summaries.
Supports English, Russian, and mixed conversations. Uses the first audio track only.

## Example report

Download the [example HTML report](docs/examples/youtube-report.html) and open it in a browser to explore the video summary and transcript.

**Local file (MKV supported)** · [Video summary](docs/examples/youtube-report.png)

<p>
  <a href="docs/examples/youtube-report.png"><img src="docs/examples/youtube-report-preview.webp" width="400" align="top" alt="Full video summary for Security by obscurity is dead"></a>
</p>

**YouTube conference recording** · [Summary key points (1/10)](docs/examples/youtube-summary-key-points.png) · [Comment key points (1/10)](docs/examples/youtube-comments-key-points.png) · [Smartest comments](docs/examples/youtube-smartest-comments.png)

<p>
  <a href="docs/examples/youtube-summary-key-points.png"><img src="docs/examples/youtube-summary-key-points-preview.webp" width="400" align="top" alt="Summary · Key points (1/10) for AI Expert WARNS: You're Not Ready For 2027"></a>
</p>

<p>
  <a href="docs/examples/youtube-comments-key-points.png"><img src="docs/examples/youtube-comments-key-points-preview.webp" width="400" align="top" alt="Comments · Key points (1/10) for AI Expert WARNS: You're Not Ready For 2027"></a>
  <a href="docs/examples/youtube-smartest-comments.png"><img src="docs/examples/youtube-smartest-comments-preview.webp" width="400" align="top" alt="Smartest comments on the same video, showing the first two entries and their original-comment buttons"></a>
</p>

## Requirements

macOS 14+, Apple Silicon, Python 3.12–3.13.
An OpenAI API key is required for GPT processing; `--offline` needs no key.

## Pipeline

select or download a recording ⇒
extract 1st audio track ⇒
transcribe and detect speakers (multiple formats)  ⇒
aggregate using GPT 6 API ⇒ clean transcription with speakers
⇒ summarize using GPT6 API (multiple formats)


If this is your first installation, follow the setup steps below.

## Quick start

```bash
./scribe.sh --setup
./scribe.sh --youtube "https://www.youtube.com/watch?v=VIDEO_ID"
./scribe.sh -f ./talk.mp4
```

Scribe saves the complete YouTube video with audio at yt-dlp’s default quality
alongside its transcript and HTML report in `./data` or `--output-dir DIR`.
Repeating the command reuses a verified local download by video ID before
contacting YouTube. The new report opens in the default browser.

YouTube report headers use the saved video title and publication date, with
participants from the transcript. The **Comments**
menu offers discussion digests and detailed retellings in **Smartest comments**.
The selected comment digest levels share one final request. Large discussions
can use bounded note batches first.
Use the expand icon beside a retelling to read its original. **Top 100 YouTube
comments** contains up to 100 original top-level comments in YouTube's order.
**Full comments** contains the full retrieved discussion and replies for offline
reading. The **Summary** and **Comments** menus identify the models used for
the video summary, comment filtering, and comment summaries.
See the [YouTube usage guide](docs/USAGE.md#youtube-comments).

Downloads start anonymously. If YouTube requires sign-in, sign in on the
selected browser and rerun with `--cookies-from-browser`, for example
`./scribe.sh --youtube "https://www.youtube.com/watch?v=VIDEO_ID" --cookies-from-browser brave`.
Alternatively, use `--cookies FILE` with a Netscape cookie file.

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

After setup, run `./macos-register-finder-hooks` once to register Scribe's Finder
action. Then right-click an MKV and choose **Quick Actions → Scribe — Local
conversion** to process it in Terminal and open the HTML report in your default
browser. See [Finder setup and permissions](docs/USAGE.md#finder-quick-action-macos).

| Command | Models prepared (approximate download) |
| --- | --- |
| `./scribe.sh --setup` | WhisperX Turbo + Nemotron 3 (**3.38 GB**) |
| `./scribe.sh --setup --transcription-model mlx` | MLX Turbo + Nemotron 3 (**1.73 GB**) |
| `./scribe.sh --setup --transcription-model all` | WhisperX Turbo + MLX Turbo + Nemotron 3 (**4.99 GB**) |

Models are saved to `data/models`. Model sizes exclude Python packages.
Setup makes no paid API calls. Repeated setup reuses valid downloads.

| Media component | Version | Approximate first-install download on Apple Silicon |
| --- | --- | --- |
| yt-dlp | `2026.10.26` | 3.2 MB |
| YouTube JavaScript support (`yt-dlp-ejs`) | `0.8.0` | 53 KB |
| Deno | `2.9.8` | 38.8 MB |
| FFmpeg | Existing `6+`, or bundled `9.0` from `imageio-ffmpeg` `0.8.1` | 0 MB when reused, otherwise 22.6 MB |

Scribe uses FFmpeg for verification, merging and audio extraction. It has no
separate ffprobe dependency.
For other installation paths and Community-1 setup, see [the usage guide](docs/USAGE.md#setup-from-github-start-here).

## Outputs

For `meeting.mkv`, Scribe writes `meeting.log.md` and `meeting.summary.html`.
Reports include summary levels, the final transcript, available source views, and a dark theme.
Input recordings are never modified.
Timestamp-only changes during processing (for example, opening a recording in a
player) are accepted after its full content hash is revalidated. Changed bytes
or a replaced source still stop publication and preserve cached work.

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
New HTML reports show the run's API token counts and estimated cost in the
footer. **Cost breakdown** lists each stage's model, reasoning effort, tokens
and estimated cost.
A lone log resumes only with matching cached source/settings and ownership.
Processing results live in `data/.cache/<full-source-sha256>/` as flat JSON stage
artifacts. Identical recording bytes reuse them after a rename or output move;
different model/settings variants coexist. Logs and HTML are exports: manual log
edits are preserved but never imported into processing or summaries.

```bash
# Replace the report from internal final JSON; preserve an existing log export
./scribe.sh -f "meeting.mkv" --summary-only

# Regenerate report AI stages from saved sources and preserve an existing log
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
# SCRIBE_SUMMARIZE_MODEL=gpt-6.2-sol:xhigh
SCRIBE_REPORT_TABS=1,3,5,10
```

CLI options override environment variables, then `.env`, then built-in defaults.

`--summarize-model MODEL[:EFFORT]` overrides the model for recording summaries
and final reconciliation. GPT-6 Luna Fast screens the saved YouTube discussion,
then GPT-6 Luna with medium reasoning writes the discussion digests and retellings.
A bare model uses `medium`; supported effort values are `low`, `medium`, `high`,
`xhigh`, and `max`, subject to model support. `none` disables reports while
reconciliation still uses `gpt-6.2-astra:xhigh`. With built-in settings,
recording summaries use `gpt-6.2-sol:xhigh` and reconciliation uses
`gpt-6.2-astra:xhigh`. Local-file topics and participant roles use
`gpt-6.2-sol:medium`.

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

Scribe sends the final transcript once and generates all requested uncached
summary levels in one OpenAI request. The default is GPT-6.2 Sol with extra-high
reasoning.

```bash
./scribe.sh -f "meeting.mkv" --summary-only --report-tabs 1 5 10
```

Existing completed reports are skipped on an ordinary run.
Use `--summary-only` to apply a different tab selection without repeating recognition.
See [report details](docs/USAGE.md#report-tabs-and-summary-detail).

## Options

| Option | Default | Behavior |
| --- | --- | --- |
| `-h`, `--help` | — | Show English help. |
| `-f FILE`, `--file FILE` | Scan `--input-dir` or `./data` | Select MKV, MP4 or WebM. Repeat to select several files. Bare names search `./data` and `~/Movies`. |
| `--youtube URL` | Off | Download one completed video at default quality with download and merge progress. Alternative to `-f`, `--input-dir` and `--monitor-dir`. Requires online mode. |
| `--cookies-from-browser BROWSER[:PROFILE]`, `--cookies FILE` | Anonymous | Choose a browser session or Netscape cookie file for YouTube sign-in. Scribe tries anonymously first. |
| `--input-dir DIR` | Working directory's `data` | Scan all MKV files in this folder, without subfolders. Cannot combine with `-f`; does not change the output directory. |
| `--monitor-dir [DIR]` | Off | Watch growing OBS MKVs and wait for 30 seconds of stability plus OBS-style finalization checks. Omit DIR for `~/Movies` on macOS or `~/Videos` on Linux/Windows. Outputs default to this folder. Alternative to `-f` and `--input-dir`. |
| `--transcription-model gpt-transcribe-online\|whisperx\|mlx\|gpt-transcribe+whisperx\|all` | `whisperx` | API only, WhisperX Turbo, MLX Turbo, GPT + WhisperX with reconciliation, or all three recognizers; every ordinary mode then runs GPT text reconciliation. |
| `--diarization-model nemotron\|community-1` | `nemotron` | Independent automatic local diarizer. Community-1 download needs HF access; ignored for API-only recognition. |
| `--summarize-model MODEL[:EFFORT]\|none` | `gpt-6.2-sol:xhigh` for summaries | Explicit model/effort overrides summaries and final GPT reconciliation. `none` disables reports; ordinary modes still reconcile. |
| `--report-tabs LEVEL [LEVEL ...]` | `SCRIBE_REPORT_TABS`, or `1,3,5,10` | Summary levels 1–10 in display order, separated by spaces or commas. Every HTML report includes Transcript. |
| `--offline` | Off | Force local recognition without summaries, API calls or downloads. For a saved YouTube video, use `-f`. |
| `--output-dir DIR` | `./data`; with `--monitor-dir`: the watched folder | Write recording transcripts, reports, error files and YouTube downloads to DIR. |
| `--force` | Off | Bypass completion skipping and recognition/API caches; may repeat paid calls. |
| `--transcribe-only` | Off | Create only the log; equivalent to `--summarize-model none`. Final GPT reconciliation still runs unless offline. |
| `--summary-only` | Off | Regenerate HTML from validated internal final JSON, without audio processing/reconciliation; a log export is optional. |
| `--verify-models` | Off | Verify SHA-256 hashes as well as sizes when preparing local models. |
| `--show-prompt` | Off | Print the combined summary prompt for the selected levels, without processing or API calls. |
| `--version` | — | Print the version. |
| `--setup` | Off | Prepare the isolated Python environment, media tools and selected models without recordings or paid API calls. |

`--transcribe-only` and `--summary-only` are mutually exclusive.
Monitor mode also excludes `-f`, `--input-dir`, `--force`, `--summary-only`,
setup and prompt preview. Long options must be written in full.

Monitoring uses observed growth, 30 seconds of stability and OBS finalization checks;
stationary or very short recordings may need `-f`.
See [monitor behaviour](docs/USAGE.md#monitor-growing-obs-recordings).

## Documentation

- [Usage guide](docs/USAGE.md): installation alternatives, paths, monitoring, retries and configuration.
- [Project context](docs/PROJECT_CONTEXT.md): design decisions, experiments, limitations and mocked tests.

## License

[MIT](LICENSE). Downloaded models and runtimes have [their own licenses](docs/USAGE.md#license).
