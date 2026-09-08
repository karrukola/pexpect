"""Implementation of coroutines using ``async def``/``await`` keywords.

These keywords replaced ``@asyncio.coroutine`` and ``yield from`` from
Python 3.5 onwards.
"""

from __future__ import annotations

import asyncio
import errno
import signal
from typing import TYPE_CHECKING, cast

from pexpect import EOF

if TYPE_CHECKING:
    from pexpect.expect import Expecter
    from pexpect.replwrap import REPLWrapper

_loop_getter = asyncio.get_running_loop


async def expect_async(expecter: Expecter, timeout: float | None = None) -> int:
    """Wait for one of the expecter's patterns and return its index."""
    # First process data that was previously read - if it maches, we don't need
    # async stuff.
    idx = expecter.existing_data()
    if idx is not None:
        return idx
    if not expecter.spawn.async_pw_transport:
        pattern_waiter = PatternWaiter()
        pattern_waiter.set_expecter(expecter)
        transport, pattern_waiter = await _loop_getter().connect_read_pipe(
            lambda: pattern_waiter, expecter.spawn
        )
        expecter.spawn.async_pw_transport = pattern_waiter, transport
    else:
        pattern_waiter, transport = expecter.spawn.async_pw_transport
        pattern_waiter.set_expecter(expecter)
        transport.resume_reading()
    try:
        return await asyncio.wait_for(pattern_waiter.fut, timeout)
    except asyncio.TimeoutError as exc:
        transport.pause_reading()
        return expecter.timeout(exc)


async def repl_run_command_async(
    repl: REPLWrapper, cmdlines: list[str], timeout: float | None = -1
) -> str:
    """Feed ``cmdlines`` to the REPL one at a time and return its output."""
    # Each _expect_prompt() below matched, so `before` holds the output the
    # child sent ahead of that prompt.
    res: list[str] = []
    repl.child.sendline(cmdlines[0])
    for line in cmdlines[1:]:
        await repl._expect_prompt(timeout=timeout, async_=True)
        res.append(cast("str", repl.child.before))
        repl.child.sendline(line)

    # Command was fully submitted, now wait for the next prompt
    prompt_idx = await repl._expect_prompt(timeout=timeout, async_=True)
    if prompt_idx == 1:
        # We got the continuation prompt - command was incomplete
        repl.child.kill(signal.SIGINT)
        await repl._expect_prompt(timeout=1, async_=True)
        msg = "Continuation prompt found - input was incomplete:"
        raise ValueError(msg)
    return "".join([*res, cast("str", repl.child.before)])


class PatternWaiter(asyncio.Protocol):
    """Resolve a future as soon as the expecter matches the incoming data."""

    transport: asyncio.ReadTransport | None = None

    def set_expecter(self, expecter: Expecter) -> None:
        """Bind this protocol to ``expecter`` and arm a fresh future."""
        self.expecter = expecter
        # Resolved with the index of the pattern that matched.
        self.fut: asyncio.Future[int] = asyncio.Future()

    def found(self, result: int) -> None:
        """Complete the future with the index of the matched pattern."""
        if not self.fut.done():
            self.fut.set_result(result)
            # Nothing can be found before connection_made() has bound the
            # transport that delivers the data.
            cast("asyncio.ReadTransport", self.transport).pause_reading()

    def error(self, exc: BaseException) -> None:
        """Complete the future with an exception."""
        if not self.fut.done():
            self.fut.set_exception(exc)
            cast("asyncio.ReadTransport", self.transport).pause_reading()

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Remember the transport so reading can be paused later."""
        # connect_read_pipe() only ever hands over a read transport, which is
        # narrower than what the protocol API promises here.
        self.transport = cast("asyncio.ReadTransport", transport)

    def data_received(self, data: bytes) -> None:
        """Feed newly read data to the expecter, resolving the future on a match."""
        spawn = self.expecter.spawn
        s = spawn._decoder.decode(data)
        spawn._log(s, "read")

        if self.fut.done():
            spawn._before.write(s)
            spawn._buffer.write(s)
            return

        try:
            index = self.expecter.new_data(s)
            if index is not None:
                # Found a match
                self.found(index)
        # BLE001: any failure must reach the awaited future
        except Exception as exc:  # any failure must reach the awaiter  # noqa: BLE001
            self.expecter.errored()
            self.error(exc)

    def eof_received(self) -> None:
        """Resolve the future with the expecter's end-of-file result."""
        # N.B. If this gets called, async will close the pipe (the spawn object)
        # for us
        try:
            self.expecter.spawn.flag_eof = True
            index = self.expecter.eof()
        except EOF as exc:
            self.error(exc)
        else:
            self.found(index)

    def connection_lost(self, exc: Exception | None) -> None:
        """Treat an EIO error as end-of-file, and report anything else."""
        if isinstance(exc, OSError) and exc.errno == errno.EIO:
            # We may get here without eof_received being called, e.g on Linux
            self.eof_received()
        elif exc is not None:
            self.error(exc)
