Installation
============

Pexpect is on PyPI, and can be installed with standard tools::

    pip install pexpect

Or::

    easy_install pexpect

Requirements
------------

This version of Pexpect requires Python 3.3 or above, or Python 2.7.

As of version 4.0, Pexpect can be used on Windows and POSIX systems. On POSIX,
:class:`pexpect.spawn` and :func:`pexpect.run` use the :mod:`pty` module from
the standard library. On Windows 10 or 11, they use ConPTY instead, by way of
`pywinpty <https://pypi.org/project/pywinpty/>`_, which ``pip install
pexpect`` brings in automatically there -- no separate install step. See
:ref:`windows` for what still differs between the two platforms.
