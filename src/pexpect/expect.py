"""Search machinery behind every ``expect()`` call.

:class:`Expecter` drives the read-and-search loop, while
:class:`searcher_string` and :class:`searcher_re` do the actual matching.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .exceptions import EOF, TIMEOUT

if TYPE_CHECKING:
    import re
    from collections.abc import Iterable

    from .spawnbase import SpawnBase


class Expecter:
    """Read from a spawn object until one of a searcher's patterns matches."""

    def __init__(
        self,
        spawn: SpawnBase,
        searcher: searcher_string | searcher_re,
        searchwindowsize: int | None = -1,
    ) -> None:
        """Bind ``searcher`` to ``spawn``.

        A ``searchwindowsize`` of -1 means to use the figure from ``spawn``,
        which should be None or a positive number.
        """
        self.spawn = spawn
        self.searcher = searcher
        if searchwindowsize == -1:
            searchwindowsize = spawn.searchwindowsize
        self.searchwindowsize = searchwindowsize
        self.lookback = None
        if hasattr(searcher, "longest_string"):
            self.lookback = searcher.longest_string

    def do_search(self, window: str | bytes, freshlen: int) -> int | None:
        """Search ``window`` and return the matching pattern's index, or None.

        On a match the spawn object's ``before``, ``after``, ``match`` and
        ``match_index`` attributes are updated; otherwise the buffer is trimmed
        to the data still worth searching.
        """
        spawn = self.spawn
        searcher = self.searcher
        freshlen = min(freshlen, len(window))
        index = searcher.search(window, freshlen, self.searchwindowsize)
        if index >= 0:
            spawn._buffer = spawn.buffer_type()
            spawn._buffer.write(window[searcher.end :])
            spawn.before = spawn._before.getvalue()[0 : -(len(window) - searcher.start)]
            spawn._before = spawn.buffer_type()
            spawn._before.write(window[searcher.end :])
            spawn.after = window[searcher.start : searcher.end]
            spawn.match = searcher.match
            spawn.match_index = index
            # Found a match
            return index
        if self.searchwindowsize or self.lookback:
            maintain = self.searchwindowsize or self.lookback
            if spawn._buffer.tell() > maintain:
                spawn._buffer = spawn.buffer_type()
                spawn._buffer.write(window[-maintain:])
        return None

    def existing_data(self) -> int | None:
        """Search the data already buffered on the spawn object.

        This is the first call from a new call to expect_loop or expect_async,
        so ``self.searchwindowsize`` may have changed and all data is treated
        as fresh.
        """
        spawn = self.spawn
        before_len = spawn._before.tell()
        buf_len = spawn._buffer.tell()
        freshlen = before_len
        if before_len > buf_len:
            if not self.searchwindowsize:
                spawn._buffer = spawn.buffer_type()
                window = spawn._before.getvalue()
                spawn._buffer.write(window)
            elif buf_len < self.searchwindowsize:
                spawn._buffer = spawn.buffer_type()
                spawn._before.seek(max(0, before_len - self.searchwindowsize))
                window = spawn._before.read()
                spawn._buffer.write(window)
            else:
                spawn._buffer.seek(max(0, buf_len - self.searchwindowsize))
                window = spawn._buffer.read()
        elif self.searchwindowsize:
            spawn._buffer.seek(max(0, buf_len - self.searchwindowsize))
            window = spawn._buffer.read()
        else:
            window = spawn._buffer.getvalue()
        return self.do_search(window, freshlen)

    def new_data(self, data: str | bytes) -> int | None:
        """Buffer freshly read ``data`` and search it.

        This is a subsequent call, after a call to existing_data.
        """
        spawn = self.spawn
        freshlen = len(data)
        spawn._before.write(data)
        if not self.searchwindowsize:
            if self.lookback:
                # search lookback + new data.
                old_len = spawn._buffer.tell()
                spawn._buffer.write(data)
                spawn._buffer.seek(max(0, old_len - self.lookback))
                window = spawn._buffer.read()
            else:
                # copy the whole buffer (really slow for large datasets).
                spawn._buffer.write(data)
                window = spawn.buffer
        elif len(data) >= self.searchwindowsize or not spawn._buffer.tell():
            window = data[-self.searchwindowsize :]
            spawn._buffer = spawn.buffer_type()
            spawn._buffer.write(window[-self.searchwindowsize :])
        else:
            spawn._buffer.write(data)
            new_len = spawn._buffer.tell()
            spawn._buffer.seek(max(0, new_len - self.searchwindowsize))
            window = spawn._buffer.read()
        return self.do_search(window, freshlen)

    def eof(self, err: Exception | None = None) -> int:
        """Return the searcher's EOF index, or raise :class:`EOF`.

        The spawn object's match attributes are updated either way.
        """
        spawn = self.spawn

        spawn.before = spawn._before.getvalue()
        spawn._buffer = spawn.buffer_type()
        spawn._before = spawn.buffer_type()
        spawn.after = EOF
        index = self.searcher.eof_index
        if index >= 0:
            spawn.match = EOF
            spawn.match_index = index
            return index
        spawn.match = None
        spawn.match_index = None
        msg = str(spawn)
        msg += f"\nsearcher: {self.searcher}"
        if err is not None:
            msg = str(err) + "\n" + msg

        raise EOF(msg) from None

    def timeout(self, err: Exception | None = None) -> int:
        """Return the searcher's TIMEOUT index, or raise :class:`TIMEOUT`.

        The spawn object's match attributes are updated either way.
        """
        spawn = self.spawn

        spawn.before = spawn._before.getvalue()
        spawn.after = TIMEOUT
        index = self.searcher.timeout_index
        if index >= 0:
            spawn.match = TIMEOUT
            spawn.match_index = index
            return index
        spawn.match = None
        spawn.match_index = None
        msg = str(spawn)
        msg += f"\nsearcher: {self.searcher}"
        if err is not None:
            msg = str(err) + "\n" + msg

        raise TIMEOUT(msg) from None

    def errored(self) -> None:
        """Clear the spawn object's match attributes after an unexpected error."""
        spawn = self.spawn
        spawn.before = spawn._before.getvalue()
        spawn.after = None
        spawn.match = None
        spawn.match_index = None

    def _read_until_match(self, timeout: float | None, end_time: float | None) -> int:
        """Read and search repeatedly until a pattern matches or time runs out.

        ``timeout`` is the time left for the next read and ``end_time`` the
        absolute deadline it is recomputed from; both are None when the caller
        asked to block forever.
        """
        spawn = self.spawn
        while True:
            # No match at this point
            if (timeout is not None) and (timeout < 0):
                return self.timeout()
            # Still have time left, so read more data
            incoming = spawn.read_nonblocking(spawn.maxread, timeout)
            if spawn.delayafterread is not None:
                time.sleep(spawn.delayafterread)
            idx = self.new_data(incoming)
            # Keep reading until exception or return.
            if idx is not None:
                return idx
            if timeout is not None:
                timeout = end_time - time.time()

    def expect_loop(self, timeout: float | None = -1) -> int:
        """Blocking expect."""
        end_time = time.time() + timeout if timeout is not None else None

        try:
            idx = self.existing_data()
            if idx is None:
                idx = self._read_until_match(timeout, end_time)
        except EOF as e:
            return self.eof(e)
        except TIMEOUT as e:
            return self.timeout(e)
        except:
            self.errored()
            raise
        return idx


