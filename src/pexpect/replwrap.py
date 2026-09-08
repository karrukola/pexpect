"""Generic wrapper for read-eval-print-loops, a.k.a. interactive shells."""

from __future__ import annotations

import os
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast, overload

import pexpect

if TYPE_CHECKING:
    import re
    from collections.abc import Awaitable

PEXPECT_PROMPT = "[PEXPECT_PROMPT>"
PEXPECT_CONTINUATION_PROMPT = "[PEXPECT_PROMPT+"

# The prompt _repl_sh() forces a shell into before it can send anything, and the
# pattern that matches it. Neither shell's own default will do: bash's is
# `\s-\v\$ ` and zsh's is `%m%#`, which render as `bash-5.2$` and `host%` --
# and as `bash-5.2#` and `host#` for root -- so the only prompt both shells can
# be relied on to show is one that was given to them.
_SH_PROMPT = "$"
_SH_PROMPT_PATTERN = r"\$"


class REPLWrapper:
    """Wrapper for a REPL.

    :param cmd_or_spawn: This can either be an instance of :class:`pexpect.spawn`
      in which a REPL has already been started, or a str command to start a new
      REPL process.
    :param str orig_prompt: The prompt to expect at first.
    :param str prompt_change: A command to change the prompt to something more
      unique. If this is ``None``, the prompt will not be changed. This will
      be formatted with the new and continuation prompts as positional
      parameters, so you can use ``{}`` style formatting to insert them into
      the command.
    :param str new_prompt: The more unique prompt to expect after the change.
    :param str extra_init_cmd: Commands to do extra initialisation, such as
      disabling pagers.
    """

    def __init__(
        self,
        cmd_or_spawn: str | pexpect.spawn[str],
        orig_prompt: str | re.Pattern[str],
        prompt_change: str | None,
        new_prompt: str = PEXPECT_PROMPT,
        continuation_prompt: str = PEXPECT_CONTINUATION_PROMPT,
        extra_init_cmd: str | None = None,
    ) -> None:
        """Attach to the REPL, turn echo off and switch it to a unique prompt."""
        if isinstance(cmd_or_spawn, str):
            self.child = pexpect.spawn(
                cmd_or_spawn, echo=False, encoding="utf-8", env={"NO_COLOR": "1"}
            )
        else:
            self.child = cmd_or_spawn
        if self.child.echo:
            # Existing spawn instance has echo enabled, disable it
            # to prevent our input from being repeated to output.
            self.child.setecho(False)
            self.child.waitnoecho()

        if prompt_change is None:
            self.prompt = orig_prompt
        else:
            self.set_prompt(orig_prompt, prompt_change.format(new_prompt, continuation_prompt))
            self.prompt = new_prompt
        self.continuation_prompt = continuation_prompt

        self._expect_prompt()

        if extra_init_cmd is not None:
            self.run_command(extra_init_cmd)

    def set_prompt(self, orig_prompt: str | re.Pattern[str], prompt_change: str) -> None:
        """Wait for ``orig_prompt``, then send the ``prompt_change`` command."""
        self.child.expect(orig_prompt)
        self.child.sendline(prompt_change)

    @overload
    def _expect_prompt(
        self,
        timeout: float | None = -1,
        async_: Literal[False] = False,
    ) -> int: ...

    @overload
    def _expect_prompt(
        self,
        timeout: float | None = -1,
        async_: Literal[True] = ...,
    ) -> Awaitable[int]: ...

    @overload
    def _expect_prompt(
        self,
        timeout: float | None = -1,
        async_: bool = ...,
    ) -> int | Awaitable[int]: ...

    def _expect_prompt(
        self,
        timeout: float | None = -1,
        async_: bool = False,  # mirrors the public `run_command` flag
    ) -> int | Awaitable[int]:
        return self.child.expect_exact(
            [self.prompt, self.continuation_prompt], timeout=timeout, async_=async_
        )

    @overload
    def run_command(
        self,
        command: str,
        timeout: float | None = -1,
        async_: Literal[False] = False,
    ) -> str: ...

    @overload
    def run_command(
        self,
        command: str,
        timeout: float | None = -1,
        async_: Literal[True] = ...,
    ) -> Awaitable[str]: ...

    @overload
    def run_command(
        self,
        command: str,
        timeout: float | None = -1,
        async_: bool = ...,
    ) -> str | Awaitable[str]: ...

    def run_command(
        self,
        command: str,
        timeout: float | None = -1,
        async_: bool = False,  # positional flag is public API
    ) -> str | Awaitable[str]:
        """Send a command to the REPL, wait for and return output.

        :param str command: The command to send. Trailing newlines are not needed.
          This should be a complete block of input that will trigger execution;
          if a continuation prompt is found after sending input, :exc:`ValueError`
          will be raised.
        :param int timeout: How long to wait for the next prompt. -1 means the
          default from the :class:`pexpect.spawn` object (default 30 seconds).
          None means to wait indefinitely.
        :param bool async_: On Python 3.4, or Python 3.3 with asyncio
          installed, passing ``async_=True`` will make this return an
          :mod:`asyncio` Future, which you can yield from to get the same
          result that this method would normally give directly.
        """
        # Split up multiline commands and feed them in bit-by-bit
        cmdlines = command.splitlines()
        # splitlines ignores trailing newlines - add it back in manually
        if command.endswith("\n"):
            cmdlines.append("")
        if not cmdlines:
            msg = "No command was given"
            raise ValueError(msg)

        if async_:
            # Imported lazily so that synchronous use never pulls in asyncio.
            from ._async import repl_run_command_async  # noqa: PLC0415

            return repl_run_command_async(self, cmdlines, timeout)

        # Each _expect_prompt() below matched, so `before` holds the output
        # the child sent ahead of that prompt.
        res: list[str] = []
        self.child.sendline(cmdlines[0])
        for line in cmdlines[1:]:
            self._expect_prompt(timeout=timeout)
            res.append(cast("str", self.child.before))
            self.child.sendline(line)

        # Command was fully submitted, now wait for the next prompt
        if self._expect_prompt(timeout=timeout) == 1:
            # We got the continuation prompt - command was incomplete
            self.child.kill(signal.SIGINT)
            self._expect_prompt(timeout=1)
            raise ValueError("Continuation prompt found - input was incomplete:\n" + command)
        return "".join([*res, cast("str", self.child.before)])


