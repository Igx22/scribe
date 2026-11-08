"""Optional, standard-library console mirror for the launcher and direct CLI.

Only entry points start this supervisor; importing Scribe has no logging effects.
The worker retains its stdin and process group, and sees a TTY on each output
that originally was a TTY. Console bytes keep their original destination.
"""
from __future__ import annotations

import codecs
from datetime import datetime
import errno
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import time
import uuid

MARKER = "_SCRIBE_CONSOLE_PARENT"


def supervised():
    """The marker survives launcher execs, but not an independent invocation."""
    return os.environ.get(MARKER) == str(os.getppid())


def credential_values(env, env_file):
    values = dict(env)
    try:
        for line in Path(env_file).read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:].strip()
            name, sep, value = line.partition("=")
            if sep and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name.strip()):
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                values.setdefault(name.strip(), value)
    except (OSError, UnicodeError):
        pass
    return sorted({value for name, value in values.items() if value and
                   re.search(r"(?:KEY|TOKEN|PASSWORD|SECRET)$", name.upper())}, key=len, reverse=True)


class DailyRunLog:
    """Exclusive per-invocation files; a local date change opens a new part."""
    def __init__(self, directory, *, clock=datetime.now, run_id=None, secrets=(), warning=None):
        self.directory = Path(directory)
        self.clock = clock
        self.run_id = run_id or f"{clock():%H%M%S-%f}_{os.getpid()}_{uuid.uuid4().hex[:8]}"
        self.secrets = secrets
        self.warning = warning or (lambda message: os.write(2, (message + "\n").encode("utf-8", "replace")))
        self.file = None
        self.day = None
        self.path = None
        self.failed = False
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self.rotate()
        except (OSError, ValueError) as exc:
            self.fail(exc)

    def redact(self, text):
        for secret in self.secrets:
            text = text.replace(secret, "[redacted]")
        return re.sub(r"(?:sk-|hf_)[A-Za-z0-9_-]{8,}", "[redacted]", text)

    def fail(self, exc):
        self.failed = True
        try:
            self.close()
        except (OSError, ValueError):
            pass
        try:
            self.warning(self.redact(f"WARNING: Console file logging disabled: {exc}"))
        except OSError:
            pass

    def rotate(self):
        day = self.clock().date().isoformat()
        if self.file is not None and day == self.day:
            return
        self.close()
        suffix = ""
        index = 1
        while True:
            path = self.directory / f"{day}_{self.run_id}{suffix}.log"
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                break
            except FileExistsError:
                index += 1
                suffix = f"_{index}"
        try:
            self.file = os.fdopen(fd, "w", encoding="utf-8", errors="replace", newline="\n")
        except BaseException:
            os.close(fd)
            raise
        self.day, self.path = day, path

    def write(self, text):
        if self.failed or not text:
            return
        try:
            self.rotate()
            self.file.write(self.redact(text))
            self.file.flush()
        except (OSError, ValueError, UnicodeError) as exc:
            self.fail(exc)

    def close(self):
        if self.file is not None:
            file, self.file = self.file, None
            file.close()

    def finish(self):
        try:
            self.close()
        except (OSError, ValueError) as exc:
            self.fail(exc)


class LogStream:
    """Incremental UTF-8/control cleanup; keep credentials across read boundaries."""
    def __init__(self, log):
        self.log = log
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.pending = ""
        self.escape = ""
        self.after_cr = False
        self.redacting_token = False
        self.reserve = max([64, *(len(secret) for secret in log.secrets)])

    def feed(self, data, final=False):
        for char in self.decoder.decode(data, final=final):
            if self.redacting_token:
                if char.isascii() and (char.isalnum() or char in "_-"):
                    continue
                self.redacting_token = False
            if self.escape:
                if self.escape == "esc":
                    self.escape = {"[": "csi", "]": "osc"}.get(char, "")
                elif self.escape == "csi" and "@" <= char <= "~":
                    self.escape = ""
                elif self.escape == "osc" and char == "\x07":
                    self.escape = ""
                elif self.escape == "osc" and char == "\x1b":
                    self.escape = "osc-end"
                elif self.escape == "osc-end":
                    self.escape = "" if char == "\\" else "osc"
                continue
            if char == "\x1b":
                self.escape = "esc"
            elif char in "\r\n":
                if not (char == "\n" and self.after_cr):
                    self.log.write(self.pending + "\n")
                    self.pending = ""
                self.after_cr = char == "\r"
            elif char == "\t" or char >= " " and char != "\x7f":
                self.pending += char
                self.after_cr = False
            if len(self.pending) >= 65536 + self.reserve:
                self.flush_partial()
        if final:
            self.log.write(self.pending + "\n" if self.pending else "")
            self.pending = ""

    def flush_partial(self):
        # Flush ordinary unterminated output too, holding only possible secret
        # prefixes. This keeps live diagnostics on disk without leaking a key
        # whose bytes arrive in multiple reads (or timer intervals).
        limit = len(self.pending)
        for prefix in ("s", "sk", "h", "hf", *self.log.secrets):
            for length in range(min(len(prefix), len(self.pending)), 0, -1):
                if self.pending.endswith(prefix[:length]):
                    limit = min(limit, len(self.pending) - length)
                    break
        token = re.search(r"(?:sk-|hf_)[A-Za-z0-9_-]*$", self.pending)
        if token:
            limit = min(limit, token.start())
        if limit > 0:
            # Never split a known credential at the boundary.
            for secret in self.log.secrets:
                start = self.pending.rfind(secret, 0, limit + len(secret))
                if start >= 0 and start < limit < start + len(secret):
                    limit = start
            self.log.write(self.pending[:limit])
            self.pending = self.pending[limit:]
        if token and len(self.pending) > 65536 and self.pending.startswith(("sk-", "hf_")):
            self.log.write("[redacted]")
            self.pending = ""
            self.redacting_token = True


