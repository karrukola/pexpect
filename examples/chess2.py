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
import time
from pathlib import Path

import pexpect
from pexpect import ANSI


class Chess:
    """Drive one gnuchess instance through the ANSI screen emulator."""

    def __init__(self, engine="/usr/local/bin/gnuchess -a -h 1") -> None:
        """Spawn the chess engine and its screen emulator."""
        self.child = pexpect.spawn(engine)
        self.term = ANSI.ANSI()
        self.last_computer_move = ""

    def read_until_cursor(self, r, c, e=0) -> int:
        """Feed the screen emulator until the cursor sits at row ``r``, column ``c``.

        Eventually something like this should move into the screen class or
        a subclass. Maybe a combination of pexpect and screen...
        """
        with Path("log").open("a") as fout:
            while self.term.cur_r != r or self.term.cur_c != c:
                try:
                    k = self.child.read(1, 10)
                except pexpect.ExceptionPexpect:
                    print(f"EXCEPTION, (r,c):({self.term.cur_r},{self.term.cur_c})\n")
                    sys.stdout.flush()
                self.term.process(k)
                fout.write(f"(r,c):({self.term.cur_r},{self.term.cur_c})\n")
                fout.flush()
                if e:
                    sys.stdout.write(k)
                    sys.stdout.flush()
                if self.term.cur_r == r and self.term.cur_c == c:
                    return 1
            print("DIDNT EVEN HIT.")
            return 1

    def expect_region(self) -> None:
        """Match against a region of the emulated screen.

        A placeholder: this is another method that would be moved into the
        screen class.
        """

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

    def do_move(self, move, e=0) -> None:
        """Wait for the input cursor, then send ``move``."""
        time.sleep(1)
        self.read_until_cursor(19, 60, e)
        self.child.sendline(move)

    def wait(self, color) -> None:
        """Block until the screen says it is ``color``'s turn to play."""
        while 1:
            r = self.term.get_region(14, 50, 14, 60)[0]
            r = r.strip()
            if r == color:
                return
            time.sleep(1)

    def parse_computer_move(self, s):
        """Pull the move out of the engine's "My move is: " line."""
        i = s.find("is: ")
        return s[i + 3 : i + 9]

    def get_computer_move(self, e=0):
        """Return the move the engine just played."""
        time.sleep(1)
        self.read_until_cursor(19, 60, e)
        time.sleep(1)
        r = self.term.get_region(17, 50, 17, 62)[0]
        return self.parse_computer_move(r)

    def switch(self) -> None:
        """Swap sides with the engine."""
        print("switching")
        self.child.sendline("switch")

    def set_depth(self, depth) -> None:
        """Set how many plies ahead the engine searches."""
        self.child.sendline("depth")
        self.child.expect("depth=")
        self.child.sendline(str(depth))

    def quit(self) -> None:
        """Tell the engine to exit."""
        self.child.sendline("quit")


def log(s) -> None:
    """Print ``s`` and append it to moves.log."""
    print(s)
    sys.stdout.flush()
    with Path("moves.log").open("a") as fout:
        fout.write(s + "\n")


print("Starting...")

black = Chess()
white = Chess()
white.read_until_cursor(19, 60, 1)
white.switch()

done = 0
while not done:
    white.wait("Black")
    move_white = white.get_computer_move(1)
    log("move white:" + move_white)

    black.do_move(move_white)
    black.wait("White")
    move_black = black.get_computer_move()
    log("move black:" + move_black)

    white.do_move(move_black, 1)

white.quit()
