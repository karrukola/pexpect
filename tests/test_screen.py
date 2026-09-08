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

import importlib.util
import unittest
import warnings

import pytest

from . import pexpect_test_case

# pexpect.screen announces its own deprecation from its module body, so this
# import raises it, and the suite treats a warning as an error. The module is
# still shipped and this file is its test, so the import has to happen and the
# warning has to be let through -- here, at the one import that expects it,
# rather than by exempting the message for the whole run. That it is raised at
# all is asserted by ScreenTestCase.test_import_warns_of_the_deprecation.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", UserWarning)
    from pexpect import screen

fill1_target = (
    "XXXXXXXXXX\n"
    "XOOOOOOOOX\n"
    "XO::::::OX\n"
    "XO:oooo:OX\n"
    "XO:o..o:OX\n"
    "XO:o..o:OX\n"
    "XO:oooo:OX\n"
    "XO::::::OX\n"
    "XOOOOOOOOX\n"
    "XXXXXXXXXX"
)
fill2_target = (
    "XXXXXXXXXXX\n"
    "XOOOOOOOOOX\n"
    "XO:::::::OX\n"
    "XO:ooooo:OX\n"
    "XO:o...o:OX\n"
    "XO:o.+.o:OX\n"
    "XO:o...o:OX\n"
    "XO:ooooo:OX\n"
    "XO:::::::OX\n"
    "XOOOOOOOOOX\n"
    "XXXXXXXXXXX"
)
put_target = (
    "\\.3.5.7.9/\n"
    ".........2\n"
    "3.........\n"
    ".........4\n"
    "5...\\/....\n"
    "..../\\...6\n"
    "7.........\n"
    ".........8\n"
    "9.........\n"
    "/2.4.6.8.\\"
)
scroll_target = (
    "\\.3.5.7.9/\n"
    "\\.3.5.7.9/\n"
    "\\.3.5.7.9/\n"
    "\\.3.5.7.9/\n"
    "5...\\/....\n"
    "..../\\...6\n"
    "/2.4.6.8.\\\n"
    "/2.4.6.8.\\\n"
    "/2.4.6.8.\\\n"
    "/2.4.6.8.\\"
)
insert_target = (
    "ZXZZZZZZXZ\n"
    ".........2\n"
    "3.........\n"
    ".........4\n"
    "Z5...\\/...\n"
    "..../Z\\...\n"
    "7.........\n"
    ".........8\n"
    "9.........\n"
    "ZZ/2.4.6ZZ"
)
get_region_target = ["......", ".\\/...", "./\\...", "......"]

unicode_box_unicode_result = "\u2554\u2557\n\u255a\u255d"
unicode_box_pretty_result = """\
+--+
|\u2554\u2557|
|\u255a\u255d|
+--+
"""


