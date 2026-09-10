Running the tests
=================

The whole suite runs under `nox <https://nox.thea.codes/>`_, once per supported
interpreter::

    nox -s test          # every version in .python-versions
    nox -s test-3.14     # one of them

Each ``test`` session measures coverage, and the ``collate_coverage`` session it
notifies combines the per-version data and writes the XML and HTML reports.
``pytest tests`` still works for a single unmeasured run.

``nox --list`` prints the rest. The other one worth knowing about is ``lint``,
which runs ruff and then mypy against every interpreter.

``tools/`` holds four scripts that describe the machine rather than test it --
its signal dispositions, its termios modes, its ``pathconf`` limits. They are
worth running on a box where pexpect misbehaves and nowhere else: each reports
on *its own stdin*, so under anything that pipes output they say ``stdin is not
a typewriter`` and little more, which is why CI does not run them.

The interpreters
----------------

``.python-versions`` lists them, and the noxfile reads that file to build its
matrix. uv understands the same filename, so one command installs everything the
matrix needs on a machine that has none of it::

    uv python install

Nothing else names a version -- not the workflow, not CI's cache key, which is
computed from this file rather than written out -- so putting 3.15 in the matrix
is an edit to that one file.

Leave ``.python-version`` (singular: the interpreter for the project's own
environment) alone while you are in there. With the singular file missing, uv
falls back to the *first* line of ``.python-versions``, which would quietly move
development onto the oldest version still supported.

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
    ``coreutils`` for ``sleep.1``. GitHub's Ubuntu runners need none of that,
    which the ``man --where sleep`` line in the CI workflow is there to keep
    true.

Running it on Windows
---------------------

pexpect's central class, ``spawn``, drives a child through a pty, and Windows
has none of its own -- but it has ConPTY, and ``src/pexpect/_winpty.py`` wraps
pywinpty's version of one behind the same ``read_bytes``/``write_bytes`` seam
``src/pexpect/_ptyproc.py`` uses for ptyprocess on POSIX. ``nox`` with no
arguments passes on both platforms as a result, though ``test`` covers less of
the suite on Windows than on POSIX.

``lint`` runs mypy twice there, once per platform: ``[tool.mypy]`` in
``pyproject.toml`` carries no ``platform`` pin, because both platforms now have
live code to check and pinning either one would silence the other's errors.
``noxfile.py``'s ``lint`` session runs the win32 pass over ``src/`` only --
its comment there says why ``tests/`` is not part of it.

``test`` runs almost everything on Windows too. What does not is four modules
and one whole directory, each skipping itself with a module-level
``pytest.mark.skipif`` rather than disappearing from collection the way the
old ``_POSIX_ONLY``/``collect_ignore`` pair in ``tests/conftest.py`` used to --
a skip is counted and reported, a dropped module is invisible. ``test_socket.py``
and ``test_socket_fd.py`` need ``os.fork`` to carry a bound method into a
subprocess; ``test_pxssh.py`` drives an ``ssh`` binary; ``test_popen_spawn.py``
drives ``cat``, ``echo``, ``sleep`` and ``ls``, plus ``SIGKILL``/``SIGTERM``
delivery, even though ``PopenSpawn`` is the class pexpect offers Windows for a
child that needs no pty. ``tests/integration`` has no module-level mark of its
own to carry, so its ``conftest.py`` skips every test under it the same way,
for the same reason: POSIX programs. Beyond these, individual tests elsewhere
skip themselves on whichever platform lacks the POSIX program they need --
``ls``, ``uname``, ``sh``, ``pwd``, ``bash`` -- the same way they always did.

What runs instead of a literal ``cat``, ``echo``, ``sleep`` or ``true`` is a
Python stand-in under ``tests/helpers/``, resolved once per platform by
``tests/commands.py`` and run under the current interpreter; POSIX still gets
the real program, unchanged. Fourteen modules drove one of those four commands
before the stand-ins existed, and are converted to call through
``tests/commands.py`` now. ``tests/test_commands.py`` also spawns each helper
directly, so a broken stand-in fails on Linux instead of only on a Windows CI
leg nobody here can watch.

A run that skips a directory and four modules cannot meet the 100% floor
``pyproject.toml`` sets, so ``collate_coverage`` holds a Windows run to
``_WINDOWS_COVERAGE_FLOOR`` in ``noxfile.py`` instead. It is a real gate, not a
formality -- a regression that drops Windows coverage fails the session -- and
it has to be re-tuned by hand whenever a module moves across the POSIX/Windows
line, which is a change the same diff will show. The figure there right now is
stale: it was measured back when nearly the whole suite dropped out of
collection on Windows, before ``pexpect.spawn`` ran there at all, so it no
longer catches much. It wants raising to whatever the first Windows CI run of
this change reports -- ``collate_coverage`` prints the total before it checks
the floor.