class searcher_string:
    """Plain string search helper for the spawn.expect_any() method.

    This helper class is for speed. For more powerful regex patterns
    see the helper class, searcher_re.

    Attributes:
        eof_index     - index of EOF, or -1
        timeout_index - index of TIMEOUT, or -1

    After a successful match by the search() method the following attributes
    are available:

        start - index into the buffer, first byte of match
        end   - index into the buffer, first byte after match
        match - the matching string itself

    """

    def __init__(self, strings: Iterable[type[EOF | TIMEOUT] | str | bytes]) -> None:
        """Create an instance of searcher_string.

        The argument 'strings' may be a list; a sequence of strings; or the EOF
        or TIMEOUT types.
        """
        self.eof_index = -1
        self.timeout_index = -1
        self._strings = []
        self.longest_string = 0
        for n, s in enumerate(strings):
            if s is EOF:
                self.eof_index = n
                continue
            if s is TIMEOUT:
                self.timeout_index = n
                continue
            self._strings.append((n, s))
            self.longest_string = max(self.longest_string, len(s))

    def __str__(self) -> str:
        """Return a human-readable string that represents the state of the object."""
        ss = [(n, f"    {n}: {s!r}") for n, s in self._strings]
        ss.append((-1, "searcher_string:"))
        if self.eof_index >= 0:
            ss.append((self.eof_index, f"    {self.eof_index}: EOF"))
        if self.timeout_index >= 0:
            ss.append((self.timeout_index, f"    {self.timeout_index}: TIMEOUT"))
        ss.sort()
        ss = list(zip(*ss, strict=False))[1]
        return "\n".join(ss)

    def search(
        self,
        buffer: str | bytes,
        freshlen: int,
        searchwindowsize: int | None = None,
    ) -> int:
        """Search 'buffer' for the first occurrence of one of the search strings.

        'freshlen' must indicate the number of bytes at the end of 'buffer'
        which have not been searched before. It helps to avoid searching the
        same, possibly big, buffer over and over again.

        See class spawn for the 'searchwindowsize' argument.

        If there is a match this returns the index of that string, and sets
        'start', 'end' and 'match'. Otherwise, this returns -1.
        """
        first_match = None

        # 'freshlen' helps a lot here. Further optimizations could
        # possibly include:
        #
        # using something like the Boyer-Moore Fast String Searching
        # Algorithm; pre-compiling the search through a list of
        # strings into something that can scan the input once to
        # search for all N strings; realize that if we search for
        # ['bar', 'baz'] and the input is '...foo' we need not bother
        # rescanning until we've read three more bytes.
        #
        # Sadly, I don't know enough about this interesting topic. /grahn

        for index, s in self._strings:
            # Without a searchwindowsize the match, if any, can only be in the
            # fresh data or at the very end of the old data; with one, obey it.
            offset = -(freshlen + len(s)) if searchwindowsize is None else -searchwindowsize
            n = buffer.find(s, offset)
            if n >= 0 and (first_match is None or n < first_match):
                first_match = n
                best_index, best_match = index, s
        if first_match is None:
            return -1
        self.match = best_match
        self.start = first_match
        self.end = self.start + len(self.match)
        return best_index


