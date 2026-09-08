#!/usr/bin/env python

"""Finite State Machine (FSM) implementation.

In addition to state this FSM also maintains a user defined "memory". So this
FSM can be used as a Push-down Automata (PDA) since a PDA is a FSM + memory.

The following describes how the FSM works, but you will probably also need to
see the example function to understand how the FSM is used in practice.

You define an FSM by building tables of transitions. For a given input symbol
the process() method uses these tables to decide what action to call and what
the next state will be. The FSM has a table of transitions that associate:

        (input_symbol, current_state) --> (action, next_state)

Where "action" is a function you define. The symbols and states can be any
objects. You use the add_transition() and add_transition_list() methods to add
to the transition table. The FSM also has a table of transitions that
associate:

        (current_state) --> (action, next_state)

You use the add_transition_any() method to add to this transition table. The
FSM also has one default transition that is not associated with any specific
input_symbol or state. You use the set_default_transition() method to set the
default transition.

When an action function is called it is passed a reference to the FSM. The
action function may then access attributes of the FSM such as input_symbol,
current_state, or "memory". The "memory" attribute can be any object that you
want to pass along to the action functions. It is not used by the FSM itself.
For parsing you would typically pass a list to be used as a stack.

The processing sequence is as follows. The process() method is given an
input_symbol to process. The FSM will search the table of transitions that
associate:

        (input_symbol, current_state) --> (action, next_state)

If the pair (input_symbol, current_state) is found then process() will call the
associated action function and then set the current state to the next_state.

If the FSM cannot find a match for (input_symbol, current_state) it will then
search the table of transitions that associate:

        (current_state) --> (action, next_state)

If the current_state is found then the process() method will call the
associated action function and then set the current state to the next_state.
Notice that this table lacks an input_symbol. It lets you define transitions
for a current_state and ANY input_symbol. Hence, it is called the "any" table.
Remember, it is always checked after first searching the table for a specific
(input_symbol, current_state).

For the case where the FSM did not match either of the previous two cases the
FSM will try to use the default transition. If the default transition is
defined then the process() method will call the associated action function and
then set the current state to the next_state. This lets you define a default
transition as a catch-all case. You can think of it as an exception handler.
There can be only one default transition.

Finally, if none of the previous cases are defined for an input_symbol and
current_state then the FSM will raise an exception. This may be desirable, but
you can always prevent this just by defining a default transition.

Noah Spurrier 20020822

PEXPECT LICENSE

    This license is approved by the OSI and FSF as GPL-compatible.
        http://opensource.org/licenses/isc-license.txt

    Copyright (c) 2012, Noah Spurrier <noah@noah.org>
    PERMISSION TO USE, COPY, MODIFY, AND/OR DISTRIBUTE THIS SOFTWARE FOR ANY
    PURPOSE WITH OR WITHOUT FEE IS HEREBY GRANTED, PROVIDED THAT THE ABOVE
    COPYRIGHT NOTICE AND THIS PERMISSION NOTICE APPEAR IN ALL COPIES.
    THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
    WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
    MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
    ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
    WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
    ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
    OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

"""

from __future__ import annotations

import string
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    # An action callback is handed the FSM it belongs to and returns nothing.
    _Action = Callable[["FSM"], None]
    # What both transition tables hold: the action to call and the state to
    # move to once it has run.
    _Transition = tuple[_Action | None, object]


class ExceptionFSM(Exception):
    """Raised when the FSM has no transition for the current input and state."""

    def __init__(self, value: object) -> None:
        """Store ``value`` as the detail reported by ``str()``."""
        self.value = value

    def __str__(self) -> str:
        """Return the detail value prefixed with the exception name."""
        return "ExceptionFSM: " + str(self.value)


