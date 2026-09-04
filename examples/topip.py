#!/usr/bin/env python

r"""Run netstat on a local or remote server and group the connections by IP address.

It calculates some simple statistical information on the number of external
inet connections. This can be used to detect if one IP address is taking up an
excessive number of connections. It can also send an email alert if a given IP
address exceeds a threshold between runs of the script. This script can be used
as a drop-in Munin plugin or it can be used stand-alone from cron. I used this
on a busy web server that would sometimes get hit with denial of service
attacks. This made it easy to see if a script was opening many multiple
connections. A typical browser would open fewer than 10 connections at once.
A script might open over 100 simultaneous connections.

./topip.py [-s server_hostname] [-u username] [-p password]
        {-a from_addr,to_addr} {-n N} {-v} {--ipv6}

    -s : hostname of the remote server to login to.
    -u : username to user for login.
    -p : password to user for login.
    -n : print stddev for the the number of the top 'N' ipaddresses.
    -v : verbose - print stats and list of top ipaddresses.
    -a : send alert if stddev goes over 20.
    -l : to log message to /var/log/topip.log
    --ipv6 : this parses netstat output that includes ipv6 format.
        Note that this actually only works with ipv4 addresses, but for
        versions of netstat that print in ipv6 format.
    --stdev=N : Where N is an integer. This sets the trigger point
        for alerts and logs. Default is to trigger if the
        max value is over 5 standard deviations.

Example:
    This will print stats for the top IP addresses connected to the given host:

        ./topip.py -s www.example.com -u mylogin -p mypassword -n 10 -v

    This will send an alert email if the maxip goes over the stddev trigger
    value and the the current top ip is the same as the last top ip
    (/tmp/topip.last):

        ./topip.py -s www.example.com -u mylogin -p mypassword \\
                -n 10 -v -a alert@example.com,user@example.com

    This will print the connection stats for the localhost in Munin format:

        ./topip.py

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

# See http://pexpect.sourceforge.net/
import contextlib
import getopt
import getpass
import os
import pickle
import smtplib
import sys
import time
from pathlib import Path

import pexpect
from pexpect import pxssh

TOPIP_LOG_FILE = "/var/log/topip.log"
TOPIP_LAST_RUN_STATS = "/var/run/topip.last"
DEFAULT_STDDEV_TRIGGER = 5


def exit_with_usage() -> None:
    """Print this script's documentation and exit with a failure status."""
    print(globals()["__doc__"])
    os._exit(1)


