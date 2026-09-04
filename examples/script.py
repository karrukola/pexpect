#!/usr/bin/env python

"""Spawn a sub-shell (bash) and give the user interactive control.

The entire shell session is logged to a file called script.log. This behaves
much like the classic BSD command 'script'.

./script.py [-a] [-c command] {logfilename}

    logfilename : This is the name of the log file. Default is script.log.
    -a : Append to log file. Default is to overwrite log file.
    -c : spawn command. Default is to spawn the sh shell.

Example:
    This will start a bash shell and append to the log named my_session.log:

        ./script.py -a -c bash my_session.log

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

import fcntl
import getopt
import os
import signal
import struct
import sys
import termios
import time
from pathlib import Path

import pexpect

global_pexpect_instance = None  # Used by signal handler


def exit_with_usage() -> None:
    """Print this script's documentation and exit with a failure status."""
    print(globals()["__doc__"])
    os._exit(1)


def main() -> int:
    """Log an interactive shell session to a file, then return an exit status."""
    ######################################################################
    # Parse the options, arguments, get ready, etc.
    ######################################################################
    try:
        optlist, args = getopt.getopt(sys.argv[1:], "h?ac:", ["help", "h", "?"])
    except getopt.GetoptError as e:
        print(str(e))
        exit_with_usage()
    options = dict(optlist)
    if len(args) > 1:
        exit_with_usage()

    if [elem for elem in options if elem in ["-h", "--h", "-?", "--?", "--help"]]:
        print("Help:")
        exit_with_usage()

    script_filename = args[0] if len(args) == 1 else "script.log"
    mode = "ab" if "-a" in options else "wb"
    # SIM115: logfile outlives the block
    fout = Path(script_filename).open(mode)  # outlives this block  # noqa: SIM115
    command = options.get("-c", "sh")

    # Begin log with date/time in the form CCCCyymm.hhmmss
    year, month, day, hour, minute, second = time.localtime()[:6]
    fout.write(f"# {year:4d}{month:02d}{day:02d}.{hour:02d}{minute:02d}{second:02d} \n")

    ######################################################################
    # Start the interactive session
    ######################################################################
    p = pexpect.spawn(command)
    p.logfile = fout
    # PLW0603: the SIGWINCH global is what this teaches
    global global_pexpect_instance  # the SIGWINCH handler needs the spawn  # noqa: PLW0603
    global_pexpect_instance = p
    signal.signal(signal.SIGWINCH, sigwinch_passthrough)

    print("Script recording started. Type ^] (ASCII 29) to escape from the script shell.")
    p.interact(chr(29))
    fout.close()
    return 0


def sigwinch_passthrough(_sig, _data) -> None:
    """Resize the child's pty to match the terminal when SIGWINCH arrives."""
    # Check for buggy platforms (see pexpect.setwinsize()).
    tiocgwinsz = getattr(termios, "TIOCGWINSZ", 1074295912)  # assumed value if missing
    s = struct.pack("HHHH", 0, 0, 0, 0)
    a = struct.unpack("HHHH", fcntl.ioctl(sys.stdout.fileno(), tiocgwinsz, s))
    global_pexpect_instance.setwinsize(a[0], a[1])


if __name__ == "__main__":
    main()
