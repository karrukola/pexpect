#!/usr/bin/env python
"""Tests for :mod:`pexpect.pxssh`, driven by the ``fakessh`` harness."""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pytest

if sys.platform != "win32":
    from pexpect import pxssh
from .pexpect_test_case import PexpectTestCase

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

    def test_fake_ssh(self) -> None:
        """Log in to the fake server, exchange a ping and log out again."""
        ssh = pxssh.pxssh()
        ssh.login("server", "me", password=FAKE_PW)
        ssh.sendline("ping")
        ssh.expect("pong", timeout=10)
        assert ssh.prompt(timeout=10)
        ssh.logout()

    def test_wrong_pw(self) -> None:
        """Refuse a login whose password the fake server rejects."""
        ssh = pxssh.pxssh()
        try:
            ssh.login("server", "me", password=WRONG_PW)
        except pxssh.ExceptionPxssh:
            pass
        else:
            msg = "Password should have been refused"
            raise AssertionError(msg)

    def test_failed_set_unique_prompt(self) -> None:
        """Fail the login when the unique prompt cannot be set."""
        ssh = pxssh.pxssh()
        ssh.set_unique_prompt = lambda: False
        try:
            ssh.login("server", "me", password=FAKE_PW, auto_prompt_reset=True)
        except pxssh.ExceptionPxssh:
            pass
        else:
            msg = "should have raised exception, pxssh.ExceptionPxssh"
            raise AssertionError(msg)

    def test_connection_refused(self) -> None:
        """Fail the login when the fake server refuses the connection."""
        ssh = pxssh.pxssh()
        try:
            ssh.login("noserver", "me", password=FAKE_PW)
        except pxssh.ExceptionPxssh:
            pass
        else:
            msg = "should have raised exception, pxssh.ExceptionPxssh"
            raise AssertionError(msg)

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

    def test_login_accepts_a_new_host_key(self) -> None:
        """Accept an unknown host key and carry on with the login.

        Given a fake server that asks whether to continue connecting before it
        asks for the password,
        When login() is called,
        Then the question is answered with yes and the login completes.
        """
        ssh = pxssh.pxssh()
        ssh.login("certserver", "me", password=FAKE_PW)
        ssh.sendline("ping")
        ssh.expect("pong", timeout=10)
        ssh.logout()

    def test_login_answers_the_terminal_type_prompt(self) -> None:
        """Tell the remote host which terminal type to use.

        Given a fake server that asks for a terminal type after the password,
        When login() is called,
        Then the terminal type is sent and the login completes.
        """
        ssh = pxssh.pxssh()
        ssh.login("termserver", "me", password=FAKE_PW, terminal_type="ansi")
        ssh.sendline("ping")
        ssh.expect("pong", timeout=10)
        ssh.logout()

    def test_prompt_with_the_default_timeout(self) -> None:
        """Match the prompt with the timeout the session was created with.

        Given a logged-in session,
        When :meth:`pxssh.pxssh.prompt` is called without a timeout, so that the
        session timeout applies,
        Then the prompt is matched.
        """
        ssh = pxssh.pxssh(timeout=10)
        ssh.login("server", "me", password=FAKE_PW)
        ssh.sendline("ping")
        ssh.expect("pong", timeout=10)
        assert ssh.prompt()
        ssh.logout()

    def test_logout_with_stopped_jobs(self) -> None:
        """Send exit twice when the remote shell reports stopped jobs.

        Given a fake server whose shell refuses the first exit because it has
        stopped jobs,
        When :meth:`pxssh.pxssh.logout` is called,
        Then exit is sent a second time and the connection closes.
        """
        ssh = pxssh.pxssh()
        ssh.login("jobserver", "me", password=FAKE_PW)
        ssh.logout()
        assert not ssh.isalive()

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
        assert ssh._check_login_response(pxssh._MATCH_TIMEOUT) is None

    def test_login_fails_when_the_prompt_cannot_be_synchronised(self) -> None:
        """Fail the login when the original prompt cannot be found.

        Given a session that never reads anything back, so that the two prompt
        samples are both empty,
        When login() tries to synchronise with the original prompt,
        Then :exc:`pxssh.ExceptionPxssh` is raised.
        """
        ssh = pxssh.pxssh()
        with (
            mock.patch.object(ssh, "try_read_prompt", return_value=b""),
            pytest.raises(pxssh.ExceptionPxssh, match="could not synchronize"),
        ):
            ssh.login("server", "me", password=FAKE_PW)

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
        for confirmation in confirmation_array:
            if confirmation in string:
                confirmation_strings += 1

        if confirmation_strings != len(confirmation_array):
            msg = "String generated from adding an SSH key is incorrect."
            raise AssertionError(msg)

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
        for confirmation in confirmation_array:
            if confirmation in string:
                confirmation_strings += 1

        if confirmation_strings != len(confirmation_array):
            msg = "String generated for custom ssh client command is incorrect."
            raise AssertionError(msg)

    def test_custom_ssh_cmd(self) -> None:
        """Log in with a custom ssh client command and exit cleanly."""
        try:
            ssh = pxssh.pxssh()
            cipher_string = (
                "-c aes128-ctr,aes192-ctr,aes256-ctr,arcfour256,arcfour128,"
                "aes128-cbc,3des-cbc,blowfish-cbc,cast128-cbc,aes192-cbc,"
                "aes256-cbc,arcfour"
            )
            ssh.login("server", "me", password=FAKE_PW, cmd="ssh " + cipher_string + " -2")

            ssh.PROMPT = r"Closed connection"
            ssh.sendline("exit")
            ssh.prompt(timeout=5)
            string = str(ssh.before) + str(ssh.after)

            if "Closed connection" not in string:
                msg = "should have logged into Mock SSH client and exited"
                raise AssertionError(msg)
        except pxssh.ExceptionPxssh as err:
            msg = "should not have raised exception, pxssh.ExceptionPxssh"
            raise AssertionError(msg) from err

    def test_failed_custom_ssh_cmd(self) -> None:
        """Fail the login when the custom ssh command names an invalid cipher."""
        try:
            ssh = pxssh.pxssh()
            cipher_string = "-c invalid_cipher"
            ssh.login("server", "me", password=FAKE_PW, cmd="ssh " + cipher_string + " -2")

            ssh.PROMPT = r"Closed connection"
            ssh.sendline("exit")
            ssh.prompt(timeout=5)
            string = str(ssh.before) + str(ssh.after)

            if "Closed connection" not in string:
                msg = "should not have completed logging into Mock SSH client and exited"
                raise AssertionError(msg)
        except pxssh.ExceptionPxssh:
            pass
        else:
            msg = "should have raised exception, pxssh.ExceptionPxssh"
            raise AssertionError(msg)

    def test_login_bash(self) -> None:
        """Log in to a fake server running bash and exchange a ping."""
        ssh = pxssh.pxssh()
        ssh.login("server bash", "me", password=FAKE_PW)
        ssh.sendline("ping")
        ssh.expect("pong", timeout=10)
        assert ssh.prompt(timeout=10)
        ssh.logout()

    def test_login_zsh(self) -> None:
        """Log in to a fake server running zsh and exchange a ping."""
        ssh = pxssh.pxssh()
        ssh.login("server zsh", "me", password=FAKE_PW)
        ssh.sendline("ping")
        ssh.expect("pong", timeout=10)
        assert ssh.prompt(timeout=10)
        ssh.logout()

    def test_login_tcsh(self) -> None:
        """Log in to a fake server running tcsh and exchange a ping."""
        ssh = pxssh.pxssh()
        ssh.login("server tcsh", "me", password=FAKE_PW)
        ssh.sendline("ping")
        ssh.expect("pong", timeout=10)
        assert ssh.prompt(timeout=10)
        ssh.logout()


if __name__ == "__main__":
    unittest.main()
