#!/usr/bin/env python
"""Detect the expected Canonical mode length using pexpect.

All systems use the value of MAX_CANON which can be found using
fpathconf(3) value PC_MAX_CANON -- with the exception of Linux
and FreeBSD.

Linux, though defining a value of 255, actually honors the value
of 4096 from linux kernel include file tty.h definition
N_TTY_BUF_SIZE.

Linux also does not honor IMAXBEL. termios(3) states, "Linux does not
implement this bit, and acts as if it is always set." Although these
tests ensure it is enabled, this is a non-op for Linux.

FreeBSD supports neither, and instead uses a fraction (1/5) of the tty
speed which is always 9600.  Therefor, the maximum limited input line
length is 9600 / 5 = 1920.

These tests only ensure the correctness of the behavior described by
the sendline() docstring -- the values listed there, and above should
be equal to the output of the given OS described, but no promises!
"""

# std import
import sys
from pathlib import Path


def detect_maxcanon() -> None:
    """Probe the tty for MAX_CANON by sending ever more bytes until it rings the bel."""
    # PLC0415: lazy so __main__ reports a missing pexpect
    import pexpect  # lazy so __main__ can report a missing pexpect  # noqa: PLC0415

    # re-use pexpect/replwrap.py's bashrc file
    bashrc = str(Path(__file__).resolve().parent.parent / "pexpect" / "bashrc.sh")

    child = pexpect.spawn("bash", ["--rcfile", bashrc], echo=True, encoding="utf8", timeout=3)

    child.sendline("echo -n READY_; echo GO")
    child.expect_exact("READY_GO")

    child.sendline("stty icanon imaxbel erase ^H; echo -n retval: $?")
    child.expect_exact("retval: 0")

    child.sendline("echo -n GO_; echo AGAIN")
    child.expect_exact("GO_AGAIN")
    child.sendline("cat")

    child.delaybeforesend = 0

    column, blocksize = 0, 64
    ch_marker = "_"

    print("auto-detecting MAX_CANON: ", end="")
    sys.stdout.flush()

    while True:
        child.send(ch_marker * blocksize)
        result = child.expect([ch_marker * blocksize, "\a"])
        if result == 0:
            # entire block fit without emitting bel
            column += blocksize
        elif result == 1:
            # an '\a' was emitted, count the number of ch_markers
            # found since last blocksize, determining our MAX_CANON
            column += child.before.count(ch_marker)
            break
    print(column)


if __name__ == "__main__":
    try:
        detect_maxcanon()
    except ImportError:
        # we'd like to use this with CI -- but until we integrate
        # with tox, we can't determine a period in testing when
        # the pexpect module has been installed
        print(
            "warning: pexpect not in module path, MAX_CANON "
            "could not be determined by systems test.",
            file=sys.stderr,
        )
