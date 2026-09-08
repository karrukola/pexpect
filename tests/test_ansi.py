#!/usr/bin/env python
"""PEXPECT LICENSE.

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

import logging
import unittest
from pathlib import Path

import pytest

from pexpect import ANSI, FSM

from . import pexpect_test_case

write_target = (
    "I've got a ferret sticking up my nose.                           \n"
    "(He's got a ferret sticking up his nose.)                        \n"
    "How it got there I can't tell                                    \n"
    "But now it's there it hurts like hell                            \n"
    "And what is more it radically affects my sense of smell.         \n"
    "(His sense of smell.)                                            "
)

write_text = (
    "I've got a ferret sticking up my nose.\n"
    "(He's got a ferret sticking up his nose.)\n"
    "How it got there I can't tell\n"
    "But now it's there it hurts like hell\n"
    "And what is more it radically affects my sense of smell.\n"
    "(His sense of smell.)\n"
    "I can see a bare-bottomed mandril.\n"
    "(Slyly eyeing his other nostril.)\n"
    "If it jumps inside there too I really don't know what to do\n"
    "I'll be the proud posessor of a kind of nasal zoo.\n"
    "(A nasal zoo.)\n"
    "I've got a ferret sticking up my nose.\n"
    "(And what is worst of all it constantly explodes.)\n"
    '"Ferrets don\'t explode," you say\n'
    "But it happened nine times yesterday\n"
    "And I should know for each time I was standing in the way.\n"
    "I've got a ferret sticking up my nose.\n"
    "(He's got a ferret sticking up his nose.)\n"
    "How it got there I can't tell\n"
    "But now it's there it hurts like hell\n"
    "And what is more it radically affects my sense of smell.\n"
    "(His sense of smell.)"
)

tetris_target = (
    "                           XX            XXXX    XX                             \n"
    "                           XXXXXX    XXXXXXXX    XX                             \n"
    "                           XXXXXX    XXXXXXXX    XX                             \n"
    "                           XX  XX    XX  XXXX    XX                             \n"
    "                           XXXXXX  XXXX  XXXX    XX                             \n"
    "                           XXXXXXXXXX    XXXX    XX                             \n"
    "                           XX  XXXXXX      XX    XX                             \n"
    "                           XXXXXX          XX    XX                             \n"
    "                           XXXX    XXXXXX  XX    XX                             \n"
    "                           XXXXXX    XXXX  XX    XX                             \n"
    "                           XX  XX    XXXX  XX    XX                             \n"
    "                           XX  XX      XX  XX    XX                             \n"
    "                           XX  XX    XXXX  XXXX  XX                             \n"
    "                           XXXXXXXX  XXXX  XXXX  XX                             \n"
    "                           XXXXXXXXXXXXXX  XXXXXXXX                             \n"
    "                           XX    XXXXXXXX  XX    XX                             \n"
    "                           XXXXXXXXXXXXXX  XX    XX                             \n"
    "                           XX  XXXX    XXXXXX    XX                             \n"
    "                           XXXXXX          XXXXXXXX                             \n"
    "                           XXXXXXXXXX      XX    XX                             \n"
    "                           XXXXXXXXXXXXXXXXXXXXXXXX                             \n"
    "                                                                                \n"
    "  J->LEFT  K->ROTATE  L->RIGHT  SPACE->DROP  P->PAUSE  Q->QUIT                  \n"
    "                                                                                "
)

torture_target = (
    "+--------------------------------------------------------------------------------+\n"
    "|a`opqrs`      This is the       `srqpo`a                                        |\n"
    "|VT100 series Torture Test Demonstration.                                        |\n"
    "|VT100 series Torture Test Demonstration.                                        |\n"
    "|This is a normal line __________________________________________________y_      |\n"
    "|This is a bold line (normal unless the Advanced Video Option is installed)      |\n"
    '|This line is underlined _ "       "       "       "       "       "    _y_      |\n'
    '|This is a blinking line _ "       "       "       "       "       "    _y_      |\n'
    "|This is inverse video _ (underlined if no AVO and cursor is underline) _y_      |\n"
    "|Normal gjpqy Underline   Blink   Underline+Blink gjpqy                          |\n"
    "|Bold   gjpqy Underline   Blink   Underline+Blink gjpqy                          |\n"
    "|Inverse      Underline   Blink   Underline+Blink                                |\n"
    "|Bold+Inverse Underline   Blink   Underline+Blink                                |\n"
    "|This is double width                                                            |\n"
    "|This is double height                                                           |\n"
    "|This is double height                                                           |\n"
    "|_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ioy                                        |\n"
    "|_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ioy                                        |\n"
    "|_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ioy                                        |\n"
    "|`abcdefghijklmnopqrstuvwxyz{|}~ lqwqk                                           |\n"
    "|`abcdefghijklmnopqrstuvwxyz{|}~ tqnqu                                           |\n"
    "|`abcdefghijklmnopqrstuvwxyz{|}~ tqnqu                                           |\n"
    "|`abcdefghijklmnopqrstuvwxyz{|}~ mqvqj                                           |\n"
    "|   This test created by Joe Smith, 8-May-85                                     |\n"
    "|                                                                                |\n"
    "+--------------------------------------------------------------------------------+\n"
)


class AnsiTestCase(pexpect_test_case.PexpectTestCase):
    """Exercise the ANSI terminal emulator against captured terminal output."""

    def test_write(self) -> None:
        """Write a block of text one character at a time and render it."""
        s = ANSI.ANSI(6, 65)
        s.fill(".")
        s.cursor_home()
        for c in write_text:
            s.write(c)
        assert str(s) == write_target

    def test_torturet(self) -> None:
        """Replay the VT100 torture test capture."""
        s = ANSI.ANSI(24, 80)
        with Path("torturet.vt").open() as f:
            sample_text = f.read()
        for c in sample_text:
            s.process(c)
        assert s.pretty() == torture_target, (
            "processed: \n" + s.pretty() + "\nexpected:\n" + torture_target
        )

    def test_tetris(self) -> None:
        """Replay a captured tetris session."""
        s = ANSI.ANSI(24, 80)
        with Path("tetris.data").open() as f:
            tetris_text = f.read()
        for c in tetris_text:
            s.process(c)
        assert str(s) == tetris_target

    def test_lines(self) -> None:
        """Wrap at the right margin and honour backspace and carriage return."""
        s = ANSI.ANSI(5, 5)
        s.write("a" * 6 + "\n")
        s.write("ab\bcd\n")
        s.write("ab\rcd\n")
        assert str(s) == ("aaaaa\na    \nacd  \ncd   \n     ")

    def test_number_x(self) -> None:
        """Test the FSM state used to handle more than 2 numeric parameters."""

        class TestANSI(ANSI.ANSI):
            captured_memory = None

            def do_sgr(self, fsm: FSM.FSM) -> None:
                assert self.captured_memory is None
                self.captured_memory = fsm.memory

        s = TestANSI(1, 20)
        s.write("\x1b[0;1;32;45mtest")
        assert str(s) == ("test                ")
        assert s.captured_memory is not None
        assert s.captured_memory == [s, "0", "1", "32", "45"]

    def test_fsm_memory(self) -> None:
        """Leave nothing but the screen on the FSM stack after numeric sequences."""
        s = ANSI.ANSI(1, 20)
        s.write("\x1b[0;1;2;3m\x1b[4;5;6;7q\x1b[?8h\x1b[?9ltest")
        assert str(s) == ("test                ")
        assert s.state.memory == [s]

    def test_utf8_bytes(self) -> None:
        """Decode multi-byte UTF-8 characters fed in as bytes, split across writes."""
        s = ANSI.ANSI(2, 10, encoding="utf-8")
        # This is the UTF-8 encoding of the UCS character "HOURGLASS"
        # followed by the UTF-8 encoding of the UCS character
        # "KEYBOARD".  These characters can't be encoded in cp437 or
        # latin-1.  The "KEYBOARD" character is split into two
        # separate writes.
        s.write(b"\xe2\x8c\x9b")
        s.write(b"\xe2\x8c")
        s.write(b"\xa8")
        assert str(s) == "\u231b\u2328        \n          "
        assert s.dump() == "\u231b\u2328                  "
        assert s.pretty() == "+----------+\n|\u231b\u2328        |\n|          |\n+----------+\n"
        assert s.get_abs(1, 1) == "\u231b"
        assert s.get_region(1, 1, 1, 5) == ["\u231b\u2328   "]

    def test_unicode(self) -> None:
        """Test passing in of a unicode string."""
        s = ANSI.ANSI(2, 10, encoding="utf-8")
        s.write("\u231b\u2328")
        assert str(s) == "\u231b\u2328        \n          "
        assert s.dump() == "\u231b\u2328                  "
        assert s.pretty() == "+----------+\n|\u231b\u2328        |\n|          |\n+----------+\n"
        assert s.get_abs(1, 1) == "\u231b"
        assert s.get_region(1, 1, 1, 5) == ["\u231b\u2328   "]

    def test_decode_error(self) -> None:
        """Replace undecodable bytes with U+FFFD by default."""
        s = ANSI.ANSI(2, 10, encoding="ascii")
        s.write(b"\xff")  # a non-ASCII character
        # In unicode, the non-ASCII character is replaced with
        # REPLACEMENT CHARACTER.
        assert str(s) == "\ufffd         \n          "
        assert s.dump() == "\ufffd                   "
        assert s.pretty() == "+----------+\n|\ufffd         |\n|          |\n+----------+\n"
        assert s.get_abs(1, 1) == "\ufffd"
        assert s.get_region(1, 1, 1, 5) == ["\ufffd    "]

    def test_cursor_movement_escapes(self) -> None:
        """Move the cursor with the relative cursor movement escape sequences.

        Given a 5x5 ANSI terminal with the cursor at the home position,
        When the sequences for cursor down, forward, back and up are written,
        both in their bare form and with an explicit count,
        Then the cursor ends up at the position implied by the sum of the moves.
        """
        s = ANSI.ANSI(5, 5)
        s.write("\x1b[B")  # down one
        s.write("\x1b[3B")  # down three, clamped to the last row
        s.write("\x1b[C")  # forward one
        s.write("\x1b[3C")  # forward three
        assert (s.cur_r, s.cur_c) == (5, 5)

        s.write("\x1b[D")  # back one
        s.write("\x1b[3D")  # back three
        s.write("\x1b[A")  # up one
        s.write("\x1b[2A")  # up two
        assert (s.cur_r, s.cur_c) == (2, 1)

    def test_cursor_save_and_restore_escapes(self) -> None:
        """Save the cursor position and come back to it.

        Given a 5x5 ANSI terminal whose cursor was moved to row 3, column 4 and
        then saved with ``ESC 7``,
        When the cursor is moved elsewhere and ``ESC 8`` is written,
        Then the cursor is back at row 3, column 4.
        """
        s = ANSI.ANSI(5, 5)
        s.write("\x1b[3;4H\x1b7")
        s.write("\x1b[1;1H")
        assert (s.cur_r, s.cur_c) == (1, 1)

        s.write("\x1b8")
        assert (s.cur_r, s.cur_c) == (3, 4)

    def test_erase_line_escapes(self) -> None:
        """Erase parts of the current line.

        Given a single-row ANSI terminal filled with dots,
        When the erase-to-end-of-line, erase-to-start-of-line and erase-line
        sequences are written with the cursor in the middle of the row,
        Then only the selected part of the row becomes spaces each time.
        """
        s = ANSI.ANSI(1, 4)

        s.fill(".")
        s.write("\x1b[1;3H\x1b[K")  # bare form, erase to end of line
        assert str(s) == "..  "

        s.fill(".")
        s.write("\x1b[1;3H\x1b[0K")  # explicit 0, erase to end of line
        assert str(s) == "..  "

        s.fill(".")
        s.write("\x1b[1;3H\x1b[1K")  # erase to start of line
        assert str(s) == "   ."

        s.fill(".")
        s.write("\x1b[1;3H\x1b[2K")  # erase the whole line
        assert str(s) == "    "

        s.fill(".")
        s.write("\x1b[1;3H\x1b[3K")  # not implemented, so nothing is erased
        assert str(s) == "...."

    def test_erase_screen_escapes(self) -> None:
        """Erase parts of the screen.

        Given a 3x2 ANSI terminal filled with dots and the cursor on row 2,
        When the erase-down, erase-up, erase-screen and an unsupported erase
        sequence are written,
        Then each sequence erases the region it selects, and the unsupported one
        leaves the screen untouched.
        """
        s = ANSI.ANSI(3, 2)

        s.fill(".")
        s.write("\x1b[2;1H\x1b[0J")  # erase from the cursor down
        assert str(s) == "..\n  \n  "

        s.fill(".")
        s.write("\x1b[2;1H\x1b[1J")  # erase from the cursor up
        assert str(s) == "  \n .\n.."

        s.fill(".")
        s.write("\x1b[2;1H\x1b[2J")  # erase the whole screen
        assert str(s) == "  \n  \n  "

        s.fill(".")
        s.write("\x1b[2;1H\x1b[3J")  # not implemented, so nothing is erased
        assert str(s) == "..\n..\n.."

    def test_enable_scroll_escape(self) -> None:
        """Re-enable scrolling over the whole screen.

        Given a 5x5 ANSI terminal whose scrolling region was narrowed to rows 2
        to 3 by ``ESC [ 2 ; 3 r``,
        When the bare ``ESC [ r`` sequence is written,
        Then the scrolling region covers every row again.
        """
        s = ANSI.ANSI(5, 5)
        s.write("\x1b[2;3r")
        assert (s.scroll_row_start, s.scroll_row_end) == (2, 3)

        s.write("\x1b[r")
        assert (s.scroll_row_start, s.scroll_row_end) == (1, 5)

    def test_reset_mode_escape(self) -> None:
        """Drop the parameter of an unimplemented reset mode sequence.

        Given a 1x10 ANSI terminal,
        When the reset-replace-mode sequence ``ESC [ 4 l`` is written and text
        follows it,
        Then the parameter is dropped from the FSM stack and the text is written
        to the screen.
        """
        s = ANSI.ANSI(1, 10)
        s.write("\x1b[4ltest")
        assert str(s) == "test      "
        assert s.state.memory == [s]

    def test_scroll_at_the_end_of_the_screen(self) -> None:
        """Scroll the screen when text runs past the lower-right corner.

        Given a 2x2 ANSI terminal,
        When five characters are written, so that the cursor runs off the
        lower-right corner,
        Then the screen scrolls up and the last character starts a fresh row.
        """
        s = ANSI.ANSI(2, 2)
        s.write("abcde")
        assert str(s) == "cd\ne "

    def test_process_bytes(self) -> None:
        """Feed single characters in as bytes.

        Given a 1x4 ANSI terminal using the default latin-1 encoding,
        When :meth:`ANSI.ANSI.process` is called with one byte at a time,
        Then the bytes are decoded and written to the screen.
        """
        s = ANSI.ANSI(1, 4)
        for byte in (b"a", b"\xe4"):
            s.process(byte)
        assert str(s) == "a\xe4  "

    def test_process_list(self) -> None:
        """Feed a whole string in through the process_list alias of write.

        Given a 1x4 ANSI terminal,
        When :meth:`ANSI.ANSI.process_list` is called with a string,
        Then every character of the string is written to the screen.
        """
        s = ANSI.ANSI(1, 4)
        s.process_list("ab")
        assert str(s) == "ab  "

    def test_write_ch_bytes(self) -> None:
        """Put a character supplied as bytes at the cursor position.

        Given a 1x4 ANSI terminal using the default latin-1 encoding,
        When :meth:`ANSI.ANSI.write_ch` is called with bytes,
        Then the bytes are decoded and the character lands at the cursor.
        """
        s = ANSI.ANSI(1, 4)
        s.write_ch(b"\xe4")
        assert str(s) == "\xe4   "


def test_dolog_does_not_touch_the_filesystem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unhandled escape sequence must not write a file into the cwd.

    Given the current directory is an empty, writable directory,
    When an ANSI terminal is fed an escape sequence with no transition of its
    own, so the FSM falls back to its default transition, :func:`ANSI.DoLog`,
    Then no file is created in that directory, and a debug log record is
    emitted instead, naming the input symbol and the FSM state that DoLog
    used to write to disk.
    """
    monkeypatch.chdir(tmp_path)
    s = ANSI.ANSI(4, 10)
    with caplog.at_level(logging.DEBUG, logger="pexpect.ANSI"):
        s.write("\x1b[4h")  # set insert mode: no transition handles 'h'
    assert list(tmp_path.iterdir()) == []
    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert debug_records, "DoLog should have emitted a debug log record"
    message = debug_records[-1].getMessage()
    assert "h" in message
    assert "NUMBER_1" in message


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(AnsiTestCase)
