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


class SplitCommandLineTestCase(pexpect_test_case.PexpectTestCase):
    """Tests for pexpect.split_command_line()."""

    def test_split_sizes(self) -> None:
        """Count the arguments split_command_line() finds, honouring quotes and escapes."""
        commands_and_sizes = (
            (r"", 0),
            (r"one", 1),
            (r"one two", 2),
            (r"one  two", 2),
            (r"one   two", 2),
            (r"one\ one", 1),
            ("'one one'", 1),
            (r"one\"one", 1),
            (r"This\' is a\'\ test", 3),
        )
        for command, size in commands_and_sizes:
            assert len(pexpect.split_command_line(command)) == size, command


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(SplitCommandLineTestCase)