def python(command: str = sys.executable) -> REPLWrapper:
    """Start a Python shell and return a :class:`REPLWrapper` object."""
    return REPLWrapper(command, ">>> ", "import sys; sys.ps1={0!r}; sys.ps2={1!r}")


def _repl_sh(command: str, args: list[str], non_printable_insert: str) -> REPLWrapper:
    # PS1 is forced here rather than left to the shell or to the caller. bash
    # gets the prompt it is matched against from the bundled bashrc.sh, but zsh
    # is started with --no-rcs and so reads no startup file at all; the
    # environment is the only channel left. Without this, _SH_PROMPT_PATTERN
    # never matches zsh's default `%m%#` and zsh waits out the full
    # timeout -- which the test suite used to hide by exporting a PS1 of its own
    # before spawning.
    env = {**os.environ, "PS1": _SH_PROMPT}
    child = pexpect.spawn(command, args, echo=False, encoding="utf-8", env=env)

    # If the user runs 'env', the value of PS1 will be in the output. To avoid
    # replwrap seeing that as the next prompt, we'll embed the marker characters
    # for invisible characters in the prompt; these show up when inspecting the
    # environment variable, but not when bash displays the prompt.
    ps1 = PEXPECT_PROMPT[:5] + non_printable_insert + PEXPECT_PROMPT[5:]
    ps2 = PEXPECT_CONTINUATION_PROMPT[:5] + non_printable_insert + PEXPECT_CONTINUATION_PROMPT[5:]
    prompt_change = f"PS1='{ps1}' PS2='{ps2}' PROMPT_COMMAND=''"

    return REPLWrapper(child, _SH_PROMPT_PATTERN, prompt_change, extra_init_cmd="export PAGER=cat")


def bash(command: str = "bash") -> REPLWrapper:
    """Start a bash shell and return a :class:`REPLWrapper` object."""
    bashrc = Path(__file__).parent / "bashrc.sh"
    return _repl_sh(command, ["--rcfile", str(bashrc)], non_printable_insert="\\[\\]")


def zsh(command: str = "zsh", args: tuple[str, ...] = ("--no-rcs", "-V", "+Z")) -> REPLWrapper:
    """Start a zsh shell and return a :class:`REPLWrapper` object."""
    return _repl_sh(command, list(args), non_printable_insert="%(!..)")
