"""Tests for awaiting a pexpect match on something the host provides.

``test_async_and_gc`` starts a Python child and then runs a full collection
while it is mid-run, which costs more than the suite's time budget; a partial
collection would not be the thing worth testing.

The other two await a command through a replwrap-wrapped bash. What they wait
on is a shell reaching a prompt, and a shell's prompt and startup files belong
to the machine, so they sit with the rest of the REPL tests rather than under a
budget that assumes a plain child process.

The last waits out the one-second timeout run_command allows for a prompt after
the SIGINT it sends, which is above the budget on any machine.
"""

import gc
import unittest

import pytest

import pexpect
from pexpect import replwrap
from tests import pexpect_test_case
from tests.utils import no_editor_repl

pytestmark = pytest.mark.usefixtures("fast_sleep", "lean_child_env")


class AsyncTests(pexpect_test_case.AsyncPexpectTestCase):
    """Tests for expect_exact awaited across a collection."""

    async def test_async_and_gc(self) -> None:
        """Keep an awaited match working across a garbage collection."""
        p = pexpect.spawn(f"{self.PYTHONBIN} sleep_for.py 0.05", encoding="utf8")
        assert await p.expect_exact("READY", async_=True) == 0
        gc.collect()
        assert await p.expect_exact("END", async_=True) == 0


class AsyncREPLWrapTests(pexpect_test_case.AsyncPexpectTestCase):
    """Tests for awaiting a command run through a replwrap-wrapped shell."""

    async def test_async_replwrap(self) -> None:
        """Await a command run through a replwrap-wrapped bash."""
        bash = replwrap.bash()
        res = await bash.run_command("time", async_=True)
        assert "real" in res, res

    async def test_async_replwrap_multiline(self) -> None:
        """Await a multi-line replwrap command, and recover after incomplete input."""
        bash = replwrap.bash()
        res = await bash.run_command("echo '1 2\n3 4'", async_=True)
        assert res.strip().splitlines() == ["1 2", "3 4"]

        # Should raise ValueError if input is incomplete
        try:
            await bash.run_command("echo '5 6", async_=True)
        except ValueError:
            pass
        else:
            msg = "Didn't raise ValueError for incomplete input"
            raise AssertionError(msg)

        # Check that the REPL was reset (SIGINT) after the incomplete input
        res = await bash.run_command("echo '1 2\n3 4'", async_=True)
        assert res.strip().splitlines() == ["1 2", "3 4"]


class AsyncInterruptTests(pexpect_test_case.AsyncPexpectTestCase):
    """Tests for recovering a REPL awaited after incomplete input."""

    async def test_recovers_when_no_prompt_follows_the_signal(self) -> None:
        """Reject incomplete input awaited on a REPL that ignores SIGINT until it reads.

        The synchronous run_command carries its own copy of this recovery; see
        the same case without await in tests/integration/test_replwrap.py.
        """
        repl = no_editor_repl()
        with pytest.raises(ValueError, match="input was incomplete"):
            await repl.run_command("keep going\\", async_=True)
        assert (await repl.run_command("done", async_=True)).strip() == "DONE"


if __name__ == "__main__":
    unittest.main()
