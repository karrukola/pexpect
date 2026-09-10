# Windows support for `pexpect.spawn` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `pexpect`'s public interface identical on Linux and on Windows 10 and 11 -- same names, same signatures -- with the methods behind them working rather than merely importing.

**Architecture:** One `spawn` class in `pexpect/pty_spawn.py` serves both platforms. A new `pexpect/_ptyproc.py` is the only module that branches on the platform: it re-exports `ptyprocess.PtyProcess` on POSIX and a `pywinpty` adapter, `pexpect/_winpty.py`, on Windows. Both present the same surface, so `pty_spawn` talks to either without a platform test. `pexpect/__init__.py` stops hiding `spawn`, `spawnu`, `run` and `runu` behind `sys.platform`.

**Tech Stack:** Python 3.10-3.14, `pywinpty >= 3.0.5` (ConPTY) on Windows, `ptyprocess >= 0.7.0` on POSIX, `pytest`, `nox`, `uv`, `ruff`, `mypy`, `coverage`.

**Spec:** `docs/superpowers/specs/2026-09-10-windows-spawn-design.md`

## Global Constraints

- `requires-python >= 3.10`. The interpreter matrix is `.python-versions`: 3.10, 3.11, 3.12, 3.13, 3.14. Do not add or remove entries.
- `pywinpty >= 3.0.5`, marker `sys_platform == 'win32'`. `ptyprocess >= 0.7.0`, marker `sys_platform != 'win32'`.
- Every unsupported call raises `pexpect.ExceptionPexpect`, never `NotImplementedError`, never a silent no-op. The message names the call.
- No public signature changes. `lint.per-file-ignores` in `pyproject.toml` already silences the rules that pexpect's public API breaks; do not "fix" a public signature to satisfy a linter.
- `ruff format --check` and `ruff check` must pass on the whole tree, on both platforms. `lint.select = ["ALL"]`.
- Coverage floor is 100% on Linux (`report.fail_under`) and `_WINDOWS_COVERAGE_FLOOR` in `noxfile.py` on Windows. Both are real gates.
- `filterwarnings = ["error"]`. A warning fails the run.
- No POSIX behaviour changes. Every Linux test that passes before a task must pass after it.
- **Windows cannot be tested locally.** The dev machine is Linux aarch64. Windows verification is a `windows-latest` CI run; push the branch and read the run.
- Commit messages are normal English prose, not caveman, and end with the two attribution lines used by the existing commits on this branch.

---

## File Structure

**Created:**
- `src/pexpect/_ptyproc.py` -- the platform switch. Re-exports `PtyProcess`, `PtyProcessError`, `use_native_pty_fork`. Nothing else in the package imports `ptyprocess` or `winpty` directly.
- `src/pexpect/_winpty.py` -- the `pywinpty` adapter. Windows-only; omitted from the POSIX coverage report.
- `tests/commands.py` -- the programs the suite drives, resolved per platform.
- `tests/helpers/cat.py`, `tests/helpers/echo.py`, `tests/helpers/sleep.py`, `tests/helpers/true.py` -- Python stand-ins for the POSIX programs.
- `tests/test_unsupported.py` -- asserts each unsupported call raises on Windows and works on POSIX.
- `tests/test_ptyproc_backend.py` -- asserts the backend surface `pty_spawn` relies on.

**Modified:**
- `src/pexpect/spawnbase.py` -- one new `_read_fd()` seam.
- `src/pexpect/pty_spawn.py` -- backend calls in place of three raw-fd calls; the `pty` import dropped; Windows branches in `_ptyproc_kwargs`, `terminate`, `interact`, `_ready`.
- `src/pexpect/__init__.py` -- the platform guard removed.
- `pyproject.toml` -- dependency markers, classifier, mypy overrides, coverage `exclude_also`.
- `noxfile.py` -- dual-platform mypy, POSIX `--omit` of `_winpty.py`, retuned Windows floor.
- `tests/conftest.py` -- `_POSIX_ONLY`/`collect_ignore` deleted, `killed_pty_children` made portable, calibration unified.
- The fourteen test modules that lose POSIX-only status.
- `README.rst`, `DEVELOPERS.rst`, `doc/install.rst`, `doc/overview.rst`, `doc/history.rst`.

---

### Task 1: The backend seam, POSIX only

Pure refactor. No Windows code, no new dependency. The existing suite is the test: it must stay green and coverage must stay at 100% on Linux. This lands first so that every later task changes one platform's behaviour at a time.

**Files:**
- Create: `src/pexpect/_ptyproc.py`
- Create: `tests/test_ptyproc_backend.py`
- Modify: `src/pexpect/spawnbase.py:322-352` (`read_nonblocking`)
- Modify: `src/pexpect/pty_spawn.py:7` (`import pty`), `:16-17` (ptyprocess imports), `:39` (`_wrap_ptyprocess_err`), `:54` (`ptyproc` annotation), `:272-274` (the FILENO trio), `:446-448` (`_spawnpty`), `:476` (`isatty`), `:729` (`send`)

**Interfaces:**
- Consumes: nothing.
- Produces: `pexpect._ptyproc.PtyProcess` with `read_bytes(size: int) -> bytes`, `write_bytes(data: bytes) -> int`, and everything `ptyprocess.PtyProcess` already has (`spawn`, `fd`, `pid`, `close`, `isatty`, `isalive`, `wait`, `status`, `exitstatus`, `signalstatus`, `flag_eof`, `terminated`, `getecho`, `setecho`, `sendcontrol`, `sendeof`, `sendintr`, `getwinsize`, `setwinsize`, `terminate`, `kill`). `pexpect._ptyproc.PtyProcessError`. `pexpect._ptyproc.use_native_pty_fork: bool`. `SpawnBase._read_fd(size: int) -> bytes`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ptyproc_backend.py`:

```python
"""The backend surface pty_spawn relies on, whichever platform supplies it.

pexpect talks to one process backend through pexpect._ptyproc: ptyprocess on
POSIX, an adapter over pywinpty on Windows. Everything here is a statement
about that seam rather than about either implementation, so it runs on both.
"""

from __future__ import annotations

import sys

import pytest

from pexpect import _ptyproc

# The methods and attributes pty_spawn.spawn reaches for. A backend missing
# any of them fails at the call site, in whichever test happens to run first.
#
# Checked against a live child rather than against the class: ptyprocess sets
# status, exitstatus, signalstatus, flag_eof, terminated, fd and pid in
# __init__, so hasattr() on the class is False for every one of them.
_REQUIRED = (
    "close",
    "exitstatus",
    "fd",
    "flag_eof",
    "getwinsize",
    "isalive",
    "isatty",
    "kill",
    "pid",
    "read_bytes",
    "sendcontrol",
    "sendeof",
    "sendintr",
    "setwinsize",
    "signalstatus",
    "status",
    "terminate",
    "terminated",
    "wait",
    "write_bytes",
)


def test_backend_offers_what_pty_spawn_calls() -> None:
    child = _ptyproc.PtyProcess.spawn([sys.executable, "-c", "input()"])
    try:
        missing = [name for name in _REQUIRED if not hasattr(child, name)]
        assert not missing, f"the {sys.platform} backend is missing {missing}"
    finally:
        child.close(force=True)


def test_backend_error_is_an_exception_class() -> None:
    assert issubclass(_ptyproc.PtyProcessError, Exception)


def test_use_native_pty_fork_is_a_bool() -> None:
    # Purely informational since ptyprocess 0.7, and read by pexpect.spawn's
    # class attribute of the same name; the type is the whole contract.
    assert isinstance(_ptyproc.use_native_pty_fork, bool)


def test_round_trip_through_the_byte_seam() -> None:
    child = _ptyproc.PtyProcess.spawn([sys.executable, "-c", "print(input())"])
    try:
        child.write_bytes(b"ping\r")
        seen = b""
        while b"ping" not in seen.replace(b"\r", b""):
            seen += child.read_bytes(1024)
    finally:
        child.close(force=True)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run --frozen pytest tests/test_ptyproc_backend.py -v`
Expected: FAIL, collection error `ModuleNotFoundError: No module named 'pexpect._ptyproc'`.

- [ ] **Step 3: Create the backend module**

Create `src/pexpect/_ptyproc.py`:

```python
"""The process backend, and the only module in this package that picks one.

pexpect drives a child through a pseudo-terminal, and the code that owns that
pty is platform-specific: ptyprocess on POSIX, ConPTY by way of pywinpty on
Windows. Both are presented here under one name so that pty_spawn -- which is
otherwise platform-neutral -- never has to ask which platform it is on.

The surface is ptyprocess's, because that is the one pexpect already used, plus
two methods ptyprocess does not need. pexpect used to read and write the pty
with os.read() and os.write() on the descriptor, which is correct for a POSIX
pty and wrong on Windows, where the descriptor pywinpty hands out is a socket:
os.read() does not accept one. read_bytes() and write_bytes() are that pair of
calls, moved to the side of the seam that knows what the descriptor is.
"""