class ScreenTestCase(pexpect_test_case.PexpectTestCase):
    """Exercise the virtual screen: fills, puts, scrolling and encodings."""

    def make_screen_with_put(self) -> screen.screen:
        """Return a 10x10 screen with numbered edges and diagonal marks."""
        s = screen.screen(10, 10)
        s.fill(".")
        for r in range(1, s.rows + 1):
            if r % 2:
                s.put_abs(r, 1, str(r))
            else:
                s.put_abs(r, s.cols, str(r))
        for c in range(1, s.cols + 1):
            if c % 2:
                s.put_abs(1, c, str(c))
            else:
                s.put_abs(s.rows, c, str(c))
        s.put_abs(1, 1, "\\")
        s.put_abs(1, s.cols, "/")
        s.put_abs(s.rows, 1, "/")
        s.put_abs(s.rows, s.cols, "\\")
        s.put_abs(5, 5, "\\")
        s.put_abs(5, 6, "/")
        s.put_abs(6, 5, "/")
        s.put_abs(6, 6, "\\")
        return s

    def test_fill(self) -> None:
        """Fill nested rectangular regions and compare the rendered screen."""
        s = screen.screen(10, 10)
        s.fill_region(10, 1, 1, 10, "X")
        s.fill_region(2, 2, 9, 9, "O")
        s.fill_region(8, 8, 3, 3, ":")
        s.fill_region(4, 7, 7, 4, "o")
        s.fill_region(6, 5, 5, 6, ".")
        assert str(s) == fill1_target

        s = screen.screen(11, 11)
        s.fill_region(1, 1, 11, 11, "X")
        s.fill_region(2, 2, 10, 10, "O")
        s.fill_region(9, 9, 3, 3, ":")
        s.fill_region(4, 8, 8, 4, "o")
        s.fill_region(7, 5, 5, 7, ".")
        s.fill_region(6, 6, 6, 6, "+")
        assert str(s) == fill2_target

    def test_put(self) -> None:
        """Place single characters at absolute positions."""
        s = self.make_screen_with_put()
        assert str(s) == put_target

    def test_get_region(self) -> None:
        """Read back a rectangular region of the screen."""
        s = self.make_screen_with_put()
        r = s.get_region(4, 4, 7, 9)
        assert r == get_region_target

    def test_cursor_save(self) -> None:
        """Restore the cursor position that was saved before moving it."""
        row = col = 5
        s = self.make_screen_with_put()
        s.cursor_home(row, col)
        s.get()  # get() returns nothing; get_abs() is what reads a character back
        c = s.get_abs(row, col)
        s.cursor_save()
        s.cursor_home()
        s.cursor_forward()
        s.cursor_down()
        s.cursor_unsave()
        assert s.cur_r == row
        assert s.cur_c == col
        assert c == s.get_abs(s.cur_r, s.cur_c)

    def test_scroll(self) -> None:
        """Scroll a range of rows down and then up within the screen."""
        s = self.make_screen_with_put()
        s.scroll_screen_rows(1, 4)
        s.scroll_down()
        s.scroll_down()
        s.scroll_down()
        s.scroll_down()
        s.scroll_down()
        s.scroll_down()
        s.scroll_screen_rows(7, 10)
        s.scroll_up()
        s.scroll_up()
        s.scroll_up()
        s.scroll_up()
        s.scroll_up()
        s.scroll_up()
        assert str(s) == scroll_target

    def test_insert(self) -> None:
        """Insert characters, shifting the remainder of the row aside."""
        s = self.make_screen_with_put()
        s.insert_abs(10, 1, "Z")
        s.insert_abs(1, 1, "Z")
        s.insert_abs(1, 1, "Z")
        s.insert_abs(1, 1, "Z")
        s.insert_abs(1, 1, "Z")
        s.insert_abs(1, 1, "Z")
        s.insert_abs(10, 1, "Z")
        s.insert_abs(1, 1, "Z")
        s.insert_abs(1, 1, "Z")
        s.insert_abs(5, 1, "Z")
        s.insert_abs(6, 6, "Z")
        s.cursor_home(1, 1)  # Also test relative insert.
        s.insert("Z")
        s.insert("Z")
        s.insert("Z")
        s.insert("Z")
        s.insert_abs(1, 8, "X")
        s.insert_abs(1, 2, "X")
        s.insert_abs(10, 9, "Z")
        s.insert_abs(10, 9, "Z")
        assert str(s) == insert_target

    def make_screen_with_box_unicode(
        self, encoding: str, encoding_errors: str = "replace"
    ) -> screen.screen:
        """Return a screen holding a double-line box fed in as unicode."""
        s = screen.screen(2, 2, encoding, encoding_errors)
        s.put_abs(1, 1, "\u2554")
        s.put_abs(1, 2, "\u2557")
        s.put_abs(2, 1, "\u255a")
        s.put_abs(2, 2, "\u255d")
        return s

    def make_screen_with_box_cp437(
        self, encoding: str, encoding_errors: str = "replace"
    ) -> screen.screen:
        """Return a screen holding a double-line box fed in as CP437 bytes."""
        s = screen.screen(2, 2, encoding, encoding_errors)
        s.put_abs(1, 1, b"\xc9")
        s.put_abs(1, 2, b"\xbb")
        s.put_abs(2, 1, b"\xc8")
        s.put_abs(2, 2, b"\xbc")
        return s

    def make_screen_with_box_utf8(
        self, encoding: str, encoding_errors: str = "replace"
    ) -> screen.screen:
        """Return a screen holding a double-line box fed in as UTF-8 bytes."""
        s = screen.screen(2, 2, encoding, encoding_errors)
        s.put_abs(1, 1, b"\xe2\x95\x94")
        s.put_abs(1, 2, b"\xe2\x95\x97")
        s.put_abs(2, 1, b"\xe2\x95\x9a")
        s.put_abs(2, 2, b"\xe2\x95\x9d")
        return s

    def test_unicode_ascii(self) -> None:
        """Feed unicode into an ASCII screen and read it back unchanged."""
        # With the default encoding set to ASCII, we should still be
        # able to feed in unicode strings and get them back out:
        s = self.make_screen_with_box_unicode("ascii")
        assert str(s) == unicode_box_unicode_result
        assert s.pretty() == unicode_box_pretty_result

    def test_decoding_errors(self) -> None:
        """Reject undecodable bytes when strict, replace them when asked to."""
        # With strict error handling, it should reject bytes it can't decode
        with pytest.raises(UnicodeDecodeError):
            self.make_screen_with_box_cp437("ascii", "strict")

        # replace should turn them into unicode replacement characters, U+FFFD
        s = self.make_screen_with_box_cp437("ascii", "replace")
        expected = "\ufffd\ufffd\n\ufffd\ufffd"
        assert str(s) == expected

    def test_unicode_cp437(self) -> None:
        """Decode CP437 bytes into the matching unicode characters."""
        s = self.make_screen_with_box_cp437("cp437", "strict")
        assert str(s) == unicode_box_unicode_result
        assert s.pretty() == unicode_box_pretty_result

    def test_unicode_utf8(self) -> None:
        """Decode UTF-8 bytes into the matching unicode characters."""
        s = self.make_screen_with_box_utf8("utf-8", "strict")
        assert str(s) == unicode_box_unicode_result
        assert s.pretty() == unicode_box_pretty_result

    def test_no_bytes(self) -> None:
        """Reject bytes input on a screen created without an encoding."""
        s = screen.screen(2, 2, encoding=None)
        s.put_abs(1, 1, "A")
        s.put_abs(2, 2, "D")

        with pytest.raises(TypeError):
            s.put_abs(1, 2, b"B")

        assert str(s) == "A \n D"

    def test_fill_with_bytes(self) -> None:
        """Fill the screen and a region with characters supplied as bytes.

        Given a screen whose encoding is the default latin-1,
        When :meth:`screen.screen.fill` and :meth:`screen.screen.fill_region`
        are called with bytes,
        Then the bytes are decoded and the decoded character fills the area.
        """
        s = screen.screen(2, 2)
        s.fill(b"\xe4")
        assert str(s) == "\xe4\xe4\n\xe4\xe4"

        s.fill_region(1, 1, 1, 2, b"\xf6")
        assert str(s) == "\xf6\xf6\n\xe4\xe4"

    def test_put_at_cursor(self) -> None:
        """Put characters at the cursor position rather than at absolute coordinates.

        Given a blank screen with the cursor moved to row 2, column 2,
        When :meth:`screen.screen.put` is called with a str and then with bytes,
        Then each character lands at the cursor position, decoding bytes on the way.
        """
        s = screen.screen(2, 2)
        s.cursor_home(2, 2)
        s.put("A")
        assert s.get_abs(2, 2) == "A"

        s.put(b"\xe4")
        assert s.get_abs(2, 2) == "\xe4"

    def test_insert_with_bytes(self) -> None:
        """Insert characters supplied as bytes, absolutely and at the cursor.

        Given a screen filled with dots,
        When :meth:`screen.screen.insert_abs` and :meth:`screen.screen.insert`
        are called with bytes,
        Then the bytes are decoded and inserted, shifting the row to the right.
        """
        s = screen.screen(1, 3)
        s.fill(".")
        s.insert_abs(1, 1, b"\xe4")
        assert str(s) == "\xe4.."

        s.cursor_home(1, 1)
        s.insert(b"\xf6")
        assert str(s) == "\xf6\xe4."

    def test_get_region_with_reversed_bounds(self) -> None:
        """Read a region whose start coordinates are past its end coordinates.

        Given a 10x10 screen with known content,
        When :meth:`screen.screen.get_region` is passed the corners in reverse
        order, so that the start row and column are greater than the end ones,
        Then the corners are swapped and the same region is returned.
        """
        s = self.make_screen_with_put()
        assert s.get_region(7, 9, 4, 4) == s.get_region(4, 4, 7, 9)

    def test_newline(self) -> None:
        """Advance to the start of the next row with newline.

        Given a blank screen with the cursor at row 1, column 2,
        When :meth:`screen.screen.newline` is called,
        Then the cursor moves to row 2, column 1.
        """
        s = screen.screen(2, 2)
        s.cursor_home(1, 2)
        s.newline()
        assert (s.cur_r, s.cur_c) == (2, 1)

    def test_cursor_up_reverse_without_scrolling(self) -> None:
        """Move the cursor up without scrolling when it is not on the top row.

        Given a screen whose rows hold distinct content and whose cursor is on
        row 2,
        When :meth:`screen.screen.cursor_up_reverse` is called,
        Then the cursor moves to row 1 and the screen content is unchanged.
        """
        s = screen.screen(2, 2)
        s.fill_region(1, 1, 1, 2, "a")
        s.fill_region(2, 1, 2, 2, "b")
        s.cursor_home(2, 1)
        s.cursor_up_reverse()
        assert s.cur_r == 1
        assert str(s) == "aa\nbb"

    def test_cursor_force_position(self) -> None:
        """Move the cursor with the force-position alias of cursor home.

        Given a blank 5x5 screen,
        When :meth:`screen.screen.cursor_force_position` is called with row 3
        and column 4,
        Then the cursor sits at row 3, column 4.
        """
        s = screen.screen(5, 5)
        s.cursor_force_position(3, 4)
        assert (s.cur_r, s.cur_c) == (3, 4)

    def test_scroll_screen_rows_are_constrained(self) -> None:
        """Clamp a scrolling region that reaches outside the screen.

        Given a 5-row screen,
        When :meth:`screen.screen.scroll_screen_rows` is called with a start row
        of 0 and an end row of 99,
        Then the region is clamped to the first and last rows of the screen.
        """
        s = screen.screen(5, 5)
        s.scroll_screen_rows(0, 99)
        assert (s.scroll_row_start, s.scroll_row_end) == (1, 5)

    def test_scroll_screen_restores_full_region(self) -> None:
        """Re-enable scrolling over the whole screen.

        Given a 5-row screen whose scrolling region was narrowed to rows 2 to 3,
        When :meth:`screen.screen.scroll_screen` is called,
        Then the scrolling region covers every row again.
        """
        s = screen.screen(5, 5)
        s.scroll_screen_rows(2, 3)
        s.scroll_screen()
        assert (s.scroll_row_start, s.scroll_row_end) == (1, 5)

    def test_erase_start_of_line(self) -> None:
        """Erase from the cursor back to the start of its row.

        Given a single-row screen filled with dots and the cursor at column 2,
        When :meth:`screen.screen.erase_start_of_line` is called,
        Then the columns up to and including the cursor become spaces.
        """
        s = screen.screen(1, 4)
        s.fill(".")
        s.cursor_home(1, 2)
        s.erase_start_of_line()
        assert str(s) == "  .."

    def test_erase_up(self) -> None:
        """Erase from the cursor up to the top of the screen.

        Given a 3x2 screen filled with dots and the cursor at row 2, column 1,
        When :meth:`screen.screen.erase_up` is called,
        Then row 1 and the start of row 2 become spaces and row 3 is untouched.
        """
        s = screen.screen(3, 2)
        s.fill(".")
        s.cursor_home(2, 1)
        s.erase_up()
        assert str(s) == "  \n .\n.."

    def test_erase_up_top_row(self) -> None:
        """Erase up from the top row without erasing past the cursor.

        Given a 3x6 screen filled with dots and the cursor on row 1, column 3,
        When :meth:`screen.screen.erase_up` is called,
        Then only the start of row 1 up to the cursor becomes spaces, the rest
        of row 1 keeps its dots, and rows 2 and 3 are untouched.
        """
        s = screen.screen(3, 6)
        s.fill(".")
        s.cursor_home(1, 3)
        s.erase_up()
        assert str(s) == "   ...\n......\n......"

    def test_erase_down(self) -> None:
        """Erase from the cursor down to the bottom of the screen.

        Given a 3x2 screen filled with dots and the cursor at row 2, column 2,
        When :meth:`screen.screen.erase_down` is called,
        Then the end of row 2 and all of row 3 become spaces and row 1 is
        untouched.
        """
        s = screen.screen(3, 2)
        s.fill(".")
        s.cursor_home(2, 2)
        s.erase_down()
        assert str(s) == "..\n. \n  "

    def test_erase_down_bottom_row(self) -> None:
        """Erase down from the bottom row without erasing before the cursor.

        Given a 3x6 screen filled with dots and the cursor on row 3, column 3,
        When :meth:`screen.screen.erase_down` is called,
        Then only row 3 from the cursor onward becomes spaces, the start of
        row 3 keeps its dots, and rows 1 and 2 are untouched.
        """
        s = screen.screen(3, 6)
        s.fill(".")
        s.cursor_home(3, 3)
        s.erase_down()
        assert str(s) == "......\n......\n..    "

    def test_import_warns_of_the_deprecation(self) -> None:
        """Announce the deprecation of this module, and of pexpect.ANSI, on import.

        A module body runs once per process and this one has already run, so
        importing pexpect.screen again hands back the module the rest of the
        suite is holding and raises nothing. The body is executed once more
        instead, into a module object that is thrown away: that is what a first
        import does, without replacing the pexpect.screen every other test --
        and pexpect.ANSI's own class hierarchy -- was built against.
        """
        spec = importlib.util.find_spec("pexpect.screen")
        assert spec is not None
        assert spec.loader is not None

        with pytest.warns(UserWarning, match="pexpect.screen and pexpect.ANSI are deprecated"):
            spec.loader.exec_module(importlib.util.module_from_spec(spec))


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(ScreenTestCase)
