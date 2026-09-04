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

import gc
import platform
import time
import unittest

import pexpect

from . import pexpect_test_case


class TestCaseDestructor(pexpect_test_case.PexpectTestCase):
    """Tests that spawn objects release their pty on garbage collection."""

    def test_destructor(self) -> str | None:
        """Reuse the same pty descriptors after each batch of spawns is collected."""
        if platform.python_implementation() != "CPython":
            # Details of garbage collection are different on other implementations
            return "SKIP"
        gc.collect()
        time.sleep(3)
        p1 = pexpect.spawn(f"{self.PYTHONBIN} hello_world.py")
        p2 = pexpect.spawn(f"{self.PYTHONBIN} hello_world.py")
        p3 = pexpect.spawn(f"{self.PYTHONBIN} hello_world.py")
        p4 = pexpect.spawn(f"{self.PYTHONBIN} hello_world.py")
        fd_t1 = (p1.child_fd, p2.child_fd, p3.child_fd, p4.child_fd)
        p1.expect(pexpect.EOF)
        p2.expect(pexpect.EOF)
        p3.expect(pexpect.EOF)
        p4.expect(pexpect.EOF)
        p1.kill(9)
        p2.kill(9)
        p3.kill(9)
        p4.kill(9)
        p1 = None
        p2 = None
        p3 = None
        p4 = None
        gc.collect()
        time.sleep(3)  # Some platforms are slow at gc... Solaris!

        p1 = pexpect.spawn(f"{self.PYTHONBIN} hello_world.py")
        p2 = pexpect.spawn(f"{self.PYTHONBIN} hello_world.py")
        p3 = pexpect.spawn(f"{self.PYTHONBIN} hello_world.py")
        p4 = pexpect.spawn(f"{self.PYTHONBIN} hello_world.py")
        fd_t2 = (p1.child_fd, p2.child_fd, p3.child_fd, p4.child_fd)
        p1.kill(9)
        p2.kill(9)
        p3.kill(9)
        p4.kill(9)
        del p1
        del p2
        del p3
        del p4
        gc.collect()
        time.sleep(3)

        p1 = pexpect.spawn(f"{self.PYTHONBIN} hello_world.py")
        p2 = pexpect.spawn(f"{self.PYTHONBIN} hello_world.py")
        p3 = pexpect.spawn(f"{self.PYTHONBIN} hello_world.py")
        p4 = pexpect.spawn(f"{self.PYTHONBIN} hello_world.py")
        fd_t3 = (p1.child_fd, p2.child_fd, p3.child_fd, p4.child_fd)

        assert fd_t1 == fd_t2 == fd_t3, (
            "pty file descriptors not properly garbage collected "
            f"(fd_t1,fd_t2,fd_t3)=({fd_t1!s},{fd_t2!s},{fd_t3!s})"
        )
        return None


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(TestCaseDestructor)