from __future__ import annotations

import os
import sys

if sys.platform == "win32":  # pragma: no cover -- the POSIX run omits this file
    from ._winpty import PtyProcess, PtyProcessError

    # No fork, so nothing to be native about. Kept because pexpect.spawn
    # carries a class attribute of this name that has been public since 3.x.
    use_native_pty_fork = False
else:
    import ptyprocess
    from ptyprocess.ptyprocess import PtyProcessError, use_native_pty_fork

    class PtyProcess(ptyprocess.PtyProcess):  # type: ignore[no-redef]
        """ptyprocess's pty child, plus the two byte-level calls pexpect makes.

        PtyProcess.spawn() instantiates through ``cls``, so a subclass comes
        back from it and no override is needed here.
        """

        def read_bytes(self, size: int) -> bytes:
            """Read at most *size* bytes from the pty, as os.read() would."""
            return os.read(self.fd, size)

        def write_bytes(self, data: bytes) -> int:
            """Write *data* to the pty and return the number of bytes taken."""
            return os.write(self.fd, data)


__all__ = ["PtyProcess", "PtyProcessError", "use_native_pty_fork"]
```

The `if sys.platform == "win32"` branch cannot import on Linux and its body
would count as missed statements, so Task 2 adds the coverage exclusion that
makes both branches legitimate. Until then the Linux coverage run reports
three missed lines in this file; that is expected and Task 2 closes it.

- [ ] **Step 4: Add the seam to `SpawnBase`**

In `src/pexpect/spawnbase.py`, inside `read_nonblocking`, replace

```python
        try:
            s = os.read(self.child_fd, size)
```

with

```python
        try:
            s = self._read_fd(size)
```

and add this method immediately above `read_nonblocking`:

```python
    def _read_fd(self, size: int) -> bytes:
        """Read at most *size* bytes from ``child_fd``.

        A plain descriptor read, which is what fdspawn and SocketSpawn want.
        pty_spawn.spawn overrides it to go through its process backend, whose
        descriptor is not always one os.read() accepts -- see pexpect._ptyproc.
        """
        return os.read(self.child_fd, size)
```

Leave both EOF branches of `read_nonblocking` exactly where they are: the
`OSError`/`EIO` arm is Linux-style EOF and the `s == b""` arm is BSD-style, and
the Windows backend reaches EOF through the second one without adding anything.

- [ ] **Step 5: Point `pty_spawn` at the backend**

In `src/pexpect/pty_spawn.py`:

1. Delete `import pty` from the imports.
2. Replace

```python
import ptyprocess
from ptyprocess.ptyprocess import use_native_pty_fork
```

with

```python
from ._ptyproc import PtyProcess, PtyProcessError, use_native_pty_fork
```

3. In `_wrap_ptyprocess_err`, change `except ptyprocess.PtyProcessError as e:` to `except PtyProcessError as e:`.
4. Change the class annotation `ptyproc: ptyprocess.PtyProcess` to `ptyproc: PtyProcess`, and update the comment above it to say the backend carries no `py.typed` marker.
5. Replace the FILENO assignments in `__init__`:

```python
        # 0, 1 and 2, which is what pty.STDIN_FILENO and friends are defined
        # as. Named as constants rather than imported because `pty` is POSIX
        # only and this class now runs on Windows too.
        self.STDIN_FILENO = 0
        self.STDOUT_FILENO = 1
        self.STDERR_FILENO = 2
```

6. Retype and redirect `_spawnpty`:

```python
    def _spawnpty(self, args: list[str] | list[bytes], **kwargs: object) -> PtyProcess:
        """Spawn a pty and return an instance of the process backend."""
        return PtyProcess.spawn(args, **kwargs)
```

7. In `isatty`, replace `return os.isatty(self.child_fd)` with `return self.ptyproc.isatty()`.
8. In `send`, replace `return os.write(self.child_fd, b)` with `return self.ptyproc.write_bytes(b)`.
9. Add the override that sends `SpawnBase`'s reads through the backend, next to `_base_read_nonblocking`:

```python
    def _read_fd(self, size: int) -> bytes:
        """Read from the pty through the process backend rather than os.read()."""
        return self.ptyproc.read_bytes(size)
```

- [ ] **Step 6: Run the tests and make sure they pass**

Run: `uv run --frozen pytest tests/test_ptyproc_backend.py -v`
Expected: PASS, 4 tests.

Run: `uv run --frozen pytest tests -x -q`
Expected: PASS, the whole suite, no new failures.

Run: `uv run --frozen nox -s "lint-3.12"`
Expected: PASS. If mypy reports `os` as unused in `pty_spawn.py`, keep it -- `os.linesep` and `os.kill` are still used -- and if ruff reports it unused, that means step 5 missed a call site.

- [ ] **Step 7: Commit**

```bash
git add src/pexpect/_ptyproc.py src/pexpect/spawnbase.py src/pexpect/pty_spawn.py tests/test_ptyproc_backend.py
git commit -m "refactor: read and write the pty through a process backend

pexpect read and wrote the child's pty with os.read() and os.write() on the
descriptor, which is correct for a POSIX pty and wrong for the socket
descriptor a Windows backend hands out. Both calls move behind
pexpect._ptyproc, the module that will pick the backend, and pty_spawn stops
importing ptyprocess and pty directly.

No behaviour change: the POSIX backend is ptyprocess with the two calls added.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01ARmrZ1bE971i3nFZfYEifV"
```

---

### Task 2: The pywinpty adapter

Adds the dependency and the Windows half of the backend. Nothing on Linux changes except the coverage configuration that makes a Windows-only module legitimate.

**Files:**
- Create: `src/pexpect/_winpty.py`
- Modify: `pyproject.toml` (dependencies, classifier, mypy override, coverage `exclude_also`)
- Modify: `noxfile.py:79-93` (`collate_coverage`)
- Modify: `uv.lock` (regenerated)

**Interfaces:**
- Consumes: `pexpect._ptyproc` from Task 1, which imports `PtyProcess` and `PtyProcessError` from this module on `win32`.
- Produces: `pexpect._winpty.PtyProcess` with the surface listed in Task 1's `_REQUIRED`, plus `fd`, `getecho`, `setecho`, `read_bytes`, `write_bytes`; and `pexpect._winpty.PtyProcessError(Exception)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ptyproc_backend.py`:

```python
def test_windows_backend_refuses_the_termios_calls() -> None:
    """getecho and setecho have no ConPTY equivalent and must say so."""
    if sys.platform != "win32":
        pytest.skip("the POSIX backend supports both calls")
    child = _ptyproc.PtyProcess.spawn([sys.executable, "-c", "input()"])
    try:
        with pytest.raises(_ptyproc.PtyProcessError, match="getecho"):
            child.getecho()
        with pytest.raises(_ptyproc.PtyProcessError, match="setecho"):
            child.setecho(state=False)
    finally:
        child.close(force=True)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run --frozen pytest tests/test_ptyproc_backend.py -v`
Expected: PASS on Linux by skipping -- one skip, the rest passing. The assertion this test makes can only fail on Windows, so the real "run it to see it fail" is the CI leg in step 7.

- [ ] **Step 3: Declare the dependency**

In `pyproject.toml`, replace

```toml
dependencies = [
    "ptyprocess>=0.7.0",
]
```

with

```toml
dependencies = [
    # ptyprocess imports termios while being imported, so the marker is not
    # an optimisation -- an unmarked install would fail on Windows.
    "ptyprocess>=0.7.0; sys_platform != 'win32'",
    # ConPTY, plus the OpenConsole.exe and conpty.dll it bundles, which is why
    # Windows 10 and 11 are both covered rather than only builds new enough to
    # ship a system ConPTY. Wheels are published for cp310 through cp314, the
    # whole of .python-versions.
    "pywinpty>=3.0.5; sys_platform == 'win32'",
]
```

Add to the classifiers, after the MacOS line:

```toml
    'Operating System :: Microsoft :: Windows',
