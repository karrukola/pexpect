# Windows support for `pexpect.spawn`

Date: 2026-09-10
Status: approved, not yet implemented

## Problem

`import pexpect; pexpect.spawn(...)` raises `AttributeError` on Windows.
That is deliberate, not a defect. `src/pexpect/__init__.py` exports
`spawn`, `spawnu`, `run` and `runu` behind `if sys.platform != "win32"`,
because `pexpect.pty_spawn` imports `pty`, which imports `termios`, and
because its process backend `ptyprocess` is POSIX-only.

The goal is that `pexpect`'s public interface is the same on Linux and on
Windows 10 and 11 -- the same names, the same signatures, the same
defaults -- and that the methods behind those signatures actually work
rather than merely import.

## Non-goals

* Windows versions before 10. ConPTY does not exist there.
* `interact()` on Windows. It hands the terminal to a human and needs
  raw-mode console input; it raises instead. See "Unsupported calls".
* Running the whole test suite on Windows. `tests/integration`,
  `test_socket.py`, `test_socket_fd.py`, `test_pxssh.py`,
  `test_replwrap.py` and `test_popen_spawn.py` are skipped there; each
  needs a POSIX program, `os.fork`, or both.
* Changing any POSIX behaviour. Every change below is either a
  platform-neutral refactor or a `win32` branch.

## Decisions

Each of these was chosen explicitly; the rejected alternatives are
recorded because the reasons are the design.

### The pty backend is pywinpty

`pywinpty >= 3.0.5` becomes a Windows-only dependency. It wraps ConPTY,
ships wheels for `cp310` through `cp314` -- the whole of
`.python-versions` -- and declares `requires_python >= 3.10`, matching
this project.

Rejected: hand-rolled `ctypes` calls to `CreatePseudoConsole`. Several
hundred lines of Windows-only code, debuggable only through CI, for
something a maintained dependency already does.

Rejected: aliasing `spawn = PopenSpawn` on Windows. The signature would
match and nothing else would; there is no console, so no echo, no
`setwinsize`, and programs that read the terminal directly still
misbehave.

### Unsupported calls raise `ExceptionPexpect`

One exception type for every call that Windows cannot honour, carrying
the method name. Signatures stay identical, so `hasattr` and duck-typed
callers see no difference, and a script that depends on a POSIX-only
capability fails loudly at the call rather than silently doing the wrong
thing.

Rejected: best-effort no-ops. A `setecho(False)` that silently succeeds
turns a password prompt into a password echoed into the log, which is the
exact bug the call was preventing.

Rejected: warn-then-degrade. This suite sets `filterwarnings = ["error"]`,
so it would behave as a raise under test and as a no-op in production --
two behaviours to document and one of them untested.

Rejected: `NotImplementedError` for `interact()` specifically. Two
exception types for one concept is worse than one.

### `winpty.PtyProcess` is wrapped, its `read()` is not

pywinpty ships `winpty.PtyProcess`, shaped deliberately like
`ptyprocess.PtyProcess`. It is used for spawning, lifecycle, window size
and termination -- all the ConPTY work.

It also gives a working `fileno()`, which was not expected: a reader
thread pumps ConPTY output into a loopback socket, and `select.select()`
accepts socket descriptors on Windows. So `read_nonblocking`'s readiness
path needs no rewrite and `fileno()` is supportable rather than raising.

Its `read()` is bypassed. That method returns `str`, while pexpect is
bytes end to end and decodes with the caller's `encoding` and
`codec_errors`; and it re-reads one byte at a time until its buffer
decodes as UTF-8:

```python
err = True
while err and data:
    try:
        data.decode('utf-8'); err = False
    except UnicodeDecodeError:
        data += self.fileobj.recv(1)
```

On truncated UTF-8 that is correct. On invalid UTF-8 -- a child emitting
cp1252 or raw binary -- it never decodes and blocks on `recv(1)`
indefinitely, inside their loop where no pexpect timeout reaches it.
Reading `ptyproc.fileobj.recv(size)` directly yields the child's real
bytes, honours `encoding=None`, honours `codec_errors`, and cannot hang
that way.

Two defects of the dependency are inherited rather than fixed, and are
recorded here so they are not rediscovered as pexpect bugs:

* Each spawn opens a listening TCP socket on `127.0.0.1`. A local process
  could win the race to connect and read the child's output.
* Their reader thread sends the in-band sentinel `b'0011Ignore'` for an
  empty read and strips it on the way out, so a child printing that exact
  string loses it. `PYWINPTY_BLOCK` defaults to `1`, which makes the
  sentinel rare.

### One `spawn` class, not two

`pexpect.pty_spawn.spawn` remains the single implementation for both
platforms. Measured against the current file, the POSIX-only surface is
six places, not a class:

