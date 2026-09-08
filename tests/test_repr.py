"""Test __str__ methods."""

from unittest import mock

import pytest

import pexpect

from . import pexpect_test_case

pytestmark = pytest.mark.usefixtures("fast_sleep", "killed_pty_children")


class TestCaseMisc(pexpect_test_case.PexpectTestCase):
    """Tests for the __str__() of spawn objects and of the exceptions they raise."""

    def test_str_spawnu(self) -> None:
        """Exercise spawnu.__str__()."""
        # given,
        p = pexpect.spawnu("cat")
        # exercise,
        value = str(p)
        # verify
        assert isinstance(value, str)

    def test_str_spawn(self) -> None:
        """Exercise spawn.__str__()."""
        # given,
        p = pexpect.spawn("cat")
        # exercise,
        value = str(p)
        # verify
        assert isinstance(value, str)

    def test_str_before_spawn(self) -> None:
        """Exercise derived spawn.__str__()."""
        # given,
        child = pexpect.spawn(None, None)
        # There is no child to read from, so hand expect() nothing and let it
        # reach the TIMEOUT whose __str__ is under test.
        with mock.patch.object(child, "read_nonblocking", return_value=b""):
            try:
                child.expect("alpha", timeout=0.01)
            except pexpect.TIMEOUT as e:
                str(e)  # Smoketest
            else:
                msg = "TIMEOUT exception expected. No exception raised."
                raise AssertionError(msg)