```

Add a mypy override next to the `ptyprocess` one:

```toml
# pywinpty ships _winpty.pyi but no py.typed marker. follow_untyped_imports
# resolves its members where the package is installed -- the Windows runners --
# and ignore_missing_imports keeps a Linux checkout, where it is not installed
# and cannot be, from failing the --platform win32 pass with import-not-found.
[[tool.mypy.overrides]]
module = [ "winpty", "winpty.*" ]
follow_untyped_imports = true
ignore_missing_imports = true
```

Add a ruff per-file-ignores entry, in the alphabetical position the existing
ones keep:

```toml
# The backend mirrors ptyprocess.PtyProcess, which pty_spawn calls positionally
# -- close(force), setecho(state), terminate(force), spawn(..., echo=...).
# Making those keyword-only here would break the call sites that already exist.
lint.per-file-ignores."src/pexpect/_winpty.py" = [
    "FBT001", "FBT002",  # boolean flags, positional because ptyprocess's are
    "PLR0913", "PLR0917",  # spawn() takes ptyprocess's argument list
]
```

Add to `report.exclude_also`, keeping the list alphabetical:

```toml
    # One of the two is dead on any given run, and neither can be executed on
    # the other platform, so a covered platform branch is not a thing either
    # floor can ask for. What holds them honest instead is that every branch
    # guarded this way has a test in tests/test_unsupported.py asserting the
    # behaviour on the platform that reaches it.
    "if sys\\.platform == .win32.:",
    "if sys\\.platform != .win32.:",
```

- [ ] **Step 4: Write the adapter**

Create `src/pexpect/_winpty.py`:

```python
"""The Windows process backend: pexpect's pty surface over pywinpty's ConPTY.

pywinpty ships winpty.PtyProcess, shaped deliberately like ptyprocess's class
of the same name, and it is used here for everything to do with the console:
starting the child, resizing it, terminating it, reaping it. It also gives a
working fileno(), which was not a given -- a reader thread pumps the ConPTY
output into a loopback socket, and select() accepts socket descriptors on
Windows -- so pexpect's readiness path needs nothing special.

Its read() is not used. That method returns str while pexpect is bytes end to
end and decodes with the caller's own encoding and codec_errors; and it re-reads
one byte at a time until its buffer decodes as UTF-8, which is right for
truncated UTF-8 and never terminates on invalid UTF-8 -- a child emitting cp1252
or raw binary blocks it inside a loop no pexpect timeout reaches. Reading the
socket it already exposes gives the child's real bytes instead.

Two properties of the dependency are inherited rather than fixed, recorded here
so they are not rediscovered as pexpect bugs: each spawn opens a listening
socket on 127.0.0.1, which a local process could race the connect on; and its
reader sends the in-band sentinel b'0011Ignore' for an empty read and strips it
again, so a child printing that exact string loses it. PYWINPTY_BLOCK defaults
to 1, which makes an empty read, and so the sentinel, rare.
"""

from __future__ import annotations

import os
import signal
import time
from typing import TYPE_CHECKING, Any

import winpty

if TYPE_CHECKING:
    from collections.abc import Sequence


class PtyProcessError(Exception):
    """Raised for a backend failure, and for a call Windows cannot honour.

    pty_spawn turns this into ExceptionPexpect through _wrap_ptyprocess_err,
    which is how an unsupported call reaches the caller as the one exception
    type pexpect raises.
    """


class PtyProcess:
    """A child running in a ConPTY, presented as pexpect's pty backend."""

    def __init__(self, proc: winpty.PtyProcess) -> None:
        self._proc = proc
        self.pid: int = proc.pid
        self.fd: int = proc.fd
        self.flag_eof = False
        self.terminated = False
        self.status: int | None = None
        self.exitstatus: int | None = None
        # A Windows process never exits by signal, so this is None for the
        # life of the object. pexpect copies it to spawn.signalstatus.
        self.signalstatus: int | None = None
        self.delayafterterminate = 0.1

    @classmethod
    def spawn(
        cls,
        argv: Sequence[str | bytes],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        echo: bool = True,
        preexec_fn: Any = None,
        dimensions: tuple[int, int] = (24, 80),
    ) -> PtyProcess:
        """Start *argv* in a ConPTY and return the backend wrapping it.

        The signature is ptyprocess's, because pty_spawn._ptyproc_kwargs() calls
        it with those names. `echo=False` and `preexec_fn` are refused: ConPTY
        keeps echo in the child's own console host, out of the parent's reach,
        and there is no fork for a preexec hook to run between.
        """
        if not echo:
            msg = "echo=False is not supported on Windows: ConPTY echo belongs to the child"
            raise PtyProcessError(msg)
        if preexec_fn is not None:
            msg = "preexec_fn is not supported on Windows: there is no fork to run it between"
            raise PtyProcessError(msg)
        # pty_spawn re-encodes the argument list when an encoding is in force,
        # and pywinpty resolves argv[0] with shutil.which() and joins the rest
        # with subprocess.list2cmdline(), both of which want str.
        decoded = [a if isinstance(a, str) else os.fsdecode(a) for a in argv]
        try:
            proc = winpty.PtyProcess.spawn(decoded, cwd=cwd, env=env, dimensions=dimensions)
        except (winpty.WinptyError, OSError) as e:
            raise PtyProcessError(*e.args) from e
        return cls(proc)

    def read_bytes(self, size: int) -> bytes:
        """Read at most *size* bytes of the child's output.

        Reads the socket pywinpty's reader thread feeds, so the bytes are the
        child's own. An empty read is end of file, which is what
        SpawnBase.read_nonblocking's BSD-style arm turns into pexpect's EOF.
        """
        data: bytes = self._proc.fileobj.recv(size)
        if not data:
            self.flag_eof = True
        return data

    def write_bytes(self, data: bytes) -> int:
        """Write *data* to the child and return the number of bytes taken."""
        # winpty.PTY.write takes str and encodes UTF-8 itself; surrogateescape
        # is what carries bytes that are not valid UTF-8 through unchanged.
        return int(self._proc.write(data.decode("utf-8", "surrogateescape")))

    def isatty(self) -> bool:
        """Return True: a ConPTY child is always attached to a console."""
        return not self.closed

    @property
    def closed(self) -> bool:
        """Whether close() has run."""
        return self.fd == -1

    def fileno(self) -> int:
        """Return the descriptor pexpect selects on."""
        return self.fd

    def getecho(self) -> bool:
        """Refuse: ConPTY echo is a property of the child's console host."""
        msg = "getecho() is not supported on Windows"
        raise PtyProcessError(msg)

    def setecho(self, state: bool) -> None:
        """Refuse: ConPTY echo is a property of the child's console host."""
        msg = "setecho() is not supported on Windows"
        raise PtyProcessError(msg)

    def sendcontrol(self, char: str) -> tuple[int, bytes]:
        """Send one control character by mnemonic name.

        Returns the pair pty_spawn unpacks: bytes written, and the byte sent,
        which pexpect logs itself.
        """
        char = char.lower()
        code = ord(char)
        if ord("a") <= code <= ord("z"):
            byte = bytes([code - ord("a") + 1])
        else:
            mnemonics = {
                "@": 0, "`": 0,
                "[": 27, "{": 27,
                "\\": 28, "|": 28,
                "]": 29, "}": 29,
                "^": 30, "~": 30,
                "_": 31,
                "?": 127,
            }
            if char not in mnemonics:
                return 0, b""
            byte = bytes([mnemonics[char]])
        return self.write_bytes(byte), byte

    def sendeof(self) -> tuple[int, bytes]:
        """Send end of file, which on a Windows console is Ctrl-Z."""
        byte = b"\x1a"
        return self.write_bytes(byte), byte

    def sendintr(self) -> tuple[int, bytes]:
        """Send Ctrl-C, which ConPTY turns into a console interrupt."""
        byte = b"\x03"
        return self.write_bytes(byte), byte

    def getwinsize(self) -> tuple[int, int]:
        """Return the console size as (rows, cols)."""
        rows, cols = self._proc.getwinsize()
        return rows, cols

    def setwinsize(self, rows: int, cols: int) -> None:
        """Resize the ConPTY."""
        self._proc.setwinsize(rows, cols)

    def isalive(self) -> bool:
        """Whether the child is still running, reaping it if it is not."""
        if self._proc.isalive():
            return True
        self._reap()
        return False

    def wait(self) -> int | None:
        """Block until the child exits and return its exit status."""
        self._proc.wait()
        self._reap()
        return self.exitstatus

    def _reap(self) -> None:
        """Record the exit status once, the way ptyprocess's isalive() does."""
        if not self.terminated:
            self.exitstatus = self._proc.exitstatus
            # ptyprocess's `status` is the raw os.waitpid() status, which has no
            # Windows counterpart. With signalstatus always None, the exit code
            # is the whole of what there is to report.
            self.status = self.exitstatus
            self.terminated = True

    def terminate(self, force: bool = False) -> bool:
        """Stop the child, returning whether it is gone.

        Ctrl-C first, which a console application can handle; then, only with
        *force*, TerminateProcess, which it cannot. There is no middle rung:
        the POSIX ladder's SIGHUP and SIGCONT have no Windows counterpart.
        """
        if not self.isalive():
            return True
        self.sendintr()
        time.sleep(self.delayafterterminate)
        if not self.isalive():
            return True
        if force:
            self.kill(signal.SIGTERM)
            time.sleep(self.delayafterterminate)
            return not self.isalive()
        return False

    def kill(self, sig: int) -> None:
        """Send *sig* to the child, for the two signals Windows can deliver.

        os.kill() on Windows delivers CTRL_C_EVENT and CTRL_BREAK_EVENT through
        GenerateConsoleCtrlEvent and treats every other value as a
        TerminateProcess exit code, so a SIGHUP here would terminate the child
        rather than hang it up. Refusing is the honest answer; the caller who
        wants an interrupt has sendintr().
        """
        if sig not in (signal.SIGTERM, signal.SIGINT):
            msg = f"kill() cannot deliver signal {sig} on Windows"
            raise PtyProcessError(msg)
        if sig == signal.SIGINT:
            self.sendintr()
            return
        os.kill(self.pid, signal.SIGTERM)

    def close(self, force: bool = True) -> None:
        """Close the connection to the child, terminating it if *force*."""
        if self.closed:
            return
        try:
            self._proc.close(force=force)
        except (winpty.WinptyError, OSError) as e:
            raise PtyProcessError(*e.args) from e
        finally:
            self.fd = -1
        self.isalive()
