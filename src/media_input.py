"""YouTube acquisition and validation for Scribe's ordinary media pipeline."""
from contextlib import contextmanager
import errno
import importlib.metadata
import io
import math
from http.cookiejar import NETSCAPE_MAGIC_RGX
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import threading
import time
import unicodedata
from urllib.parse import parse_qs, urlsplit


MEDIA_EXTENSIONS = {".mkv", ".mp4", ".webm"}
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
YOUTUBE_OFFLINE_ERROR = "--youtube requires online mode. Use -f with the saved video in --offline mode."


class MediaError(RuntimeError):
    pass


def watch_url(video_id):
    return f"https://www.youtube.com/watch?v={video_id}"


def youtube_id(url):
    try:
        parts = urlsplit(url)
        host = parts.netloc.lower()
        path = parts.path.rstrip("/").split("/")
        if parts.scheme in ("http", "https"):
            ids = []
            if host == "youtu.be" and len(path) == 2:
                ids = path[1:]
            elif host in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"):
                if path == ["", "watch"]:
                    ids = parse_qs(parts.query, keep_blank_values=True).get("v", [])
                elif len(path) == 3 and path[1] in ("shorts", "embed", "live", "v"):
                    ids = path[2:]
            if len(ids) == 1 and VIDEO_ID.fullmatch(ids[0]):
                return ids[0]
    except ValueError:
        pass
    raise MediaError("--youtube requires one YouTube video URL (watch, share, Shorts or embed), e.g. "
                     "https://www.youtube.com/watch?v=VIDEO_ID.")


