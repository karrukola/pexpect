"""Backwards-compatible spawn API shared by every Pexpect spawn class."""

from __future__ import annotations

import codecs
import errno
import os
import re
import sys
from io import BytesIO, StringIO
from typing import (
    IO,
    TYPE_CHECKING,
    Any,
    AnyStr,
    Generic,
    Literal,
    NoReturn,
    Protocol,
    TypeVar,
    cast,
    overload,
)

from .exceptions import EOF, TIMEOUT
from .expect import Expecter, searcher_re, searcher_string

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Callable, Coroutine, Iterator, Sequence
    from types import TracebackType

    from ._async_w_await import PatternWaiter

    # A pattern as accepted by :meth:`SpawnBase.expect` before compilation.
    _Pattern = str | bytes | re.Pattern[str] | re.Pattern[bytes] | type[EOF | TIMEOUT]
    # The same, after :meth:`SpawnBase.compile_pattern_list` has processed it.
    _Compiled = re.Pattern[str] | re.Pattern[bytes] | type[EOF | TIMEOUT]
    # Whatever a successful search left behind: a regex match in the usual case,
    # or the EOF/TIMEOUT type when one of those was in the pattern list.
    _Match = re.Match[str] | re.Match[bytes] | str | bytes | type[EOF | TIMEOUT]


# AnyStr is invariant, so the coder protocols below carry their own parameters:
# an encoder only consumes its string type and a decoder only produces it.
_StrT_contra = TypeVar("_StrT_contra", contravariant=True)
_StrT_co = TypeVar("_StrT_co", covariant=True)


class _Encoder(Protocol[_StrT_contra]):
    """The incremental encoder half of a string mode, str or bytes."""

    def encode(self, s: _StrT_contra, /, final: bool = ...) -> bytes:
        """Encode a chunk of the caller's string type down to bytes."""
        ...


class _Decoder(Protocol[_StrT_co]):
    """The incremental decoder half of a string mode, str or bytes."""

    def decode(self, b: bytes, /, final: bool = ...) -> _StrT_co:
        """Decode a chunk of the child's bytes up to the caller's string type."""
        ...


class _Buffer(Protocol[AnyStr]):
    """The part of BytesIO/StringIO that the read and search paths use."""

    def read(self, size: int | None = ..., /) -> AnyStr:
        """Read from the current position."""
        ...

    def write(self, s: AnyStr, /) -> int:
        """Append at the current position."""
        ...

    def getvalue(self) -> AnyStr:
        """Return everything written so far."""
        ...

    def seek(self, offset: int, whence: int = ..., /) -> int:
        """Move the current position."""
        ...

    def tell(self) -> int:
        """Return the current position."""
        ...


_MAXREAD = 2000  # max bytes read at one time into the buffer
_TIMEOUT = 30  # default seconds to wait for a pattern


class _NullCoder:
    """Pass bytes through unchanged."""

    @staticmethod
    def encode(b: bytes, final: bool = False) -> bytes:  # codec API  # noqa: ARG004  # codec API
        """Return ``b`` unchanged."""
        return b

    @staticmethod
    def decode(b: bytes, final: bool = False) -> bytes:  # codec API  # noqa: ARG004  # codec API
        """Return ``b`` unchanged."""
        return b


