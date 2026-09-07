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

import sys
import unittest

import pytest

import pexpect

from . import pexpect_test_case

pytestmark = pytest.mark.usefixtures("fast_sleep", "killed_pty_children")
# The tests below only look at the TIMEOUT they provoke, never at how long the
# wait was, so they ask for the shortest one that still reaches the timeout path.
_TIMEOUT = 0.01


class ExpTimeoutTestCase(pexpect_test_case.PexpectTestCase):
    """Tests for the TIMEOUT exception and the stack trace it carries."""

    def test_matches_exp_timeout(self) -> None:
        """Catch a raised TIMEOUT with an ``except TIMEOUT`` clause."""
        try:
            msg = "TIMEOUT match test"
            raise pexpect.TIMEOUT(msg)  # noqa: TRY301  # raising here is the behaviour under test
        except pexpect.TIMEOUT:
            pass
        else:
            self.fail("TIMEOUT not caught by an except TIMEOUT clause.")

    def test_pattern_printout(self) -> None:
        """Report the patterns of the failing call in a TIMEOUT.

        Make sure it is returning the pattern from the correct call.
        """
        try:
            p = pexpect.spawn("cat")
            p.sendline("Hello")
            p.expect("Hello")
            p.expect("Goodbye", timeout=_TIMEOUT)
        except pexpect.TIMEOUT:
            assert p.match_index is None
        else:
            self.fail("Did not generate a TIMEOUT exception.")

    def test_exp_timeout_not_thrown(self) -> None:
        """Verify that a TIMEOUT is not thrown when we match what we expect."""
        try:
            p = pexpect.spawn("cat")
            p.sendline("Hello")
            p.expect("Hello")
        except pexpect.TIMEOUT:
            self.fail(
                "TIMEOUT caught when it shouldn't be raised because we match the proper pattern."
            )

    def test_stacktrace_munging(self) -> None:
        """Keep references to pexpect itself out of a TIMEOUT stack trace."""
        try:
            p = pexpect.spawn("cat")
            p.sendline("Hello")
            p.expect("Goodbye", timeout=_TIMEOUT)
        except pexpect.TIMEOUT:
            err = sys.exc_info()[1]
            if err.get_trace().count("pexpect/__init__.py") != 0:
                self.fail(
                    "The TIMEOUT get_trace() referenced pexpect.py. "
                    "It should only reference the caller.\n" + err.get_trace()
                )

    def test_correct_stack_trace(self) -> None:
        """Keep the intermediate caller in a TIMEOUT stack trace."""

        def nested_function(spawn_instance: pexpect.spawn) -> None:
            spawn_instance.expect("junk", timeout=_TIMEOUT)

        try:
            p = pexpect.spawn("cat")
            p.sendline("Hello")
            nested_function(p)
        except pexpect.TIMEOUT:
            err = sys.exc_info()[1]
            if err.get_trace().count("nested_function") == 0:
                self.fail(
                    "The TIMEOUT get_trace() did not show the call "
                    "to the nested_function function.\n" + str(err) + "\n" + err.get_trace()
                )


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(ExpTimeoutTestCase)
