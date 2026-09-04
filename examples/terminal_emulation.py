#!/usr/bin/env python

"""Integrate pexpect with pyte, an ANSI terminal emulator.

These examples were taken from:
https://byexamples.github.io/byexample

We will execute three commands:
    - an 'echo' of a colored message to show how the ANSI colors can be removed.
    - an 'echo' of a very large message to show how pyte emulates the terminal
    geometry
    - a 'less' of a very small file to show how pyte handles not only
    the terminal geometry but also how interprets ANSI commands that control
    the position of the cursor.

See also https://github.com/pexpect/pexpect/issues/587

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

import os

import pyte

import pexpect

# The geometry of the terminal. Typically this is 24x80
# but we are going to us set a much smaller terminal
# to show how to change the default.
ROWS, COLS = 10, 40

# We create the Screen with the correct geometry and
# a Stream to process the output coming from pexpect.
screen = pyte.Screen(COLS, ROWS)
stream = pyte.Stream(screen)


def spawn_process(cmd):
    """Spawn ``cmd`` with the terminal geometry set two ways over.

    The geometry goes into the environment variables *and* into the
    'dimensions' parameter of pexpect.spawn, because not every program honors
    the geometry set by pexpect or by the env vars.
    """
    env = os.environ.copy()
    env.update({"LINES": str(ROWS), "COLUMNS": str(COLS)})

    return pexpect.spawn(cmd, echo=False, encoding="utf-8", dimensions=(ROWS, COLS), env=env)


def emulate_ansi_terminal(raw_output, *, clean=True):
    """Send ``raw_output`` to pyte.Stream and return the emulated pyte.Screen.

    In each call we *reset* the display so we don't get the same emulated
    output twice.

    Pyte emulates the whole terminal so it will return us ROWS rows of COLS
    columns each one completed with spaces. With ``clean`` we strip the
    whitespace on the right and any empty line.
    """
    stream.feed(raw_output)

    lines = screen.display
    screen.reset()

    if clean:
        lines = (line.rstrip() for line in lines)
        lines = (line for line in lines if line)

    return "\n".join(lines)


def pprint(out) -> None:
    """Print ``out`` framed by two rules as wide as the emulated terminal."""
    print("-" * COLS)
    print(out)
    print("-" * COLS)


print("\nFirst example: echo a message with ANSI color sequences.")
child = spawn_process(r'echo -e "\033[31mThis message should not be in red\033[0m"')
child.expect(pexpect.EOF)
out = emulate_ansi_terminal(child.before)

print(
    "This should *not* print any escape sequence,", "those were emulated and discarded by pyte.\n"
)
pprint(out)

print("\nSecond example: echo a very large message.")
msg = "aaaabbbb" * 8
child = spawn_process(f'echo "{msg}"')
child.expect(pexpect.EOF)
out = emulate_ansi_terminal(child.before)

print(
    "This should print the message in *two* lines because we",
    "configured a terminal very small and the message will",
    "not fit in one line.\n",
)
pprint(out)


print("\nThird example: run the less program.")
child = spawn_process(f'''bash -c "head -n7 '{__file__}' | less"''')
child.expect(pexpect.TIMEOUT, timeout=5)
out = emulate_ansi_terminal(child.before, clean=False)

pprint(out)
