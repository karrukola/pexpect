"""Tests for :mod:`pexpect.pxssh` logins that drive the ``fakessh`` harness.

Each of these starts the mock ssh client, hands it a password and walks a whole
login handshake, which is a Python interpreter plus a dozen pty round trips.
That floor is above the suite's time budget however the timeouts are tuned,
so these live here while the rest of the pxssh tests stay under it.
"""

import unittest
from unittest import mock

import pytest

from pexpect import pxssh
from tests.test_pxssh import FAKE_PW, WRONG_PW, SSHTestBase

pytestmark = pytest.mark.usefixtures("fast_sleep", "lean_child_env")

# sync_original_prompt() presses enter and reads back whatever arrives, using
# timeouts to decide when the remote has finished talking. Its default is tuned
# for a loaded machine across a real network; the mock server is a local
# process, so the shortest workable pacing applies.
_SYNC_MULTIPLIER = 0.02

# set_unique_prompt() tries the sh, csh and zsh ways of setting a prompt in
# turn, waiting pxssh._PROMPT_SET_TIMEOUT for each. A shell that only answers to
# the third syntax therefore costs two full waits: 20 s at the shipped default.
_PROMPT_SET_TIMEOUT = 0.05


class _UnpromptablePxssh(pxssh.pxssh):
    """A pxssh whose unique-prompt step always fails."""

    def set_unique_prompt(self) -> bool:
        """Report that the prompt could not be set."""
        return False


class PxsshLoginTestCase(SSHTestBase):
    """Tests that log in to the fake server for real."""

    def setUp(self) -> None:
        """Shorten the prompt-setting waits that a local mock server never needs."""
        super().setUp()
        patcher = mock.patch.object(pxssh, "_PROMPT_SET_TIMEOUT", _PROMPT_SET_TIMEOUT)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_fake_ssh(self) -> None:
        """Log in to the fake server, exchange a ping and log out again."""
        ssh = pxssh.pxssh()
        ssh.login("server", "me", password=FAKE_PW, sync_multiplier=_SYNC_MULTIPLIER)
        ssh.sendline("ping")
        ssh.expect("pong", timeout=10)
        assert ssh.prompt(timeout=10)
        ssh.logout()

    def test_failed_set_unique_prompt(self) -> None:
        """Fail the login when the unique prompt cannot be set."""
        ssh = _UnpromptablePxssh()
        try:
            ssh.login(
                "server",
                "me",
                password=FAKE_PW,
                auto_prompt_reset=True,
                sync_multiplier=_SYNC_MULTIPLIER,
            )
        except pxssh.ExceptionPxssh:
            pass
        else:
            msg = "should have raised exception, pxssh.ExceptionPxssh"
            raise AssertionError(msg)

    def test_login_accepts_a_new_host_key(self) -> None:
        """Accept an unknown host key and carry on with the login.

        Given a fake server that asks whether to continue connecting before it
        asks for the password,
        When login() is called,
        Then the question is answered with yes and the login completes.
        """
        ssh = pxssh.pxssh()
        ssh.login("certserver", "me", password=FAKE_PW, sync_multiplier=_SYNC_MULTIPLIER)
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
        ssh.login(
            "termserver",
            "me",
            password=FAKE_PW,
            terminal_type="ansi",
            sync_multiplier=_SYNC_MULTIPLIER,
        )
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
        ssh.login("server", "me", password=FAKE_PW, sync_multiplier=_SYNC_MULTIPLIER)
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
        ssh.login("jobserver", "me", password=FAKE_PW, sync_multiplier=_SYNC_MULTIPLIER)
        ssh.logout()
        assert not ssh.isalive()

    def test_custom_ssh_cmd(self) -> None:
        """Log in with a custom ssh client command and exit cleanly."""
        try:
            ssh = pxssh.pxssh()
            cipher_string = (
                "-c aes128-ctr,aes192-ctr,aes256-ctr,arcfour256,arcfour128,"
                "aes128-cbc,3des-cbc,blowfish-cbc,cast128-cbc,aes192-cbc,"
                "aes256-cbc,arcfour"
            )
            ssh.login(
                "server",
                "me",
                password=FAKE_PW,
                cmd="ssh " + cipher_string + " -2",
                sync_multiplier=_SYNC_MULTIPLIER,
            )

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

    def test_login_bash(self) -> None:
        """Log in to a fake server running bash and exchange a ping."""
        ssh = pxssh.pxssh()
        ssh.login(
            "server",
            "me",
            password=FAKE_PW,
            sync_multiplier=_SYNC_MULTIPLIER,
            cmd="ssh -s bash",
        )
        ssh.sendline("ping")
        ssh.expect("pong", timeout=10)
        assert ssh.prompt(timeout=10)
        ssh.logout()

    def test_login_zsh(self) -> None:
        """Log in to a fake server running zsh and exchange a ping.

        The mock is told to speak zsh with ``-s``, a test-only option (see
        ``tests/fakessh/ssh``): ``server`` is now quoted by pxssh, so the old
        trick of naming the shell as a second word in the server argument
        ("server zsh") arrives as a single, unsplit hostname and no longer
        reaches the mock's shell selection.
        """
        ssh = pxssh.pxssh()
        ssh.login(
            "server",
            "me",
            password=FAKE_PW,
            sync_multiplier=_SYNC_MULTIPLIER,
            cmd="ssh -s zsh",
        )
        ssh.sendline("ping")
        ssh.expect("pong", timeout=10)
        assert ssh.prompt(timeout=10)
        ssh.logout()

    def test_login_tcsh(self) -> None:
        """Log in to a fake server running tcsh and exchange a ping.

        See :meth:`test_login_zsh` for why the shell is selected through
        ``cmd="ssh -s tcsh"`` rather than a second word in the server name.
        """
        ssh = pxssh.pxssh()
        ssh.login(
            "server",
            "me",
            password=FAKE_PW,
            sync_multiplier=_SYNC_MULTIPLIER,
            cmd="ssh -s tcsh",
        )
        ssh.sendline("ping")
        ssh.expect("pong", timeout=10)
        assert ssh.prompt(timeout=10)
        ssh.logout()

    def test_login_with_a_space_in_the_server_name_is_not_split(self) -> None:
        """A server name with a space must reach the mock as one hostname.

        Given a server name that starts with the sentinel the mock refuses
        ("noserver") followed by a space and more text,
        When login() is called,
        Then the whole string arrives at the mock as a single hostname --
        distinct from the bare sentinel -- so the mock does not refuse the
        connection.

        Before ``server`` was quoted, the space would have split this into
        the literal hostname "noserver" plus a bogus positional shell name,
        and the mock's exact-match refusal ("No route to host") would have
        fired instead of a normal login.
        """
        ssh = pxssh.pxssh()
        ssh.login(
            "noserver etc",
            "me",
            password=FAKE_PW,
            sync_multiplier=_SYNC_MULTIPLIER,
        )
        ssh.sendline("ping")
        ssh.expect("pong", timeout=10)
        assert ssh.prompt(timeout=10)
        ssh.logout()

    def test_wrong_pw(self) -> None:
        """Refuse a login whose password the fake server rejects."""
        ssh = pxssh.pxssh()
        try:
            ssh.login("server", "me", password=WRONG_PW, sync_multiplier=_SYNC_MULTIPLIER)
        except pxssh.ExceptionPxssh:
            pass
        else:
            msg = "Password should have been refused"
            raise AssertionError(msg)

    def test_connection_refused(self) -> None:
        """Fail the login when the fake server refuses the connection."""
        ssh = pxssh.pxssh()
        try:
            ssh.login("noserver", "me", password=FAKE_PW, sync_multiplier=_SYNC_MULTIPLIER)
        except pxssh.ExceptionPxssh:
            pass
        else:
            msg = "should have raised exception, pxssh.ExceptionPxssh"
            raise AssertionError(msg)

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


if __name__ == "__main__":
    unittest.main()
