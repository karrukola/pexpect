#!/usr/bin/env python

"""Demonstrate controlling a screen oriented application (curses).

Starts two instances of gnuchess and then pits them against each other.

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

import sys
from pathlib import Path

import pexpect
from pexpect import ANSI

# A gnuchess move is four characters, e.g. "e7e5".
MOVE_LEN = 4

REGEX_MOVE = r"(?:[a-z]|\x1b\[C)(?:[0-9]|\x1b\[C)(?:[a-z]|\x1b\[C)(?:[0-9]|\x1b\[C)"
REGEX_MOVE_PART = r"(?:[0-9]|\x1b\[C)(?:[a-z]|\x1b\[C)(?:[0-9]|\x1b\[C)"


class Chess:
    """Drive one gnuchess instance through the ANSI screen emulator."""

    def __init__(self, engine="/usr/local/bin/gnuchess -a -h 1") -> None:
        """Spawn the chess engine and its screen emulator."""
        self.child = pexpect.spawn(engine)
        self.term = ANSI.ANSI()
        self.last_computer_move = ""

    def read_until_cursor(self, r, c) -> int | None:
        """Echo the engine's output until the cursor reaches row ``r``, column ``c``."""
        with Path("log").open("a") as fout:
            while 1:
                k = self.child.read(1, 10)
                self.term.process(k)
                fout.write(f"(r,c):({self.term.cur_r},{self.term.cur_c})\n")
                fout.flush()
                if self.term.cur_r == r and self.term.cur_c == c:
                    return 1
                sys.stdout.write(k)
                sys.stdout.flush()
        return None

    def do_scan(self) -> None:
        """Echo the engine's output forever, logging the cursor position."""
        with Path("log").open("a") as fout:
            while 1:
                c = self.child.read(1, 10)
                self.term.process(c)
                fout.write(f"(r,c):({self.term.cur_r},{self.term.cur_c})\n")
                fout.flush()
                sys.stdout.write(c)
                sys.stdout.flush()

    def do_move(self, move):
        """Wait for the input cursor, then send ``move``."""
        self.read_until_cursor(19, 60)
        self.child.sendline(move)
        return move

    def get_computer_move(self):
        """Return the engine's next move, completing it from a partial redraw."""
        print("Here")
        i = self.child.expect([r"\[17;59H", r"\[17;58H"])
        print(i)
        if i == 0:
            self.child.expect(REGEX_MOVE)
            if len(self.child.after) < MOVE_LEN:
                self.child.after = self.child.after + self.last_computer_move[3]
        if i == 1:
            self.child.expect(REGEX_MOVE_PART)
            self.child.after = self.last_computer_move[0] + self.child.after
        print("", self.child.after)
        self.last_computer_move = self.child.after
        return self.child.after

    def switch(self) -> None:
        """Swap sides with the engine."""
        self.child.sendline("switch")

    def set_depth(self, depth) -> None:
        """Set how many plies ahead the engine searches."""
        self.child.sendline("depth")
        self.child.expect("depth=")
        self.child.sendline(str(depth))

    def quit(self) -> None:
        """Tell the engine to exit."""
        self.child.sendline("quit")


print("Starting...")
white = Chess()
white.do_move("b2b4")
white.read_until_cursor(19, 60)
c1 = white.term.get_abs(17, 58)
c2 = white.term.get_abs(17, 59)
c3 = white.term.get_abs(17, 60)
c4 = white.term.get_abs(17, 61)
with Path("log").open("a") as fout:
    fout.write(f"Computer:{c1}{c2}{c3}{c4}\n")
white.do_move("c2c4")
white.read_until_cursor(19, 60)
c1 = white.term.get_abs(17, 58)
c2 = white.term.get_abs(17, 59)
c3 = white.term.get_abs(17, 60)
c4 = white.term.get_abs(17, 61)
with Path("log").open("a") as fout:
    fout.write(f"Computer:{c1}{c2}{c3}{c4}\n")
white.do_scan()

sys.exit(1)


black = Chess()
white = Chess()
white.child.expect("Your move is")
white.switch()

move_white = white.get_first_computer_move()
print("first move white:", move_white)

black.do_first_move(move_white)
move_black = black.get_first_computer_move()
print("first move black:", move_black)

white.do_move(move_black)

done = 0
while not done:
    move_white = white.get_computer_move()
    print("move white:", move_white)

    black.do_move(move_white)
    move_black = black.get_computer_move()
    print("move black:", move_black)

    white.do_move(move_black)
    print("tail of loop")

white.quit()
