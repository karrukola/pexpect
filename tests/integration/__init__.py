"""Tests whose cost is a real child process, not the code under test.

Everything in ``tests/`` runs under a per-test time budget. The tests collected here
cannot meet it, and not because of anything pexpect does: they wait on a Python
interpreter starting up, on a shell logging in, on ``man`` formatting a page, or
on a stream large enough to be worth measuring. The budget is lifted for this
directory only, so that it keeps its meaning everywhere else.
"""
