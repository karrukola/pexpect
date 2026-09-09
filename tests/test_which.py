"""Tests for :func:`pexpect.which`, the PATH search helper."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

import pexpect

from . import pexpect_test_case

# Windows has no execute permission bit: `os.access(path, os.X_OK)`, which
# `is_executable_file` ends on, answers True for any file that exists, so every
# "given non-executable" assertion below fails there -- and `chmod(0o400)`,
# which is how they arrange for one, only clears the read-only flag, which then
# stops the cleanup from deleting the file.
_needs_execute_bit = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows has no execute permission bit for os.access to read",
)


def first_existing(candidates: tuple[str, ...]) -> str | None:
    """Return the first path of ``candidates`` that exists, or None if none does."""
    return next((path for path in candidates if Path(path).exists()), None)


class TestCaseWhich(pexpect_test_case.PexpectTestCase):
    """Tests for pexpect.which()."""

    @pytest.mark.skipif(sys.platform == "win32", reason="no ls(1), and no / to start from")
    def test_which_finds_ls(self) -> None:
        """which() can find ls(1)."""
        exercise = pexpect.which("ls")
        assert exercise is not None
        assert exercise.startswith("/")

    def test_path_from_env(self) -> None:
        """Executable found from optional env argument."""
        bin_name = "pexpect-test-path-from-env"
        tempdir = Path(tempfile.mkdtemp())
        try:
            bin_path = tempdir / bin_name
            bin_path.write_text("# test file not to be run")
            try:
                bin_path.chmod(0o700)
                found_path = pexpect.which(bin_name, env={"PATH": str(tempdir)})
            finally:
                bin_path.unlink()
            assert str(bin_path) == found_path
        finally:
            tempdir.rmdir()

    @_needs_execute_bit
    def test_os_defpath_which(self) -> None:
        """which() finds an executable in os.defpath and returns its abspath."""
        bin_dir = Path(tempfile.mkdtemp())
        if sys.getfilesystemencoding() in ("ascii", "ANSI_X3.4-1968"):
            prefix = "ascii-"
        else:
            prefix = "ǝpoɔıun-"  # noqa: RUF001  # deliberate non-ASCII filename fixture
        with tempfile.NamedTemporaryFile(
            suffix=".sh", prefix=prefix, dir=bin_dir, delete=False
        ) as temp_obj:
            bin_path = Path(temp_obj.name)
        fname = bin_path.name
        save_path = os.environ["PATH"]
        save_defpath = os.defpath

        try:
            # setup
            os.environ["PATH"] = ""
            os.defpath = str(bin_dir)
            bin_path.touch()

            # given non-executable,
            bin_path.chmod(0o400)

            # exercise absolute and relative,
            assert pexpect.which(str(bin_path)) is None
            assert pexpect.which(fname) is None

            # given executable,
            bin_path.chmod(0o700)

            # exercise absolute and relative,
            assert pexpect.which(str(bin_path)) == str(bin_path)
            assert pexpect.which(fname) == str(bin_path)

        finally:
            # restore,
            os.environ["PATH"] = save_path
            os.defpath = save_defpath

            # destroy scratch files and folders,
            if bin_path.exists():
                bin_path.unlink()
            if bin_dir.exists():
                bin_dir.rmdir()

    @_needs_execute_bit
    def test_path_search_which(self) -> None:
        """which() finds an executable in $PATH and returns its abspath."""
        fname = "gcc"
        bin_dir = Path(tempfile.mkdtemp())
        bin_path = bin_dir / fname
        save_path = os.environ["PATH"]
        try:
            # setup
            os.environ["PATH"] = str(bin_dir)
            bin_path.touch()

            # given non-executable,
            bin_path.chmod(0o400)

            # exercise absolute and relative,
            assert pexpect.which(str(bin_path)) is None
            assert pexpect.which(fname) is None

            # given executable,
            bin_path.chmod(0o700)

            # exercise absolute and relative,
            assert pexpect.which(str(bin_path)) == str(bin_path)
            assert pexpect.which(fname) == str(bin_path)

        finally:
            # restore,
            os.environ["PATH"] = save_path

            # destroy scratch files and folders,
            if bin_path.exists():
                bin_path.unlink()
            if bin_dir.exists():
                bin_dir.rmdir()

    @_needs_execute_bit
    def test_which_follows_symlink(self) -> None:
        """which() follows symlinks and returns its path."""
        fname = "original"
        symname = "extra-crispy"
        bin_dir = Path(tempfile.mkdtemp())
        bin_path = bin_dir / fname
        sym_path = bin_dir / symname
        save_path = os.environ["PATH"]
        try:
            # setup
            os.environ["PATH"] = str(bin_dir)
            bin_path.touch()
            bin_path.chmod(0o400)
            sym_path.symlink_to(bin_path)

            # should not be found because symlink points to non-executable
            assert pexpect.which(symname) is None

            # but now it should -- because it is executable
            bin_path.chmod(0o700)
            assert pexpect.which(symname) == str(sym_path)

        finally:
            # restore,
            os.environ["PATH"] = save_path

            # destroy scratch files, symlinks, and folders,
            if sym_path.exists():
                sym_path.unlink()
            if bin_path.exists():
                bin_path.unlink()
            if bin_dir.exists():
                bin_dir.rmdir()

    def test_which_should_not_match_folders(self) -> None:
        """Which does not match folders, even though they are executable."""
        # make up a path and insert a folder that is 'executable', a naive
        # implementation might match (previously pexpect versions 3.2 and
        # sh versions 1.0.8, reported by @lcm337.)
        fname = "g++"
        bin_dir = Path(tempfile.mkdtemp())
        bin_dir2 = bin_dir / fname
        save_path = os.environ["PATH"]
        try:
            os.environ["PATH"] = str(bin_dir)
            bin_dir2.mkdir(0o755)
            # should not be found because it is not executable *file*,
            # but rather, has the executable bit set, as a good folder
            # should -- it should not be returned because it fails isdir()
            exercise = pexpect.which(fname)
            assert exercise is None

        finally:
            # restore,
            os.environ["PATH"] = save_path
            # destroy scratch folders,
            for _dir in (
                bin_dir2,
                bin_dir,
            ):
                if _dir.exists():
                    _dir.rmdir()