| Location | POSIX-only today | On Windows |
|---|---|---|
| `pty_spawn.py:272` | `pty.STDIN_FILENO` and friends | the literals `0`, `1`, `2`, which is what `pty` defines them as |
| `spawnbase.py:336` | `os.read(self.child_fd, size)` | a backend method |
| `pty_spawn.py:729` | `os.write(self.child_fd, b)` | a backend method |
| `pty_spawn.py:476` | `os.isatty(self.child_fd)` | a backend method |
| `pty_spawn.py:815` | the `terminate()` signal ladder | delegated to the backend |
| `pty_spawn.py:384` | the `ignore_sighup` preexec | raises |

Everything in `pty_spawn.py:947-996` is inside `interact()`, which
raises, so `termios` and `tty` leave the module with it.

Rejected: a separate `win_spawn.py` with its own `spawn` class. It would
duplicate roughly 400 lines of argument handling, sending and expect glue
and give two places for every future bug fix.

Rejected: extracting a platform-neutral base class. Justifiable if the
seam were large; it is three one-line methods.

## Design

### Dependencies

```toml
dependencies = [
    "ptyprocess>=0.7.0; sys_platform != 'win32'",
    "pywinpty>=3.0.5; sys_platform == 'win32'",
]
```

`ptyprocess` gains a POSIX marker because it imports `termios` at import
time. `Operating System :: Microsoft :: Windows` joins the classifiers,
and `uv.lock` is regenerated.

### `src/pexpect/_ptyproc.py`

The only module that branches on the platform:

```python
if sys.platform == "win32":
    from ._winpty import PtyProcess, PtyProcessError
else:
    from ptyprocess import PtyProcess, PtyProcessError
```

On POSIX it subclasses `ptyprocess.PtyProcess` to add `read_bytes`,
`write_bytes` and `isatty`, so both backends present the same surface and
`pty_spawn` needs no `sys.platform` test to talk to either.

### `src/pexpect/_winpty.py`

The adapter over `winpty.PtyProcess`. It presents the surface
`pty_spawn` already uses: `spawn()`, `pid`, `fd`, `close(force)`,
`isalive()`, `wait()`, `status`, `exitstatus`, `signalstatus`,
`flag_eof`, `terminate(force)`, `kill(sig)`, `getwinsize()`,
`setwinsize(rows, cols)`, `sendcontrol(char)`, `sendeof()`,
`sendintr()`, `read_bytes(size)`, `write_bytes(data)`, `isatty()`.

What it has to supply on top of pywinpty:

* `status` and `signalstatus`, which pywinpty does not define.
  `signalstatus` is always `None`: a Windows process does not exit by
  signal.
* `sendeof()` and `sendintr()` return `(n, byte)` as `pty_spawn`
  unpacks them; pywinpty's return `None`.
* `sendeof()` sends Ctrl-Z, `\x1a`, the Windows console EOF. pywinpty
  sends Ctrl-D.
* `terminate(force=False)` returns a `bool`; pywinpty's falls off the end
  and returns `None` when the child survives a non-forced terminate.
* `read_bytes` reads `fileobj.recv(size)`, for the reasons above, and
  returns `b""` at end of file. Nothing more is needed: the existing
  BSD-style branch in `SpawnBase.read_nonblocking` already turns an empty
  read into `flag_eof` plus `EOF`, and its `OSError`/`EIO` branch is the
  Linux-style equivalent. So the seam is `self._read_fd(size)` in place
  of `os.read(self.child_fd, size)`, with the two EOF branches left where
  they are.

### `spawn`'s Windows branches

Each raises `ExceptionPexpect` naming the call:

* `getecho()`, `setecho()`, `waitnoecho()`. Termios; under ConPTY, echo
  is a property of the child's console host and not reachable from the
  parent.
* `interact()`.
* `kill(sig)` for anything but `SIGINT`, mapped to `CTRL_C_EVENT`, and
  `SIGTERM`/`SIGKILL`, mapped to `os.kill`, which is `TerminateProcess`
  on Windows.
* the constructor arguments `preexec_fn` when not `None`,
  `ignore_sighup=True`, `echo=False`, and `use_poll=True` --
  `select.poll` does not exist on Windows.

`fileno()` returns pywinpty's socket descriptor rather than raising.
`terminate(force)` keeps the POSIX signal ladder on POSIX and delegates
to the adapter on Windows.

### The export

`src/pexpect/__init__.py` drops the `sys.platform != "win32"` guard;
`spawn`, `spawnu`, `run` and `runu` import unconditionally. That single
change is what fixes the reported `AttributeError`.

`pexpect.pxssh` and `pexpect.replwrap` need no edit. Both sit on `spawn`,
and Windows 10 and 11 ship an OpenSSH client.

## Typing and lint

`[tool.mypy] platform = "linux"` cannot stand once both platforms carry
live code: pinning to Linux would leave every Windows branch unchecked.
The `lint` session runs mypy twice, `--platform linux` and
`--platform win32`, and both must pass. `pywinpty` ships `_winpty.pyi`
but no `py.typed` marker, so it joins the existing
`follow_untyped_imports` override alongside `ptyprocess`.

