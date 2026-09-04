"""Facade re-exporting the coroutine implementation.

``async def``/``await`` are the only supported coroutine flavour, so this
module is a thin re-export of :mod:`pexpect._async_w_await`. It exists so
that ``pexpect._async`` stays an importable name for older code.
"""

from pexpect._async_w_await import PatternWaiter, expect_async, repl_run_command_async

__all__ = ["PatternWaiter", "expect_async", "repl_run_command_async"]
