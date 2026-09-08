"""Extend pexpect.spawn to specialize setting up SSH connections.

This adds methods for login, logout, and expecting the shell prompt.

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

from __future__ import annotations

import contextlib
import re
import time
from pathlib import Path
from shlex import quote
from typing import IO, TYPE_CHECKING

from pexpect import EOF, TIMEOUT, ExceptionPexpect, spawn

if TYPE_CHECKING:
    from collections.abc import Callable

    from pexpect.spawnbase import _Pattern

__all__ = ["ExceptionPxssh", "pxssh"]

# Indices into the login() expect() pattern lists, in the order they are built.
_MATCH_NEW_CERT = 0
_MATCH_ORIGINAL_PROMPT = 1
_MATCH_PASSWORD = 2
_MATCH_PERMISSION_DENIED = 3
_MATCH_TERMINAL_TYPE = 4
_MATCH_TIMEOUT = 5
_MATCH_CONNECTION_CLOSED = 6
_MATCH_EOF = 7

# Second-phase login failures, keyed by the match index that produced them.
_LOGIN_FAILURES = {
    # This is weird. This should not happen twice in a row.
    _MATCH_NEW_CERT: 'Weird error. Got "are you sure" prompt twice.',
    # For incorrect passwords, some ssh servers will ask for the password
    # again, others return 'denied' right away. Getting the password prompt
    # again means we didn't get the password right the first time.
    _MATCH_PASSWORD: "password refused",
    _MATCH_PERMISSION_DENIED: "permission denied",
    _MATCH_TERMINAL_TYPE: 'Weird error. Got "terminal type" prompt twice.',
    _MATCH_CONNECTION_CLOSED: "connection closed",
}

# SSH tunnel kinds and the ssh option letter that requests each one.
_TUNNEL_TYPES = {"local": "L", "remote": "R", "dynamic": "D"}

# How long set_unique_prompt() waits for each of the prompt syntaxes it tries.
_PROMPT_SET_TIMEOUT = 10

# Two consecutive prompt reads are taken to be the same prompt when they differ
# by less than this fraction of the first one's length.
_MAX_PROMPT_DIFFERENCE_RATIO = 0.4


# Exception classes used by this module.
class ExceptionPxssh(ExceptionPexpect):
    """Raised for pxssh exceptions."""


class pxssh(spawn[bytes]):
    """Set up SSH connections, on top of :class:`pexpect.spawn`.

    This adds methods for login, logout, and expecting the shell
    prompt. It does various tricky things to handle many situations in the SSH
    login process. For example, if the session is your first login, then pxssh
    automatically accepts the remote certificate; or if you have public key
    authentication setup then pxssh won't wait for the password prompt.

    pxssh uses the shell prompt to synchronize output from the remote host. In
    order to make this more robust it sets the shell prompt to something more
    unique than just $ or #. This should work on most Borne/Bash or Csh style
    shells.

    Example that runs a few commands on a remote server and prints the result::

        from pexpect import pxssh
        import getpass

        try:
            s = pxssh.pxssh()
            hostname = input("hostname: ")
            username = input("username: ")
            password = getpass.getpass("password: ")
            s.login(hostname, username, password)
            s.sendline("uptime")  # run a command
            s.prompt()  # match the prompt
            print(s.before)  # print everything before the prompt.
            s.sendline("ls -l")
            s.prompt()
            print(s.before)
            s.sendline("df")
            s.prompt()
            print(s.before)
            s.logout()
        except pxssh.ExceptionPxssh as e:
            print("pxssh failed on login.")
            print(e)

    Example showing how to specify SSH options::

        from pexpect import pxssh

        s = pxssh.pxssh(options={"StrictHostKeyChecking": "no", "UserKnownHostsFile": "/dev/null"})
        ...

    Note that if you have ssh-agent running while doing development with pxssh
    then this can lead to a lot of confusion. Many X display managers (xdm,
    gdm, kdm, etc.) will automatically start a GUI agent. You may see a GUI
    dialog box popup asking for a password during development. You should turn
    off any key agents during testing. The 'force_password' attribute will turn
    off public key authentication. This will only work if the remote SSH server
    is configured to allow password logins. Example of using 'force_password'
    attribute::

            s = pxssh.pxssh()
            s.force_password = True
            hostname = input("hostname: ")
            username = input("username: ")
            password = getpass.getpass("password: ")
            s.login(hostname, username, password)

    `debug_command_string` is only for the test suite to confirm that the string
    generated for SSH is correct, using this will not allow you to do
    anything other than get a string back from `pxssh.pxssh.login()`.
    """

    def __init__(
        self,
        timeout: float = 30,
        maxread: int = 2000,
        searchwindowsize: int | None = None,
        logfile: IO[bytes] | IO[str] | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        ignore_sighup: bool = True,  # public keyword flag
        echo: bool = True,  # public keyword flag
        options: dict[str, str] | None = None,
        encoding: str | None = None,
        codec_errors: str = "strict",
        debug_command_string: bool = False,  # public keyword flag
        use_poll: bool = False,  # public keyword flag
    ) -> None:
        """Prepare a pxssh session; nothing is spawned until :meth:`login`.

        The arguments are those of :class:`pexpect.spawn`, plus ``options``,
        a mapping of extra ssh ``-o`` options, and ``debug_command_string``,
        which makes :meth:`login` return the ssh command line it would have
        run instead of running it.
        """
        if options is None:
            options = {}
        # pxssh is a bytes-mode spawn, so neither overload of the constructor
        # accepts the ``str | None`` encoding this signature takes; the
        # implementation behind them does. Calling it through a callable target
        # forwards the arguments exactly as they are given.
        spawn_init: Callable[..., None] = spawn.__init__
        spawn_init(
            self,
            None,
            timeout=timeout,
            maxread=maxread,
            searchwindowsize=searchwindowsize,
            logfile=logfile,
            cwd=cwd,
            env=env,
            ignore_sighup=ignore_sighup,
            echo=echo,
            encoding=encoding,
            codec_errors=codec_errors,
            use_poll=use_poll,
        )

        self.name = "<pxssh>"

        # SUBTLE HACK ALERT! Note that the command that SETS the prompt uses a
        # slightly different string than the regular expression to match it. This
        # is because when you set the prompt the command will echo back, but we
        # don't want to match the echoed command. So if we make the set command
        # slightly different than the regex we eliminate the problem. To make the
        # set command different we add a backslash in front of $. The $ doesn't
        # need to be escaped, but it doesn't hurt and serves to make the set
        # prompt command different than the regex.

        # used to match the command-line prompt
        self.UNIQUE_PROMPT = r"\[PEXPECT\][\$\#] "
        self.PROMPT = self.UNIQUE_PROMPT

        # used to set shell command-line prompt to UNIQUE_PROMPT.
        self.PROMPT_SET_SH = r"PS1='[PEXPECT]\$ '"
        self.PROMPT_SET_CSH = r"set prompt='[PEXPECT]\$ '"
        self.PROMPT_SET_ZSH = "prompt restore;\nPS1='[PEXPECT]%(!.#.$) '"
        self.SSH_OPTS = " -o 'PubkeyAuthentication=no'"
        # StrictHostKeyChecking=no and UserKnownHostsFile=/dev/null are
        # deliberately not added here: disabling host key checking makes you
        # vulnerable to MITM attacks.
        #
        # Adding -x would disable X11 forwarding, which gets rid of the
        # annoying SSH_ASKPASS displaying a GUI password dialog. I have not
        # figured out how to disable only SSH_ASKPASS without also disabling
        # X11 forwarding. Unsetting SSH_ASKPASS on the remote side doesn't
        # disable it! Annoying!
        self.force_password = False

        self.debug_command_string = debug_command_string

        # User defined SSH options, keyed by ssh option name, for example
        # StrictHostKeyChecking or UserKnownHostsFile.
        self.options = options

    def levenshtein_distance(self, a: str | bytes, b: str | bytes) -> int:
        """Calculate the Levenshtein distance between a and b."""
        n, m = len(a), len(b)
        if n > m:
            a, b = b, a
            n, m = m, n
        # Materialised up front: every later row is a list, and the row is
        # both indexed and assigned to below.
        current: list[int] = list(range(n + 1))
        for i in range(1, m + 1):
            previous, current = current, [i] + [0] * n
            for j in range(1, n + 1):
                add, delete = previous[j] + 1, current[j - 1] + 1
                change = previous[j - 1]
                if a[j - 1] != b[i - 1]:
                    change = change + 1
                current[j] = min(add, delete, change)
        return current[n]

    def try_read_prompt(self, timeout_multiplier: float) -> str | bytes:
        """Read whatever the remote host sends within a short timeout window.

        This facilitates using communication timeouts to perform
        synchronization as quickly as possible, while supporting high latency
        connections with a tunable worst case performance. Fast connections
        should be read almost immediately. Worst case performance for this
        method is timeout_multiplier * 3 seconds.
        """
        # maximum time allowed to read the first response
        first_char_timeout = timeout_multiplier * 0.5

        # maximum time allowed between subsequent characters
        inter_char_timeout = timeout_multiplier * 0.1

        # maximum time for reading the entire prompt
        total_timeout = timeout_multiplier * 3.0

        prompt = self.string_type()
        begin = time.time()
        expired = 0.0
        timeout = first_char_timeout

        with contextlib.suppress(TIMEOUT):
            while expired < total_timeout:
                prompt += self.read_nonblocking(size=1, timeout=timeout)
                expired = time.time() - begin  # updated total time expired
                timeout = inter_char_timeout

        return prompt

    def sync_original_prompt(self, sync_multiplier: float = 1.0) -> bool:
        """Try to find the prompt by pressing enter and comparing the responses.

        Basically, press enter and record the response; press enter again and
        record the response; if the two responses are similar then assume we are
        at the original prompt. This can be a slow function. Worst case with the
        default sync_multiplier can take 12 seconds. Low latency connections are
        more likely to fail with a low sync_multiplier. Best case sync time gets
        worse with a high sync multiplier (500 ms with default).
        """
        # All of these timing pace values are magic.
        # I came up with these based on what seemed reliable for
        # connecting to a heavily loaded machine I have.
        self.sendline()
        time.sleep(0.1)

        with contextlib.suppress(TIMEOUT):
            # Clear the buffer before getting the prompt.
            self.try_read_prompt(sync_multiplier)

        self.sendline()
        self.try_read_prompt(sync_multiplier)

        self.sendline()
        a = self.try_read_prompt(sync_multiplier)

        self.sendline()
        b = self.try_read_prompt(sync_multiplier)

        ld = self.levenshtein_distance(a, b)
        len_a = len(a)
        if len_a == 0:
            return False
        return ld / len_a < _MAX_PROMPT_DIFFERENCE_RATIO

    def _ssh_key_option(self, *, ssh_key: str | bool, spawn_local_ssh: bool) -> str:
        """Return the ssh option that forwards the agent or picks a private key."""
        # Allow forwarding our SSH key to the current session.
        # `ssh_key` is either True (forward the agent) or a key path, so a plain
        # truth test would send every path down the ``-A`` branch.
        if ssh_key is True:
            return " -A"
        if spawn_local_ssh and not Path(str(ssh_key)).is_file():
            msg = "private ssh key does not exist or is not a file."
            raise ExceptionPxssh(msg)
        return f" -i {quote(str(ssh_key))}"

    @staticmethod
    def _ssh_tunnel_options(ssh_tunnels: dict, *, spawn_local_ssh: bool) -> str:
        """Return the ssh options requesting the given tunnels.

        Make sure you know what you're putting into the lists under each
        heading. Do not expect these to open 100% of the time, the port you're
        requesting might be bound. The structure should be like this::

            {
                "local": ["2424:localhost:22"],  # Local SSH tunnels
                "remote": ["2525:localhost:22"],  # Remote SSH tunnels
                "dynamic": [8888],
            }  # Dynamic/SOCKS tunnels
        """
        if ssh_tunnels == {} or not isinstance({}, type(ssh_tunnels)):
            return ""
        ssh_options = ""
        for tunnel_type, cmd_type in _TUNNEL_TYPES.items():
            for tunnel in ssh_tunnels.get(tunnel_type, []):
                spec = str(tunnel) if spawn_local_ssh else quote(str(tunnel))
                ssh_options += f" -{cmd_type} {spec}"
        return ssh_options

    def _ssh_options(
        self,
        *,
        quiet: bool,
        check_local_ip: bool,
        ssh_config: str | None,
        port: int | None,
        ssh_key: str | bool | None,
        ssh_tunnels: dict,
        spawn_local_ssh: bool,
    ) -> str:
        """Assemble the ssh command line options requested by :meth:`login`."""
        ssh_options = "".join([f" -o '{o}={v}'" for (o, v) in self.options.items()])
        if quiet:
            ssh_options += " -q"
        if not check_local_ip:
            ssh_options += " -o'NoHostAuthenticationForLocalhost=yes'"
        if self.force_password:
            ssh_options += " " + self.SSH_OPTS
        if ssh_config is not None:
            if spawn_local_ssh and not Path(ssh_config).is_file():
                msg = "SSH config does not exist or is not a file."
                raise ExceptionPxssh(msg)
            ssh_options += " -F " + quote(ssh_config)
        if port is not None:
            ssh_options += f" -p {port!s}"
        if ssh_key is not None:
            ssh_options += self._ssh_key_option(ssh_key=ssh_key, spawn_local_ssh=spawn_local_ssh)
        return ssh_options + self._ssh_tunnel_options(ssh_tunnels, spawn_local_ssh=spawn_local_ssh)

    @staticmethod
    def _check_ssh_config_username(ssh_config: str, server: str) -> None:
        """Raise TypeError unless ssh_config gives server a Host entry with a User."""
        server_regex = rf"^Host\s+{server}\s*$"
        user_regex = r"^User\s+\w+\s*$"
        config_has_server = False
        server_has_username = False
        for raw_line in Path(ssh_config).read_text().splitlines():
            line = raw_line.strip()
            if not config_has_server and re.match(server_regex, line, re.IGNORECASE):
                config_has_server = True
            elif config_has_server and "hostname" in line.lower():
                pass
            elif config_has_server and "host" in line.lower():
                server_has_username = False  # insurance
                break  # we have left the relevant section
            elif config_has_server and re.match(user_regex, line, re.IGNORECASE):
                server_has_username = True
                break

        if not config_has_server:
            msg = f"login() ssh_config has no Host entry for {server}"
            raise TypeError(msg)
        if not server_has_username:
            msg = f"login() ssh_config has no user entry for {server}"
            raise TypeError(msg)

    def _answer_login_prompts(
        self,
        i: int,
        session_regex_array: list[_Pattern],
        password: str,
        terminal_type: str,
    ) -> int:
        """Answer the certificate, password and terminal type prompts.

        Return the match index of whatever the remote host replied last.
        """
        if i == _MATCH_NEW_CERT:
            # New certificate -- always accept it.
            # This is what you get if SSH does not have the remote host's
            # public key stored in the 'known_hosts' cache.
            self.sendline("yes")
            i = self.expect(session_regex_array)
        if i == _MATCH_PASSWORD:  # password or passphrase
            self.sendline(password)
            i = self.expect(session_regex_array)
        if i == _MATCH_TERMINAL_TYPE:
            self.sendline(terminal_type)
            i = self.expect(session_regex_array)
        if i == _MATCH_EOF:
            self.close()
            msg = "Could not establish connection to host"
            raise ExceptionPxssh(msg)
        return i

    def _check_login_response(self, i: int) -> None:
        """Raise ExceptionPxssh unless the match index means we reached a shell."""
        if i == _MATCH_ORIGINAL_PROMPT:
            # can occur if you have a public key pair set to authenticate.
            ### TODO: May NOT be OK if expect() got tricked and matched a false prompt.
            return
        if i == _MATCH_TIMEOUT:
            # This is tricky... I presume that we are at the command-line prompt.
            # It may be that the shell prompt was so weird that we couldn't match
            # it. Or it may be that we couldn't log in for some other reason. I
            # can't be sure, but it's safe to guess that we did login because if
            # I presume wrong and we are not logged in then this should be caught
            # later when I try to set the shell prompt.
            return
        self.close()
        raise ExceptionPxssh(_LOGIN_FAILURES.get(i, "unexpected login response"))

    ### TODO: This is getting messy and I'm pretty sure this isn't perfect.
    ### TODO: I need to draw a flow chart for this.
    ### TODO: Unit tests for SSH tunnels, remote SSH command exec, disabling original prompt sync
    def login(
        self,
        server: str,
        username: str | None = None,
        password: str = "",
        terminal_type: str = "ansi",
        original_prompt: str = r"[#$]",
        login_timeout: float = 10,
        port: int | None = None,
        auto_prompt_reset: bool = True,  # public keyword flag
        ssh_key: str | bool | None = None,  # True forwards the agent
        quiet: bool = True,  # public keyword flag
        sync_multiplier: float = 1,
        check_local_ip: bool = True,  # public keyword flag
        # S107: this default is a prompt pattern, not a password.
        password_regex: str = r"(?i)(?:password:)|(?:passphrase for key)",  # noqa: S107
        ssh_tunnels: dict | None = None,
        spawn_local_ssh: bool = True,  # public keyword flag
        sync_original_prompt: bool = True,  # public keyword flag
        ssh_config: str | None = None,
        cmd: str = "ssh",
    ) -> bool | str:
        """Log the user into the given server.

        It uses 'original_prompt' to try to find the prompt right after login.
        When it finds the prompt it immediately tries to reset the prompt to
        something more easily matched. The default 'original_prompt' is very
        optimistic and is easily fooled. It's more reliable to try to match the original
        prompt as exactly as possible to prevent false matches by server
        strings such as the "Message Of The Day". On many systems you can
        disable the MOTD on the remote server by creating a zero-length file
        called :file:`~/.hushlogin` on the remote server. If a prompt cannot be found
        then this will not necessarily cause the login to fail. In the case of
        a timeout when looking for the prompt we assume that the original
        prompt was so weird that we could not match it, so we use a few tricks
        to guess when we have reached the prompt. Then we hope for the best and
        blindly try to reset the prompt to something more unique. If that fails
        then login() raises an :class:`ExceptionPxssh` exception.

        In some situations it is not possible or desirable to reset the
        original prompt. In this case, pass ``auto_prompt_reset=False`` to
        inhibit setting the prompt to the UNIQUE_PROMPT. Remember that pxssh
        uses a unique prompt in the :meth:`prompt` method. If the original prompt is
        not reset then this will disable the :meth:`prompt` method unless you
        manually set the :attr:`PROMPT` attribute.

        Set ``password_regex`` if there is a MOTD message with `password` in it.
        Changing this is like playing in traffic, don't (p)expect it to match straight
        away.

        If you require to connect to another SSH server from the your original SSH
        connection set ``spawn_local_ssh`` to `False` and this will use your current
        session to do so. Setting this option to `False` and not having an active session
        will trigger an error.

        Set ``ssh_key`` to a file path to an SSH private key to use that SSH key
        for the session authentication.
        Set ``ssh_key`` to `True` to force passing the current SSH authentication socket
        to the desired ``hostname``.

        Set ``ssh_config`` to a file path string of an SSH client config file to pass that
        file to the client to handle itself. You may set any options you wish in here, however
        doing so will require you to post extra information that you may not want to if you
        run into issues.

        Alter the ``cmd`` to change the ssh client used, or to prepend it with network
        namespaces. For example ```cmd="ip netns exec vlan2 ssh"``` to execute the ssh in
        network namespace named ```vlan```.
        """
        if ssh_tunnels is None:
            ssh_tunnels = {}
        session_regex_array: list[_Pattern] = [
            "(?i)are you sure you want to continue connecting",
            original_prompt,
            password_regex,
            "(?i)permission denied",
            "(?i)terminal type",
            TIMEOUT,
        ]
        session_init_regex_array: list[_Pattern] = [
            *session_regex_array,
            "(?i)connection closed by remote host",
            EOF,
        ]

        ssh_options = self._ssh_options(
            quiet=quiet,
            check_local_ip=check_local_ip,
            ssh_config=ssh_config,
            port=port,
            ssh_key=ssh_key,
            ssh_tunnels=ssh_tunnels,
            spawn_local_ssh=spawn_local_ssh,
        )

        if username is not None:
            ssh_options = ssh_options + " -l " + quote(username)
        elif ssh_config is None:
            msg = "login() needs either a username or an ssh_config"
            raise TypeError(msg)
        else:
            # make sure ssh_config has an entry for the server with a username
            self._check_ssh_config_username(ssh_config, server)

        cmd += f" {ssh_options} {quote(server)}"
        if self.debug_command_string:
            return cmd

        # Are we asking for a local ssh command or to spawn one in another session?
        if spawn_local_ssh:
            spawn._spawn(self, cmd)
        else:
            self.sendline(cmd)

        # This does not distinguish between a remote server 'password' prompt
        # and a local ssh 'passphrase' prompt (for unlocking a private key).
        i = self.expect(session_init_regex_array, timeout=login_timeout)

        # First phase: answer whatever the host asked for.
        i = self._answer_login_prompts(i, session_regex_array, password, terminal_type)

        # Second phase: decide whether we are actually logged in.
        self._check_login_response(i)

        if sync_original_prompt and not self.sync_original_prompt(sync_multiplier):
            self.close()
            msg = "could not synchronize with original prompt"
            raise ExceptionPxssh(msg)
        # We appear to be in.
        # set shell prompt to something unique.
        if auto_prompt_reset and not self.set_unique_prompt():
            self.close()
            msg = (
                "could not set shell prompt "
                f"(received: {self.before!r}, expected: {self.PROMPT!r})."
            )
            raise ExceptionPxssh(msg)
        return True

    def logout(self) -> None:
        """Send exit to the remote shell.

        If there are stopped jobs then this automatically sends exit twice.
        """
        self.sendline("exit")
        index = self.expect([EOF, "(?i)there are stopped jobs"])
        if index == 1:
            self.sendline("exit")
            self.expect(EOF)
        self.close()

    def prompt(self, timeout: float = -1) -> bool:
        """Match the next shell prompt.

        This is little more than a short-cut to the :meth:`~pexpect.spawn.expect`
        method. Note that if you called :meth:`login` with
        ``auto_prompt_reset=False``, then before calling :meth:`prompt` you must
        set the :attr:`PROMPT` attribute to a regex that it will use for
        matching the prompt.

        Calling :meth:`prompt` will erase the contents of the :attr:`before`
        attribute even if no prompt is ever matched. If timeout is not given or
        it is set to -1 then self.timeout is used.

        :return: True if the shell prompt was matched, False if the timeout was
                 reached.
        """
        expect_timeout: float | None = timeout
        if timeout == -1:
            expect_timeout = self.timeout
        i = self.expect([self.PROMPT, TIMEOUT], timeout=expect_timeout)
        return i != 1

    def set_unique_prompt(self) -> bool:
        """Set the remote prompt to something more unique than ``#`` or ``$``.

        This makes it easier for the :meth:`prompt` method to match the shell prompt
        unambiguously. This method is called automatically by the :meth:`login`
        method, but you may want to call it manually if you somehow reset the
        shell prompt. For example, if you 'su' to a different user then you
        will need to manually reset the prompt. This sends shell commands to
        the remote host to set the prompt, so this assumes the remote host is
        ready to receive commands.

        Alternatively, you may use your own prompt pattern. In this case you
        should call :meth:`login` with ``auto_prompt_reset=False``; then set the
        :attr:`PROMPT` attribute to a regular expression. After that, the
        :meth:`prompt` method will try to match your prompt pattern.
        """
        self.sendline("unset PROMPT_COMMAND")
        self.sendline(self.PROMPT_SET_SH)  # sh-style
        i = self.expect([TIMEOUT, self.PROMPT], timeout=_PROMPT_SET_TIMEOUT)
        if i == 0:  # csh-style
            self.sendline(self.PROMPT_SET_CSH)
            i = self.expect([TIMEOUT, self.PROMPT], timeout=_PROMPT_SET_TIMEOUT)
            if i == 0:  # zsh-style
                self.sendline(self.PROMPT_SET_ZSH)
                i = self.expect([TIMEOUT, self.PROMPT], timeout=_PROMPT_SET_TIMEOUT)
                if i == 0:
                    return False
        return True


# vi:ts=4:sw=4:expandtab:ft=python:
