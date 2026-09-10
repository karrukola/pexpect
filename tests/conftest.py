"""Fixtures the test modules of this suite opt into.

None of them are autouse: a module asks for what it needs with a module-level

    pytestmark = pytest.mark.usefixtures("fast_sleep", "killed_pty_children")

which also works for the ``unittest.TestCase`` subclasses this suite is built
from. A module that drives no child process asks for nothing.

Two things in pexpect spend real time, and they need different treatment.

The first is ``time.sleep``. ``pytest_time.InstantSleep`` replaces it with a
clock offset, which is right for the sleeps that only pace writes and reads, and
wrong for the ones that follow a signal: no amount of clock offset will reap a
process, so ``terminate()`` would run through SIGHUP, SIGCONT, SIGINT and
SIGKILL faster than the child could exit and ``close()`` would raise "Could not
terminate the child". Those get a slice of real time; see ``fast_sleep``.

The second is the garbage collector. A spawn that a test simply drops is closed
by its ``__del__`` whenever the collector reaches it, which is typically during
some later test, so the signals and settling delays of one test's teardown are
charged to another test's budget. ``killed_pty_children`` closes that gap.

What neither of them can reach is the child process itself. ``spawn`` execs it,
and no monkeypatching survives an exec, so what a test outside tests/integration
costs is however long this machine takes to fork a pty, exec a program into it
and reap it, once per child. That figure is hardware, not something the suite
can choose, and it is why the per-test budget is measured here rather than
written down: see ``pytest_collection_modifyitems``.

What that measurement in turn cannot see is the cost of the code running in
this process, because the child it times is exec'd and so escapes the coverage
tracer the tests themselves run under. The tests that spend their time here
rather than in a child are budgeted by the floor instead; see
``_BUDGET_FLOOR``.
"""

from __future__ import annotations

import contextlib
import os
import pathlib
import signal
import sys
import time
from typing import TYPE_CHECKING

import pytest
from pytest_time.instant_sleep import InstantSleep

import pexpect

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

# pexpect's pty API is no longer POSIX-only: `pty_spawn` picks a backend --
# `ptyprocess` on POSIX, `pexpect._winpty` over ConPTY on Windows -- and
# `pexpect.spawn` is exported from `__init__` on every platform. What is still
# platform-specific is which *programs* the suite can drive: most of this
# suite reaches for POSIX ones like `cat`, `echo` and a shell, which is why
# most of the modules named below are dropped at collection on Windows rather
# than skipped at runtime -- see _POSIX_ONLY.
from pexpect import pty_spawn

_ON_POSIX = sys.platform != "win32"

# SIGKILL is POSIX; on Windows os.kill() with SIGTERM is TerminateProcess,
# which is the same "cannot be caught" contract. Written as a platform `if`
# rather than a conditional expression because that is the form mypy
# narrows: under --platform win32, signal.SIGKILL does not exist and a
# ternary would not be excused.
if sys.platform == "win32":
    _HARD_KILL = signal.SIGTERM
else:
    _HARD_KILL = signal.SIGKILL

# tests/integration budgets itself; see pytest_collection_modifyitems below.
_SLOW_DIR = pathlib.Path(__file__).parent / "integration"

# Sleeps at least this long are the ones that follow a signal: pexpect and
# ptyprocess both settle on 0.1 s for delayafterclose and delayafterterminate.
# Shorter ones pace writes and reads (delaybeforesend is 0.05, delayafterread
# 0.0001) and nothing outside this process is waiting on them.
_SETTLING_SLEEP = 0.1

# Real seconds handed to the OS in place of a settling sleep, whatever length was
# asked for. Only the tests that call close() on a live child pay it, and usually
# once: terminate() stops at the first signal the child honours. Four in a row,
# the worst case, still fits the budget, and killed_pty_children keeps every other
# test from paying anything at all.
_YIELD_SECONDS = 0.01


# The per-test budget is this many child processes' worth of time. The most any
# one test outside tests/integration drives is four -- test_misc's
# test_read_after_close_raises_value_error spawns and closes `cat` once per read
# method, for read_nonblocking, read, readline and readlines.
#
# Twelve is that worst case with room for a stall, and the room is the point.
# Measured over six runs on an aarch64 SBC, against a budget of six: that test
# came out at 67% to 74% of it every time and no other test passed 25%. A
# margin of a third over the worst legitimate test reads as ample and is not,
# because the budget is a wall clock and the machine is shared -- one run in
# twenty lost test_spawn_refuses_to_start_a_second_child, which normally takes
# 0.35 s, to a stall that pushed it past 1.79 s. Widening costs nothing that
# matters: a test that hangs waits either forever or on pexpect's own 30 s
# default, so it is caught at any budget in this range, and only the hanging
# test pays the extra wait.
_CHILDREN_PER_TEST = 12

