"""Tests for :func:`pexpect.which`, the PATH search helper."""

import errno
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

import pexpect

from . import pexpect_test_case


def _first_existing(candidates: tuple[str, ...]) -> str | None:
    """Return the first path of ``candidates`` that exists, or None if none does."""
    return next((path for path in candidates if Path(path).exists()), None)


class TestCaseWhich(pexpect_test_case.PexpectTestCase):
    """Tests for pexpect.which()."""

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

    def test_which_should_match_other_group_user(self) -> None:
        """which() returns executables by other, group, and user ownership."""
        # create an executable and test that it is found using which() for
        # each of the 'other', 'group', and 'user' permission bits.
        fname = "g77"
        bin_dir = Path(tempfile.mkdtemp())
        bin_path = bin_dir / fname
        save_path = os.environ["PATH"]
        try:
            # setup
            os.environ["PATH"] = str(bin_dir)

            # an interpreted script requires the ability to read,
            # whereas a binary program requires only to be executable.
            #
            # to gain access to a binary program, we make a copy of
            # the existing system program echo(1).
            bin_echo = _first_existing(("/bin/echo", "/usr/bin/echo"))
            bin_which = _first_existing(("/bin/which", "/usr/bin/which"))
            if not bin_echo or not bin_which:
                pytest.skip("needs `echo` and `which` binaries")
            shutil.copy(bin_echo, bin_path)
            isroot = os.getuid() == 0
            for should_match, mode in (
                # note that although the file may have matching 'group' or
                # 'other' executable permissions, it is *not* executable
                # because the current uid is the owner of the file -- which
                # takes precedence
                (False, 0o000),  # ----------, no
                (isroot, 0o001),  # ---------x, no
                (isroot, 0o010),  # ------x---, no
                (True, 0o100),  # ---x------, yes
                (False, 0o002),  # --------w-, no
                (False, 0o020),  # -----w----, no
                (False, 0o200),  # --w-------, no
                (isroot, 0o003),  # --------wx, no
                (isroot, 0o030),  # -----wx---, no
                (True, 0o300),  # --wx------, yes
                (False, 0o004),  # -------r--, no
                (False, 0o040),  # ----r-----, no
                (False, 0o400),  # -r--------, no
                (isroot, 0o005),  # -------r-x, no
                (isroot, 0o050),  # ----r-x---, no
                (True, 0o500),  # -r-x------, yes
                (False, 0o006),  # -------rw-, no
                (False, 0o060),  # ----rw----, no
                (False, 0o600),  # -rw-------, no
                (isroot, 0o007),  # -------rwx, no
                (isroot, 0o070),  # ----rwx---, no
                (True, 0o700),  # -rwx------, yes
                (isroot, 0o4001),  # ---S-----x, no
                (isroot, 0o4010),  # ---S--x---, no
                (True, 0o4100),  # ---s------, yes
                (isroot, 0o4003),  # ---S----wx, no
                (isroot, 0o4030),  # ---S-wx---, no
                (True, 0o4300),  # --ws------, yes
                (isroot, 0o2001),  # ------S--x, no
                (isroot, 0o2010),  # ------s---, no
                (True, 0o2100),  # ---x--S---, yes
            ):
                mode_str = f"{mode:0>4o}"

                # given file mode,
                bin_path.chmod(mode)

                # exercise whether we may execute
                can_execute = self._can_execute(fname)

                assert should_match == can_execute, (should_match, can_execute, mode_str)

                # exercise whether which(1) would match
                proc = subprocess.Popen(  # noqa: S603  # located system `which` binary
                    (bin_which, fname), env={"PATH": str(bin_dir)}, stdout=subprocess.PIPE
                )
                bin_which_match = bool(not proc.wait())
                assert should_match == bin_which_match, (should_match, bin_which_match, mode_str)

                # finally, exercise pexpect's which(1) matches
                # the same.
                pexpect_match = bool(pexpect.which(fname))

                assert should_match == pexpect_match == bin_which_match, (
                    should_match,
                    pexpect_match,
                    bin_which_match,
                    mode_str,
                )

        finally:
            # restore,
            os.environ["PATH"] = save_path

            # destroy scratch files and folders,
            if bin_path.exists():
                bin_path.unlink()
            if bin_dir.exists():
                bin_dir.rmdir()

    @staticmethod
    def _can_execute(fname: str) -> bool:
        """Report whether ``fname`` on $PATH can actually be executed."""
        try:
            subprocess.Popen(fname).wait()  # noqa: S603  # fixture copy of echo(1)
        except OSError as err:
            if err.errno != errno.EACCES:
                raise
            # permission denied
            return False
        return True