```

- [ ] **Step 5: Keep the Linux coverage report honest**

The new module cannot be imported on Linux, so its statements would count as
missed. In `noxfile.py`, in `collate_coverage`, replace

```python
    floor = () if sys.platform != "win32" else (f"--fail-under={_WINDOWS_COVERAGE_FLOOR}",)
```

with

```python
    if sys.platform == "win32":
        # A subset of the library ran, so a subset's floor; see
        # _WINDOWS_COVERAGE_FLOOR.
        report_args: tuple[str, ...] = (f"--fail-under={_WINDOWS_COVERAGE_FLOOR}",)
    else:
        # src/pexpect/_winpty.py is the Windows process backend. It imports
        # `winpty`, which exists only on Windows and cannot be installed here,
        # so a POSIX run cannot execute a line of it and 100% is a statement
        # about the rest. The Windows run measures it without this.
        report_args = ("--omit=*/pexpect/_winpty.py",)
```

and pass `*report_args` to the `html` and `xml` runs in place of `*floor`.

- [ ] **Step 6: Lock, lint and run the suite**

Run: `uv lock && uv run --frozen pytest tests -x -q`
Expected: PASS. `uv.lock` gains `pywinpty` with a `sys_platform == 'win32'` marker and installs nothing new here.

Run: `uv run --frozen nox -s "lint-3.12"`
Expected: PASS. mypy analyses `_winpty.py` only under `--platform win32`, which Task 7 adds; until then it is checked by ruff alone.

Run: `uv run --frozen nox`
Expected: PASS, including the 100% coverage gate, with `_winpty.py` omitted.

- [ ] **Step 7: Commit and read the Windows leg**

```bash
git add pyproject.toml uv.lock noxfile.py src/pexpect/_winpty.py tests/test_ptyproc_backend.py
git commit -m "feat: add the Windows process backend over pywinpty

pexpect._winpty presents pexpect's pty backend surface over pywinpty's ConPTY
wrapper. It uses winpty.PtyProcess for the console work and reads the socket
that class exposes rather than its read(), which returns str and cannot
terminate on invalid UTF-8.

pywinpty is a Windows-only dependency; ptyprocess gains the complementary
marker, since it imports termios while being imported.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01ARmrZ1bE971i3nFZfYEifV"
git push -u origin feat/windows-spawn
gh run watch --exit-status
```

Expected: both Linux legs green. The Windows legs still pass without exercising
`_winpty.py`, because nothing imports `pexpect.spawn` there yet -- that is
Task 3. What this run proves is that the dependency resolves and installs on
`windows-latest` for all five interpreters.

---

### Task 3: Export `spawn` on Windows

The one-line change the bug report is about, plus the smoke test that proves a
child actually runs.

**Files:**
- Modify: `src/pexpect/__init__.py:84-90`
- Create: `tests/test_spawn_smoke.py`

**Interfaces:**
- Consumes: `pexpect._ptyproc.PtyProcess` (Tasks 1 and 2).
- Produces: `pexpect.spawn`, `pexpect.spawnu`, `pexpect.run`, `pexpect.runu` importable on every platform.

- [ ] **Step 1: Write the failing test**

Create `tests/test_spawn_smoke.py`:

```python
"""The shortest end-to-end statement: a child starts, talks, and exits.

Every other spawn test builds on this, and on Windows this is the first code
that drives a ConPTY, so when the platform is broken this is the test that says
so in one line rather than in four hundred.
"""

from __future__ import annotations

import sys

import pytest

import pexpect

pytestmark = pytest.mark.usefixtures("fast_sleep")

# Its own interpreter, so the test needs no program the platform may not have.
_GREETER = [sys.executable, "-c", "print('hello ' + input())"]


def test_the_public_names_exist() -> None:
    for name in ("spawn", "spawnu", "run", "runu"):
        assert hasattr(pexpect, name), f"pexpect.{name} is missing on {sys.platform}"


def test_a_child_answers() -> None:
    child = pexpect.spawn(_GREETER[0], _GREETER[1:], timeout=10, encoding="utf-8")
    try:
        child.sendline("world")
        child.expect("hello world")
        child.expect(pexpect.EOF)
    finally:
        child.close(force=True)
    assert child.exitstatus == 0


def test_a_child_reports_its_window_size() -> None:
    child = pexpect.spawn(_GREETER[0], _GREETER[1:], dimensions=(40, 100))
    try:
        assert child.getwinsize() == (40, 100)
        child.setwinsize(24, 80)
        assert child.getwinsize() == (24, 80)
    finally:
        child.close(force=True)


def test_fileno_is_a_descriptor() -> None:
    child = pexpect.spawn(_GREETER[0], _GREETER[1:])
    try:
        assert isinstance(child.fileno(), int)
        assert child.fileno() >= 0
    finally:
        child.close(force=True)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run --frozen pytest tests/test_spawn_smoke.py -v`
Expected: PASS on Linux -- `pexpect.spawn` has always existed here. On Windows
it fails with `AttributeError: module 'pexpect' has no attribute 'spawn'`,
which is the reported bug; step 5 is where that gets seen.

- [ ] **Step 3: Remove the guard**

In `src/pexpect/__init__.py`, replace

```python
# Python 2 is no longer supported; this flag survives only because
# `tests/test_run.py` still reads it. Remove both together.
if sys.platform != "win32":  # pragma: no branch
    # On Unix, these are available at the top level for backwards compatibility
    from .pty_spawn import spawn, spawnu
    from .run import run, runu
```

with

```python
from .pty_spawn import spawn, spawnu
from .run import run, runu
```

and delete the now-unused `import sys` if nothing else in the module uses it --
check with `grep -n "sys\." src/pexpect/__init__.py` before deleting.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `uv run --frozen pytest tests -x -q`
Expected: PASS, whole suite on Linux.

Run: `uv run --frozen nox -s "lint-3.12"`
Expected: PASS.

- [ ] **Step 5: Commit and read the Windows leg**

```bash
git add src/pexpect/__init__.py tests/test_spawn_smoke.py
git commit -m "fix: export spawn, spawnu, run and runu on Windows