def terminal_size(original, slave):
    import fcntl
    import termios
    try:
        fcntl.ioctl(slave, termios.TIOCSWINSZ, fcntl.ioctl(original, termios.TIOCGWINSZ, b"\0" * 8))
    except OSError:
        pass


def capture_output(original):
    if os.isatty(original):
        import termios
        reader, writer = os.openpty()
        try:
            attributes = termios.tcgetattr(writer)
            attributes[1] &= ~termios.OPOST  # Mirror exact bytes, without PTY CRLF translation.
            termios.tcsetattr(writer, termios.TCSANOW, attributes)
            terminal_size(original, writer)
        except BaseException:
            os.close(reader); os.close(writer)
            raise
        return reader, writer, True
    reader, writer = os.pipe()
    return reader, writer, False


def mirror(command, log):
    """Run one worker and drain both console descriptors until shutdown."""
    env = {**os.environ, MARKER: str(os.getpid()), "PYTHONUNBUFFERED": "1"}
    def without_capture():
        # exec preserves this PID and parent, so the replacement must recognize
        # the parent's PID rather than look for a supervisor that no longer exists.
        env[MARKER] = str(os.getppid())
        log.finish()
        os.execvpe(command[0], command, env)
    if log.failed:
        without_capture()
    endpoints = []
    try:
        for original in (1, 2):
            reader, writer, tty = capture_output(original)
            endpoints.append((original, reader, writer, tty))
        selector = selectors.DefaultSelector()
    except (OSError, ValueError) as exc:
        for _, reader, writer, _ in endpoints:
            os.close(reader); os.close(writer)
        log.fail(exc)
        without_capture()

    # The worker shares the terminal's foreground process group. Ctrl+C reaches
    # it naturally; the supervisor must stay alive to drain its final messages.
    previous = {}
    for number in (signal.SIGINT, signal.SIGWINCH, signal.SIGTERM):
        previous[number] = signal.getsignal(number)
    process = None

    def resize(signum, frame):
        for original, reader, _, tty in endpoints:
            if tty:
                terminal_size(original, reader)

    def terminate(signum, frame):
        if process is not None and process.poll() is None:
            process.send_signal(signum)

    signal.signal(signal.SIGINT, lambda *_: None)
    signal.signal(signal.SIGWINCH, resize)
    signal.signal(signal.SIGTERM, terminate)
    try:
        try:
            process = subprocess.Popen(command, stdout=endpoints[0][2], stderr=endpoints[1][2], env=env)
        except OSError as exc:
            for _, reader, writer, _ in endpoints:
                os.close(reader); os.close(writer)
            log.fail(exc)
            # Restore ordinary signal handling before replacing the supervisor.
            for number, handler in previous.items():
                signal.signal(number, handler)
            without_capture()
        for original, reader, writer, tty in endpoints:
            os.close(writer)
            selector.register(reader, selectors.EVENT_READ, (original, LogStream(log), tty))
        last_flush = time.monotonic()
        while selector.get_map():
            for key, _ in selector.select(timeout=.2):
                original, stream, tty = key.data
                try:
                    data = os.read(key.fd, 65536)
                except OSError as exc:
                    if exc.errno != errno.EIO or not tty:
                        raise
                    data = b""  # PTYs report EIO when their last writer closes.
                if not data:
                    stream.feed(b"", final=True)
                    selector.unregister(key.fd)
                    os.close(key.fd)
                    continue
                remaining = memoryview(data)
                try:
                    while remaining:
                        remaining = remaining[os.write(original, remaining):]
                except BrokenPipeError:
                    # Preserve downstream pipe closure rather than hanging the worker.
                    selector.unregister(key.fd)
                    os.close(key.fd)
                stream.feed(data)
            if time.monotonic() - last_flush >= 1:
                for key in selector.get_map().values():
                    key.data[1].flush_partial()
                last_flush = time.monotonic()
        code = process.wait()
        return code if code >= 0 else 128 - code
    finally:
        for key in list(selector.get_map().values()):
            key.data[1].feed(b"", final=True)
            os.close(key.fd)
        selector.close()
        for number, handler in previous.items():
            signal.signal(number, handler)
        log.finish()


def run(command):
    log = DailyRunLog(Path.cwd() / "data/log", secrets=credential_values(
        os.environ, Path(__file__).resolve().parent.parent / ".env"))
    return mirror(command, log)


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