def ffmpeg_version(executable):
    try:
        result = subprocess.run([executable, "-version"], check=True, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.match(r"ffmpeg version n?((\d+)\.[^\s]+)", result.stdout)
    if match and int(match[2]) >= 6:
        return match[1]
    return None


def ffmpeg_hint():
    return Path(sys.prefix) / ".scribe-ffmpeg"


def system_ffmpeg():
    try:
        remembered = ffmpeg_hint().read_text().strip()
    except OSError:
        remembered = ""
    candidates = (os.getenv("IMAGEIO_FFMPEG_EXE"), shutil.which("ffmpeg"), remembered)
    for candidate in dict.fromkeys(filter(None, candidates)):
        executable = shutil.which(candidate)
        if executable and ffmpeg_version(executable):
            return os.path.abspath(executable)
    return None


def bundled_ffmpeg():
    try:
        import imageio_ffmpeg
        binaries = Path(imageio_ffmpeg.__file__).with_name("binaries")
        binary = next(binaries.glob("ffmpeg-macos-aarch64-*"), None)
        if binary and ffmpeg_version(binary):
            return str(binary)
    except ImportError:
        pass
    return None


def prepare_ffmpeg():
    """Remember a usable system path, or confirm the optional bundle is healthy."""
    executable = system_ffmpeg()
    if executable:
        hint = ffmpeg_hint()
        # The launcher can run concurrently. A reader sees either complete path.
        with tempfile.NamedTemporaryFile(mode="w", dir=hint.parent, delete=False) as temp:
            temp.write(executable + "\n")
        try:
            os.replace(temp.name, hint)
        finally:
            Path(temp.name).unlink(missing_ok=True)
        return True
    return bundled_ffmpeg() is not None


def ffmpeg_executable():
    executable = system_ffmpeg() or bundled_ffmpeg()
    if executable is None:
        raise MediaError("FFmpeg 6 or newer is required. Run ./scribe.sh --setup to prepare FFmpeg.")
    return executable


def deno_executable():
    return Path(sysconfig.get_path("scripts")) / "deno"


def ensure_media_tools(say):
    try:
        import yt_dlp
        import yt_dlp_ejs
        versions = [importlib.metadata.version(name) for name in ("yt-dlp", "yt-dlp-ejs")]
        runtime = subprocess.run([deno_executable(), "--version"], check=True, capture_output=True, text=True, timeout=15)
        versions.append(" ".join(runtime.stdout.splitlines()[0].split()[:2]))
        executable = ffmpeg_executable()
        versions.append(f"FFmpeg {ffmpeg_version(executable)} ({executable})")
    except (ImportError, OSError, RuntimeError, subprocess.SubprocessError, IndexError):
        raise MediaError("Media tools are unavailable. Run ./scribe.sh --setup to prepare yt-dlp, EJS, Deno and FFmpeg.") from None
    say(f"Media tools ready: yt-dlp {versions[0]}, EJS {versions[1]}, {versions[2]}, {versions[3]}.")


def verify_video(path, duration=None):
    """Decode both tracks before publication and check for a prematurely ended transfer."""
    if path.suffix.lower() not in MEDIA_EXTENSIONS or path.is_symlink() or not path.is_file():
        return False
    result = subprocess.run([ffmpeg_executable(), "-nostdin", "-v", "error", "-xerror", "-err_detect", "explode",
                             "-abort_on", "empty_output_stream", "-i", str(path), "-map", "0:V:0", "-map", "0:a:0",
                             "-progress", "pipe:1", "-nostats", "-f", "null", "-"], capture_output=True, text=True)
    if result.returncode or result.stderr:
        return False
    if isinstance(duration, (int, float)) and duration > 3:
        times = re.findall(r"(?m)^out_time_us=(\d+)$", result.stdout)
        return bool(times) and int(times[-1]) / 1_000_000 >= duration - 3
    return True


class DownloadProgress:
    def __init__(self, say, initial_stage="YouTube download"):
        self.say = say
        self.initial_stage = initial_stage
        self.finished = threading.Event()
        self.thread = threading.Thread(target=self.heartbeat, daemon=True)
        self.label = ""
        self.started = 0
        self.detail = ""

    def stage(self, label):
        self.label, self.started, self.detail = label, time.monotonic(), ""
        self.say(f"  {label}...")

    def __enter__(self):
        self.stage(self.initial_stage)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.finished.set()
        self.thread.join()

    def heartbeat(self):
        while not self.finished.wait(8):
            elapsed = int(time.monotonic() - self.started)
            self.say(f"  {self.label} · elapsed {elapsed}s{self.detail}")

    def transfer(self, status):
        if status.get("status") == "downloading":
            done = status.get("downloaded_bytes") or 0
            total = status.get("total_bytes") or status.get("total_bytes_estimate")
            detail = f" · {done / 1_000_000:.1f} MB"
            if total:
                detail += f" ({min(done / total, 1):.0%})"
            if status.get("speed"):
                detail += f" · {status['speed'] / 1_000_000:.1f} MB/s"
            if status.get("eta") is not None:
                detail += f" · ETA {int(status['eta'])}s"
            self.detail = detail

    def postprocess(self, status):
        if status.get("status") == "started" and status.get("postprocessor") == "Merger":
            self.stage("FFmpeg merge")


class DownloadMessages:
    """Classify extractor diagnostics without forwarding raw text or cookie data."""
    def __init__(self):
        self.warnings = set()

    def debug(self, _message):
        pass

    def warning(self, message):
        self.warnings.add(self.reason(message))

    error = warning

    @staticmethod
    def reason(message):
        message = message.lower()
        if re.search(r"find-generic-password failed|cannot decrypt .*cookies|cookies could not be decrypted", message):
            return "cookie-read"
        if re.search(r"unable to open for writing|permission denied|no space left on device|read-only file system", message):
            return "disk"
        if re.search(r"\bhttp(?: error| status(?: code)?)? 403\b", message):
            return "403"
        if re.search(r"cookies?.*(?:no longer valid|expired)|(?:expired|invalidated).*session", message):
            return "expired"
        if re.search(r"private video|video is private|for members only|members.only|(?:account|membership) required|not (?:been )?granted access", message):
            return "access"
        if re.search(r"(?:sign[ -]in|log[ -]in) to (?:confirm|view|watch|access|continue|verify)|"
                     r"(?:please|must|need to|requires? you to) (?:sign[ -]in|log[ -]in)|"
                     r"(?:sign[ -]in|login|authentication) (?:is )?required", message):
            return "sign-in"
        if re.search(r"javascript runtime|challenge solving failed|ejs.*(?:unavailable|not found)", message):
            return "javascript"
        if re.search(r"unable to download (?:api|webpage)|network|timed out|certificate|resolve host|getaddrinfo", message):
            return "network"
        if "ffmpeg" in message:
            return "ffmpeg"
        if re.search(r"video unavailable|video is not available|has been removed", message):
            return "unavailable"
        return "unknown"

    def failure(self, exc, authenticated):
        cause = self.reason(str(exc))
        if authenticated and cause in ("unknown", "sign-in", "access") and "cookie-read" in self.warnings:
            raise MediaError("yt-dlp could not read or decrypt the supplied browser session. Check browser and Keychain permissions.") from None
        if authenticated and (cause == "expired" or "expired" in self.warnings):
            raise MediaError("The supplied YouTube session has expired. Sign in again or export a fresh cookie file.") from None
        if authenticated and cause in ("sign-in", "access"):
            raise MediaError("YouTube rejected the supplied session or the account lacks access to this video.") from None
        if cause == "unknown" and "javascript" in self.warnings:
            cause = "javascript"
        messages = {
            "403": "YouTube returned HTTP 403 while downloading the video.",
            "disk": "Could not write the YouTube download. Check the output directory permissions and disk space.",
            "javascript": "YouTube extraction could not use its JavaScript support. Check Deno and EJS with ./scribe.sh --setup.",
            "network": "The connection to YouTube failed. Check the network and try again.",
            "ffmpeg": "FFmpeg could not finish the YouTube media. Check the available disk space and run ./scribe.sh --setup.",
            "unavailable": "YouTube reports that this video is unavailable.",
        }
        raise MediaError(messages.get(cause, "yt-dlp could not download this completed YouTube video.")) from None


class SignInRequired(MediaError):
    pass


def _reject_live(info, *, incomplete):
    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming", "post_live"):
        raise MediaError("--youtube accepts completed videos. Wait until YouTube finishes processing the stream.")


def read_cookie_file(path):
    """Reject malformed lines before yt-dlp can echo them in its parser warnings."""
    try:
        contents = path.expanduser().read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        raise MediaError("Could not read the supplied Netscape cookie file.") from None
    lines = contents.splitlines()
    if not lines or not NETSCAPE_MAGIC_RGX.match(lines[0]):
        raise MediaError("The supplied cookie file must use Netscape format.")
    for line in lines[1:]:
        if not line.strip() or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        fields = line.removeprefix("#HttpOnly_").split("\t")
        if (len(fields) != 7 or fields[1] != ("TRUE" if fields[0].startswith(".") else "FALSE")
                or fields[3] not in ("TRUE", "FALSE")
                or (fields[4] and (not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", fields[4])
                                   or not math.isfinite(float(fields[4]))))):
            raise MediaError("The supplied Netscape cookie file contains a malformed entry.")
    return io.StringIO(contents)


def youtube_credentials(cookie_file, browser):
    if browser is not None:
        name, _, profile = browser.partition(":")
        return {"cookiesfrombrowser": (name.lower(), profile or None, None, None)}
    if cookie_file is not None:
        # yt-dlp updates the jar when closing. Keep that write in memory.
        return {"cookiefile": read_cookie_file(cookie_file)}
    return {}


def download_attempt(url, scratch, say, *, cookie_file=None, browser=None):
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.cookies import CookieLoadError
        from yt_dlp.utils import DownloadError
        ffmpeg = ffmpeg_executable()
        deno = deno_executable()
        if not os.access(deno, os.X_OK):
            raise FileNotFoundError
    except (ImportError, OSError, RuntimeError):
        raise MediaError("YouTube download tools are unavailable. Run ./scribe.sh --setup first.") from None
    logger = DownloadMessages()
    with DownloadProgress(say) as progress:
        options = {"outtmpl": str(scratch).replace("%", "%%") + "/video.%(ext)s", "noplaylist": True,
                   "allowed_extractors": ["youtube"], "match_filter": _reject_live,
                   "ffmpeg_location": ffmpeg, "js_runtimes": {"deno": {"path": str(deno)}},
                   "cachedir": False, "quiet": True, "logger": logger,
                   "progress_hooks": [progress.transfer], "postprocessor_hooks": [progress.postprocess]}
        try:
            options.update(youtube_credentials(cookie_file, browser))
            with YoutubeDL(options) as downloader:
                return downloader.extract_info(url, download=True)
        except CookieLoadError:
            raise MediaError("yt-dlp could not read the supplied browser session or Netscape cookie file.") from None
        except DownloadError as exc:
            authenticated = browser is not None or cookie_file is not None
            if not authenticated and logger.reason(str(exc)) in ("sign-in", "access"):
                raise SignInRequired("YouTube requires sign-in for this video. Rerun with "
                                     f"./scribe.sh --youtube '{url}' --cookies-from-browser brave "
                                     "or use --cookies FILE with a Netscape cookie file.") from None
            logger.failure(exc, authenticated)
        except (OSError, ValueError):
            if cookie_file is not None or browser is not None:
                raise MediaError("yt-dlp could not use the supplied browser session or Netscape cookie file.") from None
            raise MediaError("yt-dlp could not read or write the download files.") from None


COMMENT_FIELDS = ("id", "parent", "author", "text")


def normalize_youtube_comments(entries):
    rows, seen, invalid = [], set(), False
    for entry in entries:
        if (not isinstance(entry, dict) or any(not isinstance(entry.get(key), str) for key in ("id", "parent", "text"))
                or not entry["id"] or entry["id"] == "root" or not entry["parent"]):
            invalid = True
            continue
        if entry["id"] in seen:
            continue
        seen.add(entry["id"])
        row = {key: entry.get(key) for key in COMMENT_FIELDS}
        if not isinstance(row["author"], str):
            row["author"] = ""
        label = entry.get("published", entry.get("_time_text"))
        if isinstance(label, str) and label.strip():
            row["published"] = label
        rows.append(row)
    return rows, invalid


class CommentMessages(DownloadMessages):
    def __init__(self):
        super().__init__()
        self.incomplete = False
        self.confirmed_empty = False
        self.confirmed_disabled = False

    def debug(self, message):
        # yt-dlp's returned comment_count is computed from extracted rows.
        # Its comment-header progress marker reflects the upstream count.
        if re.fullmatch(r"\[youtube\] Downloading ~0 comments", message.strip()):
            self.confirmed_empty = True

    def warning(self, message):
        super().warning(message)
        if re.search(r"YouTube said:.*\bcomments?\s+(?:(?:on|for) this video\s+)?"
                     r"(?:(?:are|have been)\s+)?(?:turned off|disabled)\b", message, re.I):
            self.confirmed_disabled = True
        if re.search(r"\b(?:sign|log)[ -]in to (?:see|read) comments\b", message, re.I):
            self.warnings.add("sign-in")
        if re.search(r"comments looping|incomplete data.*(?:giving up|retrying did not help|reply thread)|"
                     r"unable to download comment", message, re.I):
            self.incomplete = True

    def error(self, message):
        super().warning(message)
        self.incomplete = True


def fetch_youtube_comments(video_id, args, say):
    """Retrieve all available threads without transferring the video or its audio."""
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.cookies import CookieLoadError
        from yt_dlp.utils import DownloadError
    except ImportError:
        raise MediaError("YouTube comment extraction tools are unavailable.") from None
    credentials = (args.cookies, args.cookies_from_browser)
    for cookie_file, browser in ((None, None), credentials) if any(credentials) else ((None, None),):
        logger = CommentMessages()
        options = {"getcomments": True, "noplaylist": True, "allowed_extractors": ["youtube"],
                   "ignore_no_formats_error": True, "ignoreerrors": True,
                   "cachedir": False, "quiet": True, "logger": logger, "socket_timeout": 20,
                   "extractor_args": {"youtube": {"comment_sort": ["new"],
                                                  "raise_incomplete_data": ["true"]}},
                   "js_runtimes": {"deno": {"path": str(deno_executable())}}}
        try:
            options.update(youtube_credentials(cookie_file, browser))
            with DownloadProgress(say, initial_stage="Fetching YouTube comments"), YoutubeDL(options) as downloader:
                info = downloader.extract_info(watch_url(video_id), download=False)
        except DownloadError as exc:
            logger.error(str(exc))
            info = None
        except (CookieLoadError, OSError, ValueError):
            info = None
        if not cookie_file and not browser and any(credentials) and logger.warnings & {"sign-in", "access"}:
            say("  YouTube requires sign-in for comments; retrying with the supplied cookie source.")
            continue
        if not isinstance(info, dict) or info.get("id") != video_id:
            return "unavailable", []
        raw = info.get("comments")
        count = info.get("comment_count")
        if isinstance(raw, list):
            rows, malformed = normalize_youtube_comments(raw)
            if rows:
                status = "partial" if malformed or count is None or logger.incomplete else "complete"
                return status, rows
            if not raw and count == 0 and logger.confirmed_empty and not logger.incomplete:
                return "empty", []
        if raw is None and count is None and logger.confirmed_disabled and not logger.incomplete:
            return "disabled", []
        return "unavailable", []
    return "unavailable", []


def _source_metadata(info, video_id):
    fields = ("format_id", "ext", "vcodec", "acodec", "width", "height", "fps", "language", "abr")
    streams = info.get("requested_formats") or [info]
    return {"id": video_id, "url": watch_url(video_id),
            **{key: info[key] for key in ("title", "channel", "duration", "language") if info.get(key) is not None},
            "streams": [{key: stream[key] for key in fields if stream.get(key) is not None} for stream in streams]}


def _publish_media(source, target):
    if sys.platform != "darwin":
        os.link(source, target)
        return
    from ctypes import CDLL, c_char_p, c_int, c_uint, get_errno
    rename = CDLL(None, use_errno=True).renamex_np
    rename.argtypes = [c_char_p, c_char_p, c_uint]
    rename.restype = c_int
    if rename(os.fsencode(source), os.fsencode(target), 0x00000004) == 0:  # RENAME_EXCL
        return
    error = get_errno()
    if error in (errno.ENOTSUP, errno.EINVAL):
        # Some volumes lack exclusive rename. Reserve the name before replacing it.
        with target.open("xb"):
            pass
        try:
            os.replace(source, target)
        except OSError:
            target.unlink(missing_ok=True)
            raise
    else:
        raise OSError(error, os.strerror(error), target)


def _published_name(output, title, video_id, extension):
    title = "".join(" " if c in "/\\:" else c for c in title if not unicodedata.category(c).startswith("C"))
    title = " ".join(title.split()).strip(". ")
    # Leave space for collision suffixes and Scribe's report/temporary filenames.
    title = title.encode()[:150].decode(errors="ignore").rstrip(". ")
    number = 1
    while True:
        label = f"{title} [{video_id}]" if title else video_id
        if number > 1:
            label = f"{title or 'Video'} ({number}) [{video_id}]"
        reserved = (*MEDIA_EXTENSIONS, ".log.md", ".summary.md", ".summary.html", ".summary.err")
        if not any(os.path.lexists(output / (label + suffix)) for suffix in reserved):
            return output / (label + extension)
        number += 1


@contextmanager
def youtube_lock(output, video_id, say):
    import fcntl
    state = output / ".scribe-youtube"
    state.mkdir(parents=True, exist_ok=True)
    # Video IDs are case-sensitive even on case-insensitive volumes.
    with (state / f"{video_id.encode().hex()}.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            say(f"Waiting for the active YouTube run for {video_id}...")
            fcntl.flock(lock, fcntl.LOCK_EX)
        yield state


def obtain_youtube(video_id, output, state, args, *, say, read_json, save_json, digest_file):
    url = watch_url(video_id)
    metadata_path = state / f"{video_id.encode().hex()}.json"
    saved = read_json(metadata_path, {})
    if (isinstance(saved, dict) and saved.get("id") == video_id
            and re.fullmatch(r"[a-f0-9]{64}", str(saved.get("sha256")))):
        named = re.compile(rf"(?:{re.escape(video_id)}|.+ \[{re.escape(video_id)}\])")
        candidates = sorted(output.iterdir(), key=lambda path: path.name != saved.get("filename"))
        for path in candidates:
            if (not named.fullmatch(path.stem) or path.suffix.lower() not in MEDIA_EXTENSIONS
                    or path.is_symlink() or not path.is_file()):
                continue
            try:
                if digest_file(path) != saved["sha256"]:
                    continue
            except OSError:
                continue
            if str(path) != saved.get("media_path"):
                saved.update(filename=path.name, media_path=str(path))
                save_json(metadata_path, saved)
            say(f"Reusing verified YouTube video: {path.name}")
            return path, saved

    if getattr(args, "summary_only", False):
        raise MediaError("--summary-only needs a verified local YouTube download and its saved transcript.")
    for authenticated in (False, True):
        with tempfile.TemporaryDirectory(prefix=f"{video_id}-", dir=state) as temp:
            scratch = Path(temp)
            try:
                info = download_attempt(url, scratch, say, cookie_file=args.cookies if authenticated else None,
                                        browser=args.cookies_from_browser if authenticated else None)
            except SignInRequired:
                if authenticated or (args.cookies is None and args.cookies_from_browser is None):
                    raise
                say("YouTube requires sign-in; retrying with the supplied cookie source.")
                continue
            downloads = (info.get("requested_downloads") or []) if isinstance(info, dict) else []
            filepath = Path(downloads[0].get("filepath") or "") if len(downloads) == 1 else Path()
            if filepath.parent != scratch or info.get("id") != video_id:
                raise MediaError("yt-dlp did not return a completed media file for this video.")
            with DownloadProgress(say, initial_stage="Verifying YouTube media"):
                if not verify_video(filepath, info.get("duration")):
                    raise MediaError("The completed YouTube download must contain readable video and audio in MKV, MP4 or WebM.")
            metadata = _source_metadata(info, video_id)
            target = _published_name(output, metadata.get("title") or "", video_id, filepath.suffix.lower())
            metadata.update(filename=target.name, media_path=str(target), sha256=digest_file(filepath))
            # Publish without replacing unrelated files. Keep the verified media if processing fails.
            save_json(metadata_path, metadata)
            _publish_media(filepath, target)
            say(f"Saved YouTube video: {target}")
            return target, metadata


if __name__ == "__main__":
    raise SystemExit(0 if sys.argv[1:] == ["--prepare-ffmpeg"] and prepare_ffmpeg() else 1)
