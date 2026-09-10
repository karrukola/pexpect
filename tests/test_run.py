#!/usr/bin/env python
"""PEXPECT LICENSE.

This license is approved by the OSI and FSF as GPL-compatible.
http://opensource.org/licenses/isc-license.txt

Copyright (c) 2012, Noah Spurrier <noah@noah.org>
PERMISSION TO USE, COPY, MODIFY, AND/OR DISTRIBUTE THIS SOFTWARE FOR ANY
PURPOSE WITH OR WITHOUT FEE IS HEREBY GRANTED, PROVIDED THAT THE ABOVE
COPYRIGHT NOTICE AND THIS PERMISSION NOTICE APPEAR IN ALL COPIES.
THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from typing import TYPE_CHECKING, Any

import pytest

import pexpect

from . import commands, pexpect_test_case

if TYPE_CHECKING:
    from collections.abc import Callable

    from pexpect.run import _Events

    # run() hands back bytes and runu() str. The two test classes below share
    # one body, which states the flavour through cr, empty and
    # prep_subprocess_out instead of through the return type.
    _RunFunc = Callable[..., Any]

pytestmark = pytest.mark.usefixtures("fast_sleep", "killed_pty_children")

# stop the child once the TIMEOUT callback has fired more often than this
_MAX_TIMEOUT_EVENTS = 3


def timeout_callback(values: dict[str, Any]) -> int:
    """Return truthy to stop run() once TIMEOUT has fired often enough."""
    if values["event_count"] > _MAX_TIMEOUT_EVENTS:
        return 1
    return 0


def function_events_callback(values: dict[str, Any]) -> str | None:
    """Drive the shell through three echo stages by looking at what it last echoed."""
    try:
        previous_echoed = values["child_result_list"][-1].decode().split("\n")[-2].strip()
        if previous_echoed.endswith("stage-1"):
            return "echo stage-2\n"
        if previous_echoed.endswith("stage-2"):
            return "echo stage-3\n"
        if previous_echoed.endswith("stage-3"):
            return "exit\n"
        msg = f"Unexpected output {previous_echoed}"
        raise ValueError(msg)
    except IndexError:
        return "echo stage-1\n"


class RunFuncTestCase(pexpect_test_case.PexpectTestCase):
    """Exercise pexpect.run(), its exit status and its events argument."""

    if sys.platform != "win32":
        runfunc: _RunFunc = staticmethod(pexpect.run)
    cr: str | bytes = b"\r"
    empty: str | bytes = b""
    prep_subprocess_out = staticmethod(lambda x: x)

    def setUp(self) -> None:
        """Build an environment with a predictable shell prompt of "GO:"."""
        self.runenv = os.environ.copy()
        self.runenv["PS1"] = "GO:"
        super().setUp()

    def test_run_exit(self) -> None:
        """Report the child's non-zero exit status when withexitstatus is set."""
        (_data, exitstatus) = self.runfunc(sys.executable + " exit1.py", withexitstatus=True)
        assert exitstatus == 1, "Exit status of 'python exit1.py' should be 1."

    @pytest.mark.skipif(sys.platform == "win32", reason="needs the POSIX program `uname`")
    def test_run(self) -> None:
        """run() collects the same output as subprocess, minus the pty carriage returns."""
        the_old_way = (
            subprocess.Popen(
                args=["uname", "-m", "-n"],  # noqa: S607  # PATH lookup of uname is the point
                stdout=subprocess.PIPE,
            )
            .communicate()[0]
            .rstrip()
        )

        (the_new_way, exitstatus) = self.runfunc("uname -m -n", withexitstatus=True)
        the_new_way = the_new_way.replace(self.cr, self.empty).rstrip()

        assert self.prep_subprocess_out(the_old_way) == the_new_way
        assert exitstatus == 0

    @pytest.mark.skipif(sys.platform == "win32", reason="needs the POSIX program `uname`")
    def test_run_with_the_default_spawn_timeout(self) -> None:
        """Run a command without overriding the spawn timeout.

        Given a timeout of -1, which run() documents as meaning "leave the
        spawn default in place",
        When :func:`pexpect.run` executes a command,
        Then the command runs to completion and its output is returned.
        """
        output = self.runfunc("uname -m -n", timeout=-1)
        assert output.replace(self.cr, self.empty).rstrip()

    def test_run_callback(self) -> None:
        """A TIMEOUT event callback can stop a child that never exits."""
        # TODO it seems like this test could block forever if run fails...
        events: _Events = {pexpect.TIMEOUT: timeout_callback}
        self.runfunc(commands.CAT, timeout=0.01, events=events)

    @pytest.mark.skipif(sys.platform == "win32", reason="needs the POSIX program `ls`")
    def test_run_bad_exitstatus(self) -> None:
        """A failing command reports a non-zero exit status."""
        (_the_new_way, exitstatus) = self.runfunc("ls -l /najoeufhdnzkxjd", withexitstatus=True)
        assert exitstatus != 0

    def test_run_event_as_string(self) -> None:
        """An event response may be a plain string to send to the child."""
        events: _Events = [
            # second match on 'abc', echo 'def'
            ("abc\r\n.*GO:", 'echo "def"\n'),
            # final match on 'def': exit
            ("def\r\n.*GO:", "exit\n"),
            # first match on 'GO:' prompt, echo 'abc'
            ("GO:", 'echo "abc"\n'),
        ]

        (_data, exitstatus) = pexpect.run(
            "bash --norc", withexitstatus=True, events=events, env=self.runenv, timeout=10
        )
        assert exitstatus == 0

    def test_run_event_as_function(self) -> None:
        """An event response may be a module-level function."""
        events: _Events = [("GO:", function_events_callback)]

        (_data, exitstatus) = pexpect.run(
            "bash --norc", withexitstatus=True, events=events, env=self.runenv, timeout=10
        )
        assert exitstatus == 0

    def test_run_event_as_method(self) -> None:
        """An event response may be a bound method."""
        events: _Events = [("GO:", self._method_events_callback)]

        (_data, exitstatus) = pexpect.run(
            "bash --norc", withexitstatus=True, events=events, env=self.runenv, timeout=10
        )
        assert exitstatus == 0

    def test_run_event_typeerror(self) -> None:
        """An event response that is neither string nor callable raises TypeError."""
        events = [("GO:", -1)]
        # -1 is not a response run() accepts, which is the point of the test, so
        # the call goes through a name that does not describe what run() takes.
        runner: Callable[..., object] = pexpect.run
        with pytest.raises(TypeError):
            runner("bash --norc", withexitstatus=True, events=events, env=self.runenv, timeout=10)

    def _method_events_callback(self, values: dict[str, Any]) -> str | None:
        """Drive the shell through three echo stages, as a bound method."""
        try:
            previous_echoed = values["child_result_list"][-1].decode().split("\n")[-2].strip()
            if previous_echoed.endswith("foo1"):
                return "echo foo2\n"
            if previous_echoed.endswith("foo2"):
                return "echo foo3\n"
            if previous_echoed.endswith("foo3"):
                return "exit\n"
            msg = f"Unexpected output {previous_echoed!r}"
            raise ValueError(msg)
        except IndexError:
            return "echo foo1\n"


class RunUnicodeFuncTestCase(RunFuncTestCase):
    """Repeat the run() tests through runu(), which works in text mode."""

    if sys.platform != "win32":
        runfunc = staticmethod(pexpect.runu)
    cr = b"\r".decode("ascii")
    empty = b"".decode("ascii")
    prep_subprocess_out = staticmethod(lambda x: x.decode("utf-8", "replace"))

    def test_run_unicode(self) -> None:
        """runu() returns str and round-trips a non-ASCII character."""
        char = chr(254)  # þ
        pattern = "<in >"

        def callback(values: dict[str, Any]) -> str | bool:
            if values["event_count"] == 0:
                return char + "\n"
            return True  # Stop the child process

        output = pexpect.runu(
            self.PYTHONBIN + " echo_w_prompt.py",
            env={"PYTHONIOENCODING": "utf-8"},
            events={pattern: callback},
        )
        assert isinstance(output, str), type(output)
        assert ("<out>" + char) in output, output


if __name__ == "__main__":
    unittest.main()
