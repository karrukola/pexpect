"""Test that :func:`pexpect.which` agrees with which(1) on every mode bit.

The one test here walks two dozen permission masks, and for each one runs the
file and then runs which(1) against it. Four dozen processes do not fit the
suite's time budget, and splitting the loop would not help: a mask that
pexpect and which(1) disagree about is only interesting next to the others.
"""

import errno
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import pytest

import pexpect
from tests import pexpect_test_case
from tests.test_which import first_existing


class TestCaseWhich(pexpect_test_case.PexpectTestCase):
    """Tests for pexpect.which() against the system which(1)."""

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
            bin_echo = first_existing(("/bin/echo", "/usr/bin/echo"))
            bin_which = first_existing(("/bin/which", "/usr/bin/which"))
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

                # exercise whether which(1) would match; only the exit status
                # is read, so the output goes to the null device rather than
                # into a pipe this loop would have to close two dozen times.
                completed = subprocess.run(  # noqa: S603  # located system `which` binary
                    (bin_which, fname),
                    env={"PATH": str(bin_dir)},
                    stdout=subprocess.DEVNULL,
                    check=False,
                )
                bin_which_match = not completed.returncode
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


if __name__ == "__main__":
    unittest.main()