class FSM:
    """Finite State Machine with a user defined "memory"."""

    def __init__(self, initial_state: object, memory: list[Any] | None = None) -> None:
        """Create the FSM with its initial state.

        The "memory" attribute is any object that you want to pass along to the
        action functions. It is not used by the FSM. For parsing you would
        typically pass a list to be used as a stack.
        """
        # Map (input_symbol, current_state) --> (action, next_state).
        self.state_transitions: dict[tuple[object, object], _Transition] = {}
        # Map (current_state) --> (action, next_state).
        self.state_transitions_any: dict[object, _Transition] = {}
        self.default_transition: _Transition | None = None

        self.input_symbol: object | None = None
        self.initial_state = initial_state
        self.current_state = self.initial_state
        self.next_state: object | None = None
        self.action: _Action | None = None
        # Declared as the stack every action callback uses, even though the
        # constructor's default leaves it None: an FSM built without a memory
        # has never supported the action callbacks that reach for it.
        self.memory: list[Any] = cast("list[Any]", memory)

    def reset(self) -> None:
        """Set current_state back to initial_state and input_symbol to None.

        The initial state was set by the constructor __init__().
        """
        self.current_state = self.initial_state
        self.input_symbol = None

    def add_transition(
        self,
        input_symbol: object,
        state: object,
        action: _Action | None = None,
        next_state: object | None = None,
    ) -> None:
        """Associate (input_symbol, current_state) with (action, next_state).

        The action may be set to None in which case the process() method will
        ignore the action and only set the next_state. The next_state may be
        set to None in which case the current state will be unchanged.

        You can also set transitions for a list of symbols by using
        add_transition_list().
        """
        if next_state is None:
            next_state = state
        self.state_transitions[(input_symbol, state)] = (action, next_state)

    def add_transition_list(
        self,
        list_input_symbols: Iterable[object],
        state: object,
        action: _Action | None = None,
        next_state: object | None = None,
    ) -> None:
        """Add the same transition for a list of input symbols.

        You can pass a list or a string. Note that it is handy to use
        string.digits, string.whitespace, string.letters, etc. to add
        transitions that match character classes.

        The action may be set to None in which case the process() method will
        ignore the action and only set the next_state. The next_state may be
        set to None in which case the current state will be unchanged.
        """
        if next_state is None:
            next_state = state
        for input_symbol in list_input_symbols:
            self.add_transition(input_symbol, state, action, next_state)

    def add_transition_any(
        self,
        state: object,
        action: _Action | None = None,
        next_state: object | None = None,
    ) -> None:
        """Associate (current_state) with (action, next_state).

        That is, any input symbol will match the current state. The process()
        method checks the "any" state associations after it first checks for an
        exact match of (input_symbol, current_state).

        The action may be set to None in which case the process() method will
        ignore the action and only set the next_state. The next_state may be
        set to None in which case the current state will be unchanged.
        """
        if next_state is None:
            next_state = state
        self.state_transitions_any[state] = (action, next_state)

    def set_default_transition(self, action: _Action | None, next_state: object) -> None:
        """Set the default transition.

        This defines an action and next_state if the FSM cannot find the input
        symbol and the current state in the transition list and if the FSM
        cannot find the current_state in the transition_any list. This is
        useful as a final fall-through state for catching errors and undefined
        states.

        The default transition can be removed by setting the attribute
        default_transition to None.
        """
        self.default_transition = (action, next_state)

    def get_transition(self, input_symbol: object, state: object) -> tuple[_Action | None, object]:
        """Return (action, next state) for the given input_symbol and state.

        This does not modify the FSM state, so calling this method has no side
        effects. Normally you do not call this method directly. It is called by
        process().

        The sequence of steps to check for a defined transition goes from the
        most specific to the least specific.

        1. Check state_transitions[] that match exactly the tuple,
            (input_symbol, state)

        2. Check state_transitions_any[] that match (state)
            In other words, match a specific state and ANY input_symbol.

        3. Check if the default_transition is defined.
            This catches any input_symbol and any state.
            This is a handler for errors, undefined states, or defaults.

        4. No transition was defined. If we get here then raise an exception.
        """
        if (input_symbol, state) in self.state_transitions:
            return self.state_transitions[(input_symbol, state)]
        if state in self.state_transitions_any:
            return self.state_transitions_any[state]
        if self.default_transition is not None:
            return self.default_transition
        msg = f"Transition is undefined: ({input_symbol!s}, {state!s})."
        raise ExceptionFSM(msg)

    def process(self, input_symbol: object) -> None:
        """Process one input symbol, changing state and calling its action.

        This method calls get_transition() to find the action and next_state
        associated with the input_symbol and current_state. If the action is
        None then the action is not called and only the current state is
        changed. This method processes one complete input symbol. You can
        process a list of symbols (or a string) by calling process_list().
        """
        self.input_symbol = input_symbol
        (self.action, self.next_state) = self.get_transition(self.input_symbol, self.current_state)
        if self.action is not None:
            self.action(self)
        self.current_state = self.next_state
        self.next_state = None

    def process_list(self, input_symbols: Iterable[object]) -> None:
        """Send each element of ``input_symbols`` to process().

        The list may be a string or any iterable object.
        """
        for s in input_symbols:
            self.process(s)