Ruff already lints the whole tree on both runners and needs no change.

## Testing

`tests/commands.py` exports `CAT`, `ECHO` and `SLEEP`, resolving to the
real programs on POSIX and to `[sys.executable, tests/helpers/<name>.py]`
on Windows. Rewriting the literal `"cat"` and `"echo hello"` command
strings in the modules below is the largest single piece of work in this
change.

`_POSIX_ONLY` and `collect_ignore` in `tests/conftest.py` go away
entirely. A module that cannot run on Windows says so itself:

```python
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="drives POSIX programs: cat, echo, sleep",
)
```

Dropping a module at collection was never the preference -- the comment
in `tests/conftest.py` gives the reason it was necessary: "a skip mark
never runs when the module that carries it cannot be imported", and
`pexpect.spawn` was unimportable on Windows. This change removes that
constraint, so the mechanism becomes a skip with a stated reason,
counted and printed by pytest, instead of a name in a list that a reader
has to cross-reference.

The precondition is that every module under `tests/` imports cleanly on
Windows, which a `pytest --collect-only` run on CI confirms before the
marks are trusted. It holds by inspection today: of the six POSIX-only
modules, none imports a POSIX-only stdlib module -- between them they
import `os`, `signal`, `socket`, `multiprocessing` and `platform`, all of
which exist on Windows -- and every `pexpect` module they import becomes
importable there under this design.

Fourteen modules lose their POSIX-only status altogether and run on both
platforms, using `tests/commands.py` for the programs they drive:
`test_expect.py`, `test_misc.py`, `test_isalive.py`,
`test_constructor.py`, `test_env.py`, `test_winsize.py`,
`test_unicode.py`, `test_ctrl_chars.py`, `test_repr.py`, `test_run.py`,
`test_delay.py`, `test_dotall.py`, `test_timeout_pattern.py`,
`test_async.py`.

Six keep a module-level `skipif`, each carrying the reason already
written in `tests/conftest.py`: `test_socket.py` and `test_socket_fd.py`
(`os.fork`), `test_pxssh.py`, `test_replwrap.py` and
`test_popen_spawn.py` (POSIX programs). `test_socket_fd.py` imports
`test_socket`, so it needs its own mark rather than inheriting one.

`tests/integration/` is a directory, and `pytestmark` is a module-level
name, so a per-module mark in each of its ten files would be repetition.
Its own `tests/integration/conftest.py` adds the mark to every item it
collects instead:

```python
def pytest_collection_modifyitems(items):
    if sys.platform == "win32":
        skip = pytest.mark.skip(reason="integration tests drive POSIX programs")
        for item in items:
            item.add_marker(skip)
```

New `tests/test_unsupported.py` asserts that each call in "`spawn`'s
Windows branches" raises `ExceptionPexpect` on Windows and succeeds on
POSIX, and that `fileno()` returns an `int` on both.

`tests/conftest.py`'s `_time_one_child` can now time a real child on
Windows, replacing the branch that returns the floor. `_WINDOWS_COVERAGE_FLOOR`
in `noxfile.py` rises to what CI measures and stays a real gate.

## Documentation

`README.rst:24` and `DEVELOPERS.rst:68` both currently say that pexpect
has no pty support on Windows, and `DEVELOPERS.rst` documents the dropped
modules and the coverage floor. All three passages change, `doc/install.rst`
and `doc/overview.rst` gain the Windows requirements, and `doc/history.rst`
gains an entry.

## Risks

* **Windows cannot be tested locally.** Development happens on Linux
  aarch64, so every Windows claim in this document is proven only by a
  `windows-latest` CI run. The work lands on a branch and iterates
  through pushes; several rounds are expected.
* **ConPTY injects VT sequences a POSIX pty does not** -- cursor queries,
  clear-line, bracketed paste. `expect("hello")` may be presented with
  `\x1b[?25l\x1b[2Jhello`, and `expect_exact` and anchored patterns are
  the exposed ones. This is the largest unknown and can only be measured
  on CI. If it bites, the answer is a documented Windows note, not
  silent scrubbing of the child's output.
* `sendeof`'s Ctrl-Z, Ctrl-C delivery through ConPTY, and EOF timing
  against pywinpty's reader thread are each an assumption until CI
  contradicts them.
* Un-dropping fourteen test modules may surface behaviour differences
  that are neither bugs in this work nor fixable on Windows. Each becomes
  either a documented difference or a Windows skip with a reason, never a
  silently weakened assertion.

## Work order

1. Dependencies, `_ptyproc.py`, `_winpty.py`, and the `__init__.py`
   export. Exit criterion: `pexpect.spawn` imports on Windows and one
   smoke test drives a child end to end.
2. The three seams and the Windows branches, with
   `tests/test_unsupported.py`.
3. `tests/commands.py`, the helper scripts, and the fourteen un-dropped
   modules, iterating on CI.
4. Dual-platform mypy, the coverage floor, and the documentation.
