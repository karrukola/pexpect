"""Tests for awaiting pexpect matches with ``async_=True``."""

try:
    import asyncio
except ImportError:
    asyncio = None

import gc
import unittest

import pytest

import pexpect
from pexpect import replwrap

from . import pexpect_test_case


@unittest.skipIf(asyncio is None, "Requires asyncio")
class AsyncTests(pexpect_test_case.AsyncPexpectTestCase):
    """Tests for expect and expect_exact awaited as coroutines."""

    async def test_simple_expect(self) -> None:
        """Await a pattern match on a ``cat`` child."""
        p = pexpect.spawn("cat")
        p.sendline("Hello asyncio")
        assert await p.expect(["Hello", pexpect.EOF], async_=True) == 0
        print("Done")

    async def test_timeout(self) -> None:
        """Raise TIMEOUT when awaiting, or match it from a pattern list."""
        p = pexpect.spawn("cat")
        with pytest.raises(pexpect.TIMEOUT):
            await p.expect("foo", timeout=1, async_=True)

        p = pexpect.spawn("cat")
        assert await p.expect(["foo", pexpect.TIMEOUT], timeout=1, async_=True) == 1

    async def test_eof(self) -> None:
        """Match EOF when it is expected, and raise it when it is not."""
        p = pexpect.spawn("cat")
        p.sendline("Hi")
        p.sendeof()
        assert await p.expect(pexpect.EOF, async_=True) == 0

        p = pexpect.spawn("cat")
        p.sendeof()
        with pytest.raises(pexpect.EOF):
            await p.expect("Blah", async_=True)

    async def test_expect_exact(self) -> None:
        """Await literal byte matches, given singly and in a pattern list."""
        p = pexpect.spawn(f"{self.PYTHONBIN} list100.py")
        assert await p.expect_exact(b"5", async_=True) == 0
        assert await p.expect_exact(["wpeok", b"11"], async_=True) == 1
        assert await p.expect_exact([b"foo", pexpect.EOF], async_=True) == 1

    async def test_async_utf8(self) -> None:
        """Await literal matches on a child whose output is decoded as utf8."""
        p = pexpect.spawn(f"{self.PYTHONBIN} list100.py", encoding="utf8")
        assert await p.expect_exact("5", async_=True) == 0
        assert await p.expect_exact(["wpeok", "11"], async_=True) == 1
        assert await p.expect_exact(["foo", pexpect.EOF], async_=True) == 1

    async def test_async_and_gc(self) -> None:
        """Keep an awaited match working across a garbage collection."""
        p = pexpect.spawn(f"{self.PYTHONBIN} sleep_for.py 1", encoding="utf8")
        assert await p.expect_exact("READY", async_=True) == 0
        gc.collect()
        assert await p.expect_exact("END", async_=True) == 0

    async def test_async_and_sync(self) -> None:
        """Interleave awaited and blocking expect_exact calls on one child."""
        p = pexpect.spawn("echo 1234", encoding="utf8", maxread=1)
        assert await p.expect_exact("1", async_=True) == 0
        assert p.expect_exact("2") == 0
        assert await p.expect_exact("3", async_=True) == 0

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
