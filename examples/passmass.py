#!/usr/bin/env python

"""Change passwords on the named machines.

Usage: passmass host1 host2 host3 . . .

Note that login shell prompt on remote machine must end in # or $.

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

import getpass
import sys
from pathlib import Path

import pexpect

USAGE = """passmass host1 host2 host3 . . ."""
COMMAND_PROMPT = "[$#] "
TERMINAL_PROMPT = r"Terminal type\?"
TERMINAL_TYPE = "vt100"
SSH_NEWKEY = r"Are you sure you want to continue connecting \(yes/no\)\?"


def login(host, user, password):
    """Log in to ``host`` over ssh and return the child sitting at a shell prompt."""
    child = pexpect.spawn(f"ssh -l {user} {host}")
    # SIM115: the child logs to it until it exits
    fout = Path("LOG.TXT").open("wb")  # the child logs to it until it exits  # noqa: SIM115
    child.logfile_read = fout  # use child.logfile to also log writes (passwords!)

    i = child.expect([pexpect.TIMEOUT, SSH_NEWKEY, "[Pp]assword: "])
    if i == 0:  # Timeout
        print("ERROR!")
        print("SSH could not login. Here is what SSH said:")
        print(child.before, child.after)
        sys.exit(1)
    if i == 1:  # SSH does not have the public key. Just accept it.
        child.sendline("yes")
        child.expect("[Pp]assword: ")
    child.sendline(password)
    # Now we are either at the command prompt or
    # the login process is asking for our terminal type.
    i = child.expect(["Permission denied", TERMINAL_PROMPT, COMMAND_PROMPT])
    if i == 0:
        print("Permission denied on host:", host)
        sys.exit(1)
    if i == 1:
        child.sendline(TERMINAL_TYPE)
        child.expect(COMMAND_PROMPT)
    return child


# (current) UNIX password:
def change_password(child, oldpassword, newpassword) -> None:
    """Walk the remote passwd command from ``oldpassword`` to ``newpassword``."""
    child.sendline("passwd")
    i = child.expect(["[Oo]ld [Pp]assword", ".current.*password", "[Nn]ew [Pp]assword"])
    # Root does not require old password, so it gets to bypass the next step.
    if i in {0, 1}:
        child.sendline(oldpassword)
        child.expect("[Nn]ew [Pp]assword")
    child.sendline(newpassword)
    i = child.expect(["[Nn]ew [Pp]assword", "[Rr]etype", "[Rr]e-enter"])
    if i == 0:
        print("Host did not like new password. Here is what it said...")
        print(child.before)
        child.send(chr(3))  # Ctrl-C
        child.sendline("")  # This should tell remote passwd command to quit.
        return
    child.sendline(newpassword)


def main() -> int | None:
    """Ask for the old and new passwords, then change them on every host given."""
    if len(sys.argv) <= 1:
        print(USAGE)
        return 1

    user = input("Username: ")
    password = getpass.getpass("Current Password: ")
    newpassword = getpass.getpass("New Password: ")
    newpasswordconfirm = getpass.getpass("Confirm New Password: ")
    if newpassword != newpasswordconfirm:
        print("New Passwords do not match.")
        return 1

    for host in sys.argv[1:]:
        child = login(host, user, password)
        if child is None:
            print("Could not login to host:", host)
            continue
        print("Changing password on host:", host)
        change_password(child, password, newpassword)
        child.expect(COMMAND_PROMPT)
        child.sendline("exit")
    return None


if __name__ == "__main__":
    main()
