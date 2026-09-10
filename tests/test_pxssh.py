#!/usr/bin/env python
"""Tests for :mod:`pexpect.pxssh`, driven by the ``fakessh`` harness."""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from shlex import quote
from unittest import mock

import pytest

from pexpect.utils import split_command_line

if sys.platform != "win32":
    from pexpect import pxssh
from .pexpect_test_case import PexpectTestCase

pytestmark = [
    pytest.mark.usefixtures("fast_sleep", "lean_child_env", "killed_pty_children"),
    pytest.mark.skipif(
        sys.platform == "win32",
        reason="drives POSIX programs and an ssh binary",
    ),
]

# Credentials the tests/fakessh/ssh stub accepts and rejects. They are fixture
# values for a mock server, not real secrets.
FAKE_PW = "s3cret"
WRONG_PW = "wr0ng"

# set_unique_prompt() tries the sh, csh and zsh ways of setting a prompt.
_PROMPT_SET_SYNTAXES = 3


class SSHTestBase(PexpectTestCase):
    """Base class that puts the ``fakessh`` stub on ``PATH``."""

    def setUp(self) -> None:
        """Prepend a scratch dir holding a ``python`` symlink, plus ``fakessh``, to PATH."""
        super().setUp()
        self.tempdir = tempfile.mkdtemp()
        self.orig_path = os.environ.get("PATH")
        Path(self.tempdir, "python").symlink_to(self.PYTHONBIN)
        fakessh_dir = str(Path(__file__).parent.resolve() / "fakessh")
        os.environ["PATH"] = (
            self.tempdir
            + os.pathsep
            + fakessh_dir
            + ((os.pathsep + self.orig_path) if self.orig_path else "")
        )

    def tearDown(self) -> None:
        """Delete the scratch dir and restore the original PATH."""
        shutil.rmtree(self.tempdir)
        if self.orig_path:
            os.environ["PATH"] = self.orig_path
        else:
            del os.environ["PATH"]


