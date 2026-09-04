"""Tests for the finite state machine calculator in pexpect.FSM."""

import builtins
import io
import sys
import unittest

import pytest

from pexpect import FSM


def _run_main(expression: str) -> str:
    """Run :func:`FSM.main` on ``expression`` and return everything it printed."""

    def _input(prompt: str) -> str:  # noqa: ARG001  # signature fixed by builtins.input
        return expression

    orig_input = builtins.input
    orig_stdout = sys.stdout
    builtins.input = _input
    sys.stdout = sio = io.StringIO()

    try:
        FSM.main()
    finally:
        builtins.input = orig_input
        sys.stdout = orig_stdout

    return sio.getvalue()


class FSMTestCase(unittest.TestCase):
    """Tests for the FSM demo calculator."""

    def test_run_fsm(self) -> None:
        """Feed a postfix expression to FSM.main() and check what it prints."""
        printed = _run_main("167 3 2 2 * * * 1 - =")
        assert "2003" in printed, printed

    def test_addition_and_division(self) -> None:
        """Evaluate the two operators the multiplying expression does not use.

        Given the FSM demo calculator,
        When an expression using '+' and one using '/' are evaluated,
        Then the sum and the quotient are printed.
        """
        assert "3" in _run_main("1 2 + =")
        assert "2.0" in _run_main("8 4 / =")

    def test_unaccepted_input_reports_an_error(self) -> None:
        """Report input the example grammar does not accept.

        Given the FSM demo calculator, whose default transition is the Error
        action,
        When a letter arrives while a number is being built, a combination no
        explicit transition covers,
        Then the default transition runs and the offending symbol is reported.
        """
        printed = _run_main("1a")
        assert "That does not compute." in printed, printed
        assert "\na\n" in printed, printed

    def test_transitions_default_to_the_current_state(self) -> None:
        """Stay in the current state when a transition omits its next state.

        Given a machine whose exact, list and catch-all transitions are all
        added without a next state,
        When the symbols of those transitions are processed,
        Then the machine stays in the state the transition was added for.
        """
        f = FSM.FSM("INIT")
        f.add_transition("a", "INIT")
        f.add_transition_list("bc", "INIT")
        f.add_transition_any("OTHER")

        f.process_list("abc")
        assert f.current_state == "INIT"

        f.current_state = "OTHER"
        f.process("z")
        assert f.current_state == "OTHER"

    def test_reset(self) -> None:
        """Return the machine to the state it was constructed with.

        Given a machine that moved from its initial state to another one,
        When :meth:`FSM.FSM.reset` is called,
        Then the current state is the initial state again and the last input
        symbol is forgotten.
        """
        f = FSM.FSM("INIT")
        f.add_transition("a", "INIT", None, "SECOND")
        f.process("a")
        assert f.current_state == "SECOND"

        f.reset()
        assert f.current_state == "INIT"
        assert f.input_symbol is None

    def test_undefined_transition_raises(self) -> None:
        """Refuse an input symbol that no transition and no default cover.

        Given a machine with a single transition and no default transition,
        When a symbol that transition does not cover is processed,
        Then :exc:`FSM.ExceptionFSM` is raised, reporting the symbol and state.
        """
        f = FSM.FSM("INIT")
        f.add_transition("a", "INIT", None, "INIT")

        with pytest.raises(FSM.ExceptionFSM) as excinfo:
            f.process("z")

        assert str(excinfo.value) == "ExceptionFSM: Transition is undefined: (z, INIT)."
        assert excinfo.value.value == "Transition is undefined: (z, INIT)."

    def test_unsupported_operator_pushes_nothing(self) -> None:
        """Drop the operands when the operator is not one of the four supported.

        Given a machine whose memory stack holds two operands and whose input
        symbol is an operator the calculator does not implement,
        When :func:`FSM.DoOperator` runs,
        Then both operands are popped and no result is pushed.
        """
        f = FSM.FSM("INIT", [1, 2])
        f.input_symbol = "%"

        FSM.DoOperator(f)

        assert f.memory == []


if __name__ == "__main__":
    unittest.main()