##############################################################################
# The following is an example that demonstrates the use of the FSM class to
# process an RPN expression. Run this module from the command line. You will
# get a prompt > for input. Enter an RPN Expression. Numbers may be integers.
# Operators are * / + - Use the = sign to evaluate and print the expression.
# For example:
#
#    167 3 2 2 * * * 1 - =
#
# will print:
#
#    2003
##############################################################################

#
# These define the actions.
# Note that "memory" is a list being used as a stack.
#


def BeginBuildNumber(fsm: FSM) -> None:
    """Push the digit that starts a new number onto the stack."""
    fsm.memory.append(fsm.input_symbol)


def BuildNumber(fsm: FSM) -> None:
    """Append the current digit to the number being built on top of the stack."""
    s = fsm.memory.pop()
    s = s + fsm.input_symbol
    fsm.memory.append(s)


def EndBuildNumber(fsm: FSM) -> None:
    """Replace the finished digit string on top of the stack with its int value."""
    s = fsm.memory.pop()
    fsm.memory.append(int(s))


def DoOperator(fsm: FSM) -> None:
    """Pop the two operands on top of the stack and push the operator's result."""
    ar = fsm.memory.pop()
    al = fsm.memory.pop()
    if fsm.input_symbol == "+":
        fsm.memory.append(al + ar)
    elif fsm.input_symbol == "-":
        fsm.memory.append(al - ar)
    elif fsm.input_symbol == "*":
        fsm.memory.append(al * ar)
    elif fsm.input_symbol == "/":
        fsm.memory.append(al / ar)


def DoEqual(fsm: FSM) -> None:
    """Print the value on top of the stack."""
    print(str(fsm.memory.pop()))


def Error(fsm: FSM) -> None:
    """Report an input symbol the example grammar does not accept."""
    print("That does not compute.")
    print(str(fsm.input_symbol))


def main() -> None:
    """Run the RPN example, where the FSM state transitions are defined.

    Note that states are strings (such as 'INIT'). This is not necessary, but
    it makes the example easier to read.
    """
    f = FSM("INIT", [])
    f.set_default_transition(Error, "INIT")
    f.add_transition_any("INIT", None, "INIT")
    f.add_transition("=", "INIT", DoEqual, "INIT")
    f.add_transition_list(string.digits, "INIT", BeginBuildNumber, "BUILDING_NUMBER")
    f.add_transition_list(string.digits, "BUILDING_NUMBER", BuildNumber, "BUILDING_NUMBER")
    f.add_transition_list(string.whitespace, "BUILDING_NUMBER", EndBuildNumber, "INIT")
    f.add_transition_list("+-*/", "INIT", DoOperator, "INIT")

    print()
    print("Enter an RPN Expression.")
    print("Numbers may be integers. Operators are * / + -")
    print("Use the = sign to evaluate and print the expression.")
    print("For example: ")
    print("    167 3 2 2 * * * 1 - =")
    inputstr = input("> ")
    f.process_list(inputstr)


if __name__ == "__main__":
    main()
