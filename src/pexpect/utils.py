"""Helpers shared by the pexpect modules.

Executable lookup, command line splitting, and EINTR-safe ``select``/``poll``
wrappers.
"""

import errno
import os
import select
import stat
import sys
import time
from pathlib import Path

# States of the little state machine used by split_command_line().
_STATE_BASIC = 0
_STATE_ESC = 1
_STATE_SINGLEQUOTE = 2
_STATE_DOUBLEQUOTE = 3
# The state when consuming whitespace between commands.
_STATE_WHITESPACE = 4
# Quote characters and the state each one opens, plus the reverse mapping used
# to recognise the closing quote.
_QUOTE_STATES = {"'": _STATE_SINGLEQUOTE, '"': _STATE_DOUBLEQUOTE}
_QUOTE_CHARS = {state: char for char, state in _QUOTE_STATES.items()}


def is_executable_file(path: str) -> bool:
    """Check that path is an executable regular file, or a symlink towards one.

    This is roughly ``os.path isfile(path) and os.access(path, os.X_OK)``.
    """
    # follow symlinks,
    fpath = Path(path).resolve()

    if not fpath.is_file():
        # non-files (directories, fifo, etc.)
        return False

    mode = fpath.stat().st_mode

    if sys.platform.startswith("sunos") and os.getuid() == 0:
        # When root on Solaris, os.X_OK is True for *all* files, irregardless
        # of their executability -- instead, any permission bit of any user,
        # group, or other is fine enough.
        #
        # (This may be true for other "Unix98" OS's such as HP-UX and AIX)
        return bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))

    return os.access(fpath, os.X_OK)


def which(filename: str, env: dict[str, str] | None = None) -> str | None:
    """Find filename on the environment path and check that it is executable.

    Return the full path to the filename if it was found and is executable,
    otherwise None.
    """
    # Special case where filename contains an explicit path.
    if Path(filename).name != filename and is_executable_file(filename):
        return filename
    search_path = (os.environ if env is None else env).get("PATH") or os.defpath
    for path in search_path.split(os.pathsep):
        candidate = str(Path(path) / filename)
        if is_executable_file(candidate):
            return candidate
    return None


def split_command_line(command_line: str) -> list[str]:
    """Split a command line into a list of arguments.

    It splits arguments on spaces, but handles embedded quotes, doublequotes,
    and escaped characters. It's impossible to do this with a regular
    expression, so I wrote a little state machine to parse the command line.
    """
    arg_list = []
    arg = ""
    state = _STATE_WHITESPACE

    for c in command_line:
        if state == _STATE_ESC:
            # Escaped character, whatever it is.
            arg = arg + c
            state = _STATE_BASIC
        elif state in _QUOTE_CHARS:
            # Inside single or double quotes until the matching quote.
            if c == _QUOTE_CHARS[state]:
                state = _STATE_BASIC
            else:
                arg = arg + c
        elif c == "\\":
            # Escape the next character
            state = _STATE_ESC
        elif c in _QUOTE_STATES:
            state = _QUOTE_STATES[c]
        elif not c.isspace():
            arg = arg + c
            state = _STATE_BASIC
        elif state != _STATE_WHITESPACE:
            # Add arg to arg_list if we aren't in the middle of whitespace.
            arg_list.append(arg)
            arg = ""
            state = _STATE_WHITESPACE

    if arg != "":
        arg_list.append(arg)
    return arg_list


def select_ignore_interrupts(
    iwtd: list[int],
    owtd: list[int],
    ewtd: list[int],
    timeout: float | None = None,
) -> tuple[list[int], list[int], list[int]]:
    """Wrap select.select() so that signals are ignored.

    If select.select() is interrupted by a signal (errno EINTR) then it is
    entered again with the remaining timeout. Mainly this is used to ignore
    sigwinch (terminal resize).
    """
    if timeout is not None:
        end_time = time.time() + timeout
    while True:
        try:
            return select.select(iwtd, owtd, ewtd, timeout)
        # PERF203: the try/except IS the EINTR retry
        except InterruptedError as err:  # the try/except IS the EINTR retry  # noqa: PERF203
            if err.args[0] == errno.EINTR:
                # if we loop back we have to subtract the
                # amount of time we already waited.
                if timeout is not None:
                    timeout = end_time - time.time()
                    if timeout < 0:
                        return ([], [], [])
            else:
                # something else caused the select.error, so
                # this actually is an exception.
                raise


def poll_ignore_interrupts(fds: list[int], timeout: float | None = None) -> list[int]:
    """Register file descriptors with poll() and ignore signals.

    Return the file descriptors that became ready. If poll() is interrupted by
    a signal (errno EINTR) then it is entered again with the remaining timeout.
    """
    if timeout is not None:
        end_time = time.time() + timeout

    # select.poll and its constants do not exist under --platform win32's
    # stubs, because the real module has none on Windows either. Neither
    # caller can reach this function there, though not for the same reason:
    # pty_spawn's constructor refuses use_poll=True outright, while
    # fdpexpect.read_nonblocking gates its whole readiness block on
    # `if os.name == "posix":` and so never consults use_poll at all -- which
    # silently ignores the timeout rather than refusing it, but does not call
    # poll() either. So the ignore below is about an unreachable call, not an
    # unhandled one.
    poller = select.poll()  # type: ignore[attr-defined]
    # One ignore covers all four attributes mypy flags on this line.
    events = select.POLLIN | select.POLLPRI | select.POLLHUP | select.POLLERR  # type: ignore[attr-defined]
    for fd in fds:
        poller.register(fd, events)

    while True:
        try:
            timeout_ms = None if timeout is None else timeout * 1000
            results = poller.poll(timeout_ms)
            return [afd for afd, _ in results]
        # PERF203: the try/except IS the EINTR retry
        except InterruptedError as err:  # the try/except IS the EINTR retry  # noqa: PERF203
            if err.args[0] == errno.EINTR:
                # if we loop back we have to subtract the
                # amount of time we already waited.
                if timeout is not None:
                    timeout = end_time - time.time()
                    if timeout < 0:
                        return []
            else:
                # something else caused the select.error, so
                # this actually is an exception.
                raise
