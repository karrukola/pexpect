#!/usr/bin/env python
"""PEXPECT LICENSE.

This license is approved by the OSI and FSF as GPL-compatible.
http://opensource.org/licenses/isc-license.txt

Copyright (c) 2016, Martin Packman <martin.packman@canonical.com>
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

import contextlib
import os
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path

import pexpect

from . import pexpect_test_case


@contextlib.contextmanager
def example_script(name: str, output: str = "success") -> Iterator[str]:
    """Create a temporary shell script that tests can run."""
    tempdir = Path(tempfile.mkdtemp(prefix="tmp-pexpect-test"))
    try:
        script_path = tempdir / name
        with script_path.open("w") as f:
            f.write(f'#!/bin/sh\necho "{output}"')
        try:
            script_path.chmod(0o755)
            yield str(tempdir)
        finally:
            script_path.unlink()
    finally:
        tempdir.rmdir()


class TestCaseEnv(pexpect_test_case.PexpectTestCase):
    """tests for the env argument to pexpect.spawn and pexpect.run."""

    def test_run_uses_env(self) -> None:
        """pexpect.run uses env argument when running child process."""
        script_name = "run_uses_env.sh"
        environ = {"PEXPECT_TEST_KEY": "pexpect test value"}
        with example_script(script_name, "$PEXPECT_TEST_KEY") as script_dir:
            script = str(Path(script_dir) / script_name)
            out = pexpect.run(script, env=environ)
        assert out.rstrip() == b"pexpect test value"

    def test_spawn_uses_env(self) -> None:
        """pexpect.spawn uses env argument when running child process."""
        script_name = "spawn_uses_env.sh"
        environ = {"PEXPECT_TEST_KEY": "pexpect test value"}
        with example_script(script_name, "$PEXPECT_TEST_KEY") as script_dir:
            script = str(Path(script_dir) / script_name)
            child = pexpect.spawn(script, env=environ)
            out = child.readline()
            child.expect(pexpect.EOF)
        assert child.exitstatus == 0
        assert out.rstrip() == b"pexpect test value"

    def test_run_uses_env_path(self) -> None:
        """pexpect.run uses binary from PATH when given in env argument."""
        script_name = "run_uses_env_path.sh"
        with example_script(script_name) as script_dir:
            out = pexpect.run(script_name, env={"PATH": script_dir})
        assert out.rstrip() == b"success"

    def test_run_uses_env_path_over_path(self) -> None:
        """pexpect.run uses PATH from env over os.environ."""
        script_name = "run_uses_env_path_over_path.sh"
        with (
            example_script(script_name, output="failure") as wrong_dir,
            example_script(script_name) as right_dir,
        ):
            orig_path = os.environ["PATH"]
            os.environ["PATH"] = wrong_dir
            try:
                out = pexpect.run(script_name, env={"PATH": right_dir})
            finally:
                os.environ["PATH"] = orig_path
        assert out.rstrip() == b"success"


if __name__ == "__main__":
    unittest.main()