pexpect.spawn raised AttributeError on Windows because __init__ hid it behind a
sys.platform check, pty_spawn imported pty, and the process backend was
POSIX-only. None of those is true any more, so the guard goes.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01ARmrZ1bE971i3nFZfYEifV"
git push
gh run watch --exit-status
```

Expected: the Windows legs now exercise `_winpty.py` for the first time.
Failures here are the design's real unknowns, in the order they are likely:
ConPTY's own VT sequences breaking `child.expect("hello world")`; `getwinsize`
disagreeing about rows and cols; EOF arriving late from pywinpty's reader
thread. Read the failure before changing anything, and if ConPTY escape
sequences are the cause, record the exact bytes in the commit message that
addresses it -- the spec calls this the largest unknown and that record is what
resolves it.

---

### Task 4: Refuse what Windows cannot do

**Files:**
- Modify: `src/pexpect/pty_spawn.py` -- `_ptyproc_kwargs` (`:373-391`), `_ready` (`:561-565`), `interact` (`:907-969`)
- Create: `tests/test_unsupported.py`

**Interfaces:**
- Consumes: `pexpect._winpty.PtyProcess.getecho`/`setecho`/`kill`, which already raise (Task 2).
- Produces: no new names. Every call listed below raises `pexpect.ExceptionPexpect` on Windows and behaves as it always has on POSIX.

- [ ] **Step 1: Write the failing test**

Create `tests/test_unsupported.py`:

```python
"""What each platform refuses, stated once, from both sides.

pexpect's interface is the same on Linux and on Windows; some of it cannot
work there. Every such call raises ExceptionPexpect naming itself, and this
module is where that contract lives -- asserting the raise on Windows and the
working behaviour on POSIX, so neither half can drift.

It is also the coverage these calls get: the sys.platform branches they live
behind are excluded from the coverage floor, because neither branch can run on
the other platform, and these tests are what stands in for that gate.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

import pexpect

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

pytestmark = pytest.mark.usefixtures("fast_sleep")

_ON_WINDOWS = sys.platform == "win32"
_CHILD = [sys.executable, "-c", "input()"]

# Written as the number rather than as signal.SIGHUP, which does not exist on
# Windows: the name would fail while this module was being imported, and a
# skipif never runs when the module carrying it cannot be imported.
_SIGHUP = 1


@pytest.fixture
def child() -> Iterator[pexpect.spawn[bytes]]:
    spawned = pexpect.spawn(_CHILD[0], _CHILD[1:], timeout=10)
    yield spawned
    spawned.close(force=True)


@pytest.mark.skipif(not _ON_WINDOWS, reason="POSIX supports every call here")
@pytest.mark.parametrize(
    ("name", "call"),
    [
        ("getecho", lambda c: c.getecho()),
        ("setecho", lambda c: c.setecho(state=False)),
        ("waitnoecho", lambda c: c.waitnoecho(timeout=1)),
        ("interact", lambda c: c.interact()),
    ],
)
def test_windows_refuses_the_terminal_calls(
    child: pexpect.spawn[bytes],
    name: str,
    call: Callable[[pexpect.spawn[bytes]], object],
) -> None:
    with pytest.raises(pexpect.ExceptionPexpect, match=name):
        call(child)


@pytest.mark.skipif(not _ON_WINDOWS, reason="POSIX delivers every signal")
def test_windows_refuses_the_signals_it_cannot_deliver(child: pexpect.spawn[bytes]) -> None:
    with pytest.raises(pexpect.ExceptionPexpect):
        child.kill(_SIGHUP)


@pytest.mark.skipif(not _ON_WINDOWS, reason="POSIX supports both arguments")
@pytest.mark.parametrize(
    ("name", "kwargs"),
    [
        ("preexec_fn", {"preexec_fn": lambda: None}),
        ("ignore_sighup", {"ignore_sighup": True}),
        ("echo", {"echo": False}),
        ("use_poll", {"use_poll": True}),
    ],
)
def test_windows_refuses_the_posix_only_arguments(name: str, kwargs: dict[str, object]) -> None:
    with pytest.raises(pexpect.ExceptionPexpect, match=name):
        pexpect.spawn(_CHILD[0], _CHILD[1:], **kwargs)


@pytest.mark.skipif(_ON_WINDOWS, reason="the Windows half is asserted above")
def test_posix_supports_the_same_calls(child: pexpect.spawn[bytes]) -> None:
    assert child.getecho() is True
    child.setecho(state=False)
    assert child.waitnoecho(timeout=5) is True
    child.kill(_SIGHUP)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run --frozen pytest tests/test_unsupported.py -v`
Expected: PASS on Linux -- one real test and the rest skipped. The Windows half
is what step 5 checks.

- [ ] **Step 3: Refuse the POSIX-only constructor arguments**

In `pty_spawn.py`, replace the body of `_ptyproc_kwargs` with:

```python
    def _ptyproc_kwargs(
        self,
        preexec_fn: Callable[[], None] | None,
        dimensions: tuple[int, int] | None,
    ) -> dict[str, Any]:
        """Build the keyword arguments handed to the process backend's spawn()."""
        kwargs: dict[str, Any] = {"echo": self.echo, "preexec_fn": preexec_fn}
        if self.ignore_sighup:
            if sys.platform == "win32":
                # No SIGHUP to ignore, and no fork to ignore it in.
                msg = "ignore_sighup is not supported on Windows"
                raise ExceptionPexpect(msg)

            def preexec_wrapper() -> None:
                """Set SIGHUP to be ignored, then call the real preexec_fn."""
                signal.signal(signal.SIGHUP, signal.SIG_IGN)
                if preexec_fn is not None:
                    preexec_fn()

            kwargs["preexec_fn"] = preexec_wrapper

        if dimensions is not None:
            kwargs["dimensions"] = dimensions
        return kwargs
```

`echo=False` and a non-None `preexec_fn` are refused by the Windows backend's
`spawn()` (Task 2), which raises `PtyProcessError`. `_spawn` calls
`self._spawnpty(...)` unwrapped today, so that error would reach the caller as
the wrong type. Wrap it:

```python
        with _wrap_ptyprocess_err():
            self.ptyproc = self._spawnpty(resolved_args, env=self.env, cwd=self.cwd, **kwargs)
```

The same applies to the three echo calls and to `kill`, which reach the backend
unwrapped. `getecho`:

```python
    def getecho(self) -> bool:
        """..."""  # keep the existing docstring
        with _wrap_ptyprocess_err():
            return self.ptyproc.getecho()
```

`setecho`, the same shape around `return self.ptyproc.setecho(state)`.

`waitnoecho` delegates to `getecho`, so without a check of its own it would
raise a message naming `getecho()` -- which breaks the rule that the message
names the call. Give it the guard as its first statement:

```python
        if sys.platform == "win32":
            # It waits for a termios flag to clear, and there is no such flag.
            msg = "waitnoecho() is not supported on Windows"
            raise ExceptionPexpect(msg)
```

`kill` calls `os.kill` directly. On Windows that turns every signal but
`SIGTERM` into a `TerminateProcess` exit code, so a `kill(SIGHUP)` would kill a
child the caller meant to hang up. Route it through the backend instead, which
needs no platform branch -- ptyprocess's `kill` is the same `os.kill` call, and
the Windows adapter's refuses what it cannot deliver:

```python
    def kill(self, sig: int) -> None:
        """..."""  # keep the existing docstring
        # The pid is the backend's; it is given for you, as os.kill's is not.
        if self.isalive():
            with _wrap_ptyprocess_err():
                self.ptyproc.kill(sig)
```

- [ ] **Step 4: Refuse `use_poll` and `interact` on Windows**

In `_ready`:

```python
    def _ready(self, timeout: float | None) -> bool:
        """Return True when the child fd has data available within *timeout*."""
        if self.use_poll:
            if sys.platform == "win32":
                # select.poll() does not exist there. select() does, and it
                # accepts the socket descriptor this backend reads through.
                msg = "use_poll is not supported on Windows"
                raise ExceptionPexpect(msg)
            return bool(poll_ignore_interrupts([self.child_fd], timeout))
        return bool(select_ignore_interrupts([self.child_fd], [], [], timeout)[0])
```

`use_poll` is assigned after `_spawn()` in `__init__`, so a constructor raise
needs the check earlier. Add it immediately after `super().__init__(...)`:

```python
        if use_poll and sys.platform == "win32":
            msg = "use_poll is not supported on Windows"
            raise ExceptionPexpect(msg)
```

and keep the `_ready` check as well: `use_poll` is a documented public
attribute a caller can set after construction.

In `interact`, make the raise the first statement and move the POSIX-only
imports into the function:

```python
    def interact(
        self,
        escape_character: str | None = _DEFAULT_ESCAPE_CHARACTER,
        input_filter: Callable[[bytes], bytes] | None = None,
        output_filter: Callable[[bytes], bytes] | None = None,
    ) -> None:
        """..."""  # keep the existing docstring, and add the paragraph below
        if sys.platform == "win32":
            # Handing the terminal to a human needs raw-mode console input,
            # which is termios and tty here and neither on Windows. Everything
            # a script does -- expect, send, read, close -- works there.
            msg = "interact() is not supported on Windows"
            raise ExceptionPexpect(msg)
        import termios  # noqa: PLC0415 -- POSIX-only, and this method is the only user
        import tty  # noqa: PLC0415 -- POSIX-only, and this method is the only user