class searcher_re:
    """Regular expression search helper for the spawn.expect_any() method.

    This helper class is for powerful pattern matching. For speed, see the
    helper class, searcher_string.

    Attributes:
        eof_index     - index of EOF, or -1
        timeout_index - index of TIMEOUT, or -1

    After a successful match by the search() method the following attributes
    are available:

        start - index into the buffer, first byte of match
        end   - index into the buffer, first byte after match
        match - the re.match object returned by a successful re.search

    """

    def __init__(
        self,
        patterns: Iterable[type[EOF | TIMEOUT] | re.Pattern[str] | re.Pattern[bytes]],
    ) -> None:
        """Create an instance that searches for 'patterns'.

        'patterns' may be a list or other sequence of compiled regular
        expressions, or the EOF or TIMEOUT types.
        """
        self.eof_index = -1
        self.timeout_index = -1
        self._searches = []
        for n, s in enumerate(patterns):
            if s is EOF:
                self.eof_index = n
                continue
            if s is TIMEOUT:
                self.timeout_index = n
                continue
            self._searches.append((n, s))

    def __str__(self) -> str:
        """Return a human-readable string that represents the state of the object."""
        ss = [(n, f"    {n}: re.compile({s.pattern!r})") for n, s in self._searches]
        ss.append((-1, "searcher_re:"))
        if self.eof_index >= 0:
            ss.append((self.eof_index, f"    {self.eof_index}: EOF"))
        if self.timeout_index >= 0:
            ss.append((self.timeout_index, f"    {self.timeout_index}: TIMEOUT"))
        ss.sort()
        ss = list(zip(*ss, strict=False))[1]
        return "\n".join(ss)

    def search(
        self,
        buffer: str | bytes,
        # ARG002: part of the public searcher protocol
        freshlen: int,  # part of the public searcher protocol  # noqa: ARG002
        searchwindowsize: int | None = None,
    ) -> int:
        """Search 'buffer' for the first occurrence of one of the regexes.

        'freshlen' must indicate the number of bytes at the end of 'buffer'
        which have not been searched before.

        See class spawn for the 'searchwindowsize' argument.

        If there is a match this returns the index of that string, and sets
        'start', 'end' and 'match'. Otherwise, returns -1.
        """
        first_match = None
        # 'freshlen' doesn't help here -- we cannot predict the
        # length of a match, and the re module provides no help.
        searchstart = 0 if searchwindowsize is None else max(0, len(buffer) - searchwindowsize)
        for index, s in self._searches:
            match = s.search(buffer, searchstart)
            if match is None:
                continue
            n = match.start()
            if first_match is None or n < first_match:
                first_match = n
                the_match = match
                best_index = index
        if first_match is None:
            return -1
        self.start = first_match
        self.match = the_match
        self.end = self.match.end()
        return best_index
