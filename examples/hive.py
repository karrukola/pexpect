#!/usr/bin/env python

r"""hive -- Hive Shell.

This lets you ssh to a group of servers and control them as if they were one.
Each command you enter is sent to each host in parallel. The response of each
host is collected and printed. In normal synchronous mode Hive will wait for
each host to return the shell command line prompt. The shell prompt is used to
sync output.

Example:
    $ hive.py --sameuser --samepass host1.example.com host2.example.net
    username: myusername
    password:
    connecting to host1.example.com - OK
    connecting to host2.example.net - OK
    targeting hosts: 192.168.1.104 192.168.1.107
    CMD (? for help) > uptime
    =======================================================================
    host1.example.com
    -----------------------------------------------------------------------
    uptime
    23:49:55 up 74 days,  5:14,  2 users,  load average: 0.15, 0.05, 0.01
    =======================================================================
    host2.example.net
    -----------------------------------------------------------------------
    uptime
    23:53:02 up 1 day, 13:36,  2 users,  load average: 0.50, 0.40, 0.46
    =======================================================================

Other Usage Examples:

1. You will be asked for your username and password for each host.

    hive.py host1 host2 host3 ... hostN

2. You will be asked once for your username and password.
   This will be used for each host.

    hive.py --sameuser --samepass host1 host2 host3 ... hostN

3. Give a username and password on the command-line:

    hive.py user1:pass2@host1 user2:pass2@host2 ... userN:passN@hostN

You can use an extended host notation to specify username, password, and host
instead of entering auth information interactively. Where you would enter a
host name use this format:

    username:password@host

This assumes that ':' is not part of the password. If your password contains a
':' then you can use '\\:' to indicate a ':' and '\\\\' to indicate a single
'\\'. Remember that this information will appear in the process listing. Anyone
on your machine can see this auth information. This is not secure.

This is a crude script that begs to be multithreaded. But it serves its
purpose.

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


# TODO add feature to support username:password@host combination
# TODO add feature to log each host output in separate file

import atexit
import contextlib
import getpass
import optparse
import os
import re
import readline
import sys
import time
from operator import methodcaller
from pathlib import Path

try:
    import pexpect
    from pexpect import pxssh
except ImportError:
    sys.stderr.write("You do not have 'pexpect' installed.\n")
    sys.stderr.write("On Ubuntu you need the 'python-pexpect' package.\n")
    sys.stderr.write("    aptitude -y install python-pexpect\n")
    sys.exit(1)


histfile = str(Path(os.environ["HOME"]) / ".hive_history")
with contextlib.suppress(OSError):
    readline.read_history_file(histfile)
atexit.register(readline.write_history_file, histfile)

SCREEN_COLS = 80
MAX_CONTROL_CODE = 255  # sendcontrol() takes a control code in the range 0..255

CMD_HELP = """Hive commands are preceded by a colon : (just think of vi).

:target name1 name2 name3 ...

    set list of hosts to target commands

:target all

    reset list of hosts to target all hosts in the hive.

:to name command

    send a command line to the named host. This is similar to :target, but
    sends only one command and does not change the list of targets for future
    commands.

:sync

    set mode to wait for shell prompts after commands are run. This is the
    default. When Hive first logs into a host it sets a special shell prompt
    pattern that it can later look for to synchronize output of the hosts. If
    you 'su' to another user then it can upset the synchronization. If you need
    to run something like 'su' then use the following pattern:

    CMD (? for help) > :async
    CMD (? for help) > sudo su - root
    CMD (? for help) > :prompt
    CMD (? for help) > :sync

:async

    set mode to not expect command line prompts (see :sync). Afterwards
    commands are send to target hosts, but their responses are not read back
    until :sync is run. This is useful to run before commands that will not
    return with the special shell prompt pattern that Hive uses to synchronize.

:refresh

    refresh the display. This shows the last few lines of output from all hosts.
    This is similar to resync, but does not expect the promt. This is useful
    for seeing what hosts are doing during long running commands.

:resync

    This is similar to :sync, but it does not change the mode. It looks for the
    prompt and thus consumes all input from all targeted hosts.

:prompt

    force each host to reset command line prompt to the special pattern used to
    synchronize all the hosts. This is useful if you 'su' to a different user
    where Hive would not know the prompt to match.

:send my text

    This will send the 'my text' wihtout a line feed to the targeted hosts.
    This output of the hosts is not automatically synchronized.

:control X

    This will send the given control character to the targeted hosts.
    For example, ":control c" will send ASCII 3.

:exit

    This will exit the hive shell.

