"""The programs this suite drives, named once and resolved per platform.

POSIX has cat, echo, sleep and true; Windows has none of them, so each resolves
to a Python stand-in under tests/helpers/ run by the current interpreter. Every
name here is a command string rather than an argument list, because that is the
form pexpect.spawn() and pexpect.run() share -- run()'s second positional
parameter is a timeout, so a test cannot splat a pair into it.

Paths are written with forward slashes. pexpect splits a command string with
pexpect.utils.split_command_line, which treats a backslash as an escape, so a
Windows path in its native spelling would lose its separators.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ON_WINDOWS = sys.platform == "win32"
_HELPERS = Path(__file__).parent / "helpers"
_PYTHON = Path(sys.executable).as_posix()


def _helper(name: str) -> str:
    """Return the command that runs the stand-in *name* under this interpreter."""
    return f"{_PYTHON} {(_HELPERS / name).as_posix()}"


CAT = _helper("cat.py") if _ON_WINDOWS else "cat"
TRUE = _helper("true.py") if _ON_WINDOWS else "true"


def echo(text: str = "") -> str:
    """Return a command that prints *text* and a newline."""
    if _ON_WINDOWS:
        return f"{_helper('echo.py')} {text}" if text else _helper("echo.py")
    return f"echo {text}" if text else "echo"


def sleep(seconds: float) -> str:
    """Return a command that sleeps for *seconds* and exits."""
    return f"{_helper('sleep.py')} {seconds}" if _ON_WINDOWS else f"sleep {seconds}"