# Never tighter than this, however fast the machine measures. The floor is what
# budgets the tests the calibration cannot see. It times an exec'd child, which
# coverage does not trace, while every test it budgets runs in the traced
# parent, and tracing costs about ten times what an untraced line costs: on the
# machine this was measured on, the calibration child came out at 16.5 ms bare
# and 18.1 ms under `coverage run`, a tenth dearer, while test_ansi.py's
# test_torturet -- which drives no child at all -- went from 14 ms to 230 ms.
# Against a budget of 12 x 19.5 ms that test lost about one full-suite run in
# eight, as did test_ctrl_chars.py's test_control_chars at the same 230 ms. The
# Windows pass met the same thing from the other side and said so in `464aa4d`:
# the floor was what the non-POSIX branch above used to return, and 150 ms is
# tighter than any machine earns once the tracer is counted.
#
# Every nox test session runs `coverage run -m pytest`, so that is the regime to
# budget for, and a second is four times the slowest test measured in it. A
# machine quick enough for this to bind is one whose children are cheap; on a
# slow one -- 290 ms a child, so a budget of 3.5 s -- it never binds. What it
# costs is that a test which hangs waits a second rather than 150 ms to be
# killed, and 150 ms was never what caught it: a hang waits either forever or
# on pexpect's own 30 s default.
_BUDGET_FLOOR = 1.0

# How many times to time a child before believing the answer. The smallest is
# taken: a budget should follow what the machine can do, not what it happened to
# be doing while another process had the CPU.
_CALIBRATION_RUNS = 3

# What to spawn to measure one child. `cat` is what most of these tests drive,
# it is on every POSIX system, and it starts without reading a config or an
# interpreter, so it measures the fork/exec/pty floor and not a program.
_CALIBRATION_COMMAND = "cat"


# The modules of this suite that cannot run on Windows, dropped at collection
# rather than skipped test by test: most of them raise while being imported,
# and a skip mark never runs when the module that carries it cannot be
# imported. Three reasons, in order:
#
# * The pty API, driven directly or through replwrap, run or pxssh.
#   `pexpect.pty_spawn` imports `pty`, which imports `termios`, and
#   `pexpect.spawn` is exported from `__init__` behind the same platform check.
#   tests/integration is all of this.
# * `os.fork`, which `test_socket` needs to put its socket server in a
#   subprocess -- the server is a bound method of the test case, which the
#   spawn start method cannot carry -- and `test_socket_fd` runs that same
#   suite over a file descriptor.
# * The POSIX programs `test_popen_spawn` drives: `cat`, `echo`, `sleep`,
#   `ls -l /bin`, plus SIGKILL and SIGTERM delivery. `PopenSpawn` itself is the
#   class pexpect offers on Windows and works there; what its tests reach for
#   does not.
#
# What is left covers the rest of what pexpect supports on Windows: fdspawn,
# SocketSpawn, the searchers, the screen emulation and the FSM.
_POSIX_ONLY = (
    "integration",
    "test_async.py",
    "test_constructor.py",
    "test_ctrl_chars.py",
    "test_delay.py",
    "test_dotall.py",
    "test_env.py",
    "test_expect.py",
    "test_isalive.py",
    "test_log.py",
    "test_misc.py",
    "test_missing_command.py",
    "test_popen_spawn.py",
    "test_pxssh.py",
    "test_replwrap.py",
    "test_repr.py",
    "test_run.py",
    "test_socket.py",
    "test_socket_fd.py",
    "test_timeout_pattern.py",
    "test_unicode.py",
    "test_winsize.py",
)

if not _ON_POSIX:
    collect_ignore = list(_POSIX_ONLY)


class _YieldingSleep(InstantSleep):
    """Instant sleep that still lets the kernel act on a signal."""

    def sleep(self, secs: float) -> None:
        """Advance the fake clock by ``secs``, yielding if a child may be dying."""
        super().sleep(secs)
        if secs >= _SETTLING_SLEEP:
            self._time.sleep(_YIELD_SECONDS)


