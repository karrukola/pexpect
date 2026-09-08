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
"""

from __future__ import annotations

import contextlib
import os
import pathlib
import signal
import time
from typing import TYPE_CHECKING

import pytest
from pytest_time.instant_sleep import InstantSleep

import pexpect
from pexpect import pty_spawn

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

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
# method, for read_nonblocking, read, readline and readlines -- so six is that
# worst case plus half again, and a test that leaks a real sleep or hangs still
# fails rather than passing slowly.
_CHILDREN_PER_TEST = 6

# Never tighter than this, however fast the machine measures. 150 ms is the
# figure the suite was written to, and on the hardware it was written on the
# slowest test took 80 ms; a machine quick enough to beat the floor gains
# nothing from a budget below it.
_BUDGET_FLOOR = 0.15

# How many times to time a child before believing the answer. The smallest is
# taken: a budget should follow what the machine can do, not what it happened to
# be doing while another process had the CPU.
_CALIBRATION_RUNS = 3

# What to spawn to measure one child. `cat` is what most of these tests drive,
# it is on every POSIX system, and it starts without reading a config or an
# interpreter, so it measures the fork/exec/pty floor and not a program.
_CALIBRATION_COMMAND = "cat"


class _YieldingSleep(InstantSleep):
    """Instant sleep that still lets the kernel act on a signal."""

    def sleep(self, secs: float) -> None:
        """Advance the fake clock by ``secs``, yielding if a child may be dying."""
        super().sleep(secs)
        if secs >= _SETTLING_SLEEP:
            self._time.sleep(_YIELD_SECONDS)


def _time_one_child() -> float:
    """Return the seconds one spawn-and-close of ``_CALIBRATION_COMMAND`` took."""
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
            os.kill(ptyproc.pid, signal.SIGKILL)
