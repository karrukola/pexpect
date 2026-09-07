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

import sys
import termios
import time

# a dumb PAM will print the password prompt first then set ECHO
# False. What it should do it set ECHO False first then print the
# prompt. Otherwise, if we see the password prompt and type out
# password real fast before it turns off ECHO then some or all of
# our password might be visibly echod back to us. Sounds unlikely?
# It happens.

# Seconds before ECHO goes off, how long it stays off, and how long the process
# lives after putting it back. Overridable from the command line so that a test
# can pick delays it is willing to wait for: waitnoecho() polls every 100 ms, so
# the first of them has to stay above that to be observable at all.
usage = f"usage: {sys.argv[0]} [echo_off_after [stays_off_for [linger]]]"
if len(sys.argv) > 4:  # noqa: PLR2004  # the script name plus the three delays
    print(usage)
    sys.exit(1)
try:
    echo_off_after, stays_off_for, linger = (
        float(value) for value in (*sys.argv[1:], *("3", "12", "2")[len(sys.argv) - 1 :])
    )
except ValueError:
    print(usage)
    sys.exit(1)

print("fake password:")
sys.stdout.flush()
time.sleep(echo_off_after)
attr = termios.tcgetattr(sys.stdout)
attr[3] = attr[3] & ~termios.ECHO
termios.tcsetattr(sys.stdout, termios.TCSANOW, attr)
time.sleep(stays_off_for)
attr[3] = attr[3] | termios.ECHO
termios.tcsetattr(sys.stdout, termios.TCSANOW, attr)
time.sleep(linger)