```

Then delete `import termios` and `import tty` from the module imports. Add to
the docstring, above the existing text:

```
        Not supported on Windows, where it raises :class:`ExceptionPexpect`.
```

Verified before writing this step: the only real uses of either module are the
three lines at the end of `interact` -- `termios.tcgetattr`, `tty.setraw`,
`termios.tcsetattr`. The `fcntl.ioctl` and `termios.TIOCGWINSZ` at `:947` are
inside `interact`'s docstring example, not its body, and the `__interact_*`
helpers use only `os.read` and `os.write`. So the two function-level imports
cover everything, and no `fcntl` import is needed. Re-check after editing with
`grep -n "termios\.\|tty\." src/pexpect/pty_spawn.py` -- every hit should be
inside `interact`.

- [ ] **Step 5: Run the tests, then read the Windows leg**

Run: `uv run --frozen pytest tests -x -q`
Expected: PASS on Linux, whole suite, including `tests/integration/test_interact.py`.

Run: `uv run --frozen nox`
Expected: PASS, 100% coverage on Linux.

```bash
git add src/pexpect/pty_spawn.py tests/test_unsupported.py
git commit -m "feat: refuse the calls Windows cannot honour

getecho, setecho, waitnoecho and interact need termios; preexec_fn and
ignore_sighup need a fork; use_poll needs select.poll; kill needs signals. Each
raises ExceptionPexpect naming itself on Windows, so a script written against
POSIX fails at the call rather than silently doing something else.

tests/test_unsupported.py asserts both halves of every one of them, which is
also the coverage the excluded platform branches get.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01ARmrZ1bE971i3nFZfYEifV"
git push
gh run watch --exit-status
```

---

### Task 5: `terminate()` and the test fixtures that kill children

**Files:**
- Modify: `src/pexpect/pty_spawn.py:805-832` (`terminate`)
- Modify: `tests/conftest.py:295-320` (`killed_pty_children`), `:57-60` (`_ON_POSIX`), `:196-208` (`_time_one_child`)

**Interfaces:**
- Consumes: `pexpect._winpty.PtyProcess.terminate` and `.kill` (Task 2).
- Produces: `spawn.terminate(force=False) -> bool` working on both platforms; `killed_pty_children` usable on both.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_spawn_smoke.py`:

```python
def test_terminate_stops_a_child_that_ignores_nothing() -> None:
    child = pexpect.spawn(sys.executable, ["-c", "input()"], timeout=10)
    try:
        assert child.isalive()
        assert child.terminate(force=True) is True
        assert child.isalive() is False
    finally:
        child.close(force=True)


def test_terminate_on_a_dead_child_is_true() -> None:
    child = pexpect.spawn(sys.executable, ["-c", ""], timeout=10)
    try:
        child.expect(pexpect.EOF)
        assert child.terminate() is True
    finally:
        child.close(force=True)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run --frozen pytest tests/test_spawn_smoke.py -v -k terminate`
Expected: PASS on Linux. On Windows the first one fails inside `terminate`,
because the POSIX branch reaches `signal.SIGHUP`, which does not exist there --
`AttributeError`, not `ExceptionPexpect`.

- [ ] **Step 3: Give `terminate` a Windows path**

In `pty_spawn.py`, at the top of `terminate`'s body after the `isalive` check:

```python
        if not self.isalive():
            return True
        if sys.platform == "win32":
            # Ctrl-C, then TerminateProcess only with force. The POSIX ladder's
            # SIGHUP and SIGCONT have no counterpart, and os.kill() there
            # treats any signal but SIGTERM as an exit code rather than a
            # signal, so walking the ladder would kill on the first rung.
            return bool(self.ptyproc.terminate(force=force))
        try:
            for sig in (signal.SIGHUP, signal.SIGCONT, signal.SIGINT):
```

Leave the rest of the method as it is. Update the docstring's first paragraph:

```
        It starts nicely with SIGHUP and SIGINT. If "force" is True then moves
        onto SIGKILL. This returns True if the child was terminated. This
        returns False if the child could not be terminated.

        On Windows there is no ladder: Ctrl-C is sent, and TerminateProcess
        follows only if *force* is True.
```

- [ ] **Step 4: Make the test fixtures portable**

In `tests/conftest.py`:

1. `_ON_POSIX` no longer guards the import -- `pty_spawn` imports everywhere now. Replace

```python
_ON_POSIX = sys.platform != "win32"
if _ON_POSIX:
    from pexpect import pty_spawn
```

with

```python
from pexpect import pty_spawn

_ON_POSIX = sys.platform != "win32"
```

and update the comment above it: the pty API is no longer POSIX-only, and what
remains platform-specific is which programs the suite can drive.

2. `_time_one_child` can now measure a real child on both platforms. Replace
   the whole `if _ON_POSIX: ... else: ...` body with:

```python
def _time_one_child() -> float:
    """Return the seconds one spawn-and-close of a child process took."""
    started = time.perf_counter()
    child = pty_spawn.spawn(_CALIBRATION_COMMAND)
    child.close()
    return time.perf_counter() - started
```

`_CALIBRATION_COMMAND` stays a single command string, which is what `spawn`
takes as its first argument -- do not splat it.

and replace the `_CALIBRATION_COMMAND` constant with the portable form,
keeping the reasoning in its comment and adding why it changed:

```python
# What to spawn to measure one child. `cat` is what most of these tests drive,
# it starts without reading a config or an interpreter, and so it measures the
# fork/exec/pty floor rather than a program. On Windows it is the Python
# stand-in tests/helpers/cat.py, which is dearer -- an interpreter start rather
# than an exec -- and that is the figure a Windows budget should scale with.
_CALIBRATION_COMMAND = commands.CAT
```

with `from . import commands` added to the imports. `commands` comes from
Task 6; if that task has not landed yet, leave `_CALIBRATION_COMMAND = "cat"`
and its `_ON_POSIX` guard alone and finish this sub-step in Task 6 step 4,
where `tests/conftest.py` is being edited anyway.

3. `killed_pty_children` sends `signal.SIGKILL`, which does not exist on
   Windows. Replace the kill with:

```python
        # SIGKILL is POSIX; on Windows os.kill() with SIGTERM is
        # TerminateProcess, which is the same "cannot be caught" contract.
        # Written as a platform `if` rather than a conditional expression
        # because that is the form mypy narrows: under --platform win32,
        # signal.SIGKILL does not exist and a ternary would not be excused.
        if sys.platform == "win32":
            hard_kill = signal.SIGTERM
        else:
            hard_kill = signal.SIGKILL
        with contextlib.suppress(OSError):
            os.kill(ptyproc.pid, hard_kill)
```

Hoist the two-line platform choice to module level beside `_ON_POSIX` if ruff
objects to it inside the loop.

- [ ] **Step 5: Run the tests and make sure they pass**

Run: `uv run --frozen pytest tests -x -q`
Expected: PASS on Linux, whole suite.

Run: `uv run --frozen nox`
Expected: PASS.

- [ ] **Step 6: Commit and read the Windows leg**

```bash
git add src/pexpect/pty_spawn.py tests/conftest.py tests/test_spawn_smoke.py
git commit -m "feat: terminate a Windows child, and kill the test suite's own

terminate() walked a POSIX signal ladder whose first rung, SIGHUP, does not
exist on Windows. There it sends Ctrl-C and, with force, TerminateProcess.

The suite's killed_pty_children fixture had the same problem with SIGKILL, and
its per-test budget can now be measured from a real child on both platforms
rather than from an empty interpreter.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01ARmrZ1bE971i3nFZfYEifV"
git push
gh run watch --exit-status
```

---

### Task 6: Run the suite's spawn tests on Windows

The largest task. Replaces the collection-time drop with per-module skips, and
gives the fourteen spawn-driving modules programs that exist on both platforms.

