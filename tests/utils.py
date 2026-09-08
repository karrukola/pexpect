"""Helpers shared by the test modules and the programs they spawn."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pexpect
from pexpect import replwrap


def no_coverage_env() -> dict[str, str]:
    """Return a copy of os.environ that won't trigger coverage measurement."""
    env = os.environ.copy()
    env.pop("COV_CORE_SOURCE", None)
    return env


def no_editor_repl() -> replwrap.REPLWrapper:
    """Wrap tests/no_editor_repl.py, which answers SIGINT the way NO_ZLE zsh does.

    Used by the sync and async tests of the incomplete-input recovery, so that
    the path taken when a shell prints no prompt after the signal is exercised
    whether or not this machine has a zsh. The prompt is passed rather than
    changed: the stand-in has no PS1 to set.
    """
    script = Path(__file__).parent / "no_editor_repl.py"
    child = pexpect.spawn(sys.executable, [str(script)], echo=False, encoding="utf-8", timeout=5)
    return replwrap.REPLWrapper(
        child,
        "[STANDIN_PROMPT>",
        prompt_change=None,
        continuation_prompt="[STANDIN_PROMPT+",
    )
