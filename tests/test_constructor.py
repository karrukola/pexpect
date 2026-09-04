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

import unittest

import pexpect

from . import pexpect_test_case


class TestCaseConstructor(pexpect_test_case.PexpectTestCase):
    """Tests for the ways spawn.__init__() can be called."""

    def test_constructor(self) -> None:
        """Give the same result whether the arguments are in the command or a list."""
        p1 = pexpect.spawn("uname -m -n -p -r -s -v")
        p2 = pexpect.spawn("uname", ["-m", "-n", "-p", "-r", "-s", "-v"])
        p1.expect(pexpect.EOF)
        p2.expect(pexpect.EOF)
        assert p1.before == p2.before

    def test_named_parameters(self) -> None:
        """Accept command, args and timeout as keyword arguments."""
        pexpect.spawn("/bin/ls", timeout=10)
        pexpect.spawn(timeout=10, command="/bin/ls")
        pexpect.spawn(args=[], command="/bin/ls")


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(TestCaseConstructor)
