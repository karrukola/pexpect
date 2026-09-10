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

import re
import unittest

import pytest

import pexpect

from . import commands, pexpect_test_case

pytestmark = pytest.mark.usefixtures("fast_sleep", "killed_pty_children")
testdata = "BEGIN\nHello world\nEND"


class TestCaseDotall(pexpect_test_case.PexpectTestCase):
    """Tests for the re.DOTALL flag applied to expect() patterns."""

    def test_dotall(self) -> None:
        """Match a pattern spanning newlines, since expect() implies DOTALL."""
        p = pexpect.spawn(commands.echo(f'"{testdata}"'))
        i = p.expect([b"BEGIN(.*)END", pexpect.EOF])
        assert i == 0, "DOTALL does not seem to be working."

    def test_precompiled(self) -> None:
        """Honour the flags of a precompiled pattern instead of adding DOTALL."""
        p = pexpect.spawn(commands.echo(f'"{testdata}"'))
        pat = re.compile(b"BEGIN(.*)END")  # This overrides the default DOTALL.
        i = p.expect([pat, pexpect.EOF])
        assert i == 1, "Precompiled pattern to override DOTALL does not seem to be working."


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(TestCaseDotall)
