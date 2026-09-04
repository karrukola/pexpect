"""Tests for the finite state machine calculator in pexpect.FSM."""

import builtins
import io
import sys
import unittest

from pexpect import FSM


class FSMTestCase(unittest.TestCase):
    """Tests for the FSM demo calculator."""

    def test_run_fsm(self) -> None:
        """Feed a postfix expression to FSM.main() and check what it prints."""

        def _input(prompt: str) -> str:  # noqa: ARG001  # signature fixed by builtins.input
            return "167 3 2 2 * * * 1 - ="

        orig_input = builtins.input
        orig_stdout = sys.stdout
        builtins.input = _input
        sys.stdout = sio = io.StringIO()

        try:
            FSM.main()
        finally:
            builtins.input = orig_input
            sys.stdout = orig_stdout

        printed = sio.getvalue()
        assert "2003" in printed, printed


if __name__ == "__main__":
    unittest.main()