class SpawnBase(Generic[AnyStr]):
    """A base class providing the backwards-compatible spawn API for Pexpect.

    This should not be instantiated directly: use :class:`pexpect.spawn` or
    :class:`pexpect.fdpexpect.fdspawn`.

    The class is generic over the type the child's output is handed back as.
    An ``encoding`` of None leaves it as ``bytes``; any codec name decodes it
    to ``str``. Each concrete subclass overloads its own constructor on that
    argument, so ``spawn("cat")`` is a ``spawn[bytes]`` while
    ``spawn("cat", encoding="utf-8")`` is a ``spawn[str]``.
    """

    encoding: str | None = None
    pid: int | None = None
    flag_eof = False

    # Chosen by _init_string_mode() from the two branches below. Each is the
    # str or the bytes flavour of one thing, so all of them are stated in terms
    # of the class's type parameter.
    string_type: type[AnyStr]
    buffer_type: Callable[[], _Buffer[AnyStr]]
    crlf: AnyStr
    linesep: AnyStr
    allowed_string_types: tuple[type[str | bytes], ...]
    write_to_stdout: Callable[[AnyStr], int]
    _encoder: _Encoder[AnyStr]
    _decoder: _Decoder[AnyStr]

    # Written by Expecter on every search, hence None until the first one and
    # None again after a search that ended in an error.
    searcher: searcher_re | searcher_string | None
    before: AnyStr | None
    after: AnyStr | type[EOF | TIMEOUT] | None
    match: _Match | None
    match_index: int | None

    # Filled in once the child has been waited on.
    exitstatus: int | None
    signalstatus: int | None
    status: int | None

    # Bound by the first async expect() and reused by every later one.
    async_pw_transport: tuple[PatternWaiter, asyncio.ReadTransport] | None

    # The untrimmed and the searchable views of what the child has written.
    _buffer: _Buffer[AnyStr]
    _before: _Buffer[AnyStr]

    def __init__(
        self,
        timeout: float | None = _TIMEOUT,
        maxread: int = _MAXREAD,
        searchwindowsize: int | None = None,
        logfile: IO[Any] | None = None,
        encoding: str | None = None,
        codec_errors: str = "strict",
    ) -> None:
        """Set up the read buffer, the log files and the string/bytes mode."""
        self.stdin = sys.stdin
        self.stdout = sys.stdout
        self.stderr = sys.stderr

        self.searcher = None
        self.ignorecase = False
        self.before = None
        self.after = None
        self.match = None
        self.match_index = None
        self.terminated = True
        self.exitstatus = None
        self.signalstatus = None
        # status returned by os.waitpid
        self.status = None
        # the child file descriptor is initially closed
        self.child_fd = -1
        self.timeout = timeout
        self.delimiter = EOF
        self.logfile = logfile
        # input from child (read_nonblocking)
        self.logfile_read: IO[Any] | None = None
        # output to send (send, sendline)
        self.logfile_send: IO[Any] | None = None
        # max bytes to read at one time into buffer
        self.maxread = maxread
        # Data before searchwindowsize point is preserved, but not searched.
        self.searchwindowsize = searchwindowsize
        # Delay used before sending data to child. Time in seconds.
        # Set this to None to skip the time.sleep() call completely.
        self.delaybeforesend: float | None = 0.05
        # Used by close() to give kernel time to update process status.
        # Time in seconds.
        self.delayafterclose = 0.1
        # Used by terminate() to give kernel time to update process status.
        # Time in seconds.
        self.delayafterterminate = 0.1
        # Delay in seconds to sleep after each call to read_nonblocking().
        # Set this to None to skip the time.sleep() call completely: that
        # would restore the behavior from pexpect-2.0 (for performance
        # reasons or because you don't want to release Python's global
        # interpreter lock).
        self.delayafterread: float | None = 0.0001
        self.softspace = False
        self.name = "<" + repr(self) + ">"
        self.closed = True

        self._init_string_mode(encoding, codec_errors)

        # storage for async transport
        self.async_pw_transport = None
        # This is the read buffer. See maxread.
        self._buffer = self.buffer_type()
        # The buffer may be trimmed for efficiency reasons.  This is the
        # untrimmed buffer, used to create the before attribute.
        self._before = self.buffer_type()

    def _init_string_mode(self, encoding: str | None, codec_errors: str) -> None:
        """Configure the codecs, buffer type and line endings for the chosen mode.

        With ``encoding`` of None the child's output is handed back as bytes;
        otherwise it is incrementally decoded to ``str``.
        """
        self.encoding = encoding
        self.codec_errors = codec_errors
        # Each branch settles what AnyStr is for this instance, but only the
        # overloaded constructor of a concrete subclass can say so in the type
        # system. Inside the class body the two flavours have to be cast onto
        # the type parameter.
        if encoding is None:
            # bytes mode (accepts some unicode for backwards compatibility)
            null_coder = _NullCoder()
            self._encoder = cast("_Encoder[AnyStr]", null_coder)
            self._decoder = cast("_Decoder[AnyStr]", null_coder)
            self.string_type = cast("type[AnyStr]", bytes)
            self.buffer_type = cast("Callable[[], _Buffer[AnyStr]]", BytesIO)
            self.crlf = cast("AnyStr", b"\r\n")
            self.allowed_string_types = (bytes, str)
            self.linesep = cast("AnyStr", os.linesep.encode("ascii"))

            def write_to_stdout(b: bytes) -> int:
                try:
                    return sys.stdout.buffer.write(b)
                except AttributeError:
                    # If stdout has been replaced, it may not have .buffer
                    return sys.stdout.write(b.decode("ascii", "replace"))

            self.write_to_stdout = cast("Callable[[AnyStr], int]", write_to_stdout)
        else:
            # unicode mode
            self._encoder = cast(
                "_Encoder[AnyStr]", codecs.getincrementalencoder(encoding)(codec_errors)
            )
            self._decoder = cast(
                "_Decoder[AnyStr]", codecs.getincrementaldecoder(encoding)(codec_errors)
            )
            self.string_type = cast("type[AnyStr]", str)
            self.buffer_type = cast("Callable[[], _Buffer[AnyStr]]", StringIO)
            self.crlf = cast("AnyStr", "\r\n")
            self.allowed_string_types = (str,)
            self.linesep = cast("AnyStr", os.linesep)
            self.write_to_stdout = cast("Callable[[AnyStr], int]", sys.stdout.write)

    def _log(self, s: str | bytes, direction: str) -> None:
        if self.logfile is not None:
            self.logfile.write(s)
            self.logfile.flush()
        second_log = self.logfile_send if (direction == "send") else self.logfile_read
        if second_log is not None:
            second_log.write(s)
            second_log.flush()

    # For backwards compatibility, in bytes mode (when encoding is None)
    # unicode is accepted for send and expect. Unicode mode is strictly unicode
    # only.
    def _coerce_expect_string(self, s: str | bytes) -> str | bytes:
        if self.encoding is None and not isinstance(s, bytes):
            return s.encode("ascii")
        return s

    # In bytes mode, regex patterns should also be of bytes type
    def _coerce_expect_re(
        self,
        r: re.Pattern[str] | re.Pattern[bytes],
    ) -> re.Pattern[str] | re.Pattern[bytes]:
        p = r.pattern
        if self.encoding is None and not isinstance(p, bytes):
            return re.compile(p.encode("utf-8"))
        # And vice-versa
        if self.encoding is not None and isinstance(p, bytes):
            return re.compile(p.decode("utf-8"))
        return r

    def _coerce_send_string(self, s: str | bytes) -> str | bytes:
        if self.encoding is None and not isinstance(s, bytes):
            return s.encode("utf-8")
        return s

    def _get_buffer(self) -> AnyStr:
        return self._buffer.getvalue()

    def _set_buffer(self, value: AnyStr) -> None:
        self._buffer = self.buffer_type()
        self._buffer.write(value)

    # This property is provided for backwards compatibility (self.buffer used
    # to be a string/bytes object)
    buffer = property(_get_buffer, _set_buffer)

    def read_nonblocking(
        self,
        size: int = 1,
        # ARG002: honoured by overrides, not here
        timeout: float | None = None,  # honoured by overrides, not here  # noqa: ARG002
    ) -> AnyStr:
        """Read data from the file descriptor.

        This is a simple implementation suitable for a regular file.
        Subclasses using ptys or pipes should override it.

        The timeout parameter is ignored.
        """
        try:
            s = os.read(self.child_fd, size)
        except OSError as err:
            if err.args[0] == errno.EIO:
                # Linux-style EOF
                self.flag_eof = True
                msg = "End Of File (EOF). Exception style platform."
                raise EOF(msg) from err
            raise
        if s == b"":
            # BSD-style EOF
            self.flag_eof = True
            msg = "End Of File (EOF). Empty string style platform."
            raise EOF(msg)

        decoded = self._decoder.decode(s, final=False)
        self._log(decoded, "read")
        return decoded

    def _pattern_type_err(self, pattern: object) -> NoReturn:
        msg = (
            "got {badtype} ({badobj!r}) as pattern, must be one"
            " of: {goodtypes}, pexpect.EOF, pexpect.TIMEOUT".format(
                badtype=type(pattern),
                badobj=pattern,
                goodtypes=", ".join([str(ast) for ast in self.allowed_string_types]),
            )
        )
        raise TypeError(msg)

    def compile_pattern_list(
        self,
        patterns: _Pattern | list[_Pattern] | None,
    ) -> list[_Compiled]:
        """Compile a pattern-string or a list of pattern-strings.

        Patterns must be a StringType, EOF, TIMEOUT, SRE_Pattern, or a list of
        those. Patterns may also be None which results in an empty list (you
        might do this if waiting for an EOF or TIMEOUT condition without
        expecting any pattern).

        This is used by expect() when calling expect_list(). Thus expect() is
        nothing more than::

             cpl = self.compile_pattern_list(pl)
             return self.expect_list(cpl, timeout)

        If you are using expect() within a loop it may be more
        efficient to compile the patterns first and then call expect_list().
        This avoid calls in a loop to compile_pattern_list()::

             cpl = self.compile_pattern_list(my_pattern)
             while some_condition:
                 ...
                 i = self.expect_list(cpl, timeout)
                 ...
        """
        if patterns is None:
            return []
        if not isinstance(patterns, list):
            patterns = [patterns]

        # Allow dot to match \n
        compile_flags = re.DOTALL
        if self.ignorecase:
            compile_flags = compile_flags | re.IGNORECASE
        compiled_pattern_list: list[_Compiled] = []
        for p in patterns:
            if isinstance(p, self.allowed_string_types):
                compiled_pattern_list.append(
                    re.compile(self._coerce_expect_string(p), compile_flags),
                )
            elif p is EOF:
                compiled_pattern_list.append(EOF)
            elif p is TIMEOUT:
                compiled_pattern_list.append(TIMEOUT)
            elif isinstance(p, re.Pattern):
                compiled_pattern_list.append(self._coerce_expect_re(p))
            else:
                self._pattern_type_err(p)
        return compiled_pattern_list

    @overload
    def expect(
        self,
        pattern: _Pattern | list[_Pattern] | None,
        timeout: float | None = -1,
        searchwindowsize: int | None = -1,
        async_: Literal[False] = False,
        **kw: object,
    ) -> int: ...

    @overload
    def expect(
        self,
        pattern: _Pattern | list[_Pattern] | None,
        timeout: float | None = -1,
        searchwindowsize: int | None = -1,
        async_: Literal[True] = ...,
        **kw: object,
    ) -> Coroutine[Any, Any, int]: ...

    @overload
    def expect(
        self,
        pattern: _Pattern | list[_Pattern] | None,
        timeout: float | None = -1,
        searchwindowsize: int | None = -1,
        async_: bool = ...,
        **kw: object,
    ) -> int | Coroutine[Any, Any, int]: ...

    def expect(
        self,
        pattern: _Pattern | list[_Pattern] | None,
        timeout: float | None = -1,
        searchwindowsize: int | None = -1,
        async_: bool = False,  # documented positional flag
        **kw: object,
    ) -> int | Coroutine[Any, Any, int]:
        """Seek through the stream until a pattern is matched.

        The pattern is overloaded and may take several types. The pattern can
        be a StringType, EOF, a compiled re, or a list of any of those types.
        Strings will be compiled to re types. This returns the index into the
        pattern list. If the pattern was not a list this returns index 0 on a
        successful match. This may raise exceptions for EOF or TIMEOUT. To
        avoid the EOF or TIMEOUT exceptions add EOF or TIMEOUT to the pattern
        list. That will cause expect to match an EOF or TIMEOUT condition
        instead of raising an exception.

        If you pass a list of patterns and more than one matches, the first
        match in the stream is chosen. If more than one pattern matches at that
        point, the leftmost in the pattern list is chosen. For example::

            # the input is 'foobar'
            index = p.expect(["bar", "foo", "foobar"])
            # returns 1('foo') even though 'foobar' is a "better" match

        Please note, however, that buffering can affect this behavior, since
        input arrives in unpredictable chunks. For example::

            # the input is 'foobar'
            index = p.expect(["foobar", "foo"])
            # returns 0('foobar') if all input is available at once,
            # but returns 1('foo') if parts of the final 'bar' arrive late

        When a match is found for the given pattern, the class instance
        attribute *match* becomes an re.MatchObject result.  Should an EOF
        or TIMEOUT pattern match, then the match attribute will be an instance
        of that exception class.  The pairing before and after class
        instance attributes are views of the data preceding and following
        the matching pattern.  On general exception, class attribute
        *before* is all data received up to the exception, while *match* and
        *after* attributes are value None.

        When the keyword argument timeout is -1 (default), then TIMEOUT will
        raise after the default value specified by the class timeout
        attribute. When None, TIMEOUT will not be raised and may block
        indefinitely until match.

        When the keyword argument searchwindowsize is -1 (default), then the
        value specified by the class maxread attribute is used.

        A list entry may be EOF or TIMEOUT instead of a string. This will
        catch these exceptions and return the index of the list entry instead
        of raising the exception. The attribute 'after' will be set to the
        exception type. The attribute 'match' will be None. This allows you to
        write code like this::

                index = p.expect(["good", "bad", pexpect.EOF, pexpect.TIMEOUT])
                if index == 0:
                    do_something()
                elif index == 1:
                    do_something_else()
                elif index == 2:
                    do_some_other_thing()
                elif index == 3:
                    do_something_completely_different()

        instead of code like this::

                try:
                    index = p.expect(["good", "bad"])
                    if index == 0:
                        do_something()
                    elif index == 1:
                        do_something_else()
                except EOF:
                    do_some_other_thing()
                except TIMEOUT:
                    do_something_completely_different()

        These two forms are equivalent. It all depends on what you want. You
        can also just expect the EOF if you are waiting for all output of a
        child to finish. For example::

                p = pexpect.spawn("/bin/ls")
                p.expect(pexpect.EOF)
                print(p.before)

        If you are trying to optimize for speed then see expect_list().

        Passing ``async_=True`` will make this return an :mod:`asyncio`
        coroutine, which you can await to get the same result that this method
        would normally give directly. So, inside a coroutine, you can replace
        this code::

            index = p.expect(patterns)

        With this non-blocking form::

            index = await p.expect(patterns, async_=True)
        """
        if "async" in kw:
            async_ = bool(kw.pop("async"))
        if kw:
            msg = f"Unknown keyword arguments: {kw}"
            raise TypeError(msg)

        compiled_pattern_list = self.compile_pattern_list(pattern)
        return self.expect_list(compiled_pattern_list, timeout, searchwindowsize, async_)

    @overload
    def expect_list(
        self,
        pattern_list: Sequence[_Compiled],
        timeout: float | None = -1,
        searchwindowsize: int | None = -1,
        async_: Literal[False] = False,
        **kw: object,
    ) -> int: ...

    @overload
    def expect_list(
        self,
        pattern_list: Sequence[_Compiled],
        timeout: float | None = -1,
        searchwindowsize: int | None = -1,
        async_: Literal[True] = ...,
        **kw: object,
    ) -> Coroutine[Any, Any, int]: ...

    @overload
    def expect_list(
        self,
        pattern_list: Sequence[_Compiled],
        timeout: float | None = -1,
        searchwindowsize: int | None = -1,
        async_: bool = ...,
        **kw: object,
    ) -> int | Coroutine[Any, Any, int]: ...

    def expect_list(
        self,
        pattern_list: Sequence[_Compiled],
        timeout: float | None = -1,
        searchwindowsize: int | None = -1,
        async_: bool = False,  # documented positional flag
        **kw: object,
    ) -> int | Coroutine[Any, Any, int]:
        """Match already-compiled patterns and return the index that matched.

        The list may also contain EOF or TIMEOUT (which are not compiled
        regular expressions). This method is similar to the expect() method
        except that expect_list() does not recompile the pattern list on every
        call. This may help if you are trying to optimize for speed, otherwise
        just use the expect() method.  This is called by expect().

        Like :meth:`expect`, passing ``async_=True`` will make this return an
        asyncio coroutine.
        """
        if timeout == -1:
            timeout = self.timeout
        if "async" in kw:
            async_ = bool(kw.pop("async"))
        if kw:
            msg = f"Unknown keyword arguments: {kw}"
            raise TypeError(msg)

        compiled = cast("Sequence[re.Pattern[AnyStr] | type[EOF | TIMEOUT]]", pattern_list)
        exp = Expecter(self, searcher_re(compiled), searchwindowsize)
        if async_:
            # PLC0415: asyncio only when asked
            from ._async import expect_async  # asyncio only when asked  # noqa: PLC0415

            return expect_async(exp, timeout)
        return exp.expect_loop(timeout)

    @overload
    def expect_exact(
        self,
        pattern_list: _Pattern | Sequence[_Pattern],
        timeout: float | None = -1,
        searchwindowsize: int | None = -1,
        async_: Literal[False] = False,
        **kw: object,
    ) -> int: ...

    @overload
    def expect_exact(
        self,
        pattern_list: _Pattern | Sequence[_Pattern],
        timeout: float | None = -1,
        searchwindowsize: int | None = -1,
        async_: Literal[True] = ...,
        **kw: object,
    ) -> Coroutine[Any, Any, int]: ...

    @overload
    def expect_exact(
        self,
        pattern_list: _Pattern | Sequence[_Pattern],
        timeout: float | None = -1,
        searchwindowsize: int | None = -1,
        async_: bool = ...,
        **kw: object,
    ) -> int | Coroutine[Any, Any, int]: ...

    def expect_exact(
        self,
        pattern_list: _Pattern | Sequence[_Pattern],
        timeout: float | None = -1,
        searchwindowsize: int | None = -1,
        async_: bool = False,  # documented positional flag
        **kw: object,
    ) -> int | Coroutine[Any, Any, int]:
        """Match with plain string searching instead of regular expressions.

        The 'pattern_list' may be a string; a list or other sequence of
        strings; or TIMEOUT and EOF.

        This call might be faster than expect() for two reasons: string
        searching is faster than RE matching and it is possible to limit the
        search to just the end of the input buffer.

        This method is also useful when you don't want to have to worry about
        escaping regular expression characters that you want to match.

        Like :meth:`expect`, passing ``async_=True`` will make this return an
        asyncio coroutine.
        """
        if timeout == -1:
            timeout = self.timeout
        if "async" in kw:
            async_ = bool(kw.pop("async"))
        if kw:
            msg = f"Unknown keyword arguments: {kw}"
            raise TypeError(msg)

        single = isinstance(pattern_list, self.allowed_string_types) or pattern_list in (
            TIMEOUT,
            EOF,
        )

        def prepare_pattern(pattern: _Pattern) -> AnyStr | type[EOF | TIMEOUT]:
            if pattern in (TIMEOUT, EOF):
                return cast("type[EOF | TIMEOUT]", pattern)
            if not isinstance(pattern, self.allowed_string_types):
                self._pattern_type_err(pattern)
            # _coerce_expect_string() has just brought the pattern into this
            # instance's string mode, which is what AnyStr stands for here.
            return cast("AnyStr", self._coerce_expect_string(pattern))

        if single:
            patterns: Iterator[_Pattern] = iter([cast("_Pattern", pattern_list)])
        else:
            try:
                patterns = iter(cast("Sequence[_Pattern]", pattern_list))
            except TypeError:
                self._pattern_type_err(pattern_list)
        prepared = [prepare_pattern(p) for p in patterns]

        exp = Expecter(self, searcher_string(prepared), searchwindowsize)
        if async_:
            # PLC0415: asyncio only when asked
            from ._async import expect_async  # asyncio only when asked  # noqa: PLC0415

            return expect_async(exp, timeout)
        return exp.expect_loop(timeout)

    def expect_loop(
        self,
        searcher: searcher_re | searcher_string,
        timeout: float | None = -1,
        searchwindowsize: int | None = -1,
    ) -> int:
        """Run the common loop used inside expect.

        The 'searcher' should be an instance of searcher_re or
        searcher_string, which describes how and what to search for in the
        input.

        See expect() for other arguments, return value and exceptions.
        """
        exp = Expecter(self, searcher, searchwindowsize)
        return exp.expect_loop(timeout)

    def read(self, size: int = -1) -> AnyStr:
        """Read at most "size" bytes from the file.

        Less is returned if the read hits EOF before obtaining size bytes. If
        the size argument is negative or omitted, read all data until EOF is
        reached. The bytes are returned as a string object. An empty string is
        returned when EOF is encountered immediately.
        """
        if size == 0:
            return self.string_type()
        if size < 0:
            # delimiter default is EOF
            self.expect(self.delimiter)
            return cast("AnyStr", self.before)

        # I could have done this more directly by not using expect(), but
        # I deliberately decided to couple read() to expect() so that
        # I would catch any bugs early and ensure consistent behavior.
        # It's a little less efficient, but there is less for me to
        # worry about if I have to later modify read() or expect().
        # Note, it's OK if size==-1 in the regex. That just means it
        # will never match anything in which case we stop only on EOF.
        cre = re.compile(self._coerce_expect_string(f".{{{size}}}"), re.DOTALL)
        # delimiter default is EOF
        index = self.expect([cre, self.delimiter])
        if index == 0:
            # FIXME self.before should be ''. Should I assert this?
            return cast("AnyStr", self.after)
        return cast("AnyStr", self.before)

    def readline(self, size: int = -1) -> AnyStr:
        r"""Read and return one entire line.

        The newline at the end of line is returned as part of the string,
        unless the file ends without a newline. An empty string is returned if
        EOF is encountered immediately. This looks for a newline as a CR/LF
        pair (\\r\\n) even on UNIX because this is what the pseudotty device
        returns. So contrary to what you may expect you will receive newlines
        as \\r\\n.

        If the size argument is 0 then an empty string is returned. In all
        other cases the size argument is ignored, which is not standard
        behavior for a file-like object.
        """
        if size == 0:
            return self.string_type()
        # delimiter default is EOF
        index = self.expect([self.crlf, self.delimiter])
        if index == 0:
            return cast("AnyStr", self.before) + self.crlf
        return cast("AnyStr", self.before)

    def __iter__(self) -> Iterator[AnyStr]:
        """Iterate over the child's output line by line, as a file-like object."""
        return iter(self.readline, self.string_type())

    # ARG002: file API
    def readlines(self, sizehint: int = -1) -> list[AnyStr]:  # file API  # noqa: ARG002
        """Read until EOF using readline() and return a list of the lines read.

        The optional 'sizehint' argument is ignored. Remember, because this
        reads until EOF that means the child process should have closed its
        stdout. If you run this method on a child that is still running with
        its stdout open then this method will block until it timesout.
        """
        lines = []
        while True:
            line = self.readline()
            if not line:
                break
            lines.append(line)
        return lines

    def fileno(self) -> int:
        """Expose file descriptor for a file-like interface."""
        return self.child_fd

    def flush(self) -> None:
        """Do nothing; present only to support the file-like object interface."""

    def isatty(self) -> bool:
        """Overridden in subclass using tty."""
        return False

    if TYPE_CHECKING:

        def close(self) -> None:
            """Close the connection with the child application.

            SpawnBase does not implement this: every concrete subclass does,
            and __exit__ below calls through to it. Declared for the type
            checker only, so the class carries no such attribute at runtime
            and instantiating SpawnBase directly behaves as it always has.
            """

    # For 'with spawn(...) as child:'
    def __enter__(self) -> SpawnBase[AnyStr]:
        """Return self so the spawn object can be used as a context manager."""
        return self

    def __exit__(
        self,
        etype: type[BaseException] | None,
        evalue: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the child on leaving the ``with`` block."""
        # We rely on subclasses to implement close(). If they don't, it's not
        # clear what a context manager should do.
        self.close()
