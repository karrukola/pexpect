#!/usr/bin/env python

"""Run Apache Status on a remote host and print the number of requests per second.

./astat.py [-s server_hostname] [-u username] [-p password]
    -s : hostname of the remote server to login to.
    -u : username to user for login.
    -p : Password to user for login.

Example:
    This will print information about the given host:
        ./astat.py -s www.example.com -u mylogin -p mypassword

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
import sys

from pexpect import pxssh


def exit_with_usage() -> None:
    """Print this script's docstring as usage and exit with a failure status."""
    print(globals()["__doc__"])
    os._exit(1)


def main() -> None:
    """Log in over ssh and print the Apache request rate."""
    ######################################################################
    ## Parse the options, arguments, get ready, etc.
    ######################################################################
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

    hostname = options["-s"] if "-s" in options else input("hostname: ")
    username = options["-u"] if "-u" in options else input("username: ")
    password = options["-p"] if "-p" in options else getpass.getpass("password: ")

    #
    # Login via SSH
    #
    p = pxssh.pxssh()
    p.login(hostname, username, password)
    p.sendline("apachectl status")
    p.expect(r"([0-9]+\.[0-9]+)\s*requests/sec")
    requests_per_second = p.match.groups()[0]
    p.logout()
    print(requests_per_second)


if __name__ == "__main__":
    main()
