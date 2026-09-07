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
from unittest import mock

import pytest

import pexpect

from . import pexpect_test_case

pytestmark = pytest.mark.usefixtures("fast_sleep", "killed_pty_children")


class MissingCommandTestCase(pexpect_test_case.PexpectTestCase):
    """Tests for spawning a command that does not exist."""

    def test_missing_command(self) -> None:
        """Raise ExceptionPexpect when the command cannot be found."""
        # A missing command is the one lookup that walks every PATH entry, so
        # the cost of the test is the cost of the developer's PATH. Point it at
        # a single directory: the test only cares that the command is absent.
        with (
            mock.patch.dict(os.environ, {"PATH": self.project_dir}),
            pytest.raises(pexpect.ExceptionPexpect),
        ):
            pexpect.spawn("ZXQYQZX")


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(MissingCommandTestCase)
