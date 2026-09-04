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

try:
    # This allows coverage to measure code run in this process
    import coverage

    coverage.process_startup()
except ImportError:
    pass

import sys

from utils import no_coverage_env

import pexpect


def rot_one_input(data: bytes) -> bytes:
    """Shift every input byte up by one, so the child reports 98 for an 'a'."""
    return bytes(byte + 1 for byte in data)


def shout_output(data: bytes) -> bytes:
    """Upper-case the child's output, so READY arrives as READY<LOUD>."""
    return data.replace(b"READY", b"READY<LOUD>")


def main() -> None:
    """Interact with a child getch.py until the escape character or EOF."""
    if "--dead-child" in sys.argv:
        # A child that has already exited: interact() has nothing to copy and
        # returns as soon as it sees that the child is not alive.
        p = pexpect.spawn(f"{sys.executable} exit1.py", env=no_coverage_env())
        p.expect(pexpect.EOF)
        p.interact()
        print("Escaped interact")
        return

    p = pexpect.spawn(
        f"{sys.executable} getch.py",
        env=no_coverage_env(),
        use_poll="--use-poll" in sys.argv,
    )

    # defaults matches api
    escape_character = chr(29)

    if len(sys.argv) > 1 and "--no-escape" in sys.argv:
        escape_character = None

    # `--utf8' is accepted for the caller's convenience but not forwarded: the
    # child reads raw bytes, which is what test_interact_exit_unicode asserts on.

    if "--filters" in sys.argv:
        p.interact(
            escape_character=escape_character,
            input_filter=rot_one_input,
            output_filter=shout_output,
        )
    else:
        p.interact(escape_character=escape_character)

    print("Escaped interact")


if __name__ == "__main__":
    main()
