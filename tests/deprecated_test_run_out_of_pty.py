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


class ExpectTestCase(pexpect_test_case.PexpectTestCase):
    """Tests for the error raised when the platform runs out of ptys."""

    # This takes too long to run and isn't all that interesting of a test.
    def off_test_run_out_of_pty(self) -> None:
        """Raise ExceptionPexpect once no pty device is left.

        Assumes that the tested platform has < 10000 pty devices. This test
        currently does not work under Solaris: there it runs out of file
        descriptors first and ld.so starts to barf:
            ld.so.1: pt_chmod: fatal: /usr/lib/libc.so.1: Too many open files.
        """
        plist = []
        for count in range(10000):
            try:
                plist.append(pexpect.spawn("ls -l"))
            except pexpect.ExceptionPexpect:  # noqa: PERF203  # this IS how pty exhaustion is detected
                for c in range(count):
                    plist[c].close()
                return
            except Exception as err:  # noqa: BLE001  # any other exception is a test failure
                self.fail("Expected ExceptionPexpect. " + str(err))
        self.fail("Could not run out of pty devices. This may be OK.")


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(ExpectTestCase)
