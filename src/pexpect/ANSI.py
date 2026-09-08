"""ANSI (VT100) terminal emulator implemented as a subclass of screen.

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

# references:
#     http://en.wikipedia.org/wiki/ANSI_escape_code
#     http://www.retards.org/terminals/vt102.html
#     http://vt100.net/docs/vt102-ug/contents.html
#     http://vt100.net/docs/vt220-rm/
#     http://www.termsys.demon.co.uk/vtansi.htm

from __future__ import annotations

import string
from pathlib import Path
from typing import TYPE_CHECKING, cast

from . import FSM, screen

if TYPE_CHECKING:
    from collections.abc import Callable

    # screen.screen.__init__ takes (r, c, encoding, encoding_errors). term and
    # ANSI forward the trailing arguments through *args and **kwargs, whose one
    # element type cannot describe two differently typed parameters, so the
    # forwarding target is typed as an unchecked callable.
    _ScreenInit = Callable[..., None]

# Parameter of <ESC>[{n}J and <ESC>[{n}K that selects the whole screen or line.
ERASE_ALL = 2


#
# The 'Do.*' functions are helper functions for the ANSI class.
#
def DoEmit(fsm: FSM.FSM) -> None:
    """Write the current input symbol to the screen."""
    screen = fsm.memory[0]
    screen.write_ch(fsm.input_symbol)


def DoStartNumber(fsm: FSM.FSM) -> None:
    """Push the current input symbol as the first digit of a new number."""
    fsm.memory.append(fsm.input_symbol)


def DoBuildNumber(fsm: FSM.FSM) -> None:
    """Append the current input symbol to the number being built."""
    ns = fsm.memory.pop()
    ns = ns + fsm.input_symbol
    fsm.memory.append(ns)


def DoBackOne(fsm: FSM.FSM) -> None:
    """Move the cursor back one column."""
    screen = fsm.memory[0]
    screen.cursor_back()


def DoBack(fsm: FSM.FSM) -> None:
    """Move the cursor back by the number on the stack."""
    count = int(fsm.memory.pop())
    screen = fsm.memory[0]
    screen.cursor_back(count)


def DoDownOne(fsm: FSM.FSM) -> None:
    """Move the cursor down one row."""
    screen = fsm.memory[0]
    screen.cursor_down()


def DoDown(fsm: FSM.FSM) -> None:
    """Move the cursor down by the number on the stack."""
    count = int(fsm.memory.pop())
    screen = fsm.memory[0]
    screen.cursor_down(count)


def DoForwardOne(fsm: FSM.FSM) -> None:
    """Move the cursor forward one column."""
    screen = fsm.memory[0]
    screen.cursor_forward()


def DoForward(fsm: FSM.FSM) -> None:
    """Move the cursor forward by the number on the stack."""
    count = int(fsm.memory.pop())
    screen = fsm.memory[0]
    screen.cursor_forward(count)


def DoUpReverse(fsm: FSM.FSM) -> None:
    """Move the cursor up one row, scrolling if it is already at the top."""
    screen = fsm.memory[0]
    screen.cursor_up_reverse()


def DoUpOne(fsm: FSM.FSM) -> None:
    """Move the cursor up one row."""
    screen = fsm.memory[0]
    screen.cursor_up()


def DoUp(fsm: FSM.FSM) -> None:
    """Move the cursor up by the number on the stack."""
    count = int(fsm.memory.pop())
    screen = fsm.memory[0]
    screen.cursor_up(count)


def DoHome(fsm: FSM.FSM) -> None:
    """Move the cursor to the row and column on the stack."""
    c = int(fsm.memory.pop())
    r = int(fsm.memory.pop())
    screen = fsm.memory[0]
    screen.cursor_home(r, c)


def DoHomeOrigin(fsm: FSM.FSM) -> None:
    """Move the cursor to the origin, row 1 column 1."""
    c = 1
    r = 1
    screen = fsm.memory[0]
    screen.cursor_home(r, c)


def DoEraseDown(fsm: FSM.FSM) -> None:
    """Erase from the current line down to the bottom of the screen."""
    screen = fsm.memory[0]
    screen.erase_down()


def DoErase(fsm: FSM.FSM) -> None:
    """Erase the part of the screen selected by the number on the stack."""
    arg = int(fsm.memory.pop())
    screen = fsm.memory[0]
    if arg == 0:
        screen.erase_down()
    elif arg == 1:
        screen.erase_up()
    elif arg == ERASE_ALL:
        screen.erase_screen()


def DoEraseEndOfLine(fsm: FSM.FSM) -> None:
    """Erase from the cursor to the end of the current line."""
    screen = fsm.memory[0]
    screen.erase_end_of_line()


def DoEraseLine(fsm: FSM.FSM) -> None:
    """Erase the part of the current line selected by the number on the stack."""
    arg = int(fsm.memory.pop())
    screen = fsm.memory[0]
    if arg == 0:
        screen.erase_end_of_line()
    elif arg == 1:
        screen.erase_start_of_line()
    elif arg == ERASE_ALL:
        screen.erase_line()


def DoEnableScroll(fsm: FSM.FSM) -> None:
    """Enable scrolling for the entire display."""
    screen = fsm.memory[0]
    screen.scroll_screen()


def DoCursorSave(fsm: FSM.FSM) -> None:
    """Save the current cursor position."""
    screen = fsm.memory[0]
    screen.cursor_save_attrs()


def DoCursorRestore(fsm: FSM.FSM) -> None:
    """Restore the cursor position saved by :func:`DoCursorSave`."""
    screen = fsm.memory[0]
    screen.cursor_restore_attrs()


def DoScrollRegion(fsm: FSM.FSM) -> None:
    """Set the scrolling region to the two rows on the stack."""
    screen = fsm.memory[0]
    r2 = int(fsm.memory.pop())
    r1 = int(fsm.memory.pop())
    screen.scroll_screen_rows(r1, r2)


def DoMode(fsm: FSM.FSM) -> None:
    """Discard the mode number of a set/reset mode sequence.

    Only replace mode (4) is ever sent here, and it is not implemented, so the
    number is popped off the stack and dropped.
    """
    fsm.memory.pop()


def DoLog(fsm: FSM.FSM) -> None:
    """Append the input symbol and the current state to a file named 'log'."""
    screen = fsm.memory[0]
    fsm.memory = [screen]
    # Every transition that logs is driven by ANSI.write(), which feeds the
    # machine one character at a time between the string states below.
    input_symbol = cast("str", fsm.input_symbol)
    current_state = cast("str", fsm.current_state)
    with Path("log").open("a") as fout:
        fout.write(input_symbol + "," + current_state + "\n")


class term(screen.screen):
    """Abstract, generic terminal.

    This does nothing. This is a placeholder that provides a common base class
    for other terminals such as an ANSI terminal.
    """

    def __init__(self, r: int = 24, c: int = 80, *args: str | None, **kwargs: str | None) -> None:
        """Initialize a terminal with a screen of the given dimensions."""
        screen_init: _ScreenInit = screen.screen.__init__
        screen_init(self, r, c, *args, **kwargs)


class ANSI(term):
    """ANSI (VT100) terminal.

    It is a stream filter that recognizes ANSI terminal escape sequences and
    maintains the state of a screen object.
    """

    def __init__(self, r: int = 24, c: int = 80, *args: str | None, **kwargs: str | None) -> None:
        """Initialize an ANSI terminal of the given dimensions."""
        term.__init__(self, r, c, *args, **kwargs)

        self.state = FSM.FSM("INIT", [self])
        self._add_escape_transitions()
        self._add_bracket_transitions()

    def _add_escape_transitions(self) -> None:
        """Add the transitions for the escape sequences that lack a '['."""
        self.state.set_default_transition(DoLog, "INIT")
        self.state.add_transition_any("INIT", DoEmit, "INIT")
        self.state.add_transition("\x1b", "INIT", None, "ESC")
        self.state.add_transition_any("ESC", DoLog, "INIT")
        self.state.add_transition("(", "ESC", None, "G0SCS")
        self.state.add_transition(")", "ESC", None, "G1SCS")
        self.state.add_transition_list("AB012", "G0SCS", None, "INIT")
        self.state.add_transition_list("AB012", "G1SCS", None, "INIT")
        self.state.add_transition("7", "ESC", DoCursorSave, "INIT")
        self.state.add_transition("8", "ESC", DoCursorRestore, "INIT")
        self.state.add_transition("M", "ESC", DoUpReverse, "INIT")
        self.state.add_transition(">", "ESC", DoUpReverse, "INIT")
        self.state.add_transition("<", "ESC", DoUpReverse, "INIT")
        self.state.add_transition("=", "ESC", None, "INIT")  # Selects application keypad.
        self.state.add_transition("#", "ESC", None, "GRAPHICS_POUND")
        self.state.add_transition_any("GRAPHICS_POUND", None, "INIT")

    def _add_bracket_transitions(self) -> None:
        """Add the transitions for the escape sequences that start with '['."""
        self.state.add_transition("[", "ESC", None, "ELB")
        # ELB means Escape Left Bracket. That is ^[[
        self.state.add_transition("H", "ELB", DoHomeOrigin, "INIT")
        self.state.add_transition("D", "ELB", DoBackOne, "INIT")
        self.state.add_transition("B", "ELB", DoDownOne, "INIT")
        self.state.add_transition("C", "ELB", DoForwardOne, "INIT")
        self.state.add_transition("A", "ELB", DoUpOne, "INIT")
        self.state.add_transition("J", "ELB", DoEraseDown, "INIT")
        self.state.add_transition("K", "ELB", DoEraseEndOfLine, "INIT")
        self.state.add_transition("r", "ELB", DoEnableScroll, "INIT")
        self.state.add_transition("m", "ELB", self.do_sgr, "INIT")
        self.state.add_transition("?", "ELB", None, "MODECRAP")
        self.state.add_transition_list(string.digits, "ELB", DoStartNumber, "NUMBER_1")
        self.state.add_transition_list(string.digits, "NUMBER_1", DoBuildNumber, "NUMBER_1")
        self.state.add_transition("D", "NUMBER_1", DoBack, "INIT")
        self.state.add_transition("B", "NUMBER_1", DoDown, "INIT")
        self.state.add_transition("C", "NUMBER_1", DoForward, "INIT")
        self.state.add_transition("A", "NUMBER_1", DoUp, "INIT")
        self.state.add_transition("J", "NUMBER_1", DoErase, "INIT")
        self.state.add_transition("K", "NUMBER_1", DoEraseLine, "INIT")
        self.state.add_transition("l", "NUMBER_1", DoMode, "INIT")
        ### It gets worse... the 'm' code can have infinite number of
        ### number;number;number before it. I've never seen more than two,
        ### but the specs say it's allowed. crap!
        self.state.add_transition("m", "NUMBER_1", self.do_sgr, "INIT")
        ### LED control. Same implementation problem as 'm' code.
        self.state.add_transition("q", "NUMBER_1", self.do_decsca, "INIT")

        # \E[?47h switch to alternate screen
        # \E[?47l restores to normal screen from alternate screen.
        self.state.add_transition_list(string.digits, "MODECRAP", DoStartNumber, "MODECRAP_NUM")
        self.state.add_transition_list(
            string.digits, "MODECRAP_NUM", DoBuildNumber, "MODECRAP_NUM"
        )
        self.state.add_transition("l", "MODECRAP_NUM", self.do_modecrap, "INIT")
        self.state.add_transition("h", "MODECRAP_NUM", self.do_modecrap, "INIT")

        # RM   Reset Mode                Esc [ Ps l                   none
        self.state.add_transition(";", "NUMBER_1", None, "SEMICOLON")
        self.state.add_transition_any("SEMICOLON", DoLog, "INIT")
        self.state.add_transition_list(string.digits, "SEMICOLON", DoStartNumber, "NUMBER_2")
        self.state.add_transition_list(string.digits, "NUMBER_2", DoBuildNumber, "NUMBER_2")
        self.state.add_transition_any("NUMBER_2", DoLog, "INIT")
        self.state.add_transition("H", "NUMBER_2", DoHome, "INIT")
        self.state.add_transition("f", "NUMBER_2", DoHome, "INIT")
        self.state.add_transition("r", "NUMBER_2", DoScrollRegion, "INIT")
        ### It gets worse... the 'm' code can have infinite number of
        ### number;number;number before it. I've never seen more than two,
        ### but the specs say it's allowed. crap!
        self.state.add_transition("m", "NUMBER_2", self.do_sgr, "INIT")
        ### LED control. Same problem as 'm' code.
        self.state.add_transition("q", "NUMBER_2", self.do_decsca, "INIT")
        self.state.add_transition(";", "NUMBER_2", None, "SEMICOLON_X")

        # Create a state for 'q' and 'm' which allows an infinite number of ignored numbers
        self.state.add_transition_any("SEMICOLON_X", DoLog, "INIT")
        self.state.add_transition_list(string.digits, "SEMICOLON_X", DoStartNumber, "NUMBER_X")
        self.state.add_transition_list(string.digits, "NUMBER_X", DoBuildNumber, "NUMBER_X")
        self.state.add_transition_any("NUMBER_X", DoLog, "INIT")
        self.state.add_transition("m", "NUMBER_X", self.do_sgr, "INIT")
        self.state.add_transition("q", "NUMBER_X", self.do_decsca, "INIT")
        self.state.add_transition(";", "NUMBER_X", None, "SEMICOLON_X")

    def process(self, c: str | bytes) -> None:
        """Process a single character. Called by :meth:`write`."""
        if isinstance(c, bytes):
            c = self._decode(c)
        self.state.process(c)

    # E741: public parameter name
    def process_list(self, l: str | bytes) -> None:  # public parameter name  # noqa: E741
        """Process a string of characters. An alias for :meth:`write`."""
        self.write(l)

    def write(self, s: str | bytes) -> None:
        """Process text, writing it to the virtual screen while handling ANSI escape codes."""
        if isinstance(s, bytes):
            s = self._decode(s)
        for c in s:
            self.process(c)

    def flush(self) -> None:
        """Do nothing; the virtual screen is updated as text is written."""

    def write_ch(self, ch: str | bytes) -> None:
        """Put a character at the current cursor position.

        The cursor position is moved forward with wrap-around, but no scrolling
        is done if the cursor hits the lower-right corner of the screen.
        """
        if isinstance(ch, bytes):
            ch = self._decode(ch)

        # \r and \n both produce a call to cr() and lf(), respectively.
        ch = ch[0]

        if ch == "\r":
            self.cr()
            return
        if ch == "\n":
            self.crlf()
            return
        if ch == chr(screen.BS):
            self.cursor_back()
            return
        self.put_abs(self.cur_r, self.cur_c, ch)
        old_r = self.cur_r
        old_c = self.cur_c
        self.cursor_forward()
        if old_c == self.cur_c:
            self.cursor_down()
            if old_r != self.cur_r:
                self.cursor_home(self.cur_r, 1)
            else:
                self.scroll_up()
                self.cursor_home(self.cur_r, 1)
                self.erase_line()

    def do_sgr(self, fsm: FSM.FSM) -> None:
        """Select Graphic Rendition, e.g. color."""
        screen = fsm.memory[0]
        fsm.memory = [screen]

    def do_decsca(self, fsm: FSM.FSM) -> None:
        """Select character protection attribute."""
        screen = fsm.memory[0]
        fsm.memory = [screen]

    def do_modecrap(self, fsm: FSM.FSM) -> None:
        r"""Handle \x1b[?<number>h and \x1b[?<number>l.

        If anyone wanted to actually use these, they'd need to add more states
        to the FSM rather than just improve or override this method.
        """
        screen = fsm.memory[0]
        fsm.memory = [screen]
