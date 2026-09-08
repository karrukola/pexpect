"""A stand-in for a REPL whose line editor is off, spawned by the replwrap tests.

zsh is started with NO_ZLE, and a shell in that state does not abandon a partly
entered command when SIGINT arrives: it records the signal and acts on it only
when it next reads from the terminal, printing nothing at all until then. That
is the case ``REPLWrapper.run_command`` follows its SIGINT with a newline for.

Reproducing it here rather than driving a real zsh keeps that recovery reachable
on a machine with no zsh installed, which is most of them -- otherwise the branch
would be covered only where the suite's optional shell happens to be present.

A line ending in a backslash is treated as incomplete; anything else is a
command, answered in upper case.
"""

from __future__ import annotations

import signal
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import FrameType

PROMPT = "[STANDIN_PROMPT>"
CONTINUATION = "[STANDIN_PROMPT+"

# A list rather than a module-level name rebound from the handler, which would
# need `global`.
_interrupted = [False]


def _remember(_signum: int, _frame: FrameType | None) -> None:
    """Record the signal and return, printing nothing, as a shell with no editor does."""
    _interrupted[0] = True


def _write(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


signal.signal(signal.SIGINT, _remember)
_write(PROMPT)

while True:
    line = sys.stdin.readline()
    if not line:
        break
    if _interrupted[0]:
        # The read that got here is what makes the signal take effect. Drop the
        # line along with whatever was pending and start a fresh prompt.
        _interrupted[0] = False
        _write(PROMPT)
    elif line.rstrip("\r\n").endswith("\\"):
        _write(CONTINUATION)
    else:
        _write(line.rstrip("\r\n").upper() + "\r\n" + PROMPT)