def _time_one_child() -> float:
    """Return the seconds one spawn-and-close of a child process took."""
    started = time.perf_counter()
    child = pty_spawn.spawn(_CALIBRATION_COMMAND)
    child.close()
    return time.perf_counter() - started


def _measured_budget() -> float:
    """Return the per-test time budget this machine has earned, in seconds.

    A test outside tests/integration costs one or more child processes plus its
    own logic, and the child is the part that cannot be faked away, so the
    budget is stated in children and the cost of one is measured here. The
    measurement runs under the same sleep regime the tests do -- see
    ``fast_sleep`` -- because otherwise it would be timing pexpect's settling
    delays, which no test outside that directory ever pays in full.
    """
    with pytest.MonkeyPatch.context() as patcher:
        _YieldingSleep().install(patcher)
        try:
            cost = min(_time_one_child() for _ in range(_CALIBRATION_RUNS))
        except (OSError, pexpect.ExceptionPexpect):
            # No child could be started at all, which every test here is about
            # to report far more clearly than a timeout would.
            return _BUDGET_FLOOR
    return max(_BUDGET_FLOOR, _CHILDREN_PER_TEST * cost)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Give every test outside tests/integration a budget scaled to this machine.

    tests/integration sets its own, generous budget from its own conftest, and
    is skipped here rather than being marked twice: which of two markers on one
    item ``pytest-timeout`` reads is not something to depend on.
    """
    timed = [item for item in items if _SLOW_DIR not in item.path.parents]
    if not timed:
        return
    budget = _measured_budget()
    for item in timed:
        item.add_marker(pytest.mark.timeout(budget))


@pytest.fixture
def fast_sleep(monkeypatch: pytest.MonkeyPatch) -> _YieldingSleep:
    """Skip through every ``time.sleep`` call made by the test or by pexpect."""
    sleep = _YieldingSleep()
    sleep.install(monkeypatch)
    return sleep


@pytest.fixture
def lean_child_env(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    """Keep the children a module spawns off the developer's machine and out of pyrepl.

    replwrap sources ~/.bashrc so that a wrapped bash behaves like the user's
    own; under test that means every spawned bash pays for whatever is in it,
    which on a well-furnished account is close to a second.

    Since 3.13 an interactive Python builds a full-screen editor before it shows
    a prompt, which doubles the startup of every REPL a test drives. Nothing here
    tests pyrepl; the tests drive the line protocol, which both REPLs share.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PYTHON_BASIC_REPL", "1")


@pytest.fixture
def killed_pty_children(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Kill the pty children a test leaves running, rather than leaving it to gc.

    A dropped spawn is closed by ptyprocess's ``__del__`` whenever the collector
    reaches it, which is usually during a later test, and that close signals the
    child and sleeps between signals. Killing here charges the wait to the test
    that started the child, and it costs nothing: ``terminate()`` finds the child
    already gone on its first ``isalive()`` and never reaches a sleep.

    Reaping is left to that close. ``waitpid`` here would take the child away
    from ptyprocess, whose ``isalive()`` raises when someone else has reaped it.

    Only the modules under a time budget ask for this. It keeps a reference to
    every spawn until the test ends, so a test that asserts anything about the
    collector -- ``tests/integration/test_destructor.py`` -- would never see its
    spawns collected, and SIGKILL would cut short a child that is writing its own
    coverage data.
    """
    children: list[pty_spawn.spawn] = []
    # Annotating the target is what lets record() forward whatever arguments the
    # test passed: an overloaded __init__ cannot be called with *args/**kwargs.
    spawn_init: Callable[..., None] = pty_spawn.spawn.__init__

    def record(self: pty_spawn.spawn, *args: object, **kwargs: object) -> None:
        spawn_init(self, *args, **kwargs)
        children.append(self)

    monkeypatch.setattr(pty_spawn.spawn, "__init__", record)
    yield
    for child in children:
        # No ptyproc means the spawn never started a child, and `terminated`
        # means pexpect has already reaped it: signalling a reaped pid would
        # land on whatever process the kernel has since given the number to.
        ptyproc = getattr(child, "ptyproc", None)
        if ptyproc is None or ptyproc.terminated:
            continue
        with contextlib.suppress(OSError):
            os.kill(ptyproc.pid, _HARD_KILL)
