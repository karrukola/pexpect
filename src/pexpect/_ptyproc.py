"""The process backend, and the only module in this package that picks one.

pexpect drives a child through a pseudo-terminal, and the code that owns that
pty is platform-specific: ptyprocess on POSIX, ConPTY by way of pywinpty on
Windows. Both are presented here under one name so that pty_spawn -- which is
otherwise platform-neutral -- never has to ask which platform it is on.

The surface is ptyprocess's, because that is the one pexpect already used, plus
two methods ptyprocess does not need. pexpect used to read and write the pty
with os.read() and os.write() on the descriptor, which is correct for a POSIX
pty and wrong on Windows, where the descriptor pywinpty hands out is a socket:
os.read() does not accept one. read_bytes() and write_bytes() are that pair of
calls, moved to the side of the seam that knows what the descriptor is.
"""

from __future__ import annotations

import os
import sys

if sys.platform == "win32":  # pragma: no cover -- the POSIX run omits this file
    from ._winpty import PtyProcess, PtyProcessError

    # No fork, so nothing to be native about. Kept because pexpect.spawn
    # carries a class attribute of this name that has been public since 3.x.
    use_native_pty_fork = False
else:
    import ptyprocess
    from ptyprocess.ptyprocess import PtyProcessError, use_native_pty_fork

    class PtyProcess(ptyprocess.PtyProcess):  # type: ignore[no-redef]
        """ptyprocess's pty child, plus the two byte-level calls pexpect makes.

        PtyProcess.spawn() instantiates through ``cls``, so a subclass comes
        back from it and no override is needed here.
        """

        def read_bytes(self, size: int) -> bytes:
            """Read at most *size* bytes from the pty, as os.read() would."""
            return os.read(self.fd, size)

        def write_bytes(self, data: bytes) -> int:
            """Write *data* to the pty and return the number of bytes taken."""
            return os.write(self.fd, data)


__all__ = ["PtyProcess", "PtyProcessError", "use_native_pty_fork"]
