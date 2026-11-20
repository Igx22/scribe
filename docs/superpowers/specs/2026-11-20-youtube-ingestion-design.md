# YouTube URL ingestion and local media input

Date: 2026-11-20

Task: SCR-101

Status: Approved for implementation, testing and commit.

## User workflow

A user with a configured Scribe installation runs `./scribe.sh --setup` and can then
pass one YouTube video URL or select a local MKV, MP4 or WebM file. The normal
YouTube run produces the full video with sound, the transcript and a standalone
HTML report. Keeping the picture track makes future slide extraction possible.
Extracting slides or frames is a separate feature.

```bash
./scribe.sh --setup
./scribe.sh --youtube "https://www.youtube.com/watch?v=VIDEO_ID"
./scribe.sh --youtube "URL" --output-dir ~/Movies/talks
./scribe.sh --youtube "URL" --cookies-from-browser brave
./scribe.sh --youtube "URL" --cookies cookies.txt
./scribe.sh -f ./talk.mp4
```

`--youtube` takes one completed video and is mutually exclusive with `-f`,
`--input-dir` and `--monitor-dir`. A watch URL that also identifies a playlist
selects only that video. Playlist-only URLs, batches of URLs and live streams
are outside this version. Reject `--youtube` with `--offline` during argument
validation, even if the video was downloaded previously. Explain that URL input
requires online mode and that a saved video can be passed to `-f` offline.

## Download and reuse

1. Extract the video ID from the supplied URL locally. Resolve the destination
   just as Scribe resolves `--output-dir`. The default is `./data` relative to
   the launch directory. Save the media directly in that directory alongside its
   transcript and report. For example, with `--output-dir ~/Movies/talks`, all
   three go directly into `~/Movies/talks/`.
2. Before contacting YouTube or reading any cookies, look in that directory for
   a completed download of the same video ID. Verify that the file is readable
   and contains both video and audio. Reuse it across URL spellings and title
   changes. When the usual completed-output check passes, report the skip and
   finish. If the report is missing, pass the existing media to Scribe and reuse
   compatible processing checkpoints.
3. On a cache miss, try yt-dlp anonymously first, including when a cookie
   source was supplied. If the extractor identifies a sign-in requirement,
   follow the authentication rules below. Use yt-dlp's default quality
   selection. The manual 720p experiment sets no resolution limit for this feature.
4. Keep the complete video and audio. When both arrive in one supported
   container, use that file directly. When delivered separately, let yt-dlp
   invoke FFmpeg to merge the streams by copying them into a compatible
   container. Pass the actual finished MKV, MP4 or WebM path to Scribe. An MP4
   or WebM can go straight to audio extraction without an intermediate MKV.
5. Publish the download for reuse only after transfer, any merge and the media
   check have succeeded. Partial files and unfinished merges are ineligible.
   Concurrent invocations for the same destination and ID must share the
   completed result. Keep the source video after processing, including if report
   generation fails.

**Proposed filename convention.** Use `<safe title> [<video-id>].<ext>`, falling
back to `<video-id>.<ext>` when the sanitized title is empty or unavailable.
Strip path separators and control characters, keep the name within filesystem
limits and preserve the ID suffix. The ID distinguishes videos with the same
title and allows a repeat run to find an existing file even if the title later
changes. Preserve unrelated files in the destination.

Keep the source URL, ID, original title, channel, duration, selected streams
and language when available, and the completed media path. The HTML links to
the source and uses its title when available. Failure to infer a topic or
speaker role must still allow the completed transcript and summaries to render.
The existing content cache remains keyed by the SHA-256 of the recording bytes
and compatible settings. Video ID identifies the download within its destination.

## Authentication

After an anonymous attempt reports that sign-in is required:

- With `--cookies-from-browser BROWSER[:PROFILE]`, let yt-dlp use the selected
  local browser session. The user signs into YouTube in that browser beforehand.
  On macOS, the system may prompt for permission to read the session.
- With `--cookies FILE`, let yt-dlp use the supplied Netscape-format cookie file.
  The two cookie options are mutually exclusive and apply to URL input only.
- With neither option, stop with a short explanation and an example command to
  rerun with the user's chosen cookie source. A public download that succeeds
  anonymously never accesses the browser or cookie file.

A bare HTTP 403, missing JavaScript runtime or network failure is insufficient
evidence of a sign-in requirement. Report the relevant cause when known. If an
authenticated attempt fails, explain whether the session was unreadable, expired
or lacked access when the extractor gives that information. Keep cookie values
out of console output, diagnostic files, source metadata and reports.

## Local input and approaches considered

Extend explicit `-f` / `--file` selection to MKV, MP4 and WebM. Both a local
file and a completed download enter the same processing path starting with
FFmpeg extraction of the first audio track. Keep repeatable `-f`, filename
lookup, output ownership and the existing cache rules. A file without readable
audio gets a clear error before recognition starts.

