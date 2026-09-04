#!/usr/bin/env python

"""Run a sequence of commands on a remote host using SSH.

It runs simple system checks such as uptime and free to monitor the state of
the remote host.

./monitor.py [-s server_hostname] [-u username] [-p password]
    -s : hostname of the remote server to login to.
    -u : username to user for login.
    -p : Password to user for login.

Example:
    This will print information about the given host:
        ./monitor.py -s www.example.com -u mylogin -p mypassword

It works like this:
    Login via SSH (This is the hardest part).
    Run and parse 'uptime'.
    Run 'iostat'.
    Run 'vmstat'.
    Run 'netstat'
    Run 'free'.
    Exit the remote host.

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

import getopt
import getpass
import os
import re
import sys

import pexpect

#
# Some constants.
#
COMMAND_PROMPT = "[#$] "  ### This is way too simple for industrial use -- we will change is ASAP.
TERMINAL_PROMPT = r"(?i)terminal type\?"
TERMINAL_TYPE = "vt100"
# This is the prompt we get if SSH does not have the remote host's public key stored in the cache.
SSH_NEWKEY = "(?i)are you sure you want to continue connecting"
# The prompt we switch to once logged in. It is unique enough not to match command output.
UNIQUE_PROMPT = r"\[PEXPECT\]\$ "


def exit_with_usage() -> None:
    """Print this script's documentation and exit with a failure status."""
    print(globals()["__doc__"])
    os._exit(1)


def parse_args() -> tuple[str, str, str]:
    """Return the host, username and password to use, asking for whatever was not given."""
    try:
        optlist, args = getopt.getopt(sys.argv[1:], "h?s:u:p:", ["help", "h", "?"])
    except getopt.GetoptError as e:
        print(str(e))
        exit_with_usage()
    options = dict(optlist)
    if len(args) > 1:
        exit_with_usage()

    if [elem for elem in options if elem in ["-h", "--h", "-?", "--?", "--help"]]:
        print("Help:")
        exit_with_usage()

    host = options["-s"] if "-s" in options else input("hostname: ")
    user = options["-u"] if "-u" in options else input("username: ")
    password = options["-p"] if "-p" in options else getpass.getpass("password: ")
    return host, user, password


def login(host: str, user: str, password: str) -> pexpect.spawn:
    """Log in over SSH and return the child, with its shell prompt set to UNIQUE_PROMPT."""
    child = pexpect.spawn(f"ssh -l {user} {host}")
    i = child.expect([pexpect.TIMEOUT, SSH_NEWKEY, COMMAND_PROMPT, "(?i)password"])
    if i == 0:  # Timeout
        print("ERROR! could not login with SSH. Here is what SSH said:")
        print(child.before, child.after)
        print(str(child))
        sys.exit(1)
    if i == 1:  # In this case SSH does not have the public key cached.
        child.sendline("yes")
        child.expect("(?i)password")
    # PLR2004: index into the expect() list above
    if i == 2:  # index into the expect() list above  # noqa: PLR2004
        # This may happen if a public key was setup to automatically login.
        # But beware, the COMMAND_PROMPT at this point is very trivial and
        # could be fooled by some output in the MOTD or login message.
        pass
    # PLR2004: index into the expect() list above
    if i == 3:  # index into the expect() list above  # noqa: PLR2004
        child.sendline(password)
        # Now we are either at the command prompt or
        # the login process is asking for our terminal type.
        i = child.expect([COMMAND_PROMPT, TERMINAL_PROMPT])
        if i == 1:
            child.sendline(TERMINAL_TYPE)
            child.expect(COMMAND_PROMPT)
    #
    # Set command prompt to something more unique.
    #
    child.sendline(r"PS1='[PEXPECT]\$ '")  # In case of sh-style
    i = child.expect([pexpect.TIMEOUT, UNIQUE_PROMPT], timeout=10)
    if i == 0:
        print("# Couldn't set sh-style prompt -- trying csh-style.")
        child.sendline(r"set prompt='[PEXPECT]\$ '")
        i = child.expect([pexpect.TIMEOUT, UNIQUE_PROMPT], timeout=10)
        if i == 0:
            print("Failed to set command prompt using sh or csh style.")
            print("Response was:")
            print(child.before)
            sys.exit(1)
    return child


def report_uptime(child: pexpect.spawn) -> None:
    """Run 'uptime' on the remote host and print the uptime and load averages."""
    child.sendline("uptime")
    child.expect(
        r"up\s+(.*?),\s+([0-9]+) users?,\s+load averages?: "
        r"([0-9]+\.[0-9][0-9]),?\s+([0-9]+\.[0-9][0-9]),?\s+([0-9]+\.[0-9][0-9])"
    )
    duration, users, av1, av5, av15 = child.match.groups()
    # The duration field is also broken into its parts here, but nothing consumes them
    # yet: the report below prints the raw duration string. This is the unfinished start
    # of a formatter that would render "3 days, 4 hours, 5 mins".
    _days = "0"
    _hours = "0"
    _mins = "0"
    if "day" in duration:
        child.match = re.search(r"([0-9]+)\s+day", duration)
        _days = str(int(child.match.group(1)))
    if ":" in duration:
        child.match = re.search("([0-9]+):([0-9]+)", duration)
        _hours = str(int(child.match.group(1)))
        _mins = str(int(child.match.group(2)))
    if "min" in duration:
        child.match = re.search(r"([0-9]+)\s+min", duration)
        _mins = str(int(child.match.group(1)))
    print()
    print(f"Uptime: {duration} days, {users} users, {av1} (1 min), {av5} (5 min), {av15} (15 min)")
    child.expect(UNIQUE_PROMPT)


def main() -> None:
    """Log in to the remote host and print a report of a few system checks."""
    host, user, password = parse_args()
    child = login(host, user, password)

    # Now we should be at the command prompt and ready to run some commands.
    print("---------------------------------------")
    print("Report of commands run on remote host.")
    print("---------------------------------------")

    # Run uname.
    child.sendline("uname -a")
    child.expect(UNIQUE_PROMPT)
    print(child.before)
    linux_mode = 1 if "linux" in child.before.lower() else 0

    # Run and parse 'uptime'.
    report_uptime(child)

    # Run iostat.
    child.sendline("iostat")
    child.expect(UNIQUE_PROMPT)
    print(child.before)

    # Run vmstat.
    child.sendline("vmstat")
    child.expect(UNIQUE_PROMPT)
    print(child.before)

    # Run free.
    if linux_mode:
        child.sendline("free")  # Linux systems only.
        child.expect(UNIQUE_PROMPT)
        print(child.before)

    # Run df.
    child.sendline("df")
    child.expect(UNIQUE_PROMPT)
    print(child.before)

    # Run lsof.
    child.sendline("lsof")
    child.expect(UNIQUE_PROMPT)
    print(child.before)

    # Other commands worth adding here in the same style: 'netstat', or
    # 'mysql -p -e "SHOW STATUS;"' -- the latter needs its own password prompt handled.

    # Now exit the remote host.
    child.sendline("exit")
    index = child.expect([pexpect.EOF, "(?i)there are stopped jobs"])
    if index == 1:
        child.sendline("exit")
        child.expect(pexpect.EOF)


if __name__ == "__main__":
    main()