"""


def login(args, cli_username=None, cli_password=None):
    """Connect to every host in the args list; return the host names and their connections."""
    # I have to keep a separate list of host names because Python dicts are not ordered.
    # I want to keep the same order as in the args list.
    host_names = []
    hive_connect_info = {}
    hive = {}
    # build up the list of connection information (hostname, username, password, port)
    for host_connect_string in args:
        hcd = parse_host_connect_string(host_connect_string)
        hostname = hcd["hostname"]
        port = hcd["port"]
        if port == "":
            port = None
        if len(hcd["username"]) > 0:
            username = hcd["username"]
        elif cli_username is not None:
            username = cli_username
        else:
            username = input(f"{hostname} username: ")
        if len(hcd["password"]) > 0:
            password = hcd["password"]
        elif cli_password is not None:
            password = cli_password
        else:
            password = getpass.getpass(f"{hostname} password: ")
        host_names.append(hostname)
        hive_connect_info[hostname] = (hostname, username, password, port)
    # build up the list of hive connections using the connection information.
    for hostname in host_names:
        print("connecting to", hostname)
        try:
            # pxssh logs bytes, so this handle is opened in binary mode.
            # SIM115: logfile outlives the block
            fout = Path("log_" + hostname).open("wb")  # outlives this block  # noqa: SIM115
            hive[hostname] = pxssh.pxssh()
            # Disable host key checking.
            hive[hostname].SSH_OPTS = (
                hive[hostname].SSH_OPTS
                + " -o 'StrictHostKeyChecking=no'"
                + " -o 'UserKnownHostsFile /dev/null' "
            )
            hive[hostname].force_password = True
            hive[hostname].login(*hive_connect_info[hostname])
            print(hive[hostname].before)
            hive[hostname].logfile = fout
            print("- OK")
        # BLE001: an unreachable host is skipped, not fatal
        except Exception as e:  # a host we cannot reach is skipped, not fatal  # noqa: BLE001
            print("- ERROR", end=" ")
            print(str(e))
            print("Skipping", hostname)
            hive[hostname] = None
    return host_names, hive


def drop_host(hive, hostname, error) -> None:
    """Report a host that stopped responding and remove it from the hive."""
    print(f"Had trouble communicating with {hostname}, so removing it from the target list.")
    print(str(error))
    hive[hostname] = None


def for_each_host(hive, hostnames, action) -> None:
    """Run action on each live targeted host, dropping any host that fails."""
    for hostname in hostnames:
        try:
            if hive[hostname] is not None:
                action(hive[hostname])
        # BLE001, PERF203: in-loop try IS the per-host isolation
        except Exception as e:  # isolate one bad host from the hive  # noqa: BLE001, PERF203
            drop_host(hive, hostname, e)


def print_banner(text) -> None:
    """Print the separator banner that introduces one host's output."""
    print("/" + "=" * (SCREEN_COLS - 2))
    print("| " + text)
    print("\\" + "-" * (SCREEN_COLS - 2))


def print_host_output(hive, hostname) -> None:
    """Print a banner for the host followed by the output it last produced."""
    print_banner(hostname)
    if hive[hostname] is None:
        print(f"# DEAD: {hostname}")
    else:
        print(hive[hostname].before)


def print_all_host_output(hive, hostnames) -> None:
    """Print what each targeted host last sent, followed by a separator line."""
    for hostname in hostnames:
        print_host_output(hive, hostname)
    print("#" * 79)


def print_responses(hive, hostnames) -> None:
    """Wait for each targeted host to come back to its prompt and print its response."""
    for hostname in hostnames:
        try:
            print_banner(hostname)
            if hive[hostname] is None:
                print(f"# DEAD: {hostname}")
            else:
                hive[hostname].prompt(timeout=2)
                print(hive[hostname].before)
        # BLE001, PERF203: in-loop try IS the per-host isolation
        except Exception as e:  # isolate one bad host from the hive  # noqa: BLE001, PERF203
            drop_host(hive, hostname, e)
    print("#" * 79)


def send_one_command(hive, hostname, txt) -> None:
    """Send one command line to a single host and print the response it gives back."""
    print_banner(hostname)
    if hive[hostname] is None:
        print(f"# DEAD: {hostname}")
        return
    try:
        hive[hostname].sendline(txt)
        hive[hostname].prompt(timeout=2)
        print(hive[hostname].before)
    # BLE001: per-host isolation
    except Exception as e:  # isolate one bad host from the hive  # noqa: BLE001
        drop_host(hive, hostname, e)


def expect_on_hosts(hive, hostnames, pattern) -> None:
    """Wait for a pattern on each targeted host and print the output before it."""
    print("looking for", pattern)
    try:
        for hostname in hostnames:
            if hive[hostname] is not None:
                hive[hostname].expect(pattern)
                print(hive[hostname].before)
    # BLE001: per-host isolation
    except Exception as e:  # isolate one bad host from the hive  # noqa: BLE001
        drop_host(hive, hostname, e)


