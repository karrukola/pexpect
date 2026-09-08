Running the tests
=================

The whole suite runs under `nox <https://nox.thea.codes/>`_, once per supported
interpreter::

    nox -s test          # every version in noxfile.py
    nox -s test-3.14     # one of them

Each ``test`` session measures coverage, and the ``collate_coverage`` session it
notifies combines the per-version data and writes the XML and HTML reports.
``pytest tests`` still works for a single unmeasured run.

System packages the suite drives
--------------------------------

pexpect exists to talk to other programs, so a handful of tests need those
programs present. They are not Python dependencies and ``uv sync`` will not
bring them in; on Debian or Ubuntu::

    apt-get install zsh man-db

``zsh``
    ``tests/integration/test_replwrap.py::test_zsh`` drives a real zsh through
    ``replwrap.zsh()``. It skips itself when zsh is not on the path, so a
    missing zsh costs coverage rather than a failure -- and quietly, which is
    why it is listed here.

``man-db``, plus the man pages themselves
    ``test_pager_as_cat`` reads ``man sleep`` to show that ``PAGER=cat`` keeps a
    pager from hanging the REPL. Unlike the zsh test it has no guard, so it
    fails outright where the man pages are absent. Minimized container images
    are the usual case: Ubuntu's cloud and container images divert ``man`` to a
    stub and set ``path-exclude=/usr/share/man/*`` in
    ``/etc/dpkg/dpkg.cfg.d/excludes``, so installing ``man-db`` alone is not
    enough -- ``unminimize``, or drop that exclusion and reinstall
    ``coreutils`` for ``sleep.1``.

Adding a test
=============

The tests are all located in the tests/ directory. To add a new unit
test all you have to do is create the file in the tests/ directory with a
filename in this format::

    test_*.py

New test case classes may wish to inherit from ``PexpectTestCase.PexpectTestCase``
in the tests directory, which sets up some convenient functionality.

Time budgets
============

Every test outside ``tests/integration`` is given a per-test timeout, measured
at collection time from what one child process costs on the machine running it;
``tests/conftest.py`` explains why the budget is stated in child processes
rather than in seconds. A test that needs to spend real time -- reading a
formatted man page, waiting out a ``sleep``, starting a REPL -- belongs in
``tests/integration``, which sets its own generous budget.