Normalizing every download to MKV would fit today's extension check but would
add an unnecessary step for a usable MP4 or WebM. Downloading only audio saves
space but discards the picture track needed for future slides. The selected
approach keeps the full media in its compatible container and extends the core
to accept all three formats.

Scope the local-format expansion to explicit file selection and the shared
processing path. `--monitor-dir` stays specific to growing OBS MKVs, with its
existing stability and finalization checks. Downloads have their own completion
signal. Directory scanning and Finder action registration keep their current
file selection rules in this ticket.

## Setup, progress and documentation

On supported macOS installations, `./scribe.sh --setup` installs or reuses and
checks the tools required for YouTube and local media, including yt-dlp with
YouTube JavaScript support, a compatible runtime such as Deno, and FFmpeg
with any required companion such as ffprobe. Reuse a compatible system FFmpeg
when available and skip downloading the bundled FFmpeg in that case. Otherwise,
install or reuse Scribe's bundled FFmpeg. The downloader must be able to find
the setup-managed tools even when no system copy is on PATH. After successful setup, routine use
requires no separate tool installation or manual downloads. Repeated setup
reuses healthy components. Package selection and update mechanics are left to
implementation planning.

Print the download and merge stage names as they begin. During a long transfer,
show available progress from yt-dlp such as percentage, bytes, speed or ETA.
For a long FFmpeg merge, show progress when measurable and elapsed time
otherwise. Proposed cadence: show an update within about ten seconds and keep
updating while the operation runs. Log a short reuse/skip message on a repeat run.

**README deliverable.** Update the existing quick start and CLI reference
concisely. Show setup, a URL command and a local `-f` example, list MKV/MP4/WebM,
and specify the download location and reuse rule. In a short paragraph explain
anonymous-first download, when to retry with the signed-in browser session
(include one copyable example), and the cookie-file alternative. Mention visible
download/merge progress, the OBS-only monitor and the URL/offline conflict in
their existing option entries. Keep detailed troubleshooting in the usage guide.

Beside the existing table of model download sizes, add a compact table of the
tools and supporting libraries that setup installs for media input. List each
component, the version setup uses and its approximate first-install download
size on the supported Mac. Cover yt-dlp, its YouTube JavaScript support, the
selected JavaScript runtime, and FFmpeg (including ffprobe if used). For tools
shipped together, give the download size once for the bundle.

## Acceptance checks

- After setup on a supported Mac with no separately installed download tools,
  one public URL produces playable video with audio, a transcript and a usable
  HTML report. A newly generated HTML opens in the default browser. Default
  quality is used. Browser profiles and cookies are never read for this download.
- A repeat run finds a verified download in the effective output directory
  before any network request. A changed title or equivalent URL still matches
  the ID. Equal titles with different IDs coexist. Missing exports resume
  from the local media. Interrupted or corrupt downloads never enter ASR.
- Anonymous success, sign-in with either explicit cookie source, missing or
  denied credentials, and a non-authentication failure exercise distinct paths.
  Conflicting URL/offline flags fail before network, cookie or processing work.
- Local MKV, MP4 and WebM all work via `-f`. An MP4 or WebM from the downloader
  enters the same path in its original container. OBS monitoring retains its
  existing eligibility and readiness checks.
- Long downloads and merges show ongoing progress even when no percentage is
  available. The README examples and flag descriptions match the shipped CLI.
- The README lists tool versions and approximate download sizes alongside the
  model table. Verify the figures against the macOS packages fetched by a clean
  setup and identify any bundled or reused component with no separate download.

### Local acceptance recording

Use `data/examples/FLoC0dhY4u4-000000-000212.mkv` for a local end-to-end
check. It contains the first 00:02:12 of the video downloaded for SCR-100,
starting at 00:00:00 and ending after the speaker's opening thought.
Run the clip through `-f` and check that the generated HTML opens and its
transcript includes the closing words audible at the end of the clip. Use
local MP4 and WebM copies of the same excerpt to check those inputs with
identical source material. Keep the media and generated reports in the
Git-ignored `data/examples/` directory. GitHub CI runs independently of
this local recording. The public URL and authentication checks above
exercise the downloader separately.

## References and prior evidence

- [yt-dlp documentation](https://github.com/yt-dlp/yt-dlp#readme).
- [Browser cookies and cookie-file FAQ](https://github.com/yt-dlp/yt-dlp/wiki/FAQ).
- [YouTube JavaScript runtime requirements](https://github.com/yt-dlp/yt-dlp/wiki/EJS).
- The SCR-100 manual run is recorded in `data/youtube/FLoC0dhY4u4/VERIFICATION.md`.
  Its directory layout and quality limit were specific to that run.
