"""Tests for the delaybeforesend and delayafterread attributes."""

import pytest

import pexpect

from . import commands, pexpect_test_case

pytestmark = pytest.mark.usefixtures("fast_sleep", "killed_pty_children")


class TestCaseDelay(pexpect_test_case.PexpectTestCase):
    """Tests for various delay attributes."""

    def test_delaybeforesend(self) -> None:
        """Test various values for delaybeforesend."""
        p = pexpect.spawn(commands.CAT)

        p.delaybeforesend = 1
        p.sendline("line 1")
        p.expect("line 1")

        p.delaybeforesend = 0.0
        p.sendline("line 2")
        p.expect("line 2")

        p.delaybeforesend = None
        p.sendline("line 3")
        p.expect("line 3")

    def test_delayafterread(self) -> None:
        """Test various values for delayafterread."""
        p = pexpect.spawn(commands.CAT)

        p.delayafterread = 1
        p.sendline("line 1")
        p.expect("line 1")

        p.delayafterread = 0.0
        p.sendline("line 2")
        p.expect("line 2")

        p.delayafterread = None
        p.sendline("line 3")
        p.expect("line 3")