# C901, PLR0912, PLR0915: flat dispatch over the hive commands
def main() -> None:  # flat dispatch over the hive commands  # noqa: C901, PLR0912, PLR0915
    """Log into every host, then run the interactive hive command loop."""
    cli_username = input("username: ") if options.sameuser else None

    cli_password = getpass.getpass("password: ") if options.samepass else None

    host_names, hive = login(args, cli_username, cli_password)

    synchronous_mode = True
    target_hostnames = host_names[:]
    print("targeting hosts:", " ".join(target_hostnames))
    while True:
        cmd = input("CMD (? for help) > ")
        cmd = cmd.strip()
        if cmd in {"?", ":help", ":h"}:
            print(CMD_HELP)
            continue
        if cmd == ":refresh":
            refresh(hive, target_hostnames, timeout=0.5)
            print_all_host_output(hive, target_hostnames)
            continue
        if cmd == ":resync":
            resync(hive, target_hostnames, timeout=0.5)
            print_all_host_output(hive, target_hostnames)
            continue
        if cmd == ":sync":
            synchronous_mode = True
            resync(hive, target_hostnames, timeout=0.5)
            continue
        if cmd == ":async":
            synchronous_mode = False
            continue
        if cmd == ":prompt":
            for_each_host(hive, target_hostnames, methodcaller("set_unique_prompt"))
            continue
        if cmd[:5] == ":send":
            cmd, txt = cmd.split(None, 1)
            for_each_host(hive, target_hostnames, methodcaller("send", txt))
            continue
        if cmd[:3] == ":to":
            cmd, hostname, txt = cmd.split(None, 2)
            send_one_command(hive, hostname, txt)
            continue
        if cmd[:7] == ":expect":
            cmd, pattern = cmd.split(None, 1)
            expect_on_hosts(hive, target_hostnames, pattern)
            continue
        if cmd[:7] == ":target":
            target_hostnames = cmd.split()[1:]
            if len(target_hostnames) == 0 or target_hostnames[0] == all:
                target_hostnames = host_names[:]
            print("targeting hosts:", " ".join(target_hostnames))
            continue
        if cmd in {":exit", ":q", ":quit"}:
            break
        if cmd[:8] == ":control" or cmd[:5] == ":ctrl":
            cmd, c = cmd.split(None, 1)
            if ord(c) - 96 < 0 or ord(c) - 96 > MAX_CONTROL_CODE:
                print_banner("Invalid character. Must be [a-zA-Z], @, [, ], \\, ^, _, or ?")
                continue
            for_each_host(hive, target_hostnames, methodcaller("sendcontrol", c))
            continue
        if cmd == ":esc":
            for hostname in target_hostnames:
                if hive[hostname] is not None:
                    hive[hostname].send(chr(27))
            continue
        #
        # Run the command on all targets in parallel
        #
        for_each_host(hive, target_hostnames, methodcaller("sendline", cmd))

        #
        # print the response for each targeted host.
        #
        if synchronous_mode:
            print_responses(hive, target_hostnames)


def refresh(hive, hive_names, timeout=0.5) -> None:
    """Wait for the TIMEOUT on each host."""
    # TODO This is ideal for threading.
    for hostname in hive_names:
        if hive[hostname] is not None:
            hive[hostname].expect([pexpect.TIMEOUT, pexpect.EOF], timeout=timeout)


def resync(hive, hive_names, timeout=2, max_attempts=5) -> None:
    """Wait for the shell prompt on each host to get them all to the same state.

    The timeout is set low so that hosts that are already at the prompt will not
    slow things down too much. If a prompt match is made for a hosts then keep
    asking until it stops matching. This is a best effort to consume all input if
    it printed more than one prompt. It's kind of kludgy. Note that this will
    always introduce a delay equal to the timeout for each machine. So for 10
    machines with a 2 second delay you will get AT LEAST a 20 second delay if not
    more.
    """
    # TODO This is ideal for threading.
    for hostname in hive_names:
        if hive[hostname] is not None:
            for _attempts in range(max_attempts):
                if not hive[hostname].prompt(timeout=timeout):
                    break


def parse_host_connect_string(hcs):
    """Parse a host connection string of the form username:password@hostname:port.

    All fields are optional except hostname. A dictionary is returned with all
    four keys. Keys that were not included are set to empty strings ''. Note that
    if your password has the '@' character then you must backslash escape it.
    """
    if "@" in hcs:
        p = re.compile(
            r"(?P<username>[^@:]*)(:?)(?P<password>.*)(?!\\)@(?P<hostname>[^:]*):?(?P<port>[0-9]*)"
        )
    else:
        p = re.compile(r"(?P<username>)(?P<password>)(?P<hostname>[^:]*):?(?P<port>[0-9]*)")
    m = p.search(hcs)
    d = m.groupdict()
    d["password"] = d["password"].replace("\\@", "@")
    return d


if __name__ == "__main__":
    start_time = time.time()
    parser = optparse.OptionParser(
        formatter=optparse.TitledHelpFormatter(),
        usage=globals()["__doc__"],
        version="$Id: hive.py 533 2012-10-20 02:19:33Z noah $",
        conflict_handler="resolve",
    )
    parser.add_option("-v", "--verbose", action="store_true", default=False, help="verbose output")
    parser.add_option(
        "--samepass", action="store_true", default=False, help="Use same password for each login."
    )
    parser.add_option(
        "--sameuser", action="store_true", default=False, help="Use same username for each login."
    )
    (options, args) = parser.parse_args()
    if len(args) < 1:
        parser.error("missing argument")
    if options.verbose:
        print(time.asctime())
    main()
    if options.verbose:
        print(time.asctime())
    if options.verbose:
        print("TOTAL TIME IN MINUTES:", end=" ")
    if options.verbose:
        print((time.time() - start_time) / 60.0)
