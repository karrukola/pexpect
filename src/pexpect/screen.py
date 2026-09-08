"""Virtual screen used to support ANSI terminal emulation.

The screen representation and state is implemented in this class. Most of the
methods are inspired by ANSI screen control codes. The
:class:`~pexpect.ANSI.ANSI` class extends this class to add parsing of ANSI
escape codes.

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

import codecs
import copy
import warnings

warnings.warn(
    (
        "pexpect.screen and pexpect.ANSI are deprecated. "
        "We recommend using pyte to emulate a terminal screen: "
        "https://pypi.python.org/pypi/pyte"
    ),
    stacklevel=2,
)

NUL = 0  # Fill character; ignored on input.
ENQ = 5  # Transmit answerback message.
BEL = 7  # Ring the bell.
BS = 8  # Move cursor left.
HT = 9  # Move cursor to next tab stop.
LF = 10  # Line feed.
VT = 11  # Same as LF.
FF = 12  # Same as LF.
CR = 13  # Move cursor to left margin or newline.
SO = 14  # Invoke G1 character set.
SI = 15  # Invoke G0 character set.
XON = 17  # Resume transmission.
XOFF = 19  # Halt transmission.
CAN = 24  # Cancel escape sequence.
SUB = 26  # Same as CAN.
ESC = 27  # Introduce a control sequence.
DEL = 127  # Fill character; ignored on input.
SPACE = " "  # Space or blank character.


def constrain(n: int, vmin: int, vmax: int) -> int:
    """Return the number n constrained to the vmin and vmax bounds."""
    if n < vmin:
        return vmin
    if n > vmax:
        return vmax
    return n


class screen:
    """Maintain the state of a virtual text screen as a rectangular array.

    This maintains a virtual cursor position and handles scrolling as
    characters are added. This supports most of the methods needed by an ANSI
    text screen. Row and column indexes are 1-based (not zero-based, like
    arrays).

    Characters are represented internally using ``str``. Methods that accept
    input characters, when passed ``bytes``, convert them from the encoding
    specified in the 'encoding' parameter to the constructor. Methods that
    return screen contents return ``str``. Passing ``encoding=None`` limits the
    API to only accept ``str`` input, so passing bytes in will raise
    :exc:`TypeError`.
    """

    def __init__(
        self,
        r: int = 24,
        c: int = 80,
        encoding: str | None = "latin-1",
        encoding_errors: str = "replace",
    ) -> None:
        """Initialize a blank screen of the given dimensions."""
        self.rows = r
        self.cols = c
        self.encoding = encoding
        self.encoding_errors = encoding_errors
        self.decoder: codecs.IncrementalDecoder | None
        if encoding is not None:
            self.decoder = codecs.getincrementaldecoder(encoding)(encoding_errors)
        else:
            self.decoder = None
        self.cur_r = 1
        self.cur_c = 1
        self.cur_saved_r = 1
        self.cur_saved_c = 1
        self.scroll_row_start = 1
        self.scroll_row_end = self.rows
        self.w = [[SPACE] * self.cols for _ in range(self.rows)]

    def _decode(self, s: bytes) -> str:
        """Convert from the external coding system to the internal one.

        The external system is the encoding passed to the constructor; the
        internal one is ``str``.
        """
        if self.decoder is not None:
            return self.decoder.decode(s)
        msg = "This screen was constructed with encoding=None, so it does not handle bytes."
        raise TypeError(msg)

    def _unicode(self) -> str:
        """Return a printable representation of the screen.

        The end of each screen line is terminated by a newline.
        """
        return "\n".join(["".join(c) for c in self.w])

    __str__ = _unicode

    def dump(self) -> str:
        """Return a copy of the screen as a string.

        This is similar to :meth:`__str__` except that lines are not terminated
        with line feeds.
        """
        return "".join(["".join(c) for c in self.w])

    def pretty(self) -> str:
        """Return a copy of the screen with an ASCII text box around the border.

        This is similar to :meth:`__str__` except that it adds a box.
        """
        top_bot = "+" + "-" * self.cols + "+\n"
        return (
            top_bot
            + "\n".join(["|" + line + "|" for line in str(self).split("\n")])
            + "\n"
            + top_bot
        )

    def fill(self, ch: str | bytes = SPACE) -> None:
        """Fill the whole screen with the character ch."""
        if isinstance(ch, bytes):
            ch = self._decode(ch)

        self.fill_region(1, 1, self.rows, self.cols, ch)

    def fill_region(self, rs: int, cs: int, re: int, ce: int, ch: str | bytes = SPACE) -> None:
        """Fill the region bounded by (rs, cs) and (re, ce) with the character ch."""
        if isinstance(ch, bytes):
            ch = self._decode(ch)

        rs = constrain(rs, 1, self.rows)
        re = constrain(re, 1, self.rows)
        cs = constrain(cs, 1, self.cols)
        ce = constrain(ce, 1, self.cols)
        if rs > re:
            rs, re = re, rs
        if cs > ce:
            cs, ce = ce, cs
        for r in range(rs, re + 1):
            for c in range(cs, ce + 1):
                self.put_abs(r, c, ch)

    def cr(self) -> None:
        """Move the cursor to the beginning (col 1) of the current row."""
        self.cursor_home(self.cur_r, 1)

    def lf(self) -> None:
        """Move the cursor down with scrolling."""
        old_r = self.cur_r
        self.cursor_down()
        if old_r == self.cur_r:
            self.scroll_up()
            self.erase_line()

    def crlf(self) -> None:
        """Advance the cursor with CRLF properties.

        The cursor will line wrap and the screen may scroll.
        """
        self.cr()
        self.lf()

    def newline(self) -> None:
        """Alias for :meth:`crlf`."""
        self.crlf()

    def put_abs(self, r: int, c: int, ch: str | bytes) -> None:
        """Screen array starts at 1 index."""
        r = constrain(r, 1, self.rows)
        c = constrain(c, 1, self.cols)
        ch = self._decode(ch)[0] if isinstance(ch, bytes) else ch[0]
        self.w[r - 1][c - 1] = ch

    def put(self, ch: str | bytes) -> None:
        """Put a character at the current cursor position."""
        if isinstance(ch, bytes):
            ch = self._decode(ch)

        self.put_abs(self.cur_r, self.cur_c, ch)

    def insert_abs(self, r: int, c: int, ch: str | bytes) -> None:
        """Insert a character at (r, c).

        Everything under and to the right is shifted right one character. The
        last character of the line is lost.
        """
        if isinstance(ch, bytes):
            ch = self._decode(ch)

        r = constrain(r, 1, self.rows)
        c = constrain(c, 1, self.cols)
        for ci in range(self.cols, c, -1):
            self.put_abs(r, ci, self.get_abs(r, ci - 1))
        self.put_abs(r, c, ch)

    def insert(self, ch: str | bytes) -> None:
        """Insert a character at the current cursor position."""
        if isinstance(ch, bytes):
            ch = self._decode(ch)

        self.insert_abs(self.cur_r, self.cur_c, ch)

    def get_abs(self, r: int, c: int) -> str:
        """Return the character at (r, c)."""
        r = constrain(r, 1, self.rows)
        c = constrain(c, 1, self.cols)
        return self.w[r - 1][c - 1]

    def get(self) -> None:
        """Read the character at the current cursor position.

        Nothing is returned; use :meth:`get_abs` to obtain the character.
        """
        self.get_abs(self.cur_r, self.cur_c)

    def get_region(self, rs: int, cs: int, re: int, ce: int) -> list[str]:
        """Return a list of lines representing the region."""
        rs = constrain(rs, 1, self.rows)
        re = constrain(re, 1, self.rows)
        cs = constrain(cs, 1, self.cols)
        ce = constrain(ce, 1, self.cols)
        if rs > re:
            rs, re = re, rs
        if cs > ce:
            cs, ce = ce, cs
        sc = []
        for r in range(rs, re + 1):
            line = ""
            for c in range(cs, ce + 1):
                ch = self.get_abs(r, c)
                line = line + ch
            sc.append(line)
        return sc

    def cursor_constrain(self) -> None:
        """Keep the cursor within the screen area."""
        self.cur_r = constrain(self.cur_r, 1, self.rows)
        self.cur_c = constrain(self.cur_c, 1, self.cols)

    def cursor_home(self, r: int = 1, c: int = 1) -> None:  # <ESC>[{ROW};{COLUMN}H
        """Move the cursor to row r, column c."""
        self.cur_r = r
        self.cur_c = c
        self.cursor_constrain()

    def cursor_back(self, count: int = 1) -> None:  # <ESC>[{COUNT}D (not confused with down)
        """Move the cursor back by count columns."""
        self.cur_c = self.cur_c - count
        self.cursor_constrain()

    def cursor_down(self, count: int = 1) -> None:  # <ESC>[{COUNT}B (not confused with back)
        """Move the cursor down by count rows."""
        self.cur_r = self.cur_r + count
        self.cursor_constrain()

    def cursor_forward(self, count: int = 1) -> None:  # <ESC>[{COUNT}C
        """Move the cursor forward by count columns."""
        self.cur_c = self.cur_c + count
        self.cursor_constrain()

    def cursor_up(self, count: int = 1) -> None:  # <ESC>[{COUNT}A
        """Move the cursor up by count rows."""
        self.cur_r = self.cur_r - count
        self.cursor_constrain()

    def cursor_up_reverse(self) -> None:  # <ESC> M   (called RI -- Reverse Index)
        """Move the cursor up one row, scrolling if it is already at the top."""
        old_r = self.cur_r
        self.cursor_up()
        if old_r == self.cur_r:
            self.scroll_up()

    def cursor_force_position(self, r: int, c: int) -> None:  # <ESC>[{ROW};{COLUMN}f
        """Identical to Cursor Home."""
        self.cursor_home(r, c)

    def cursor_save(self) -> None:  # <ESC>[s
        """Save current cursor position."""
        self.cursor_save_attrs()

    def cursor_unsave(self) -> None:  # <ESC>[u
        """Restores cursor position after a Save Cursor."""
        self.cursor_restore_attrs()

    def cursor_save_attrs(self) -> None:  # <ESC>7
        """Save current cursor position."""
        self.cur_saved_r = self.cur_r
        self.cur_saved_c = self.cur_c

    def cursor_restore_attrs(self) -> None:  # <ESC>8
        """Restores cursor position after a Save Cursor."""
        self.cursor_home(self.cur_saved_r, self.cur_saved_c)

    def scroll_constrain(self) -> None:
        """Keep the scroll region within the screen region."""
        if self.scroll_row_start <= 0:
            self.scroll_row_start = 1
        self.scroll_row_end = min(self.scroll_row_end, self.rows)

    def scroll_screen(self) -> None:  # <ESC>[r
        """Enable scrolling for entire display."""
        self.scroll_row_start = 1
        self.scroll_row_end = self.rows

    def scroll_screen_rows(self, rs: int, re: int) -> None:  # <ESC>[{start};{end}r
        """Enable scrolling from row {start} to row {end}."""
        self.scroll_row_start = rs
        self.scroll_row_end = re
        self.scroll_constrain()

    def scroll_down(self) -> None:  # <ESC>D
        """Scroll display down one line."""
        # Screen is indexed from 1, but arrays are indexed from 0.
        s = self.scroll_row_start - 1
        e = self.scroll_row_end - 1
        self.w[s + 1 : e + 1] = copy.deepcopy(self.w[s:e])

    def scroll_up(self) -> None:  # <ESC>M
        """Scroll display up one line."""
        # Screen is indexed from 1, but arrays are indexed from 0.
        s = self.scroll_row_start - 1
        e = self.scroll_row_end - 1
        self.w[s:e] = copy.deepcopy(self.w[s + 1 : e + 1])

    def erase_end_of_line(self) -> None:  # <ESC>[0K -or- <ESC>[K
        """Erase from the current cursor position to the end of the current line."""
        self.fill_region(self.cur_r, self.cur_c, self.cur_r, self.cols)

    def erase_start_of_line(self) -> None:  # <ESC>[1K
        """Erase from the current cursor position to the start of the current line."""
        self.fill_region(self.cur_r, 1, self.cur_r, self.cur_c)

    def erase_line(self) -> None:  # <ESC>[2K
        """Erases the entire current line."""
        self.fill_region(self.cur_r, 1, self.cur_r, self.cols)

    def erase_down(self) -> None:  # <ESC>[0J -or- <ESC>[J
        """Erase the screen from the current line down to the bottom of the screen."""
        self.erase_end_of_line()
        self.fill_region(self.cur_r + 1, 1, self.rows, self.cols)

    def erase_up(self) -> None:  # <ESC>[1J
        """Erase the screen from the current line up to the top of the screen."""
        self.erase_start_of_line()
        self.fill_region(self.cur_r - 1, 1, 1, self.cols)

    def erase_screen(self) -> None:  # <ESC>[2J
        """Erases the screen with the background color."""
        self.fill()

    def set_tab(self) -> None:  # <ESC>H
        """Set a tab at the current position."""

    def clear_tab(self) -> None:  # <ESC>[g
        """Clear the tab at the current position."""

    def clear_all_tabs(self) -> None:  # <ESC>[3g
        """Clear all tabs."""


#        Insert line             Esc [ Pn L
#        Delete line             Esc [ Pn M
#        Delete character        Esc [ Pn P
#        Scrolling region        Esc [ Pn(top);Pn(bot) r
