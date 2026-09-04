"""Test __str__ methods."""

import pexpect

from . import pexpect_test_case


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
        child.read_nonblocking = lambda _size, _timeout: b""
        try:
            child.expect("alpha", timeout=0.1)
        except pexpect.TIMEOUT as e:
            str(e)  # Smoketest
        else:
            msg = "TIMEOUT exception expected. No exception raised."
            raise AssertionError(msg)