``.gitattributes`` says ``* text=auto eol=lf``, and it earns its place here:
the suite compares bytes it reads from ``tests/TESTDATA.txt`` and the ``.vt``
captures against literals containing ``\n``, and ``src/pexpect/bashrc.sh`` is
sourced by a shell that takes a trailing CR as part of the command. A clone
made with ``core.autocrlf=true`` before that file existed still has CRLF on
disk; in a clean tree, ``git rm -r --cached . && git reset --hard`` refreshes
it.

CI verifies all of it: both jobs run on ``windows-latest`` as well as on
``ubuntu-latest``, and the two commands are the same ones. See `How CI runs it`_.

How CI runs it
==============

``.github/workflows/ci.yml`` has two jobs, ``Lint`` and ``Test``, and between them
they run two commands: ``nox -s lint`` and ``nox -s test``. There is no *version*
matrix in the workflow. GitHub Actions is told which sessions to run, nox decides
which interpreters that covers, and the version list stays in one place.

There is an operating system matrix, because a runner image is the one thing a
nox session cannot choose for itself: each job runs on ``ubuntu-latest`` and on
``windows-latest``, so four jobs in all. ``fail-fast: false``, because a break
on one platform is a fact about that platform and cancelling the other leg to
save a few minutes hides whether the break is everywhere or only there. Only
one step differs between the legs -- the ``apt-get`` below is guarded with
``if: runner.os == 'Linux'`` -- and the artifact names carry
``${{ matrix.os }}``, since two steps uploading one name in a single run is an
error rather than a merge.

A Windows leg lints the whole tree and tests the part of it Windows can reach;
`Running it on Windows`_ says which part, and why the coverage floor it is held
to is a different number. `astral-sh/setup-uv
<https://github.com/astral-sh/setup-uv>`_ puts uv there, and uv installs whichever
interpreters the runner is missing when a session first asks for one -- five of
them, on a cold cache. The workflow sets ``NOX_DOWNLOAD_PYTHON: auto``, which is
nox's default said out loud, because the whole arrangement depends on it: nox
turns a missing interpreter into an error whenever ``CI`` is set, so without the
download a version added to the matrix would fail the run rather than be quietly
skipped.

That download is what the cache is for. ``cache-python: true`` tells setup-uv to
carry uv's managed interpreters in the Actions cache alongside its wheel cache,
and ``cache-dependency-glob`` names ``uv.lock`` and ``.python-versions``, so both
caches turn over exactly when their contents should: a dependency change, or a
change to the matrix. Nothing needs pruning by hand, and a cold cache costs a
download rather than a failure.

CI installs ``zsh`` and ``man-db`` (see above -- without zsh two tests skip and
coverage lands under the floor). The runner has had a working ``man`` since CI
moved there, so ``man-db`` is belt and braces; the ``man --where sleep`` check
closing that step is what makes a runner image that stops shipping man pages say
so in one line, rather than through a puzzling ``test_pager_as_cat`` failure.

macOS is the gap that is left: the package's classifiers claim it and no runner
covers it. Closing it is one more entry in the ``os`` matrix, and nothing in the
sessions or the version matrix has to change for it -- which is the point of
keeping the versions in ``.python-versions`` and the workflow free of them. It
should need no ``if:`` of its own either, since what the ``apt-get`` step
installs is either present on that image or reachable through ``brew``, but that
is a claim a run would have to settle.

What CI publishes
-----------------

Each job uploads what it produced, once per runner:
``mypy-reports-<os>`` (one JUnit XML per interpreter) and
``coverage-reports-<os>`` (the combined XML and the HTML tree). Neither is a
gate. The gates are inside the sessions -- ruff and mypy exit non-zero, and the
coverage floor fails ``collate_coverage`` when the combined total slips -- so a
red run says what went wrong before anyone downloads an artifact. Both reports
are still written in that case, which is the point of publishing them.

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

Test order
==========

`pytest-randomly <https://pypi.org/project/pytest-randomly/>`_ is a development
dependency and is always on. It shuffles the modules, the classes within a
module and the tests within a class, so the suite runs in a different order
every time and no test can come to rely on another having run first. The order
is printed at the top of each run::

    Using --randomly-seed=3415093736

Pass that number back to replay the exact order a failure appeared in::

    pytest tests --randomly-seed=3415093736

Do not reach for ``-p no:randomly``. A run that always goes in the same order
is the one arrangement that cannot tell you whether the suite is order
independent, and switching it off to make a failure go away hides the defect
rather than the symptom. Every module also passes when run on its own, which is
the same property from the other side.

What this asks of a new test is that nothing process-wide outlives it. The
working directory, the environment and ``PATH`` are already handled --
``PexpectTestCase`` restores the first and ``monkeypatch`` or
``mock.patch.dict`` the others -- but a signal handler, an interval timer, a
listening socket or a child process left behind lands on whichever test the
shuffle happens to run next. ``self.addCleanup`` is the shortest way to say so:
see ``test_signal_handling`` in ``tests/test_expect.py``, which borrows
``SIGALRM`` and has to give it back.
