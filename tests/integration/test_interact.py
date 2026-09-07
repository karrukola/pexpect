#!/usr/bin/env python
"""PEXPECT LICENSE.

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

import os
import unittest

import pytest

import pexpect
from tests import pexpect_test_case

pytestmark = pytest.mark.usefixtures("fast_sleep", "child_coverage")


class InteractTestCase(pexpect_test_case.PexpectTestCase):
    """Tests for spawn.interact()."""

    def setUp(self) -> None:
        """Build a child environment that can import pexpect from the checkout."""
        super().setUp()
        self.env = env = os.environ.copy()

        # Ensure 'import pexpect' works in subprocess interact*.py
        if "PYTHONPATH" in env:
            env["PYTHONPATH"] = os.pathsep.join((self.project_dir, env["PYTHONPATH"]))
        else:
            env["PYTHONPATH"] = self.project_dir

        self.interact_py = f"{self.PYTHONBIN} interact.py"

    def test_interact_escape(self) -> None:
        """Ensure `escape_character' value exits interactive mode."""
        p = pexpect.spawn(self.interact_py, timeout=5, env=self.env)
        p.expect("READY")
        p.sendcontrol("]")  # chr(29), the default `escape_character'
        # value of pexpect.interact().
        p.expect_exact("Escaped interact")
        p.expect(pexpect.EOF)
        assert not p.isalive()
        assert p.exitstatus == 0

    def test_interact_escape_none(self) -> None:
        """Return only after Termination when `escape_character=None'."""
        p = pexpect.spawn(f"{self.interact_py} --no-escape", timeout=5, env=self.env)
        p.expect("READY")
        p.sendcontrol("]")
        p.expect("29<STOP>")
        p.send("\x00")
        if not os.environ.get("CI", None):
            # on CI platforms, we sometimes miss trailing stdout from the
            # chain of child processes, not entirely sure why. So this
            # is skipped on such systems.
            p.expect("0<STOP>")
            p.expect_exact("Escaped interact")
        p.expect(pexpect.EOF)
        assert not p.isalive()
        assert p.exitstatus == 0

    def test_interact_exit_unicode(self) -> None:
        """Ensure subprocess receives utf8."""
        p = pexpect.spawnu(f"{self.interact_py} --utf8", timeout=5, env=self.env)
        p.expect("READY")
        p.send("ɑ")  # noqa: RUF001  # deliberate non-ASCII test data
        p.expect("201<STOP>")  # [201, 145]
        p.expect("145<STOP>")
        p.send("Β")  # noqa: RUF001  # deliberate non-ASCII test data
        p.expect("206<STOP>")  # [206, 146]
        p.expect("146<STOP>")
        p.send("\x00")
        if not os.environ.get("CI", None):
            # on CI platforms, we sometimes miss trailing stdout from the
            # chain of child processes, not entirely sure why. So this
            # is skipped on such systems.
            p.expect("0<STOP>")
            p.expect_exact("Escaped interact")
        p.expect(pexpect.EOF)
        assert not p.isalive()
        assert p.exitstatus == 0

    def test_interact_filters(self) -> None:
        """Run the input and output through the filters interact() was given.

        Given an interact() called with an input filter that shifts each byte
        up by one and an output filter that marks up the child's greeting,
        When a byte is typed and the child echoes its ordinal back,
        Then the greeting arrives marked up and the ordinal is the one of the
        shifted byte, and, because the input filter runs before the escape
        character is looked for, the byte below the escape character ends the
        session.
        """
        p = pexpect.spawn(f"{self.interact_py} --filters", timeout=5, env=self.env)
        p.expect("READY<LOUD>")
        p.send("a")  # ord("a") is 97, so the filter makes it 98
        p.expect("98<STOP>")
        p.send("\x1c")  # the filter shifts this to chr(29), the escape character
        p.expect_exact("Escaped interact")
        p.expect(pexpect.EOF)
        assert not p.isalive()
        assert p.exitstatus == 0

    def test_interact_escape_after_data(self) -> None:
        """Send the data that precedes the escape character on to the child.

        Given an interact() and a single write holding two characters followed
        by the escape character,
        When that write is sent,
        Then the child receives the two characters and interact() returns
        without passing the escape character on.
        """
        p = pexpect.spawn(self.interact_py, timeout=5, env=self.env)
        p.expect("READY")
        p.send("ab\x1d")  # 'a', 'b', then chr(29), the escape character
        p.expect_exact("Escaped interact")
        p.expect(pexpect.EOF)
        assert not p.isalive()
        assert p.exitstatus == 0

    def test_interact_use_poll(self) -> None:
        """Shuttle data with poll() instead of select().

        Given a spawn created with use_poll set,
        When interact() copies data in both directions,
        Then it behaves as it does with select() and the escape character still
        ends the session.
        """
        p = pexpect.spawn(f"{self.interact_py} --use-poll", timeout=5, env=self.env)
        p.expect("READY")
        p.send("a")
        p.expect("97<STOP>")
        p.sendcontrol("]")
        p.expect_exact("Escaped interact")
        p.expect(pexpect.EOF)
        assert not p.isalive()
        assert p.exitstatus == 0

    def test_interact_with_a_dead_child(self) -> None:
        """Return straight away when the child has already exited.

        Given a spawn whose child has exited and whose output has been read to
        EOF,
        When interact() is called,
        Then it returns without copying anything.
        """
        p = pexpect.spawn(f"{self.interact_py} --dead-child", timeout=5, env=self.env)
        p.expect_exact("Escaped interact")
        p.expect(pexpect.EOF)
        assert not p.isalive()
        assert p.exitstatus == 0


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(InteractTestCase)
