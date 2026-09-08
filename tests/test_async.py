"""Tests for awaiting pexpect matches with ``async_=True``.

The two that await a command through a replwrap-wrapped bash are in
``tests/integration/test_async.py``: what they wait on is a shell reaching a
prompt, which is the host's business and not this suite's.
"""

import pytest

import pexpect

from . import pexpect_test_case

pytestmark = pytest.mark.usefixtures("fast_sleep", "lean_child_env", "killed_pty_children")


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
            await p.expect("foo", timeout=0.01, async_=True)

        p = pexpect.spawn("cat")
        assert await p.expect(["foo", pexpect.TIMEOUT], timeout=0.01, async_=True) == 1

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

    async def test_async_and_sync(self) -> None:
        """Interleave awaited and blocking expect_exact calls on one child."""
        p = pexpect.spawn("echo 1234", encoding="utf8", maxread=1)
        assert await p.expect_exact("1", async_=True) == 0
        assert p.expect_exact("2") == 0
        assert await p.expect_exact("3", async_=True) == 0
