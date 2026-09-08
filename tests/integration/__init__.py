"""Tests whose cost, or whose configuration, belongs to the machine.

Everything in ``tests/`` runs under a per-test time budget measured from what one
child process costs here. Two kinds of test cannot honour it, and neither because
of anything pexpect does.

Some wait on something slow: a Python interpreter starting up, a shell logging
in, ``man`` formatting a page, a stream large enough to be worth measuring.

The rest drive a program this repository does not ship, whose behaviour the host
decides. An interactive shell is the clear case -- zsh is often not installed at
all, and bash's prompt and startup files are the user's, not ours -- so the tests
that take a shell to a prompt are collected here even when they are quick,
rather than being budgeted as though a prompt were a property of pexpect.

The budget is lifted for this directory only, so that it keeps its meaning
everywhere else.
"""