**Files:**
- Create: `tests/commands.py`, `tests/helpers/__init__.py`, `tests/helpers/cat.py`, `tests/helpers/echo.py`, `tests/helpers/sleep.py`, `tests/helpers/true.py`
- Modify: `tests/conftest.py:140-186` (`_POSIX_ONLY`, `collect_ignore`)
- Create: `tests/integration/conftest.py` addition
- Modify: `tests/test_expect.py`, `test_misc.py`, `test_isalive.py`, `test_constructor.py`, `test_env.py`, `test_winsize.py`, `test_unicode.py`, `test_ctrl_chars.py`, `test_repr.py`, `test_run.py`, `test_delay.py`, `test_dotall.py`, `test_timeout_pattern.py`, `test_async.py`
- Modify: `tests/test_socket.py`, `test_socket_fd.py`, `test_pxssh.py`, `test_replwrap.py`, `test_popen_spawn.py` (each gains a `skipif`)

**Interfaces:**
- Consumes: `pexpect.spawn` on Windows (Task 3).
- Produces: `tests.commands.CAT: str`, `tests.commands.TRUE: str`, `tests.commands.echo(text: str = "") -> str`, `tests.commands.sleep(seconds: float) -> str`. Each returns a command string suitable for `pexpect.spawn(...)` and `pexpect.run(...)`.

- [ ] **Step 1: Write the helper programs and the command table**

Create `tests/helpers/__init__.py` as an empty file, then:

`tests/helpers/cat.py`:

```python
"""Copy stdin to stdout, a line at a time, until end of file.

`cat` is what most of this suite drives and Windows has no such program. Line
at a time rather than in blocks, because the tests expect a line to come back
as soon as it is sent.
"""

import sys

for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
```

`tests/helpers/echo.py`:

```python
"""Print the arguments, separated by spaces, then a newline. Stand-in for `echo`."""

import sys

print(" ".join(sys.argv[1:]))
```

`tests/helpers/sleep.py`:

```python
"""Sleep for the number of seconds given as the only argument. Stand-in for `sleep`."""

import sys
import time

time.sleep(float(sys.argv[1]))
```

`tests/helpers/true.py`:

```python
"""Exit 0 immediately. Stand-in for `true`."""
```

`tests/commands.py`:

```python
"""The programs this suite drives, named once and resolved per platform.

POSIX has cat, echo, sleep and true; Windows has none of them, so each resolves
to a Python stand-in under tests/helpers/ run by the current interpreter. Every
name here is a command string rather than an argument list, because that is the
form pexpect.spawn() and pexpect.run() share -- run()'s second positional
parameter is a timeout, so a test cannot splat a pair into it.

Paths are written with forward slashes. pexpect splits a command string with
pexpect.utils.split_command_line, which treats a backslash as an escape, so a
Windows path in its native spelling would lose its separators.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ON_WINDOWS = sys.platform == "win32"
_HELPERS = Path(__file__).parent / "helpers"
_PYTHON = Path(sys.executable).as_posix()


def _helper(name: str) -> str:
    """Return the command that runs the stand-in *name* under this interpreter."""
    return f"{_PYTHON} {(_HELPERS / name).as_posix()}"


CAT = _helper("cat.py") if _ON_WINDOWS else "cat"
TRUE = _helper("true.py") if _ON_WINDOWS else "true"


def echo(text: str = "") -> str:
    """Return a command that prints *text* and a newline."""
    if _ON_WINDOWS:
        return f"{_helper('echo.py')} {text}" if text else _helper("echo.py")
    return f"echo {text}" if text else "echo"


def sleep(seconds: float) -> str:
    """Return a command that sleeps for *seconds* and exits."""
    return f"{_helper('sleep.py')} {seconds}" if _ON_WINDOWS else f"sleep {seconds}"
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run --frozen python -c "from tests import commands; print(commands.CAT, commands.echo('hi'), commands.sleep(0.5))"`
Expected: `cat echo hi sleep 0.5` on Linux. Then:

Run: `uv run --frozen pytest tests/test_misc.py -q`
Expected: PASS -- nothing uses `commands` yet. This step is the "see it fail"
for the conversion: pick one test and convert it first, in step 3.

- [ ] **Step 3: Convert one module, then the rest**

Start with `tests/test_misc.py`, the heaviest at 40 command literals. Add
`from . import commands` to its imports, then replace the literals. The
distribution across all fourteen modules, measured:

| Literal | Count | Replacement |
|---|---|---|
| `"cat"` | 81 | `commands.CAT` |
| `"true"` | 3 | `commands.TRUE` |
| `"sleep 0.01"`, `"sleep 0.05"`, `"sleep 3"`, `"sleep 5"` | 6 | `commands.sleep(0.01)` and so on |
| `"echo"`, `"echo abc"`, `"echo abcdef"`, `"echo alpha"`, `"echo 1234"`, `"echo foobarbazbop"`, `"echo hello.?world"` | 8 | `commands.echo()`, `commands.echo("abc")`, ... |

Four kinds of literal have no stand-in and mark tests that are about POSIX
itself rather than about pexpect. Each gets its own `skipif` rather than a
replacement, with the reason naming what it needs:

- `"ls"`, `"ls -l /bin"`, `"/bin/ls"`, `"/bin/ls -l /bin"` -- a program at an absolute POSIX path, and output the test matches against
- `"uname"`, `"uname -m -n -p -r -s -v"` -- POSIX-only program
- `"sh"` -- POSIX shell
- `""`, `" ls"`, `"   "` -- these are about `split_command_line` and the empty-command error, so they stay as they are and need no skip

```python
    @pytest.mark.skipif(sys.platform == "win32", reason="needs the POSIX program `ls`")
    def test_...(self) -> None:
```

Convert the remaining thirteen modules the same way, in this order, running
each module's tests after it: `test_expect.py` (39), `test_unicode.py` (11),
`test_run.py` (11), `test_isalive.py` (7), `test_async.py` (6),
`test_timeout_pattern.py` (4), `test_repr.py` (2), `test_dotall.py` (2),
`test_delay.py` (2), `test_constructor.py` (1). `test_env.py`,
`test_winsize.py` and `test_ctrl_chars.py` have no command literals and need
only their entry removed from `_POSIX_ONLY` in step 4.

After each module: `uv run --frozen pytest tests/<module> -q`. Expected: PASS,
with the same number of tests as before the conversion.

- [ ] **Step 4: Replace the collection-time drop with skips**

In `tests/conftest.py`, delete the `_POSIX_ONLY` tuple, the `collect_ignore`
assignment, and the paragraph of the module docstring that describes them.
Replace that docstring paragraph with:

```
A module that cannot run on Windows says so itself, with a module-level
``pytest.mark.skipif`` naming what it needs. Dropping such modules at
collection was necessary while ``pexpect.spawn`` could not be imported there --
a skip mark never runs when the module carrying it cannot be imported -- and it
is not any more.
```

Then add to each of the five modules, immediately after its imports:

`tests/test_socket.py` and `tests/test_socket_fd.py`:

```python
pytestmark = [
    pytest.mark.usefixtures("fast_sleep"),
    pytest.mark.skipif(
        sys.platform == "win32",
        # The server is a bound method of the test case, which no spawn start
        # method can carry, so it needs a forked subprocess.
        reason="needs os.fork to run its socket server",
    ),
]
```

`test_socket_fd.py` imports `test_socket`, so it needs its own mark rather
than inheriting one, and needs `import sys` added.

`tests/test_pxssh.py`, `tests/test_replwrap.py` and `tests/test_popen_spawn.py`
get the same shape with their own reasons: `"drives POSIX programs and an ssh
binary"`, `"drives bash and zsh"`, and `"drives cat, echo, sleep and ls, plus
SIGKILL and SIGTERM delivery"` respectively. Keep whatever `pytestmark` each
already has and add to it -- `test_pxssh.py`'s is a `usefixtures` mark with
three fixtures.

For `tests/integration/`, whose ten modules would each need the same mark, add
to `tests/integration/conftest.py`:

```python
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip the whole directory on Windows.

    Every module here drives a POSIX program -- bash, zsh, ssh, man, ls -- or
    the pty behaviour that only a POSIX pty has. A directory has no
    module-level ``pytestmark``, so the mark is added per item instead.
    """
    if sys.platform == "win32":
        skip = pytest.mark.skip(reason="integration tests drive POSIX programs")
        for item in items:
            item.add_marker(skip)
```

with `import sys` added. If that conftest already defines
`pytest_collection_modifyitems` for its own timeout budget, add the skip to
that function rather than defining a second one -- two definitions in one
module means the later silently wins.

- [ ] **Step 5: Confirm every module imports on Windows**

The skips only run if the modules carrying them can be imported, which is the
precondition the spec records. Prove it rather than assume it:

Run: `uv run --frozen pytest tests --collect-only -q`
Expected: collection succeeds, no errors, and the count matches the pre-change
count. On Linux this proves nothing about Windows -- CI's `--collect-only` on
the Windows leg is the real check, and step 7 reads it.

- [ ] **Step 6: Run the suite and the coverage gate**

Run: `uv run --frozen pytest tests -q`
Expected: PASS, whole suite, same test count as before this task plus the new
skips.

Run: `uv run --frozen nox`
Expected: PASS, 100% on Linux.

- [ ] **Step 7: Commit and read the Windows leg**

```bash
git add tests/
git commit -m "test: run the spawn tests on Windows

Fourteen modules drove cat, echo, sleep and true and so could not run on
Windows. tests/commands.py names each program once and resolves it to a Python
stand-in there, and the handful of tests that are about a POSIX program rather
than about pexpect carry their own skipif.

The six modules that still cannot run say so with a module-level skipif instead
of being dropped by collect_ignore, which was a workaround for pexpect.spawn
being unimportable on Windows.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01ARmrZ1bE971i3nFZfYEifV"
git push
gh run watch --exit-status
```

Expected: the Windows legs run roughly four hundred more tests than before.
This is where ConPTY's differences from a POSIX pty surface in bulk. For each
failure, decide between three answers and say which in the commit message: a
real bug in `_winpty.py`; a difference that belongs in the documentation with
the test carrying a `skipif` naming it; or a test that was asserting POSIX pty
mechanics rather than pexpect behaviour. Never weaken an assertion to make a
platform pass.

---

### Task 7: Type-check both platforms, retune the floor, write the docs

**Files:**
- Modify: `noxfile.py:44-59` (`lint`), `:25-31` (`_WINDOWS_COVERAGE_FLOOR`)
- Modify: `pyproject.toml` (`[tool.mypy] platform`)
- Modify: `README.rst:24`, `DEVELOPERS.rst:68-127`, `doc/install.rst`, `doc/overview.rst`, `doc/history.rst`

**Interfaces:**
- Consumes: everything above.
- Produces: no new names.

- [ ] **Step 1: Write the failing check**

Run: `uv run --frozen mypy --platform win32 src`
Expected: FAIL. `[tool.mypy] platform = "linux"` is overridden by the flag, and
this is the first time the Windows branches are analysed; expect errors in
`_winpty.py`, `_ptyproc.py` and the `sys.platform == "win32"` blocks. That
output is this task's work list.

- [ ] **Step 2: Remove the platform pin**

In `pyproject.toml`, delete the `platform = "linux"` line and the comment above
it that explains why pexpect is POSIX-only, and replace both with:

```toml
# No `platform` pin. It used to be "linux", because `pty`, `termios`, `tty` and
# `fcntl` exist nowhere else and neither did pexpect.spawn, so a Windows
# checkout ended in several hundred attr-defined errors about code that never
# ran there. Both platforms now carry live code, so both are checked -- the
# lint session runs mypy twice, once per platform, and pinning either one here
# would silence the other.
```

- [ ] **Step 3: Run mypy twice in the lint session**

In `noxfile.py`, replace the single mypy call with:

```python
    # Both platforms, because the library carries live code for both: the
    # process backend behind pexpect._ptyproc is ptyprocess on POSIX and
    # pywinpty on Windows, and whichever platform mypy assumes, the other one's
    # branch drops out of the analysis.
    #
    # The win32 pass covers src/ only. The suite's POSIX-only modules reach for
    # os.fork, signal.SIGHUP and signal.SIGKILL at the top level of a function,
    # guarded by a pytest skipif that mypy cannot read, so a win32 pass over
    # tests/ would report a few dozen attr-defined errors about tests that
    # never run there. What the second pass is for is the library's Windows
    # code, and src/ is where all of it lives.
    #
    # One report per interpreter per platform -- the sessions would otherwise
    # take turns overwriting one reports/mypy.xml, which CI publishes.
    for platform, targets in (("linux", (_SRC_ROOT, _TESTS_ROOT)), ("win32", (_SRC_ROOT,))):
        session.run(
            "mypy",
            f"--platform={platform}",
            "--junit-xml",
            f"reports/mypy-{session.python}-{platform}.xml",
            *targets,
        )
```

- [ ] **Step 4: Fix what the second pass finds**

Run: `uv run --frozen nox -s "lint-3.12"`

Work through the errors. The ones to expect, and their answers:

- `Name "PtyProcess" already defined` in `_ptyproc.py` -- the `type: ignore[no-redef]` in Task 1 covers it; if mypy names a different code, use that code rather than a bare ignore.
- `Module has no attribute "SIGHUP"` under `--platform win32` in the POSIX branches -- these are inside `if sys.platform != "win32":` or the `else` of a `win32` check, which mypy narrows; if one is not, restructure the branch rather than silencing it.
- `winpty` import errors -- the override added in Task 2 handles them; if `follow_untyped_imports` and `ignore_missing_imports` together still error, the module list in the override is wrong.

Expected at the end: PASS on both platforms, five interpreters.

- [ ] **Step 5: Retune the Windows coverage floor**

Read the Windows figure from the CI run of Task 6 -- `collate_coverage` prints
the total before it checks the floor. Set `_WINDOWS_COVERAGE_FLOOR` to that
figure rounded down to a whole percent, and rewrite its comment:

```python
# The coverage floor for a Windows run, which cannot be the 100% in
# pyproject.toml because it cannot run the whole suite: tests/integration and
# the five modules that drive POSIX programs skip themselves there, and
# interact() cannot run at all. What is left reaches this, so the floor still
# catches a Windows regression -- it just has to be re-tuned whenever a module
# moves across that line, which is a thing a reviewer can see in the same diff.
_WINDOWS_COVERAGE_FLOOR = <the measured figure>
```

- [ ] **Step 6: Write the documentation**

`README.rst:24` currently says pexpect does not work on Windows. Replace that
sentence with what is now true: `pexpect.spawn` works on Windows 10 and 11
through ConPTY, by way of `pywinpty`; `interact()` and the terminal-echo calls
raise `ExceptionPexpect` there; and `PopenSpawn` remains available for a child
that needs no pty.

`DEVELOPERS.rst`, the "Running it on Windows" section: it says Windows has no
pty and describes `_POSIX_ONLY` and the coverage floor. Rewrite it around what
the suite now does -- the fourteen modules that run on both platforms, the
stand-in programs in `tests/helpers/`, the six modules that skip themselves and
why, `tests/integration`'s directory-wide skip, and the retuned floor. Keep the
paragraph explaining that the floor is a real gate.

`doc/install.rst`: add the Windows requirements -- Windows 10 or 11, and that
`pip install pexpect` brings `pywinpty` there automatically.

`doc/overview.rst`: add a short section listing what raises on Windows, pointing
at `tests/test_unsupported.py` as the authority.

`doc/history.rst`: add an entry under the unreleased version naming the change,
the new dependency, and the calls that raise.

- [ ] **Step 7: Full run, then commit**

Run: `uv run --frozen nox`
Expected: PASS -- lint on both platforms for five interpreters, tests, 100%
coverage on Linux.

```bash
git add noxfile.py pyproject.toml README.rst DEVELOPERS.rst doc/
git commit -m "build: type-check both platforms, and document the Windows support

mypy was pinned to linux because pexpect had no Windows code to check. It has
now, so the lint session runs both platforms and both must pass.

The Windows coverage floor is retuned to what the suite reaches there now that
the spawn tests run, and README, DEVELOPERS and doc/ say what works on Windows
and what raises.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01ARmrZ1bE971i3nFZfYEifV"
git push
gh run watch --exit-status
```

Expected: all four CI jobs green.

---

## Verification checklist

Before calling the work done, on a green CI run:

- [ ] `pexpect.spawn`, `pexpect.spawnu`, `pexpect.run`, `pexpect.runu` import on `windows-latest` for 3.10 through 3.14.
- [ ] `tests/test_spawn_smoke.py` passes on both platforms.
- [ ] `tests/test_unsupported.py` passes on both platforms, with the Windows half actually running rather than skipping -- check the CI log for `skipped` counts.
- [ ] The fourteen converted modules report the same test count on both platforms, allowing for the individual `skipif`s added in Task 6 step 3.
- [ ] Linux coverage is 100%; Windows coverage meets the retuned floor.
- [ ] `ruff format --check`, `ruff check`, and mypy on both platforms pass for all five interpreters.
- [ ] No POSIX test that passed at `0724807` fails now.
