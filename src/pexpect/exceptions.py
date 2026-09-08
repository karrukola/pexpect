"""Exception classes used by Pexpect."""

import sys
import traceback
from pathlib import Path

_PACKAGE_DIR = str(Path(__file__).parent)


class ExceptionPexpect(Exception):
    """Base class for all exceptions raised by this module."""

    def __init__(self, value: object) -> None:
        """Store ``value`` as the exception message and expose it as ``.value``."""
        super().__init__(value)
        self.value = value

    def __str__(self) -> str:
        """Return the message this exception was raised with."""
        return str(self.value)

    def get_trace(self) -> str:
        """Return an abbreviated stack trace with lines that only concern the caller.

        In other words, the stack trace inside the Pexpect module is not
        included.
        """
        frames = traceback.extract_tb(sys.exc_info()[2])
        outside = [item for item in frames if _PACKAGE_DIR not in item[0]]
        return "".join(traceback.format_list(outside))


class EOF(ExceptionPexpect):
    """Raised when EOF is read from a child.

    This usually means the child has exited.
    """


class TIMEOUT(ExceptionPexpect):
    """Raised when a read time exceeds the timeout."""