class PxsshTestCase(SSHTestBase):
    """Tests for logging in, tunnelling and ssh command-line building."""

    def test_ssh_tunnel_string(self) -> None:
        """Build local, remote and dynamic tunnel options into the ssh command."""
        ssh = pxssh.pxssh(debug_command_string=True)
        tunnels = {
            "local": ["2424:localhost:22"],
            "remote": ["2525:localhost:22"],
            "dynamic": [8888],
        }
        confirmation_strings = 0
        confirmation_array = ["-R 2525:localhost:22", "-L 2424:localhost:22", "-D 8888"]
        string = ssh.login("server", "me", password=FAKE_PW, ssh_tunnels=tunnels)
        # debug_command_string=True makes login() return the ssh command line it built.
        assert isinstance(string, str)
        for confirmation in confirmation_array:
            if confirmation in string:
                confirmation_strings += 1

        if confirmation_strings != len(confirmation_array):
            msg = "String generated from tunneling is incorrect."
            raise AssertionError(msg)

    def test_remote_ssh_tunnel_string(self) -> None:
        """Build tunnel options when the ssh client is spawned on a remote session."""
        ssh = pxssh.pxssh(debug_command_string=True)
        tunnels = {
            "local": ["2424:localhost:22"],
            "remote": ["2525:localhost:22"],
            "dynamic": [8888],
        }
        confirmation_strings = 0
        confirmation_array = ["-R 2525:localhost:22", "-L 2424:localhost:22", "-D 8888"]
        string = ssh.login(
            "server", "me", password=FAKE_PW, ssh_tunnels=tunnels, spawn_local_ssh=False
        )
        assert isinstance(string, str)
        for confirmation in confirmation_array:
            if confirmation in string:
                confirmation_strings += 1

        if confirmation_strings != len(confirmation_array):
            msg = "String generated from remote tunneling is incorrect."
            raise AssertionError(msg)

    def test_ssh_config_passing_string(self) -> None:
        """Pass an ssh client config file through as ``-F <path>``."""
        ssh = pxssh.pxssh(debug_command_string=True)
        with tempfile.NamedTemporaryFile() as temp_file:
            config_path = temp_file.name
            string = ssh.login(
                "server", "me", password=FAKE_PW, spawn_local_ssh=False, ssh_config=config_path
            )
            assert isinstance(string, str)
        if "-F " + config_path not in string:
            msg = "String generated from SSH config passing is incorrect."
            raise AssertionError(msg)

    def test_username_or_ssh_config(self) -> None:
        """Reject a login given neither a username nor an ssh config."""
        try:
            ssh = pxssh.pxssh(debug_command_string=True)
            ssh.login("server")
            msg = "Should have failed due to missing username and missing ssh_config."
            raise AssertionError(msg)
        except TypeError:
            pass

    def test_ssh_config_user(self) -> None:
        """Take the username from the Host block matching the server."""
        ssh = pxssh.pxssh(debug_command_string=True)
        with tempfile.NamedTemporaryFile() as temp_file:
            config_path = temp_file.name
            temp_file.write(b"HosT server\nUsEr me\nhOSt not-server\n")
            temp_file.seek(0)
            ssh.login("server", ssh_config=config_path)

    def test_ssh_config_no_username_empty_config(self) -> None:
        """Reject an ssh config that has no Host entry at all."""
        ssh = pxssh.pxssh(debug_command_string=True)
        with tempfile.NamedTemporaryFile() as temp_file:
            config_path = temp_file.name
            try:
                ssh.login("server", ssh_config=config_path)
                msg = "Should have failed due to no Host."
                raise AssertionError(msg)
            except TypeError:
                pass

    def test_ssh_config_wrong_host(self) -> None:
        """Reject an ssh config whose Host entries do not name the server."""
        ssh = pxssh.pxssh(debug_command_string=True)
        with tempfile.NamedTemporaryFile() as temp_file:
            config_path = temp_file.name
            temp_file.write(b"Host not-server\nHost also-not-server\n")
            temp_file.seek(0)
            try:
                ssh.login("server", ssh_config=config_path)
                msg = "Should have failed due to no matching Host."
                raise AssertionError(msg)
            except TypeError:
                pass

    def test_ssh_config_no_user(self) -> None:
        """Reject a matching Host block that carries no User entry."""
        ssh = pxssh.pxssh(debug_command_string=True)
        with tempfile.NamedTemporaryFile() as temp_file:
            config_path = temp_file.name
            temp_file.write(b"Host server\nHost not-server\n")
            temp_file.seek(0)
            try:
                ssh.login("server", ssh_config=config_path)
                msg = "Should have failed due to no user."
                raise AssertionError(msg)
            except TypeError:
                pass

    def test_ssh_config_empty_user(self) -> None:
        """Reject a matching Host block whose User entry is blank."""
        ssh = pxssh.pxssh(debug_command_string=True)
        with tempfile.NamedTemporaryFile() as temp_file:
            config_path = temp_file.name
            temp_file.write(b"Host server\nuser   \nHost not-server\n")
            temp_file.seek(0)
            try:
                ssh.login("server", ssh_config=config_path)
                msg = "Should have failed due to empty user."
                raise AssertionError(msg)
            except TypeError:
                pass

    def test_login_over_an_existing_session(self) -> None:
        """Send the ssh command into the session instead of spawning one.

        Given a session and a login asked not to spawn a local ssh,
        When login() is called,
        Then the ssh command line is sent to the session rather than spawned.
        """
        ssh = pxssh.pxssh()
        with (
            mock.patch.object(ssh, "sendline") as sendline,
            mock.patch.object(ssh, "expect", return_value=pxssh._MATCH_ORIGINAL_PROMPT),
            mock.patch.object(ssh, "sync_original_prompt", return_value=True),
            mock.patch.object(ssh, "set_unique_prompt", return_value=True),
        ):
            assert ssh.login("server", "me", password=FAKE_PW, spawn_local_ssh=False)

        assert sendline.call_args_list[0].args[0].endswith(" server")

    def test_login_treats_a_timeout_as_a_login(self) -> None:
        """Assume a login worked when no prompt could be matched.

        Given a login whose prompt search timed out, which pxssh treats as a
        prompt too odd to match rather than as a failure,
        When the login response is checked,
        Then no exception is raised.
        """
        ssh = pxssh.pxssh()
        ssh._check_login_response(pxssh._MATCH_TIMEOUT)

    def test_try_read_prompt_stops_at_its_total_timeout(self) -> None:
        """Stop reading the prompt once the whole time budget is used up.

        Given a session that always has another character to read,
        When :meth:`pxssh.pxssh.try_read_prompt` is called,
        Then it returns what it read so far instead of reading forever.
        """
        ssh = pxssh.pxssh()
        with mock.patch.object(ssh, "read_nonblocking", return_value=b"x"):
            prompt = ssh.try_read_prompt(0.01)

        assert prompt
        assert set(prompt) == {ord("x")}

    def test_set_unique_prompt_gives_up(self) -> None:
        """Report failure when no prompt-setting syntax works.

        Given a session where the sh, csh and zsh prompt commands all time out,
        When :meth:`pxssh.pxssh.set_unique_prompt` is called,
        Then it returns False.
        """
        ssh = pxssh.pxssh()
        with (
            mock.patch.object(ssh, "sendline"),
            mock.patch.object(ssh, "expect", return_value=0) as expect,
        ):
            assert not ssh.set_unique_prompt()

        assert expect.call_count == _PROMPT_SET_SYNTAXES

    def test_levenshtein_distance_with_the_shorter_string_second(self) -> None:
        """Measure the distance whichever way round the strings are given.

        Given two strings of different lengths,
        When :meth:`pxssh.pxssh.levenshtein_distance` is called with the longer
        one first and then with the shorter one first,
        Then the same distance is reported both times.
        """
        ssh = pxssh.pxssh()
        assert ssh.levenshtein_distance("kitten", "sit") == ssh.levenshtein_distance(
            "sit", "kitten"
        )

    def test_ssh_options_string(self) -> None:
        """Build the ssh options that the login flags ask for.

        Given a session created with extra ssh options and a login that asks
        for a port, a noisy client, no local-host key check and a forced
        password,
        When the ssh command line is built,
        Then every one of those options appears in it.
        """
        ssh = pxssh.pxssh(debug_command_string=True, options={"StrictHostKeyChecking": "no"})
        ssh.force_password = True

        string = ssh.login(
            "server",
            "me",
            password=FAKE_PW,
            port=2222,
            quiet=False,
            check_local_ip=False,
        )

        assert isinstance(string, str)
        assert "-o 'StrictHostKeyChecking=no'" in string
        assert " -q" not in string
        assert "NoHostAuthenticationForLocalhost=yes" in string
        assert ssh.SSH_OPTS in string
        assert " -p 2222" in string

    def test_missing_ssh_key_is_rejected(self) -> None:
        """Refuse a private key path that names no file.

        Given a login asked to use a private key that does not exist,
        When the ssh command line is built for a local ssh,
        Then :exc:`pxssh.ExceptionPxssh` is raised.
        """
        ssh = pxssh.pxssh(debug_command_string=True)
        with pytest.raises(pxssh.ExceptionPxssh, match="private ssh key does not exist"):
            ssh.login("server", "me", password=FAKE_PW, ssh_key="/no/such/private/key")

    def test_missing_ssh_config_is_rejected(self) -> None:
        """Refuse an ssh config path that names no file.

        Given a login asked to use an ssh config file that does not exist,
        When the ssh command line is built for a local ssh,
        Then :exc:`pxssh.ExceptionPxssh` is raised.
        """
        ssh = pxssh.pxssh(debug_command_string=True)
        with pytest.raises(pxssh.ExceptionPxssh, match="SSH config does not exist"):
            ssh.login("server", "me", password=FAKE_PW, ssh_config="/no/such/ssh/config")

    def test_ssh_config_user_after_a_hostname_line(self) -> None:
        """Look past a HostName line for the User of the matching Host block.

        Given an ssh config whose Host block for the server carries a HostName
        line before its User line,
        When login() takes the username from that config,
        Then the HostName line is skipped and the User line is found.
        """
        ssh = pxssh.pxssh(debug_command_string=True)
        with tempfile.NamedTemporaryFile() as temp_file:
            temp_file.write(b"Host server\nHostName 10.0.0.1\nUser me\n")
            temp_file.seek(0)
            assert ssh.login("server", ssh_config=temp_file.name)

    def test_ssh_key_string(self) -> None:
        """Build ``-A`` for agent forwarding and ``-i <path>`` for an explicit key."""
        ssh = pxssh.pxssh(debug_command_string=True)
        confirmation_strings = 0
        confirmation_array = [" -A"]
        string = ssh.login("server", "me", password=FAKE_PW, ssh_key=True)
        assert isinstance(string, str)
        for confirmation in confirmation_array:
            if confirmation in string:
                confirmation_strings += 1

        if confirmation_strings != len(confirmation_array):
            msg = "String generated from forcing the SSH agent sock is incorrect."
            raise AssertionError(msg)

        confirmation_strings = 0
        with tempfile.NamedTemporaryFile() as temp_file:
            ssh_key = temp_file.name
            confirmation_array = [" -i " + ssh_key]
            string = ssh.login("server", "me", password=FAKE_PW, ssh_key=ssh_key)
            assert isinstance(string, str)
        for confirmation in confirmation_array:
            if confirmation in string:
                confirmation_strings += 1

        if confirmation_strings != len(confirmation_array):
            msg = "String generated from adding an SSH key is incorrect."
            raise AssertionError(msg)

    def test_server_with_a_shell_metacharacter_is_quoted(self) -> None:
        """Quote a server name so a shell metacharacter cannot start a second command.

        Given a server name containing a ``;``,
        When the ssh command line is built,
        Then the server appears quoted rather than as bare text a remote
        shell could split into two commands.
        """
        ssh = pxssh.pxssh(debug_command_string=True)
        server = "host; touch /tmp/pwned"
        string = ssh.login(server, "me", password=FAKE_PW, ssh_key=True)
        assert isinstance(string, str)
        assert string.endswith(" " + quote(server))
        assert not string.endswith(" " + server)

    def test_server_with_a_space_is_quoted(self) -> None:
        """Quote a server name containing a space.

        Given a server name with a space in it,
        When the ssh command line is built,
        Then the server appears quoted, and split_command_line() reads it
        back as a single argv entry instead of splitting it into a
        hostname and a shell.
        """
        ssh = pxssh.pxssh(debug_command_string=True)
        server = "two words"
        string = ssh.login(server, "me", password=FAKE_PW)
        assert isinstance(string, str)
        assert string.endswith(" " + quote(server))
        assert split_command_line(string)[-1] == server

    def test_username_with_a_space_is_quoted(self) -> None:
        """Quote a username containing a space.

        Given a username with a space in it,
        When the ssh command line is built,
        Then the username is quoted, and split_command_line() reads it
        back as a single argv entry instead of splitting it in two.
        """
        ssh = pxssh.pxssh(debug_command_string=True)
        username = "user name"
        string = ssh.login("server", username, password=FAKE_PW)
        assert isinstance(string, str)
        assert " -l " + quote(username) in string
        assert username in split_command_line(string)

    def test_ssh_key_path_with_a_space_is_quoted(self) -> None:
        """Quote a private key path containing a space.

        Given a private key path under a directory whose name has a space,
        When the ssh command line is built,
        Then the path is quoted, and split_command_line() reads it back as
        a single argv entry instead of splitting it in two.
        """
        ssh = pxssh.pxssh(debug_command_string=True)
        with tempfile.TemporaryDirectory(suffix=" with space") as tempdir:
            ssh_key = str(Path(tempdir) / "id_rsa")
            Path(ssh_key).touch()
            string = ssh.login("server", "me", password=FAKE_PW, ssh_key=ssh_key)
        assert isinstance(string, str)
        assert " -i " + quote(ssh_key) in string
        assert ssh_key in split_command_line(string)

    def test_custom_ssh_cmd_debug(self) -> None:
        """Keep a custom ssh client command and its options in the built command."""
        ssh = pxssh.pxssh(debug_command_string=True)
        cipher_string = (
            "-c aes128-ctr,aes192-ctr,aes256-ctr,arcfour256,arcfour128,"
            "aes128-cbc,3des-cbc,blowfish-cbc,cast128-cbc,aes192-cbc,"
            "aes256-cbc,arcfour"
        )
        confirmation_strings = 0
        confirmation_array = [cipher_string, "-2"]
        string = ssh.login("server", "me", password=FAKE_PW, cmd="ssh " + cipher_string + " -2")
        assert isinstance(string, str)
        for confirmation in confirmation_array:
            if confirmation in string:
                confirmation_strings += 1

        if confirmation_strings != len(confirmation_array):
            msg = "String generated for custom ssh client command is incorrect."
            raise AssertionError(msg)

    def test_failed_custom_ssh_cmd_debug(self) -> None:
        """Keep an invalid cipher option in the built command string."""
        ssh = pxssh.pxssh(debug_command_string=True)
        cipher_string = "-c invalid_cipher"
        confirmation_strings = 0
        confirmation_array = [cipher_string, "-2"]
        string = ssh.login("server", "me", password=FAKE_PW, cmd="ssh " + cipher_string + " -2")
        assert isinstance(string, str)
        for confirmation in confirmation_array:
            if confirmation in string:
                confirmation_strings += 1

        if confirmation_strings != len(confirmation_array):
            msg = "String generated for custom ssh client command is incorrect."
            raise AssertionError(msg)


if __name__ == "__main__":
    unittest.main()
