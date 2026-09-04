"""Tests for sending, matching and logging non-ASCII text."""

import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

import pexpect

from . import pexpect_test_case

# the program cat(1) may display ^D\x08\x08 when \x04 (EOF, Ctrl-D) is sent
_CAT_EOF = "^D\x08\x08"

# "unicode" spelled with lookalike letters; the non-ASCII round trip is the point
_UNICODE_ARGV = "ǝpoɔıun"  # deliberate non-ASCII fixture  # noqa: RUF001


class UnicodeTests(pexpect_test_case.PexpectTestCase):
    """Exercise sending, matching and logging text outside ASCII."""

    def test_expect_basic(self) -> None:
        """Match non-ASCII lines echoed back by cat."""
        p = pexpect.spawnu("cat")
        p.sendline("Hello")
        p.sendline("there")
        p.sendline("Mr. þython")  # þ is more like th than p, but never mind
        p.expect("Hello")
        p.expect("there")
        p.expect("Mr. þython")
        p.sendeof()
        p.expect(pexpect.EOF)

    def test_expect_exact_basic(self) -> None:
        """Match non-ASCII lines with expect_exact()."""
        p = pexpect.spawnu("cat")
        p.sendline("Hello")
        p.sendline("there")
        p.sendline("Mr. þython")
        p.expect_exact("Hello")
        p.expect_exact("there")
        p.expect_exact("Mr. þython")
        p.sendeof()
        p.expect_exact(pexpect.EOF)

    def test_expect_setecho_toggle(self) -> None:
        """Toggle tty echo off and then back on."""
        p = pexpect.spawnu("cat", timeout=5)
        try:
            self._expect_echo_toggle_off(p)
        except OSError:
            if sys.platform.lower().startswith("sunos"):
                msg = "Not supported on this platform."
                raise unittest.SkipTest(msg) from None
            raise
        self._expect_echo_toggle_on(p)

    def test_expect_echo_exact(self) -> None:
        """Like test_expect_echo(), but using expect_exact()."""
        p = pexpect.spawnu("cat", timeout=5)
        p.expect = p.expect_exact
        self._expect_echo(p)

    def test_expect_setecho_toggle_exact(self) -> None:
        """Toggle tty echo off and back on while using expect_exact()."""
        p = pexpect.spawnu("cat", timeout=5)
        p.expect = p.expect_exact
        try:
            self._expect_echo_toggle_off(p)
        except OSError:
            if sys.platform.lower().startswith("sunos"):
                msg = "Not supported on this platform."
                raise unittest.SkipTest(msg) from None
            raise
        self._expect_echo_toggle_on(p)

    def _expect_echo(self, p: pexpect.spawn) -> None:
        p.sendline("1234")  # Should see this twice (once from tty echo and again from cat).
        index = p.expect(["1234", "abcdé", "wxyz", pexpect.EOF, pexpect.TIMEOUT])
        assert index == 0, (index, p.before)
        index = p.expect(["1234", "abcdé", "wxyz", pexpect.EOF])
        assert index == 0, index

    def _expect_echo_toggle_off(self, p: pexpect.spawn) -> None:
        p.setecho(0)  # Turn off tty echo
        p.waitnoecho()
        p.sendline("abcdé")  # Now, should only see this once.
        p.sendline("wxyz")  # Should also be only once.
        patterns = [pexpect.EOF, pexpect.TIMEOUT, "abcdé", "wxyz", "1234"]
        index = p.expect(patterns)
        assert index == patterns.index("abcdé"), index
        patterns = [pexpect.EOF, "abcdé", "wxyz", "7890"]
        index = p.expect(patterns)
        assert index == patterns.index("wxyz"), index

    def _expect_echo_toggle_on(self, p: pexpect.spawn) -> None:
        p.setecho(1)  # Turn on tty echo
        time.sleep(0.2)  # there is no waitecho() !
        p.sendline("7890")  # Should see this twice.
        patterns = [pexpect.EOF, "abcdé", "wxyz", "7890"]
        index = p.expect(patterns)
        assert index == patterns.index("7890"), index
        index = p.expect(patterns)
        assert index == patterns.index("7890"), index
        p.sendeof()

    def test_log_unicode(self) -> None:
        """Log the unicode text sent to and read back from the child."""
        msg = "abcΩ÷"
        tmpdir = Path(tempfile.mkdtemp())
        path_send = tmpdir / "logfile_send"
        path_read = tmpdir / "logfile_read"
        p = pexpect.spawnu("cat")
        # both log files are closed further down, after the child has exited
        p.logfile_send = path_send.open("w", encoding="utf-8")
        p.logfile_read = path_read.open("w", encoding="utf-8")
        p.sendline(msg)
        p.sendeof()
        p.expect(pexpect.EOF)
        p.close()
        p.logfile_send.close()
        p.logfile_read.close()

        # ensure the 'send' log is correct,
        with path_send.open(encoding="utf-8") as f:
            assert f.read() == msg + "\n\x04"

        # ensure the 'read' log is correct,
        with path_read.open(encoding="utf-8", newline="") as f:
            output = f.read().replace(_CAT_EOF, "")
            assert output == (msg + "\r\n") * 2

        shutil.rmtree(tmpdir)

    def test_spawn_expect_ascii_unicode(self) -> None:
        """Expect ASCII-only unicode patterns from a bytes-based spawn."""
        # A bytes-based spawn should be able to handle ASCII-only unicode, for
        # backwards compatibility.
        p = pexpect.spawn("cat")
        p.sendline("Camelot")
        p.expect("Camelot")

        p.sendline("Aargh")
        p.sendline("Aårgh")
        p.expect_exact("Aargh")

        p.sendeof()
        p.expect(pexpect.EOF)

    def test_spawn_send_unicode(self) -> None:
        """Send non-ASCII text through a bytes-based spawn."""
        # A bytes-based spawn should be able to send arbitrary unicode
        p = pexpect.spawn("cat")
        p.sendline("3½")
        p.sendeof()
        p.expect(pexpect.EOF)

    def test_spawn_utf8_incomplete(self) -> None:
        """Decode UTF-8 that does not align with the read boundaries."""
        # This test case ensures correct incremental decoding, which
        # otherwise fails when the stream inspected by os.read()
        # does not align exactly at a utf-8 multibyte boundary:
        #    UnicodeDecodeError: 'utf8' codec can't decode byte 0xe2 in
        #                        position 0: unexpected end of data
        p = pexpect.spawnu("cat", maxread=1)
        p.sendline("▁▂▃▄▅▆▇█")
        p.sendeof()
        p.expect("▁▂▃▄▅▆▇█")

    def test_readline_bin_echo(self) -> None:
        """Read a line as str from a spawnu object."""
        # Test using readline() with spawnu objects. pexpect 3.2 had threw
        # a TypeError when concatenating a bytestring to a unicode type.

        # given,
        child = pexpect.spawnu(
            "echo",
            [
                "input",
            ],
        )

        # exercise,
        assert child.readline() == "input" + child.crlf

    def test_unicode_argv(self) -> None:
        """Ensure a program can be executed with unicode arguments."""
        p = pexpect.spawn(f"echo {_UNICODE_ARGV}", timeout=5, encoding="utf8")
        p.expect(_UNICODE_ARGV)
        p.expect(pexpect.EOF)
        assert not p.isalive()
        assert p.exitstatus == 0


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(UnicodeTests)