def stats(r):
    """Return a dict of the median, average, standard deviation, min and max of a sequence.

    >>> from topip import stats
    >>> print stats([5,6,8,9])
    {'med': 8, 'max': 9, 'avg': 7.0, 'stddev': 1.5811388300841898, 'min': 5}
    >>> print stats([1000,1006,1008,1014])
    {'med': 1008, 'max': 1014, 'avg': 1007.0, 'stddev': 5.0, 'min': 1000}
    >>> print stats([1,3,4,5,18,16,4,3,3,5,13])
    {'med': 4, 'max': 18, 'avg': 6.8181818181818183, 'stddev': 5.6216817577237475, 'min': 1}
    >>> print stats([1,3,4,5,18,16,4,3,3,5,13,14,5,6,7,8,7,6,6,7,5,6,4,14,7])
    {'med': 6, 'max': 18, 'avg': 7.0800000000000001, 'stddev': 4.3259218670706474, 'min': 1}
    """
    total = sum(r)
    avg = float(total) / float(len(r))
    sdsq = sum([(i - avg) ** 2 for i in r])
    s = sorted(r)
    return dict(
        list(
            zip(
                ["med", "avg", "stddev", "min", "max"],
                (s[len(s) // 2], avg, (sdsq / len(r)) ** 0.5, min(r), max(r)),
                strict=False,
            )
        )
    )


def send_alert(message, subject, addr_from, addr_to, smtp_server="localhost") -> None:
    """Send an email alert."""
    message = f"From: {addr_from}\r\nTo: {addr_to}\r\nSubject: {subject}\r\n\r\n" + message
    server = smtplib.SMTP(smtp_server)
    server.sendmail(addr_from, addr_to, message)
    server.quit()


def parse_command_line() -> tuple[dict[str, str], list[str]]:
    """Return the command line as an options dict and a list of positional arguments."""
    try:
        optlist, args = getopt.getopt(
            sys.argv[1:], "h?valqs:u:p:n:", ["help", "h", "?", "ipv6", "stddev="]
        )
    except getopt.GetoptError as e:
        print(str(e))
        exit_with_usage()
    if [elem for elem in optlist if elem in ["-h", "--h", "-?", "--?", "--help"]]:
        print("Help:")
        exit_with_usage()
    return dict(optlist), args


def print_munin_config() -> None:
    """Print the Munin plugin configuration for this graph."""
    print("graph_title Netstat Connections per IP")
    print("graph_vlabel Socket connections per IP")
    print("connections_max.label max")
    print("connections_max.info Maximum number of connections per IP")
    print("connections_avg.label avg")
    print("connections_avg.info Average number of connections per IP")
    print("connections_stddev.label stddev")
    print("connections_stddev.info Standard deviation")


def netstat_pattern(*, ipv6: bool) -> str:
    """Return the pattern that captures the peer address and port of a netstat line."""
    if ipv6:
        return r"(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+::ffff:(\S+):(\S+)\s+.*?\r"
    return r"(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(?:::ffff:)*(\S+):(\S+)\s+.*?\r"


def start_netstat(hostname, username, password, *, use_localhost: bool):
    """Run 'netstat -n -t' locally or over SSH; return the child and its prompt pattern."""
    if use_localhost:
        return pexpect.spawn("netstat -n -t"), pexpect.TIMEOUT
    p = pxssh.pxssh()
    p.login(hostname, username, password)
    p.sendline("netstat -n -t")
    return p, p.PROMPT


def count_connections_per_ip(p, prompt, pattern) -> list[tuple[str, int]]:
    """Return (ip, connection count) pairs from netstat's output, least busy first."""
    ip_list = {}
    # Reading stops on EOF (local netstat exits) or on a timeout waiting for the prompt.
    with contextlib.suppress(Exception):
        while 1:
            i = p.expect([prompt, pattern])
            if i == 0:
                break
            k = p.match.groups()[4].decode("utf-8")
            if k in ip_list:
                ip_list[k] = ip_list[k] + 1
            else:
                ip_list[k] = 1

    # remove a few common, uninteresting addresses from the dictionary.
    ip_list = {key: value for key, value in ip_list.items() if "192.168." not in key}
    ip_list = {key: value for key, value in ip_list.items() if "127.0.0.1" not in key}

    ip_list = list(ip_list.items())
    ip_list.sort(key=lambda x: x[1])
    return ip_list


def load_last_stats() -> dict:
    """Return the stats saved by the previous run, or an empty result if there are none."""
    try:
        with Path(TOPIP_LAST_RUN_STATS).open("rb") as fin:
            # S301: unpickles only its own state file
            return pickle.load(fin)  # our own state file, written below  # noqa: S301
    except (OSError, EOFError, pickle.PickleError):
        return {"maxip": None}


def save_last_stats(s) -> None:
    """Save this run's stats for the next run to compare against."""
    # Best effort: the state directory is usually only writable by root.
    with contextlib.suppress(OSError):
        path = Path(TOPIP_LAST_RUN_STATS)
        with path.open("wb") as fout:
            pickle.dump(s, fout)
        path.chmod(0o664)


def log_event(s) -> None:
    """Append the busiest IP and its connection count to the log file."""
    with Path(TOPIP_LOG_FILE).open("a") as fout:
        dts = time.asctime()
        fout.write(f"{dts} - {s['maxip'][1]:d} connections from {s['maxip'][0]!s}\n")


def resolve_target(options: dict[str, str]) -> tuple[str, str, str, bool]:
    """Return (hostname, username, password, use_localhost), asking for what is missing."""
    # if host was not specified then assume localhost munin plugin.
    hostname = options.get("-s", "localhost")
    # If localhost then don't ask for username/password.
    use_localhost = hostname in {"localhost", "127.0.0.1"}
    username = password = ""
    if not use_localhost:
        username = options["-u"] if "-u" in options else input("username: ")
        password = options["-p"] if "-p" in options else getpass.getpass("password: ")
    return hostname, username, password, use_localhost


def alert_and_log(s, hostname: str, options: dict[str, str]) -> None:
    """Alert and log if the busiest IP stayed above the trigger for two runs, then save state."""
    verbose = "-v" in options
    stddev_trigger = (
        float(options["--stddev"]) if "--stddev" in options else DEFAULT_STDDEV_TRIGGER
    )
    # load the stats from the last run.
    last_stats = load_last_stats()

    if s["maxip"][1] > (s["stddev"] * stddev_trigger) and s["maxip"] == last_stats["maxip"]:
        if verbose:
            print("The maxip has been above trigger for two consecutive samples.")
        if "-a" in options:
            if verbose:
                print("SENDING ALERT EMAIL")
            (alert_addr_from, alert_addr_to) = tuple(options["-a"].split(","))
            send_alert(str(s), f"ALERT on {hostname}", alert_addr_from, alert_addr_to)
        if "-l" in options:
            if verbose:
                print("LOGGING THIS EVENT")
            log_event(s)

    save_last_stats(s)


def main() -> int | None:
    """Sample netstat, then report, alert on or log the busiest IP address."""
    options, args = parse_command_line()

    if len(args) > 0:
        if args[0] == "config":
            print_munin_config()
            return 0
        if args[0] != "":
            print(args, len(args))
            return 0
    # Without -s we are the Munin plugin sampling the local host.
    munin_flag = "-s" not in options
    hostname, username, password, use_localhost = resolve_target(options)
    average_n = int(options["-n"]) if "-n" in options else None
    verbose = "-v" in options

    # run netstat (either locally or via SSH).
    p, prompt = start_netstat(hostname, username, password, use_localhost=use_localhost)

    # For each matching netstat line put the ip address in the list.
    ip_list = count_connections_per_ip(p, prompt, netstat_pattern(ipv6="--ipv6" in options))
    if len(ip_list) < 1:
        if verbose:
            print("Warning: no networks connections worth looking at.")
        return 0

    # generate some stats for the ip addresses found.
    if average_n is not None and average_n <= 1:
        average_n = None
    # Reminder: the * unary operator treats the list elements as arguments.
    zipped = zip(*ip_list[0:average_n], strict=False)
    s = stats(list(zipped)[1])
    s["maxip"] = ip_list[0]

    # print munin-style or verbose results for the stats.
    if munin_flag:
        print("connections_max.value", s["max"])
        print("connections_avg.value", s["avg"])
        print("connections_stddev.value", s["stddev"])
        return 0
    if verbose:
        print()

    alert_and_log(s, hostname, options)
    return None


if __name__ == "__main__":
    main()
