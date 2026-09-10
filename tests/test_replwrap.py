"""Tests for :mod:`pexpect.replwrap` that start no shell.

Everything that drives a real shell is in ``tests/integration/test_replwrap.py``.
Which shells a machine has and how each one is configured is not something this
suite can settle -- zsh is often not installed at all -- and a shell that has to
reach a prompt costs more than the per-test budget out here allows.

What is left is the part of replwrap that runs before any child does.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import pytest

import pexpect
from pexpect import replwrap

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="drives bash and zsh",
)


class REPLWrapNoShellTestCase(unittest.TestCase):
    """Tests for replwrap paths that raise before a shell is spawned."""

    def test_zsh_reports_a_missing_shell(self) -> None:
        """Report a zsh binary that is not on the path.

        Given a command name that names no executable on the path, so that the
        test does not depend on zsh being installed,
        When :func:`replwrap.zsh` is asked to start it,
        Then :exc:`pexpect.ExceptionPexpect` is raised.
        """
        # A name that matches nothing is the one lookup that walks every PATH
        # entry, so point PATH at a single directory to keep the cost of the
        # test off the length of the developer's PATH.
        with (
            mock.patch.dict(os.environ, {"PATH": str(Path(__file__).parent)}),
            pytest.raises(pexpect.ExceptionPexpect),
        ):
            replwrap.zsh(command="zsh-does-not-exist")


if __name__ == "__main__":
    unittest.main()
