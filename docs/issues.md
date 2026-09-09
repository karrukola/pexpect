# Known issues

Bugs and latent defects found while running a full `ruff` lint pass over the
repository, later while taking the test suite to 100% line and branch coverage,
later still while annotating the package for `mypy`, then while getting the
suite to run clean on 3.10 through 3.14, then in a review pass whose only task
was to look for defects, then while making the suite fail on any warning it
raises, then while moving CI onto the nox sessions, then while getting `nox`
to pass on Windows, then while running the suite on a machine that is not CI,
and last while putting both CI jobs on a Windows runner as well. Every entry
from the first four was left alone at the time it was found,
because fixing it would change runtime behaviour and that was out of scope for
all of them — the lint work was required to be behaviour-preserving, the
coverage work to add tests rather than change the library, and the typing work
to add annotations rather than either.

**Thirty-one are now fixed**, and every entry says which it is. Six came from
the earlier passes: 21, 27, 29 and 30 during the typing pass, because the
annotations could not describe them without either stating something untrue
about the code or preserving the defect behind a cast; then 31, which stopped
`replwrap.zsh()` from working at all on a machine that had not been configured
for it while the test that should have caught it supplied the missing
configuration itself; and 32, found while verifying 31 and fixed in turn — its
entry keeps the wrong diagnosis it was first filed with, because correcting it
is most of what the entry has to say.

Fourteen are the review pass's own: 33 to 39, 41 to 46, and 50. That pass had
no behaviour-preserving constraint on it, so its entries were fixed rather than
filed, each with the test that proves it. What it left alone it
leaves alone for a reason it states: 40 needs a maintainer's decision about a
documented contract, 47 is not worth the changelog line, 48 is release tooling,
and 49 was found during the implementation and has not been through the review
the rest had. Then 51 and 52, the warnings pass's own, fixed the same
way. Six, 53 to 58, are the CI pass's, and were fixed by the rewrite
that found them: five of them are defects in how CI and the noxfile were
configured rather than in anything the library does, and the sixth is what the
package was shipping. The last three, 59 to 61, are the Windows pass's, and are
configuration too — a type check aimed at the wrong platform, a repository that
did not say what its line endings are, and a conftest that could not be
imported there. Entries 1 to 20, 22 to 26, 28, and 62 and 63 are still
outstanding.

Line numbers in the first six sections refer to the tree as of the lint pass and
were each verified against the source, not inferred from the rule that surfaced
them; the review pass's own section and the warnings pass's state the current
ones. The CI pass's cite the tree it replaced, since the lines it quotes from
`.github/workflows/ci.yml` are lines that no longer exist, and the Windows
pass's cite the tree it found, for the same reason. The library paths
are given under `src/pexpect/`, its location since the switch to the src layout;
that move was a pure rename, so the line numbers are unaffected by it.

Three related bugs *were* fixed during that pass, because they blocked the test
suite or were introduced by an autofix, and are recorded at the bottom for
context.

---

## Library (`src/pexpect/`)

### 1. `screen.get()` returns `None`

**`src/pexpect/screen.py:240`**

```python
def get(self):
    self.get_abs(self.cur_r, self.cur_c)  # result discarded
```

`get_abs()`'s return value is thrown away, so `get()` always returns `None`.
This is pre-existing — the same code is at `HEAD`.

The knock-on effect is a silently useless test. `tests/test_screen.py:171`
does:

```python
c = s.get()
...
assert c == s.get()
```

Both sides are `None`, so the assertion passes without verifying anything about
the character under the restored cursor. Fixing `get()` would make that
assertion meaningful, but it is a public API behaviour change and the test may
then legitimately fail.

**Fix:** `return self.get_abs(self.cur_r, self.cur_c)`.

### 2. `pxssh` tunnel guard rejects every `dict` subclass

**`src/pexpect/pxssh.py:325`**

```python
if ssh_tunnels == {} or not isinstance({}, type(ssh_tunnels)):
```

The `isinstance` arguments are the wrong way round: it asks whether a plain
`{}` is an instance of the *caller's* type. That is `False` for any subclass of
`dict`, so passing an `OrderedDict` or `defaultdict` of tunnels silently
produces no `-L`/`-R`/`-D` options at all — `login()` succeeds and no tunnel is
forwarded.

**Fix:** `not isinstance(ssh_tunnels, dict)`.

### 3. `ssh_key=False` is treated as a file path

**`src/pexpect/pxssh.py:306`**

```python
if spawn_local_ssh and not Path(str(ssh_key)).is_file():
```

`ssh_key` is documented as `True` (forward the agent) or a path. Passing
`False` reaches this line and, before the lint pass, hit
`os.path.isfile(False)` — i.e. `False` interpreted as file descriptor `0`,
which raises a `RuntimeWarning` on Python 3.12+. The lint pass preserved the
observable result with `Path(str(ssh_key))`, so the warning is gone but the
input is still nonsense being coerced rather than rejected.

**Fix:** validate the type explicitly and raise `ExceptionPxssh` for a
non-`str`, non-`True` value.

### 4. `SocketSpawn.use_poll` is stored and never read

**`src/pexpect/socket_pexpect.py:54` (parameter), `:72` (assignment)**

`read_nonblocking` uses `socket.settimeout` instead, so the flag has no effect.
It is part of the public signature, so it cannot simply be deleted.

**Fix:** either honour it in `read_nonblocking` or document it as accepted and
ignored.

### 5. `PopenSpawn.send()`'s documented return value is accidental

**`src/pexpect/popen_spawn.py:165`**

The docstring promises "Returns the number of bytes written" and the body is
now `return self.proc.stdin.write(b)`. That happens to be correct on Python 3.
It reads as guaranteed but is really just whatever the underlying stream
returns; a non-standard file-like object assigned to `stdin` would break the
contract silently.

**Fix:** return `len(b)` explicitly, or narrow the docstring.

### 6. Async continuation-prompt error omits the offending command

**`src/pexpect/_async_w_await.py:65`** vs **`src/pexpect/replwrap.py:126`**

The synchronous path appends the command to the message:

```python
raise ValueError("Continuation prompt found - input was incomplete:\n" + command)
```

The async path raises the same message with the command left off, so an
incomplete input is much harder to diagnose from an async call site.

**Fix:** append the command in the async path too.

### 7. EINTR retry loops are dead code

**`src/pexpect/utils.py:111` (`select_ignore_interrupts`), `:143` (`poll_ignore_interrupts`)**

Since PEP 475 (Python 3.5) `select` and `poll` retry on `EINTR` themselves, so
`InterruptedError` no longer escapes. Additionally `InterruptedError.args[0]`
is always `EINTR`, which makes the `else: raise` arm in both loops unreachable.

Both functions still work; they are just elaborate no-ops. Removing them is a
design decision, not a lint fix — and they carry a `# noqa: PERF203` each,
justified on the assumption the retry is live.

### 8. Unreachable guard in `spawn._spawn`

**`src/pexpect/pty_spawn.py:362`**

```python
if self.command is None:
```

By this point the command has already been resolved to a non-`None` value or an
`ExceptionPexpect` has been raised. This was equally unreachable when it was an
`assert`, and was preserved as an explicit raise rather than silently dropped —
a guard removed by mistake is worse than a guard that never fires.

### 9. Fragile coupling in the searchers

**`src/pexpect/expect.py:318-326`** (and the same shape at `:398`)

`best_index` and `best_match` are only bound inside the `if` that also sets
`first_match`, then read after the loop. It is safe today because `first_match
is None` guards the read, but the three variables have to stay in lockstep for
that to hold. No live defect; noted because it is easy to break.

### 10. `_check_ssh_config_username` has no explicit flush

**`src/pexpect/pxssh.py:365`**

Reading a config written through `NamedTemporaryFile` relies on `seek(0)`
flushing the write buffer. That holds on CPython (`BufferedRandom.seek`
flushes) but is not guaranteed by the API and there is no explicit `flush()`.
Affects the test fixtures rather than production use.

---

## Examples (`examples/`)

These ship as teaching material, so a broken example misleads readers directly.
None of them have test coverage.

### 11. `ssh_tunnel.py` has never started a tunnel

**`examples/ssh_tunnel.py:42`**

```python
"ssh -C -N -f -L 25:127.0.0.1:25 ... %(user)@%(host)"
```

Both conversions are missing their `s`. `tunnel_command % globals()` therefore
raises:

```
ValueError: unsupported format character '@' (0x40) at index 61
```

on every call. The surrounding broad `except` prints it and retries forever, so
the script spins silently instead of failing.

**Fix:** `%(user)s@%(host)s`.

### 12. `hive.py` — `:target all` compares against the builtin `all`

**`examples/hive.py:374`**

```python
if len(target_hostnames) == 0 or target_hostnames[0] == all:
```

`all` is the builtin function, not the string, so the comparison is always
`False`. Targets become `["all"]` and the next command dies with
`KeyError: 'all'`.

**Fix:** `== "all"`.

### 13. `chess.py` reads attributes that are never set

**`examples/chess.py:50` and `:67`**

```python
self.term.process_list(self.before)
self.term.process_list(self.after)
```

`Chess` only ever sets `self.child`; there is no `self.before` or `self.after`.
Constructing a `Chess` raises `AttributeError` immediately.

**Fix:** `self.child.before` / `self.child.after`.

### 14. `chess2.py` — `k` can be unbound

**`examples/chess2.py:56`**

If the preceding `self.child.read()` raises, `k` is never assigned and
`self.term.process(k)` on the next line raises `NameError`, masking the real
error.

**Fix:** `continue` in the `except`, or initialise `k = ""`.

### 15. `chess3.py` calls methods it does not define

**`examples/chess3.py:138`, `:141`, `:142`**

`get_first_computer_move()` and `do_first_move()` exist only on `chess.py`'s
`Chess` class. `chess3.py` has its own `Chess` without them. Currently
unreachable because `sys.exit(1)` sits at `:130`.

### 16. Dead tail after `sys.exit` in all three chess examples

**`examples/chess.py:163`, `examples/chess2.py:157`, `examples/chess3.py:159`**

`white.quit()` sits after `sys.exit(1)` (`chess.py`, `chess3.py`) or after a
`while not done:` loop that never sets `done` (`chess2.py`). Unreachable either
way.

These lines previously read `g.quit()`, an undefined name left over from an
earlier variable naming. The lint pass changed them to `white.quit()` — the
minimum needed to make the name defined — but the whole tail of each script is
still dead and a maintainer may prefer to prune it.

### 17. `script.py` crashes on startup

**`examples/script.py:85`**

The log file is opened in binary mode (correct — pexpect logs bytes) but the
header is written as a `str`:

```python
fout.write(f"# {year:4d}{month:02d}{day:02d}...")
```

which raises `TypeError`. Pre-existing; it was a `%`-format string before the
lint pass and is still a `str` after.

**Fix:** `fout.write(header.encode())`.

### 18. `monitor.py` has an unfinished uptime formatter

**`examples/monitor.py:147-148` (and the lines just after)**

The uptime duration is parsed into days / hours / minutes, then never used —
the report prints the raw duration with a hard-coded suffix, so `"3:45"` or
`"17 min"` gets mislabelled as days. The locals were renamed `_days` /
`_hours` / `_mins` with a comment to record the intent without changing output.

**Fix:** format the report from the parsed components.

### 19. `topip.py` — `-a` cannot receive its argument

**`examples/topip.py:132` (getopt spec), `:251` (use)**

```python
getopt.getopt(sys.argv[1:], "h?valqs:u:p:n:", [...])
```

There is no colon after `a`, so `-a` takes no argument. `topip.py -a
from@x,to@y` yields `('-a', '')` with the addresses landing in positional
`args`. The later unpack then fails:

```python
(alert_addr_from, alert_addr_to) = tuple(options["-a"].split(","))
# ValueError: not enough values to unpack (expected 2, got 1)
```

The usage text at the top of the file documents `{-a from_addr,to_addr}`, so
the intent is clear. This alert path has never worked.

**Fix:** `"h?va:lqs:u:p:n:"`.

Related, and worth knowing: the lint pass moved this unpack out of the
option-parsing block and into the alert path, so the guaranteed crash now fires
when an alert triggers rather than at startup. Restoring the original timing was
judged not worth the odd code, given the option is broken either way — fixing
the getopt spec makes the question moot.

### 20. `os._exit(1)` in `exit_with_usage` skips the stdout flush

**`examples/monitor.py:68`, `examples/script.py:56`** (and the same pattern in
the other examples)

`os._exit` bypasses interpreter cleanup, so buffered output is discarded.
`script.py -h` and `monitor.py -h` print nothing when stdout is a pipe.

**Fix:** `sys.exit(1)`, or flush before `os._exit`.

---

## Tests (`tests/`)

### 21. `test_socket.py` — server subprocess dies instead of shutting down

**Fixed.** The explicit-shutdown path runs for the first time.

**`tests/test_socket.py:148`**

```python
if result.startswith(self.exit[0]):
```

`self.exit` is `b"X\r\n"`, so `self.exit[0]` is the **int** `88`. That raises:

```
TypeError: startswith first arg must be bytes or a tuple of bytes, not int
```

The server subprocess only catches `KeyboardInterrupt`, so it dies here rather
than performing the orderly `shutdown`/`close`.

`test_socket` and `test_socket_with_write` still pass — the dying process closes
the connection and the client sees the EOF it was waiting for. So they pass for
the wrong reason, and the explicit-shutdown path has never executed.

**Fix:** `self.exit[:1]`.

### 22. `interact.py` — `--utf8` has always been a no-op

**`tests/interact.py:46`**

The flag set a local `encoding = "utf8"` that was never passed to
`pexpect.spawn()`. `test_interact_exit_unicode` passes anyway because the parent
uses `spawnu` and the child reads raw bytes. The dead assignment was removed and
a comment now records that the flag is accepted but not forwarded.

**Fix:** forward `encoding=` — but that changes what `interact()` writes, so it
needs a deliberate decision about what the test should assert.

### 23. Tests that return `"SKIP"` instead of skipping

**`tests/integration/test_destructor.py:45`, `tests/test_isalive.py:66`**

An old pexpect idiom: the test returns the string `"SKIP"` rather than raising
`unittest.SkipTest` or using `@unittest.skipUnless`. Returning a non-`None`
value from a test is deprecated in `unittest` 3.12+ and in pytest. pytest 9.1.1
still accepts it, so this is a scheduled failure rather than a current one.

**Fix:** `@unittest.skipUnless(...)` or `raise unittest.SkipTest(...)`.

### 24. `test_failed_custom_ssh_cmd_debug` asserts the success condition

**`tests/test_pxssh.py:264`**

Despite the `failed_` prefix it asserts the same thing as
`test_custom_ssh_cmd_debug` — that the invalid cipher appears in the debug
string. What it actually verifies is "the command string is built verbatim,
valid or not", which is a reasonable thing to test but not what the name claims.

**Fix:** rename it, or assert the failure it implies.

---

## Found during the coverage pass (`src/pexpect/`)

These four came out of taking the suite to 100% coverage: each is a line or
branch that the tests could not reach by using the documented API.

### 25. `spawn.waitnoecho(timeout=None)` raises `TypeError`

**`src/pexpect/pty_spawn.py:435`**

```python
if timeout < 0 and timeout is not None:
```

The two halves of the guard are the wrong way round. With `timeout=None` — which
the docstring documents as "block until ECHO flag is False" — the comparison
`None < 0` raises `TypeError: '<' not supported between instances of 'NoneType'
and 'int'` before the `is not None` half can short-circuit it.

The crash only shows up when echo is still on, because the loop returns at the
`getecho()` check above it on the first pass otherwise. That is why
`waitnoecho(timeout=None)` appears to work: every current caller happens to be
past the point where the child has already turned echo off.

The knock-on effect is that the `if timeout is not None:` branch two lines below
can never take its false arm, so it carries a `# pragma: no branch` pointing
here.

**Fix:** swap the operands to `if timeout is not None and timeout < 0:`.

### 26. `spawn.expect_loop()` does not honour the `-1` timeout sentinel

**`src/pexpect/spawnbase.py:498`**

```python
def expect_loop(self, searcher, timeout=-1, searchwindowsize=-1):
    exp = Expecter(self, searcher, searchwindowsize)
    return exp.expect_loop(timeout)
```

Every other entry point (`expect`, `expect_list`, `expect_exact`,
`read_nonblocking`) starts with `if timeout == -1: timeout = self.timeout`.
This one does not, so the documented "-1 means use the spawn default" contract
does not hold: the `-1` is passed straight through as a deadline that has
already passed, and the call raises `TIMEOUT` as soon as the buffer misses.

`tests/test_expect.py::test_expect_loop` therefore has to pass an explicit
timeout, and says so.

**Fix:** add the same `if timeout == -1: timeout = self.timeout` line.

### 27. `PopenSpawn._read_incoming()` logs an exception object to a byte stream

**Fixed.** The message is logged as this spawn's string type, and the reader
thread survives to queue its EOF sentinel.

**`src/pexpect/popen_spawn.py:142`**

```python
except OSError as e:
    self._log(e, "read")
```

`_log()` writes its first argument straight to `logfile` and `logfile_read`,
both of which are byte or text streams. Passing the `OSError` itself raises
`TypeError: a bytes-like object is required, not 'OSError'` from inside the
reader thread, which then dies without queueing the `None` sentinel that marks
the end of the child's output — so every later read waits for data that will
never come.

Without a logfile set, `_log()` does nothing and the error is silently
swallowed, which is why this has gone unnoticed.

**Fix:** log `str(e)` encoded for the stream in use, or drop the call.

### 28. The post-EOF drain in `PopenSpawn.read_nonblocking()` is unreachable

**`src/pexpect/popen_spawn.py:103`**

```python
if self._read_reached_eof:
    if buf:
        self._buf = buf[size:]
        return buf[:size]
```

`_read_reached_eof` is only ever set inside the read loop below, and the loop
consumes the `None` sentinel that sets it only while `len(buf) < size`. So
whenever the flag goes up, `buf[size:]` is empty and nothing is left to hand
out on the next call. The guard can only fire if something outside the class
seeds `_buf`, which is what
`tests/test_popen_spawn.py::test_read_after_eof_drains_the_buffer` does, and
says so.

Not a bug in itself — the branch is a sensible guard — but it is dead code as
written.

---

## Found during the typing pass (`src/pexpect/`)

Both of these were fixed rather than annotated, because neither could be
described truthfully: the declared string type would have had to disagree with
what the code returns.

### 29. `SocketSpawn` never decodes what it reads

**`src/pexpect/socket_pexpect.py:149`**

```python
s = self.socket.recv(size)
...
return s
```

Every other `read_nonblocking` implementation returns
`self._decoder.decode(...)`. This one returns the socket's raw bytes, so with an
encoding set the bytes are written into the `StringIO` buffer that str mode
installs:

```python
SocketSpawn(sock, encoding="utf-8").expect("anything")
# TypeError: string argument expected, got 'bytes'
```

Bytes mode is unaffected, which is why no test caught it: `_NullCoder.decode`
hands the same bytes back, so the fix is a no-op there.

**Fixed:** `return self._decoder.decode(s, final=False)`.

### 30. `PopenSpawn.read_nonblocking()` fails on a spawn with no timeout

**`src/pexpect/popen_spawn.py:116`**

```python
if timeout == -1:
    timeout = self.timeout
elif timeout is None:
    timeout = 1e6
```

The `elif` skips the normalisation in exactly the case that needs it. Reaching
the second branch requires `timeout` to have arrived as None, but the first
branch is what puts a None there, when the spawn was created with
`timeout=None`:

```
TypeError: '<' not supported between instances of 'float' and 'NoneType'
```

So `PopenSpawn(cmd, timeout=None)` — documented as "block forever" — raises on
the first read. `expect()` always passes a timeout explicitly, which is why the
suite never reached it.

**Fixed:** `if` rather than `elif`.

---

## Found during the test-suite pass

Both of these came out of getting the suite to run on 3.10 through 3.14. The
shells `replwrap` drives had to be installed before any of it could run at all,
and once zsh was present it turned out that only the test harness had ever made
`replwrap.zsh()` work.

### 31. `replwrap.zsh()` never worked on an unconfigured machine — **fixed**

**`src/pexpect/replwrap.py:196` (`_repl_sh`)**

`_repl_sh` waits for the pattern `\$` as the shell's first prompt. `bash()`
supplies that itself: it starts bash with the bundled `bashrc.sh`, which sets
`PS1="$"`. `zsh()` starts zsh with `--no-rcs`, so no startup file is read and
nothing sets a prompt — and zsh's own default is `%m%#`, which renders as
`host%`, or `host#` for root, and contains no `$` at all. `replwrap.zsh()`
therefore waited out the full 30-second timeout and raised `TIMEOUT` for any
caller whose inherited `PS1` did not happen to contain a `$`.

`test_zsh` did not catch it because `REPLWrapTestBase.setUp` ran
`os.putenv("PS1", r"\$")` before spawning anything, so the harness supplied the
one condition the library was missing. The test passed while the public function
was unusable.

**Fixed:** `_repl_sh` forces `PS1` in the child's environment, which is the only
channel left once `--no-rcs` has ruled out a startup file, and the pin is gone
from the tests. With the pin gone and the fix reverted, `test_zsh` fails.

### 32. `replwrap.zsh()` could not recover from incomplete input — **fixed**

**`src/pexpect/replwrap.py:186` (`run_command`), `src/pexpect/_async_w_await.py:65`
(`repl_run_command_async`)**

On bash, an unterminated quote produces the continuation prompt, `run_command`
sees it as match index 1, sends SIGINT and raises `ValueError`. On zsh the same
input raised `TIMEOUT` after the full timeout instead.

This entry first recorded that as a failure to *detect* the continuation prompt.
That was wrong, and the correction is the useful part: detection was never the
problem. Instrumenting the two steps separately shows zsh returning index 1 from
the same `_expect_prompt` bash does — the marker `PS2` arrives exactly as
configured. What failed was the step after it. `run_command` sends SIGINT to
abandon the partial command and then waits for a prompt, and zsh sent nothing,
staying alive and silent until the wait expired.

The cause is `+Z` in `zsh()`'s default arguments, which is NO_ZLE and turns the
line editor off — deliberately, because the editor echoes each command back and
wraps the prompt in terminal escapes. A shell in that state records a signal and
acts on it only when it next reads from the terminal. Nothing else explains it:
sending the signal to the process group instead of the process, and sending the
terminal's own interrupt character with `sendintr()`, both leave zsh equally
silent, while enabling the editor recovers it and corrupts every subsequent
reply with escape sequences.

**Fixed:** after the SIGINT, both the sync and the async paths now fall back to
sending a newline if no prompt arrives, which is the read that makes the signal
take effect. A newline is the one input that cannot complete a partial command:
at a continuation prompt it extends whatever is still open, and once the signal
has been acted on it is an empty command line. bash never reaches the fallback,
so its timing is unchanged.

The gap in the tests was real, and is closed. `test_zsh` covered only the
empty-input branch, `run_command("")`, which raises `ValueError` before any
shell is involved, and `test_multiline` — the only test of the continuation
path — ran bash alone, which is why a shell-specific failure in the recovery
went unseen. There is now a zsh test for the real thing, plus
`tests/no_editor_repl.py`, a stand-in that records SIGINT and acts on it at its
next read, so the fallback stays covered on a machine with no zsh installed.

---

## Found during the code review pass (2026-09-08)

These sixteen came out of reading the library end to end with no other task
running. Each was reproduced before it was written down: the evidence quoted
under each entry is output from a script run against this tree, and the line
numbers are the current ones rather than the lint pass's.

Two independent adversarial reviews were then run against this section, and both
found real errors in it. What they changed is recorded in place — six of the
sixteen had a proposed fix that was wrong or incomplete, and two of those would
have shipped green. The corrections are worth as much as the findings, so the
entries carry them rather than hiding them.

One claim this section made in its first draft is worth retracting explicitly,
because it is the kind of thing that reads as reassurance and is not. It said
that the suite passes while every entry holds, so none of these is a
regression. The first half is true — 356 passed, `ruff` clean, `mypy` clean on
17 files — and the second does not follow from it. **45** is a regression: its
filter was correct until `expect()` moved out of `pexpect/__init__.py` in 4.0,
and the suite went on passing across that move because the test names the same
module the filter does.

### What fixing any of these costs

Three things gate every entry below, none of which is visible from the entry
itself:

* `pyproject.toml:114` sets `report.fail_under = 100`. Applying this section's
  fixes with no new tests takes the suite to 98.53% and `nox -s test` red. Each
  fix needs its test in the same commit.
* `doc/history.rst` opens at "Version 4.9" and has no unreleased section. Six of
  these change caller-visible behaviour and need one created.
* `tests/conftest.py` gives every test outside `tests/integration` a budget
  measured in child processes. Where a proof needs a REPL, a SIGKILL or a real
  clock, it belongs in `tests/integration`; the per-entry notes say which.

### 33. `expect()` throws away the buffer on a zero-length match at the end of the window

**Fixed.** A zero-length trailing match now leaves `before` and the buffer
alone. The clamp is in, and a test pins the case that would have broken had it
been left out.

**`src/pexpect/expect.py:58`**

```python
spawn.before = spawn._before.getvalue()[0 : -(len(window) - searcher.start)]
```

The slice means "everything except the part of the window from the match
onwards", and it is right for every match with a body. When the match is
zero-length and sits at the very end of the window, `len(window) -
searcher.start` is `0`, `-0` is `0`, and the slice collapses to `[0:0]`. So
`before` comes back empty. The next three lines make it worse rather than
better: `_buffer` and `_before` are both rewritten from `window[searcher.end:]`,
which is also empty, so the data is not left behind for the next call either.
It is simply gone.

Any pattern that can match the empty string at the end of the buffer triggers
it. `$` is the obvious one, and `\s*$` — "wait for the end of the output" — is
the one somebody would actually write:

```python
p = pexpect.spawn("cat", encoding="utf-8")
p.send("abcdef")
p.expect_exact("abc")  # buffer now holds 'def'
p.expect(r"\s*$")  # idx=0 before='' after='' buffer=''
p.expect(r"f$")  # control: idx=0 before='de' after='f'
```

The control line is the point: the same buffer, a pattern one character longer,
and `before` is correct. Nothing in the suite matches an empty string at the end
of a window — the only `$` in the tests is a literal inside a `[$#]` prompt
class — which is why it has gone unseen.

**Fix:** compute the cut as a positive index, and clamp it:

```python
before_value = spawn._before.getvalue()
tail = len(window) - searcher.start
spawn.before = before_value[: max(0, len(before_value) - tail)]
```

The `max(0, ...)` is not decoration. `_before` can be shorter than the search
window, because `_set_buffer` (the public `buffer` property) writes `_buffer`
and leaves `_before` alone; in that state `tail` exceeds `len(before_value)` and
the unclamped form invents a character that was never in `before`:

```text
_before='xy'  window='abc'  start=0  tail=3
  today      ''
  unclamped  'x'   <- wrong, and reachable through a documented setter
  clamped    ''
```

The two reviews disagreed on this point, one calling the clamp optional. The
arithmetic above settles it.

### 34. `interact()` crashes on a str-mode spawn that has a logfile

**Fixed.** `_log_control()` took a `direction` parameter first, so the child's
output lands in `logfile_read` and the user's keystrokes in `logfile_send`; a
str-mode `interact()` with a logfile now survives a round trip, and
`tests/interact.py` can set a logfile so the test harness can say so.

**`src/pexpect/pty_spawn.py:986`, `:1005`, `:1008`**

All three call `self._log(data, ...)` with the raw bytes just read from a file
descriptor. `_log()` writes its argument straight into `logfile`,
`logfile_read` and `logfile_send`, and on a spawn created with an `encoding`
those are text streams. The first keystroke in either direction ends the
session:

```text
INTERACT-RAISED: TypeError: string argument expected, got 'bytes'
  File "src/pexpect/pty_spawn.py", line 1008, in __interact_stdin_to_child
    self._log(data, "send")
  File "src/pexpect/spawnbase.py", line 272, in _log
    self.logfile.write(s)
```

The docstring two screens above promises the opposite — "If a logfile is
specified, then the data sent and received from the child process in interact
mode is duplicated to the given log" — and `interact()`'s own signature
documents that the filters see bytes "even with `encoding='utf-8'` support", so
bytes at this point are expected; handing them to the log is what is not.

`sendcontrol()` and `sendeof()` on the same class already solve this, in
`_log_control()` at `pty_spawn.py:739`: decode when an encoding is in force,
then log. The interact paths predate it and never adopted it.

This is invisible to the suite because `tests/integration/test_interact.py`
drives `tests/interact.py`, which sets no logfile.

**Fix:** route all three through `_log_control()` — but not as it stands.
`_log_control()` hard-codes `direction="send"`, so sending the read side through
it would file the child's output under `logfile_send`. It needs the direction as
a parameter first:

```python
def _log_control(self, s: bytes, direction: str = "send") -> None:
```

then `self._log_control(data, "read")` at `:986` and `self._log_control(data)`
at `:1005` and `:1008`. With that in place a str-mode `interact()` logs
`log='hi\rhi\r\nhi\r\n'`, `read='hi\r\nhi\r\n'`, `send='hi\r'` — the split the
attributes promise.

### 35. `replwrap` hands the child an environment of exactly one variable

**Fixed.** `env={**os.environ, "NO_COLOR": "1", "TERM": "dumb"}`. The `TERM`
half was not optional: without it the 3.13+ REPL rebuilt its full-screen editor
and every reply came back as `\x1b[?12l\x1b[?25h\x1b[1@4...` in place of the
output, which is what the naive one-liner produced when it was tried.

**`src/pexpect/replwrap.py:58`**

```python
self.child = pexpect.spawn(cmd_or_spawn, echo=False, encoding="utf-8", env={"NO_COLOR": "1"})
```

`spawn`'s `env` argument *replaces* the environment rather than adding to it, so
every REPL started from a command string — including `replwrap.python()`, the
module's own entry point — runs with no `PATH`, no `HOME`, no `VIRTUAL_ENV`, no
locale and no proxy settings:

```text
sorted(os.environ) in the child   ['LC_CTYPE', 'NO_COLOR']
os.environ.get('HOME')            None
os.environ.get('PATH')            None
```

The intent is on record in the commit that introduced it — `95d09c5`, "Force
NO_COLOR=1 to fix test failures with Python 3.13+ REPL" — and adding one
variable is all it was meant to do. `_repl_sh()` in the same module gets this
right for `PS1` (`env = {**os.environ, "PS1": _SH_PROMPT}`), so the module
contains both the mistake and its own correction, thirty lines apart. `bash()`
and `zsh()` go through `_repl_sh` and are unaffected; `python()` and any
`REPLWrapper("some-repl", ...)` are not.

What survives is a REPL that cannot find its own configuration. A wrapped
`ipython` reads no profile; anything the REPL shells out to falls back to
`os.defpath`; `~` still expands, because CPython asks the password database when
`HOME` is unset, so the failure is partial and quiet rather than loud.

The suite does not catch it because `tests/integration/test_replwrap.py:176`
builds its spawn with the same `env={"NO_COLOR": "1"}`, so the test child is as
bare as the library's own — the same shape of blind spot that **31** was filed
for.

**Fix:** `env={**os.environ, "NO_COLOR": "1", "TERM": "dumb"}`. The obvious
one-liner without `TERM` is a regression: inheriting the real `TERM` lets the
3.13+ REPL build its full-screen editor again, and every reply comes back
wrapped in escape sequences (`[?12l[?25h[1@i[1@m...`). The suite would not
notice that either, because `lean_child_env` sets `PYTHON_BASIC_REPL=1` for the
tests. A test for this has to `monkeypatch.delenv("PYTHON_BASIC_REPL")` to be
able to fail, and belongs in `tests/integration` — it starts a REPL.

### 36. `SocketSpawn` never logs what it reads

**Fixed.** One line: the decoded data is logged before it is returned.

**`src/pexpect/socket_pexpect.py:157`** (`read_nonblocking`)

Every other implementation logs what it read — `SpawnBase`'s at
`spawnbase.py:345`, `PopenSpawn`'s at `popen_spawn.py:197`. This one returns the
decoded data without logging it, so `logfile` and `logfile_read` are accepted by
the constructor, stored, flushed by the send path at `socket_pexpect.py:128`,
and never receive a byte of what the socket sends:

```python
s = SocketSpawn(sock, timeout=3, logfile=io.BytesIO())
s.expect(b"hello")
# logfile.getvalue() == b''
```

Half of a documented feature is missing rather than broken, which is the kind of
thing a test asserts about `spawn` and never re-asserts about its siblings:
`tests/test_log.py` has four tests and all four use `pexpect.spawn`.

**Fix:** `self._log(decoded, "read")` before the return. Only that line is new —
the `decode()` call the first draft of this entry proposed alongside it is
already there, landed as part of **29**.

Worth stating because it is a new failure mode rather than a fixed one: a
`SocketSpawn` built with an `encoding` *and* a binary logfile currently logs
nothing, and will then raise `TypeError` on the first read, exactly as **34**
does. That combination is wrong either way; the fix makes it say so.

### 37. `SocketSpawn.read_nonblocking(size, 0)` raises `BlockingIOError`

**Fixed.** `except (TimeoutError, BlockingIOError)`, so a zero timeout raises
`TIMEOUT` here as it does everywhere else.

**`src/pexpect/socket_pexpect.py:152`** (in `_timeout`), **`:182`**

The docstring documents `timeout=0` as "poll", and the whole timeout mechanism
here is `socket.settimeout()`. But zero is the one value `settimeout()` does not
treat as a timeout: it puts the socket in non-blocking mode, where an empty
receive buffer raises `BlockingIOError`, not `TimeoutError`. The `except
TimeoutError` below therefore does not catch it and the caller sees the raw OS
error.

This is not only reachable by a caller polling on purpose, as the first draft of
this entry said. `Expecter._read_until_match` gives up only when the remaining
time is *negative*, so it passes a zero timeout straight through, and the plain
public call does it:

```python
SocketSpawn(sock, timeout=3).expect(b"x", timeout=0)
# BlockingIOError: [Errno 11] Resource temporarily unavailable
pexpect.spawn("cat").expect("x", timeout=0)
# TIMEOUT: Timeout exceeded.        <- what every other spawn class does
```

**Fix:** `except (TimeoutError, BlockingIOError)`, both raising `TIMEOUT`. Both
mean the same thing to a caller: nothing to read yet.

Sequencing note, which is the functional half of the coupling **47** mentions
only cosmetically: if **4** is ever resolved by *honouring* `use_poll`, this
method stops using `socket.settimeout()` and this catch becomes dead code.
Decide **4** before writing a test that pins the `BlockingIOError` path.

### 38. `PopenSpawn` cannot be used as a context manager

**Fixed.** Both methods exist. `close()` escalates the way `pty_spawn.close()`
does — stdin, `wait(delayafterclose)`, SIGTERM, `wait(delayafterterminate)`,
SIGKILL — rather than blocking on a child that never reads its stdin, and
`isalive()` records `exitstatus`, `signalstatus` and `terminated` on the way
past.

**`src/pexpect/popen_spawn.py`** (the class has no `close()` and no `isalive()`)

`SpawnBase.__exit__` calls `self.close()`, and the base declares `close()` under
`if TYPE_CHECKING` only — deliberately, and its docstring says so, since a
subclass that forgot it should not inherit a broken one. `PopenSpawn` is that
subclass:

```python
with PopenSpawn("cat") as c:
    c.sendline("hi")
# AttributeError: 'PopenSpawn' object has no attribute 'close'
```

The `with` form is the first thing `pexpect/__init__.py` shows a reader after
`spawn` itself, and `fdspawn` and `SocketSpawn` both implement `close()`, so
`PopenSpawn` is the only spawn class in the package that cannot be used that
way. `isalive()` is missing on the same class, which is the other half of the
same gap.

**Fix:** add both, and not the way the first draft of this entry put it. "Close
stdin, then wait for the child" hangs: `with PopenSpawn("sleep 5")` then blocks
for five seconds, and for a child that never exits on stdin EOF it blocks
forever — while `pty_spawn.close()` force-terminates by default. Follow that
instead: close stdin, `proc.wait(self.delayafterclose)`, SIGTERM,
`wait(self.delayafterterminate)`, SIGKILL, `wait()`. `isalive()` should record
what it learns the way `spawn.isalive()` does — set `exitstatus`,
`signalstatus` and `terminated` — rather than just returning `poll() is None`.

Do not give `close()` a `force` flag: `ruff`'s FBT001/FBT002 fire on it, and
this module's per-file ignores cover only PLR0913/PLR0917. The no-argument
`close()` of `fdspawn` and `SocketSpawn` is the signature to match.

### 39. `PopenSpawn.read_nonblocking()` never waits, so `expect()` busy-polls

**Fixed.** The queue is waited on only while the buffer is empty, so a match
still costs about a millisecond while a genuine timeout costs 1.00 s of wall
clock for 0.0008 s of CPU, down from 0.15 s. `read_nonblocking()` raises
`TIMEOUT` on an empty deadline, and the `size == 0` fast path is untouched.

**`src/pexpect/popen_spawn.py:184-186`**

```python
while (time.time() - t0) < timeout and size and len(buf) < size:
    try:
        incoming = self._read_queue.get_nowait()
    except Empty:
        break
```

The loop is written as if it waited out the timeout, and the header even
recomputes the elapsed time on each pass, but `get_nowait()` plus `break` means
the first empty queue ends it. So the method returns an empty string instead of
either waiting for data or raising `TIMEOUT`, which is what the same method on
every other spawn class does:

```python
p = PopenSpawn("cat", timeout=1)
p.read_nonblocking(10, 1.0)  # b'' after 0.0001s
```

`expect()` survives this because `Expecter._read_until_match` treats an empty
read as "no match yet" and goes round again, but that turns a blocking wait into
a spin at `delayafterread` — 0.0001 s — and it shows on a clock:

| spawn class | wall | CPU |
|---|---|---|
| `PopenSpawn` | 1.00 s | 0.15 s |
| `spawn` (pty) | 1.00 s | 0.00 s |

Fifteen percent of a core to wait for nothing, and a direct caller of
`read_nonblocking()` gets a return value that means EOF for a file-like object
and does not mean it here.

**Fix, with the trap that the first draft of this entry walked into.** Replacing
`get_nowait()` with `get(timeout=remaining)` makes the loop wait for `size`
characters — `maxread`, so 2000 of them — instead of for the first one. Measured
after that change: `PopenSpawn("cat")`, `sendline("hello")`, `expect("hello")`
went from about a millisecond to the full ten-second timeout. Wait only while
the buffer is empty:

```python
incoming = self._read_queue.get(timeout=remaining) if not buf else self._read_queue.get_nowait()
```

then raise `TIMEOUT` when the deadline passes with nothing read. Measured with
that form: a match costs 0.001 s, and a genuine timeout is 1.00 s wall for
0.0008 s of CPU. Two constraints on the way in: keep the `size == 0` fast path
returning empty, or `tests/test_popen_spawn.py::test_read_nonblocking_of_nothing`
fails; and the method needs splitting to stay under `ruff`'s C901, after which
the `# noqa: PERF203` on the old `except Empty` is unused and RUF100 will say so.

A duration assertion cannot go in `tests/test_popen_spawn.py` as it stands:
that module uses `fast_sleep`, which fakes `time.time()` while `Queue.get`
waits on the real clock. Assert the outcome — `TIMEOUT` raised, prompt matched —
not the timing, or measure with `perf_counter` outside the fixture.

### 40. The documented pattern contract and the three coercions disagree

**Not fixed.** The choice between widening the documented contract and
narrowing `_coerce_expect_re` belongs to a maintainer; the entry states both
options and what each one costs.

**`src/pexpect/spawnbase.py:282`** (`_coerce_expect_string`), **`:288`**
(`_coerce_expect_re`), **`:300`** (`_coerce_send_string`), and
**`doc/api/pexpect.rst:83-85`**

The three coercions do not agree on an encoding. Sending uses UTF-8, compiling a
pattern object uses UTF-8, and compiling a pattern *string* uses ASCII:

```python
p = pexpect.spawn("cat")  # bytes mode
p.send("café")  # 5 -- encoded as UTF-8
p.expect(re.compile("café"))  # 0, after=b'caf\xc3\xa9'
p.expect("café")  # UnicodeEncodeError: 'ascii' codec can't encode '\xe9'
p.expect_exact("café")  # UnicodeEncodeError, same place
```

One instance, one pattern, three outcomes. The first draft of this entry called
the ASCII arm the bug and proposed switching it to UTF-8. Both reviews rejected
that, and the documentation is why:

> For backwards compatibility, some Unicode is allowed in bytes mode: the send
> methods will encode arbitrary unicode as UTF-8 before sending it to the child
> process, and its expect methods can accept ascii-only unicode strings.

So the ASCII restriction on `expect` is the documented contract, and the
*outlier* is `_coerce_expect_re`, which is more permissive than the docs
promise. What is left is a genuine defect of a different kind — three code
paths, one documentation sentence, and no agreement between them — with a
decision behind it that is not the reviewer's to take:

* widen the docs and `_coerce_expect_string` to UTF-8, and accept that a
  pattern which fails loudly today becomes one that silently never matches
  against a child that is not sending UTF-8; or
* narrow `_coerce_expect_re` to ASCII, and break callers who compile their own
  non-ASCII patterns today.

**Fix:** none applied. This one needs a maintainer's call and a changelog line,
not a quiet correction. Whichever way it goes, the error message deserves
improving: `UnicodeEncodeError` from inside `re.compile` says nothing about the
rule it enforced.

### 41. `pxssh.login()` interpolates the server, user and paths without quoting — security

**Fixed.** All four values are `shlex.quote`d; `self.options` was left alone,
for the reason below. See the note at the end of this section: the fix disarmed
two tests that had been smuggling an ssh argument through the server name, and
those were repaired too.

**`src/pexpect/pxssh.py:326`, `:374`, `:553`, `:561`**

This is the entry to read first. It was ninth in a flat list in the first draft,
next to a dead attribute, and that framing was wrong.

The ssh command line is assembled by string concatenation, and four of the
values that go into it are not quoted: the private key path (`f" -i {ssh_key}"`),
the config path (`" -F " + ssh_config`), the username (`" -l " + username`) and
the server (`cmd += f" {ssh_options} {server}"`). The tunnel specifications a few
lines away *are* quoted, through `shlex.quote`, so the module already knows the
problem exists:

```python
pxssh.pxssh(debug_command_string=True).login("host; touch /tmp/pwned", "user name", ssh_key=True)
# 'ssh  -q -A -l user name host; touch /tmp/pwned'
```

Two distinct failures come out of that one string. A value with a space in it —
an ordinary key path under `~/My Keys/`, or the username above — is split into
two argv entries by `split_command_line()` and the command silently means
something else. And when `login()` is called with `spawn_local_ssh=False`, the
whole string is handed to `sendline()` for a *remote shell* to parse, where the
`;` above starts a second command. pxssh is used in automation where the
hostname comes from inventory data, which is exactly where an untrusted value
gets in.

**Fix:** `shlex.quote` each of the four. `quote` is already imported at `:30`.
Safe on the local path too — verified round-trip through
`split_command_line()` for `'`, `"`, space, `;` and `$` — so the two paths need
not diverge.

Not `self.options` at `:363`, which the first draft of this entry threw in as an
afterthought. Those values are already wrapped in single quotes, and
`shlex.quote("StrictHostKeyChecking=no")` returns it *unquoted*, so `-o
'StrictHostKeyChecking=no'` would become `-o StrictHostKeyChecking=no` and
`tests/test_pxssh.py:281` fails on the literal it asserts. An option *value*
containing a single quote is a real hole in that line, but closing it means
quoting the value inside the existing quotes and changing that assertion
deliberately.

### 42. `ANSI` writes a file called `log` into the working directory

**Fixed.** `DoLog` writes to `logging.getLogger(__name__)` at debug level and
the file is gone, which let `tests/test_ansi.py` drop the `chdir` into a
temporary directory that it had been carrying to cope with this.

**`src/pexpect/ANSI.py:216`** (`DoLog`), **`:224`**, **`:258`**

`DoLog` is the FSM's default transition and the "any" transition out of several
states, so it runs whenever the emulator meets an escape sequence it does not
implement. What it does is open `log` in the current directory, in append mode,
and write a line to it:

```python
t = ANSI.ANSI(4, 10)
t.write("\x1b[4h")  # set insert mode
# ./log now exists, containing 'h,NUMBER_1\n'
```

`\x1b[4h` is not exotic, and the asymmetry is worth noting: `\x1b[4l` *is*
handled, by `DoMode` at `:297`; only `h` has no transition out of `NUMBER_1`. So
any program that switches to insert mode leaves a file behind in whatever
directory the calling process happens to be in. Where the directory cannot be
written the write itself escapes `ANSI.write()` — reproduced with a deleted cwd,
which raises `FileNotFoundError` from inside a character write. (A read-only
directory does not reproduce as root, which is worth knowing before writing a
test for that half.)

The suite knows. `tests/test_ansi.py:139` creates a temporary directory,
`chdir`s into it for the duration of the torture-test replay, and says why:
"This causes ANSI.py's DoLog to write in the cwd. Make sure we're in a
writeable directory." A workaround in the tests is not a fix in the library.

**Fix:** keep `DoLog` — it is a public FSM callback and `ANSI` wires it into six
transitions — but give it `logging.getLogger(__name__).debug(...)` instead of
the file, which is silent unless the application configures it. Keep the
`fsm.memory = [screen]` reset, which is behaviour rather than logging. The
module is deprecated in favour of `pyte`, so the smaller change is the better
one. `tests/test_ansi.py` can then drop its `chdir`.

### 43. `split_command_line()` mishandles leading whitespace, and `spawn("")` raises `IndexError`

**Fixed.** Both halves: the state machine starts in `_STATE_WHITESPACE`, so a
leading space no longer opens an empty argument, and `_resolve_command()` raises
`ExceptionPexpect` for an empty command instead of indexing an empty list.

**`src/pexpect/utils.py:79`** (the initial state), **`src/pexpect/pty_spawn.py:351`**

The first draft of this entry reported only the empty-string case:

```text
pexpect.spawn("")      IndexError: list index out of range
pexpect.run("")        IndexError: list index out of range
pexpect.spawn("   ")   ExceptionPexpect: The command was not found or was not executable: .
```

An empty command is what a caller gets from an unset configuration value, and
`ExceptionPexpect` is what the very next lines raise for every other unusable
command — including, as the third line shows, a command of nothing but spaces.

But the state machine has the more interesting half of it. `split_command_line`
starts in `_STATE_BASIC`, so leading whitespace closes an argument that was
never opened:

```text
split_command_line(" ls")   ['', 'ls']
pexpect.spawn(" ls")        ExceptionPexpect: The command was not found or was not executable: .
```

A command string with a leading space fails today, and the reported name is `.`
rather than anything the caller wrote. That is not an edge case a caller has to
construct; it is what string concatenation produces.

**Fix:** two parts, and the first is the root cause. Start the machine in
`_STATE_WHITESPACE` in `utils.py`, which makes `""`, `"   "` and `" ls"` all
behave; then keep an explicit guard in `_resolve_command` for an empty result:
`raise ExceptionPexpect("The command to be executed is empty.")`. The
`("", 0)` case in `tests/test_command_list_split.py` is unaffected by the state
change; `spawn("   ")`'s message changes, which is the point.

This also softens **8**'s premise. That entry calls the `if self.command is
None` guard unreachable because "the command has already been resolved to a
non-`None` value or an `ExceptionPexpect` has been raised" — which is not true
today, since the empty string escapes as an `IndexError` instead. Fixing this
entry is what makes **8**'s claim correct.

### 44. `run()`'s `list[str]` annotation is not true

**Fixed.** All eight signatures now say `str`. `mypy src tests` stays clean, so
nothing in the repository was relying on the annotation that was not true.

**`src/pexpect/run.py:41`, `:55`, `:69`, `:82`** (and `:244`, `:258`, `:272`,
`:285` for `runu`)

All eight signatures declare `command: str | list[str]`, but `run()` forwards
the value to `spawn(command)` as a single argument, and `spawn` only accepts a
list through its *second* parameter. A list reaches `split_command_line()`,
which iterates it as characters, so the elements are concatenated:

```python
pexpect.run(["echo", "hi"])
# ExceptionPexpect: The command was not found or was not executable: echohi.
```

`mypy` does not catch the mismatch because `run()` calls through
`_spawn_bytes: Callable[..., spawn[bytes]]` at `run.py:24`, which erases the
parameter types on the way.

**Fix:** narrow the annotation to `str`. This is annotation-only — no runtime
behaviour changes — but it is visible to downstream type checking: code that
passes a list type-checks today and stops. It also leaves
`PopenSpawn(cmd: str | list[str])`, where a list genuinely works, as the
odd one out, which is worth a sentence in the changelog rather than a second
change. Accepting a list in `run()` would mean adding an `args` parameter, which
is a feature rather than a correction. There is no test to add; `mypy` is the
proof.

### 45. `get_trace()` no longer hides the frames it promises to hide

**Fixed.** The filter drops any frame whose file sits inside the package
directory, so it needs no maintenance the next time a raise moves.

**`src/pexpect/exceptions.py:29`**

```python
if ("pexpect/__init__" not in item[0]) and ("pexpect/expect" not in item[0])
```

The docstring says "the stack trace inside the Pexpect module is not included".
The filter names two modules, and what a caller actually gets is:

```text
  File "probe3.py", line 24, in <module>       <- the caller, wanted
  File "src/pexpect/spawnbase.py", line 550, in expect
  File "src/pexpect/spawnbase.py", line 616, in expect_list
```

The first draft of this entry said the raising code had moved out of both
filtered modules. That is wrong, and the correct diagnosis is sharper: the
`expect.py` frames *are* still filtered, and what leaks is `spawnbase.py`,
because `expect()` and `expect_list()` moved out of `pexpect/__init__.py` in
4.0. The filter was right before that move and has been stale since.

`tests/test_misc.py:628-629` asserts two things — `"raise " not in tb` and
`"pexpect/__init__.py" not in tb` — and the trace above satisfies both, which is
why the move went unnoticed; `tests/test_timeout_pattern.py:81` checks the same
one module name.

**Fix:** filter on the package directory rather than on two module names —
`str(Path(__file__).parent)` against `item[0]` — which needs no maintenance the
next time a raise moves. One consequence to state in the test: a traceback
raised wholly inside pexpect then returns `""`.

### 46. `screen.erase_up()` and `erase_down()` erase the row the cursor is on

**Fixed.** Both boundaries are guarded. `erase_down` had no test at all before
this; it has one now, as does the top-row case of `erase_up`.

**`src/pexpect/screen.py:372`** (`erase_down`), **`:377`** (`erase_up`)

Both methods clear from the cursor to one edge of the screen, in two steps: the
partial current line, then the whole rows beyond it. At the boundary the second
step undoes the first.

```python
self.erase_start_of_line()
self.fill_region(self.cur_r - 1, 1, 1, self.cols)  # erase_up
```

With the cursor on row 1 there are no rows above, but `cur_r - 1` is `0`,
`fill_region` constrains that to `1`, and the region becomes row 1 in full —
including the columns to the right of the cursor that `erase_start_of_line()`
had just been careful to leave alone. `erase_down` has the same defect at the
other end, with `cur_r + 1` constrained back down to `rows`:

```text
screen(3, 6) filled with dots
  cursor (1,3), erase_up()     row 1 = '      '   expected '   ...'
  cursor (3,3), erase_down()   row 3 = '      '   expected '..    '
```

`tests/test_screen.py:428` puts the cursor on row 2, so the `erase_up` boundary
is not covered, and there is no `test_erase_down` at all.

**Fix:** guard each region fill — `if self.cur_r > 1:` and
`if self.cur_r < self.rows:`. Both new branches need a boundary test, which the
100% branch requirement will insist on anyway.

### 47. `fdspawn.own_fd` is set and never read

**Not fixed, deliberately.** Both reviews said to leave it, and this entry
exists so that nobody reads the attribute and believes it means something.

**`src/pexpect/fdpexpect.py:129`**

`close()` at `:134` closes `child_fd` unconditionally, so the flag has no
reader; `own_fd` appears exactly once in the tree. It is a leftover from
upstream's `close()`, which branched on it into `self.close(self)` — a call with
an extra positional argument, so a `TypeError` rather than the infinite
recursion the first draft of this entry claimed, and unreachable either way
because nothing ever set the flag True.

Same shape as **4** (`SocketSpawn.use_poll`): a stored attribute with no
behaviour behind it.

**Fix:** none recommended. Deleting a public attribute costs a changelog line
and buys nothing; both reviews said leave it. Honouring it — close only a
descriptor `fdspawn` opened itself, which is what the module's "You are
responsible for opening and closing the file descriptor" implies — is a real
change and needs a decision, not a tidy-up. Recorded here so that nobody reads
the attribute and believes it means something.

### 48. Three sources of truth for the version number

**Not fixed.** Release tooling rather than a code fix, and the one-line version
of it can break `import pexpect`; the entry says what to do instead.

**`src/pexpect/__init__.py:86`**, **`pyproject.toml:3`**, **`doc/conf.py:38`**

`pyproject.toml` declares `dynamic = ["version"]` and derives it with
`setuptools_scm`; `__init__.py` hard-codes `4.9.0`; `doc/conf.py` hard-codes
`4.9`. Nothing reconciles the three, and in this checkout the first two disagree
by construction: `pexpect.__version__` is `4.9.0` while
`importlib.metadata.version("pexpect")` reports a `0.0.post1.devNNNN` string
frozen into `pexpect.egg-info` at install time — the two reviews saw different
`NNNN`, which is itself the point.

After any release that forgets to hand-edit line 86, the package reports the
previous version to every caller that asks it the documented way, and the built
documentation reports a third.

**Fix:** not `__version__ = importlib.metadata.version("pexpect")` on its own,
as the first draft of this entry suggested — that raises
`PackageNotFoundError` at import time for a vendored or uninstalled copy, so
`import pexpect` fails outright, and for anyone working in a checkout it turns
a meaningful `4.9.0` into an scm build string. Use `setuptools_scm`'s
`version_file` so the number is written into the package at build time and read
from there, and point `doc/conf.py` at the same value. Failing that, leave the
hand-edit alone and add line 86 and `doc/conf.py:38` to a release checklist.
This is release tooling rather than a code fix, and nothing in the repository
reads `__version__`, so no test catches any of it.

### 49. `terminated` is True on a live child for three of the four spawn classes

**`src/pexpect/spawnbase.py:177`**, and the absence of any counterpart to
**`src/pexpect/pty_spawn.py:440`**

`SpawnBase.__init__` sets `self.terminated = True`, and exactly one subclass
puts it back: `spawn._spawn()` sets it False once the child is running. So every
other spawn class reports a running child as terminated, from construction until
something happens to correct it:

```text
PopenSpawn("cat")   isalive=True  terminated=True
spawn("cat")        isalive=True  terminated=False
fdspawn(fd)         isalive=True  terminated=True
```

`terminated` is a documented public attribute, and the three classes disagree
with the one that has always been right. Nothing in the library reads it, which
is why the suite never noticed — it was found while writing the tests for **38**,
where an `isalive()` test had to be written around it.

**Fix:** clear the flag where each class learns it has something live —
`PopenSpawn.__init__` once `Popen` has returned, `fdspawn.__init__` and
`SocketSpawn.__init__` once the descriptor has been accepted — rather than
flipping the base class's default, which would leave a `spawn(None)` factory
instance claiming a child it has not started.

Not fixed here. It changes an observable value on three public classes, and
unlike everything above it, it has not been through the review this section's
other entries had.

### 50. The `with spawn(...)` idiom does not type-check

**`src/pexpect/spawnbase.py:823`**

```python
def __enter__(self) -> SpawnBase[AnyStr]:
```

The annotation widens the object to the base class, so inside a `with` block
every method a concrete class adds is invisible to a type checker:

```python
with pexpect.spawn("cat") as child:
    child.sendline("x")
# error: "SpawnBase[bytes]" has no attribute "sendline"  [attr-defined]
```

`send`, `sendline`, `close`, `isalive`, `interact` and `terminate` are all
subclass methods, so a `with` block is typed as offering almost nothing a caller
would use it for — and the idiom is not obscure: `pexpect/__init__.py`'s module
docstring advertises it, directly under the plain `spawn` example.

This surfaced from the other direction. The tests written for **38** used the
`with` form, as the entry asked, and that is what turned `mypy src tests` — the
gate `noxfile.py` runs — red for the first time.

**Fix:** return the self type, so the concrete class survives the `with`. The
project targets 3.10, where `typing.Self` does not exist at runtime, so it is
the self-type TypeVar idiom: a module-level `TypeVar` bound to
`"SpawnBase[Any]"`, and `def __enter__(self: _SelfT) -> _SelfT:`.

### What the fixes cost, and one thing they broke

Thirteen of the sixteen were implemented, plus **50**; **40**, **47**, **48**
and **49** are left as recorded above, each for a stated reason. Every fix
landed with the test that proves it, because the suite gates on 100% line and
branch coverage and would otherwise have gone red. The suite is 388 tests, up
from 356, and passes in random order as well as in file order.

Two of the fixes went in differently from how this section first proposed them,
and the entries say so in place: **34** needed `_log_control()` to learn a
`direction` before anything could be routed through it, and **35** needed
`TERM="dumb"` alongside the inherited environment. Both of those would have
shipped green.

The one worth recording separately is **41**, because it is the only fix here
that broke something that was passing. `tests/integration/test_pxssh_login.py`
selected the mock server's remote shell by smuggling it into the hostname —
`login("server zsh", ...)` and `login("server tcsh", ...)` — which worked
precisely because `server` was interpolated unquoted and
`split_command_line()` then broke it into two argv words. Quoting the hostname
is the fix, and it turned both of those tests into duplicates of the bash one.

They did not fail. They passed, having quietly stopped testing the thing they
are named after, and the only reason anyone noticed is that
`pxssh.set_unique_prompt()`'s csh and zsh success arms lost their only exercise
and the branch coverage fell from 100% to 99%:

```text
src/pexpect/pxssh.py   220   0   88   2   99%   652->657, 655->657
```

The mock client now takes the shell as an option instead, passed through
`login(cmd=...)`, which pxssh does not quote and is documented not to. Worth
keeping in mind for **2**, **3** and **10**, which are the other pxssh entries:
this module's tests reach the library through a command line they assemble by
hand, so a change to how that line is built can disarm a test without failing
it. The coverage gate is what caught this one, which is the argument for keeping
it at 100.

---

## Found by failing the suite on warnings (2026-09-08)

`pyproject.toml` gained `[tool.pytest] filterwarnings = ["error"]`, which turns
every warning raised anywhere in a run -- including during collection -- into a
failure. Fourteen distinct sources came out, and they arrived in a shape worth
knowing about before reading them: a `ResourceWarning` is raised by a
*finalizer*, so pytest charges it to whichever test happened to trigger the
collection rather than to the test that leaked the object. The first run blamed
`tests/test_expect.py::test_coerce_expect_re_enc_none` and
`tests/test_pxssh.py::test_try_read_prompt_stops_at_its_total_timeout` for
objects neither of them had ever touched.

**Two were library defects**, recorded as **51** and **52** below and fixed.
One is `pexpect.screen`'s own deprecation notice, which is not a defect at all:
it is raised from the module body, so it lands during collection, where a
`filterwarnings` mark cannot reach it. That one is now asserted by
`tests/test_screen.py::ScreenTestCase::test_import_warns_of_the_deprecation`
and let through at the two imports that raise it, rather than exempted for the
whole run. The remaining eleven were tests abandoning what they opened. They
are tabulated after the entries rather than numbered, because none of them is a
defect in pexpect, and the table is keyed by the site that opened the object
rather than by the warning, so one row can stand for several: a dropped
`PopenSpawn` raises the still-running subprocess, its stdin pipe and -- its
reader thread outliving it, which is **51** -- both of the `fork()` warnings.

The suite is 391 tests, up from 390, and passes in random order on 3.10
through 3.14 with coverage still at 100%.

### 51. `PopenSpawn.close()` leaks the child's output pipe and its reader thread

**`src/pexpect/popen_spawn.py:323`** -- **fixed**

`close()` escalated correctly to reap the child and closed `proc.stdin`, but
never touched `proc.stdout`, and never waited for the reader thread that
`__init__` starts to drain it. So a closed `PopenSpawn` still held one
descriptor and one thread, and released both only when the collector reached
the object:

```text
tests/test_popen_spawn.py::ExpectTestCase::test_context_manager_closes_the_child
  ResourceWarning: unclosed file <_io.FileIO name=20 mode='rb' closefd=True>
```

A program that creates and closes many of them runs out of descriptors. The
surviving thread costs more than it looks, and this is what makes the entry
worth more than its own warning: a process with a live thread cannot `fork()`
without a `DeprecationWarning` on 3.12 and later, so the threads left behind by
`tests/test_popen_spawn.py` made *every* child started by a later module warn --
`pty.py:66: DeprecationWarning: This process is multi-threaded, use of
forkpty() may lead to deadlocks in the child`, charged to `tests/test_run.py`,
`tests/test_unicode.py`, `tests/test_winsize.py` and three more, none of which
had anything to do with it.

**Fixed** by joining the reader thread and then closing the read end. The join
is bounded by `delayafterclose` rather than open-ended: the child is reaped by
the time it runs, so the thread sees the end of the pipe within microseconds,
but a *grandchild* can hold the write end open past the child's death and
`close()` must not block on one. The order matters -- the thread reads by
descriptor number, and a number closed under a blocked read is one the kernel
is free to hand to something else.

### 52. Nothing releases the asyncio transport an awaited `expect()` binds

**`src/pexpect/_async_w_await.py:36`, `src/pexpect/spawnbase.py:157`** --
**fixed**

The first `await expect(...)` on a spawn calls `connect_read_pipe()` and stores
the result on the spawn as `async_pw_transport`, so that the next await resumes
reading rather than building another transport. Nothing ever unbound it. On a
real EOF asyncio closes the transport itself -- `PatternWaiter.eof_received()`
says as much in a comment -- so the leak is invisible in exactly the tests that
read a child to the end, and shows up only for a spawn that was awaited, matched
and then dropped or closed:

```text
tests/integration/test_destructor.py::TestCaseDestructor::test_destructor
  ResourceWarning: unclosed transport <_UnixReadPipeTransport fd=16 open>
```

Four transports, from four awaited matches in two other modules, all reported
against the one test that calls `gc.collect()`.

**Fixed** with `SpawnBase._close_async_transport()`, called by all four
concrete `close()` implementations before they release the descriptor, because
closing the transport is what takes the event loop's reader off it. Two things
in it are less obvious than they look. It unbinds the attribute *before*
closing, because the transport's "pipe" is the spawn object itself, so closing
it ends in asyncio calling that same `close()` a second time. And it suppresses
`RuntimeError`, because a transport that outlived its event loop cannot be
closed through -- `close()` schedules the callback that would release the pipe,
and scheduling on a closed loop raises.

### The eleven that were the tests' own

Not defects in pexpect, and not numbered for that reason. Each is a test
opening something and leaving it to the collector, which under
`filterwarnings = ["error"]` fails a run and, being a finalizer, usually fails
the wrong test.

| Where | What was left open |
|---|---|
| `tests/test_popen_spawn.py` | Thirty spawns, four of which were ever closed: a still-running subprocess, both pipes and a reader thread apiece for the other twenty-six. Now built through a `_spawn()` helper that registers `close()` as cleanup, which the four that close themselves then find already done. |
| `tests/test_socket.py` (`setUp`) | One or two sockets created only to ask the kernel which address family works here, then dropped. Now closed by the `_family_works()` helper that asks. |
| `tests/test_socket.py` | Eight connections to the test server, never closed. Now opened by a `connect()` helper that registers the close. |
| `tests/test_socket_fd.py` | The same eight, inherited, plus `test_fileobj`'s own. This module spawns on the bare descriptor, so `fdspawn.close()` closes it out from under the socket object and closing that again is EBADF -- which is why the shared cleanup suppresses `OSError`. |
| `tests/test_socket_pexpect.py` | Two spawns over a preloaded socket pair. |
| `tests/test_filedescriptor.py::test_fileobj` | A file object whose descriptor `fdspawn` had taken and closed. Its finalizer closed the descriptor a second time, which is both a `ResourceWarning` and a `PytestUnraisableExceptionWarning` -- `OSError: [Errno 9] Bad file descriptor`, raised where nothing can catch it. Now opened with `closefd=False`, which is what "fdspawn takes ownership" means in code rather than in a comment -- and which is the caller's side of the question **47** leaves open. |
| `tests/integration/test_which.py` | Twenty-four pipes from `which(1)`, opened by `subprocess.Popen(stdout=PIPE)` for an exit status the caller reads and output it never reads. Now `subprocess.run(stdout=DEVNULL)`. |
| `tests/test_async.py`, `tests/integration/test_async.py` | Children dropped rather than closed, which is what left **52**'s transports unreleased. |

---

## Found during the CI pass (2026-09-08)

`.github/workflows/ci.yml` was rewritten to run nox sessions on a plain
`ubuntu-latest` runner, so that the version matrix belongs to nox and the
workflow never names a version: `.python-versions` parameterises the sessions,
uv fetches whatever interpreter the runner is missing, and setup-uv's
`cache-python` keeps those fetches off the critical path. Five defects came out
of reading the old workflow closely enough to replace it, none of them in the
library. The first is why the rest went unnoticed: that workflow has not been
able to finish a run since the move to `pyproject.toml`, four days before this
pass. A sixth, **58**, came out of clearing away what the old CI left behind.

The Coveralls upload and the `finish` job that closed its parallel build are
gone with it. Coverage is combined by the `collate_coverage` session, as it
already was for a local run, and published as a workflow artifact; the gate is
`report.fail_under = 100` in `pyproject.toml`, which fails the session that
produced the regression rather than a badge somewhere else.

The two diagnostic scripts the old test step ran ahead of pytest --
`tools/display-sighandlers.py` and `tools/display-terminalinfo.py` -- are not in
the new workflow either, and dropping them costs nothing that CI ever had. Both
report on their own stdin, which in a workflow step is a pipe: what the second
printed under CI was `stdin is not a typewriter` and a table of pipe limits,
never the termios state a pty library would want, and the signal table the first
prints is identical across the whole matrix but for one name `dir(signal)` gained
in 3.14. They stay in `tools/`, where a developer with a terminal can get the
answer they were written to give.

### 53. The workflow installed from two files that had been deleted

**`.github/workflows/ci.yml:39`** -- **fixed**

`pip install -r requirements-testing.txt`, and two steps later
`pytest --cov pexpect --cov-config .coveragerc`. `requirements-testing.txt` was
removed by `3de7753` and `.coveragerc` by `66c0d5b`, both on 2026-09-04, when
the project moved its dependencies and its coverage settings into
`pyproject.toml`. Every run since has failed at the install step, which is also
why **54** and **55** went unnoticed: no run reached the step that either one
would have affected.

### 54. The matrix tested versions the project had dropped, and neither of the two it had gained

**`.github/workflows/ci.yml:19`** -- **fixed**

`python-version: ["3.7", "3.8", "3.9", "3.10", "3.11", "3.12", "pypy3.9"]`,
plus a `3.6` entry pinned to `ubuntu-20.04`, against a `requires-python` of
`>=3.10` and a noxfile matrix of 3.10 through 3.14. Five of the eight
combinations named versions the package now refuses to install on -- 3.6
through 3.9, and a PyPy implementing 3.9 -- while 3.13 and 3.14 went untested;
and `ubuntu-20.04` has been retired as a runner image, so the `include` holding
3.6 could not be scheduled at all.

This is the defect the rewrite is really about: a matrix written out in the
workflow is a second copy of a list that already exists, and the copy is the one
nothing checks. There is now no copy -- `.python-versions` is read by the
noxfile, hashed into CI's cache key, and named by nothing else.

### 55. `PYTHONIOENCODING=UTF8` was exported in a step of its own

**`.github/workflows/ci.yml:38`** -- **fixed**

Each `run:` block is a separate shell, and this `export` sat in the *Install
packages* step, two steps before the one that ran pytest. The single
environment variable CI set for the suite's benefit reached `pip` and nothing
else -- a pty library's tests, of all things, running under whatever encoding
the runner happened to default to.

It is gone rather than moved. The suite has been passing for years without that
export ever taking effect, on runners that provide a UTF-8 locale of their own,
so the honest fix is to stop claiming to set something: a variable the tests
actually need belongs in the workflow's `env:` block, where every step inherits
it, and none of them turns out to.

### 56. `_ON_CI` was computed and never read

**`noxfile.py:11`** -- **fixed**

Next to a link to nox's `error_on_missing_interpreters` option, which nox
already defaults to `"CI" in os.environ` -- so by the time the link had been
followed there was nothing left for the variable to do, and it stayed anyway.

Deleted, along with the `os` import it needed. What it was reaching for is real
and worth knowing: on CI a missing interpreter is an error rather than a skip,
which is why the workflow says `NOX_DOWNLOAD_PYTHON: auto` and why the link now
sits beside that line. The noxfile is left with no opinion about CI at all,
which is the correct number of opinions for it to have.

### 57. Five `lint` sessions wrote one mypy report

**`noxfile.py:46`** -- **fixed**

`--junit-xml reports/mypy.xml` in a session parameterised over five
interpreters: each run overwrote the last, so the file described whichever
finished most recently. It went unnoticed while nothing read the file. CI now
publishes it, and the name carries the interpreter --
`reports/mypy-{session.python}.xml`.

### 58. The package declared no long description

**`pyproject.toml:3`** -- **fixed**

`[project]` had no `readme`, so the wheel and the sdist carried neither a
`Description-Content-Type` nor a body: the PyPI page for a release cut from
this tree would have been metadata and nothing else. Found while deciding
where the build badge at the top of `README.rst` should point -- that file is
the project's front page in two places and was shipped in neither.

`readme = "README.rst"` in `0cfa28f`, verified with `twine check` rather than
by reading the metadata, because an RST body that fails to render is rejected
at upload time and not at build time. `[project] description`, the one-line
summary that sits above the body, is still absent.

### Dead CI configuration, since removed

None of these was a defect, and none is numbered. Each pointed at a service
that stopped building this project years ago, and each named at least one file
the project no longer has, so none could be repaired by less work than deleting
it. They were left alone when this section was first written, on the grounds
that removing a service's configuration is also how a project loses the record
of what used to run it -- which is what this table is now for.

| What | Gone in | What it was |
|---|---|---|
| `.travis.yml` | `b86fced` | Python 2.7 through 3.7 and `pypy`, `pip install coveralls`, `--cov-config .coveragerc`. travis-ci.org stopped serving requests in 2021, and Travis had not built this project since `fe44359` moved CI to GitHub Actions in 2022. |
| The `travis-ci.org` badge heading `README.rst` and `doc/index.rst` | `b86fced` | A broken image on the repository page and in the documentation, for years. It now points at `karrukola/pexpect`'s own workflow, which is the choice this row used to be waiting on. |
| `tools/teamcity-runtests.sh`, `tools/teamcity-coverage-report.sh` | `8b49489` | `mkvirtualenv`, `python setup.py install` and `--cov-config .coveragerc`: a virtualenvwrapper, a build backend and a config file the project no longer has. No TeamCity build configuration accompanied them into the repository, so what they were wired into is not something the checkout can say. |
| `coveralls` (`[dependency-groups] dev`) | `26dbbb2` | Installed for a service whose only callers were the two rows above. Nothing in the noxfile or the workflow ever invoked it, and dropping it takes twelve packages out of every environment nox builds. |

---

## Found while getting the suite to run on Windows (2026-09-09)

`nox` on a Windows checkout failed every session it has. `lint` ended in 338
mypy errors across 46 files, not one of them about anything the code does
wrong. `test` could not collect a single test, because `tests/conftest.py`
imports `pexpect.pty_spawn` at module scope and `pty` is not importable there.
Once it could, the comparisons against bytes read from `tests/TESTDATA.txt`
failed on line endings the clone had rewritten. And `collate_coverage` failed
at a 100% floor that a subset of the suite cannot reach.

Five defects, **three of them fixed**: 59, 60 and 61 are configuration this
repository was missing, and 62 and 63 are what pexpect itself does on Windows,
left alone because changing either is a change to a documented contract rather
than a fix.

What runs there now is 92 of the suite's 391 tests -- 81 that pass and 11 that
skip -- on 3.10 through 3.14, reaching 46.23% coverage against
`_WINDOWS_COVERAGE_FLOOR` in `noxfile.py`. `tests/conftest.py` names the
modules it drops and gives a reason for each; the short version is that the pty
API is most of this suite and Windows has no pty. The 100% in `pyproject.toml`
is left as the statement it is, about a run that has the whole suite.

CI ran on `ubuntu-latest` and nothing else while this pass was open, so none of
it was verified by a workflow at the time -- only by running `nox` on Windows,
which is what this pass made possible. The `os` matrix that puts both jobs on
`windows-latest` too came straight after, and verifies it now.

### 59. mypy analysed for the platform it was running on

**`pyproject.toml:236`** -- **fixed**

`[tool.mypy]` set `check_untyped_defs` and nothing else, so mypy took its
`platform` from the interpreter that invoked it. On Windows that takes
`termios`, `tty`, `fcntl`, `select.poll`, `os.getuid` and `signal.SIGHUP` out
of the stubs, along with `pexpect.spawn`, `pexpect.spawnu`, `pexpect.run` and
`pexpect.runu` -- `__init__` exports those four behind a
`sys.platform != "win32"` check, so on Windows they really are absent. 338
errors in 46 files, every one of them mypy correctly answering a question about
a platform this library does not run on.

`platform = "linux"`. A type check should reach the same verdict on every
machine, and the verdict worth reaching is the one that describes where the
code runs. It changes nothing about the Linux CI run that was already producing
it.

### 60. The repository did not say what its line endings are

**no `.gitattributes`** -- **fixed**

With `core.autocrlf=true`, which is what git's Windows installer offers and
therefore what most Windows clones have, every text file is checked out CRLF.
Two things in this tree do not survive that. `tests/TESTDATA.txt` and the three
`.vt` captures are read as bytes and compared against literals containing
`\n`, so `test_socket_pexpect::test_socket` failed with
`assert b" END\r\n" == b" END\n"`; and `src/pexpect/bashrc.sh`, which
`replwrap.bash()` has the child source, is read by a shell that takes a
trailing CR as part of the command.

`* text=auto eol=lf`. The index was already LF, so nothing had been committed
wrong -- this only settles what a checkout puts on disk, which is the thing
that was never stated. An existing clone needs
`git rm -r --cached . && git reset --hard` in a clean tree to pick it up.

### 61. The suite could not be collected at all on Windows

**`tests/conftest.py:45`** -- **fixed**

`from pexpect import pty_spawn`, at module scope, for two helpers that need it:
the child the per-test budget is calibrated from, and the `killed_pty_children`
fixture. `pty_spawn` imports `pty`, which imports `tty`, which imports
`termios`, which does not exist on Windows -- so `pytest tests` ended in
`ImportError while loading conftest` before collecting the 92 tests that have
nothing to do with a pty.

The import is behind the platform check now, and so is the branch of
`_time_one_child` that uses it: off POSIX the budget is calibrated from an
empty interpreter instead of a pty child, that being about the cheapest child a
Windows machine can start. Returning `_BUDGET_FLOOR` there was the first
attempt and was wrong: 150 ms is tighter than the budget any POSIX machine
earns, and `test_torturet` costs 110 ms on 3.10 under coverage's tracing, so it
timed out under `coverage run` while passing without it.

The modules that cannot run there are dropped at collection rather than skipped
test by test, because most of them raise while being imported and a skip mark
never runs when the module carrying it cannot be imported.

### 62. `fdspawn.read_nonblocking` ignores its timeout off POSIX and blocks forever

**`src/pexpect/fdpexpect.py:212`**

```python
if os.name == "posix":  # pragma: no branch
    ...
    rlist, wlist, xlist = select_ignore_interrupts(rlist, wlist, xlist, timeout)
    if self.child_fd not in rlist:
        raise TIMEOUT("Timeout exceeded.")
return cast("AnyStr", super().read_nonblocking(size))
```

The `select` is the only thing implementing the timeout and it is inside the
guard, so on any other platform the method falls through to
`SpawnBase.read_nonblocking`, which is a bare `os.read` -- whose docstring
says, accurately, "The timeout parameter is ignored." A caller who passes a
timeout gets none, and on a descriptor that never becomes readable the call
never returns. `tests/test_filedescriptor.py::test_read_nonblocking_times_out`
opens a pipe nothing writes to and hangs there, which is how this was found;
that test is skipped on Windows rather than the library changed.

Not fixed. Honouring the timeout on Windows means a mechanism per kind of
handle -- `select` takes sockets only, a pipe wants `PeekNamedPipe`, a regular
file is always ready -- which is a feature for `fdspawn` to grow rather than a
line to change. The `# pragma: no branch` is right as it stands: the branch has
one outcome per platform, and coverage is measured per platform.

### 63. `which()` accepts any file that exists on Windows

**`src/pexpect/utils.py:50`**

```python
return os.access(fpath, os.X_OK)
```

Windows has no execute permission bit, and `os.access` with `X_OK` there
answers the same as `F_OK`: True for anything that exists. So
`is_executable_file` is a file-exists test on Windows, and `which("notes.txt")`
hands back a path as soon as that file is on `PATH` -- a path that then goes to
`PopenSpawn` as a command. Four tests in `tests/test_which.py` state the POSIX
answer, arranging for a non-executable file with `chmod(0o400)`, which on
Windows only clears the write bit; all four are skipped there, and the write
bit is why three of them failed in cleanup rather than in the assertion.

Not fixed. What a Windows `which()` should consult is `PATHEXT`, the way
`shutil.which` does, and adopting that answer is a decision about a documented
contract -- the same reason **40** is still open.

---

## Found while running the suite off CI (2026-09-09)

### The one that could only pass on CI

Not a defect in pexpect, and not numbered for that reason. `nox` was green on
GitHub Actions and failed on a developer's machine, on every interpreter in the
matrix, in
`tests/integration/test_interact.py::InteractTestCase::test_interact_str_mode_with_logfile`.

The child chain the `--logfile` mode builds -- `interact.py` running
`/bin/sh -c "echo READY; exec cat"` -- echoes a typed line back exactly twice,
once as the inner pty's own local echo and once as `cat` copying stdin to
stdout, so what reaches the caller after the banner is `hi\r\nhi\r\n`. The test
waited for it as

    p.expect_exact("hi")
    if not os.environ.get("CI", None):
        p.expect_exact("hi\r\nhi\r\n")

and `expect_exact()` consumes what it matches. The first call took the first
`hi`, leaving `\r\nhi\r\n` in the buffer, so the second asked for a third echo
that no one was going to send and the spawn's own `timeout=5` ended the test --
well inside the 60 s budget `tests/integration` sets, which is why the failure
read as pexpect timing out rather than as pytest killing a hung test.

Green on CI only because `CI` is set there and the second wait is skipped
whole, which is also what kept it from being caught when it was written, in
`059a254`: that commit's own verification ran under the workflow. No local run
of the suite has ever passed this test.

Now one wait per echo, the second still skipped on CI, which is what the
comment above it always said the test was doing. It also tightens the CI path:
the surviving wait is for `hi\r\n` rather than for `hi`, so the
`log_read.startswith("hi\r\n")` assertion at the end of the test no longer
depends on a newline that nothing had waited for.

### The per-test budget could not see what the tests actually cost

Also not a defect in pexpect, and not numbered. With the test above fixed, a
full `nox` still lost a test about one run in eight, to

    Failed: Timeout (>0.2338...s) from pytest-timeout

in `tests/test_ansi.py::AnsiTestCase::test_torturet` or in
`tests/test_ctrl_chars.py::TestCtrlChars::test_control_chars`, whichever the
scheduler picked on.

`tests/conftest.py` sizes the per-test budget as
`max(_BUDGET_FLOOR, _CHILDREN_PER_TEST x cost of one spawn-and-close of cat)`,
measured at collection time so that it follows the machine rather than being
written down. The measurement is sound for what it measures and blind to the
rest: the calibration child is exec'd, so the coverage tracer never reaches it,
while every test the budget covers runs inside the traced parent. On the machine
this was found on, the calibration child cost 16.5 ms bare and 18.1 ms under
`coverage run` -- a tenth dearer -- while `test_torturet`, which drives no child
at all, went from 14 ms to 230 ms. Against a budget of 12 x 19.5 ms = 234 ms
that is a coin flip, and every `nox` test session runs `coverage run -m pytest`.

Fixed by raising `_BUDGET_FLOOR` from 0.15 to 1.0. The floor is the right lever
because it exists to stop the budget following a fast machine down, and a
machine fast enough for it to bind is one whose children are cheap -- which is
exactly when the children term stops covering in-process work. On a slow
machine, 290 ms a child and so a budget of 3.5 s, it never binds and nothing
changes.

### The suite's own greeting race, seen as a timeout

Also not a defect in pexpect, and not numbered. With the budget raised, a full
`nox` still lost `tests/test_socket.py::test_multiple_interrupts`, or one of
the three sibling tests in `tests/test_socket_fd.py`, about one run in eight
to

    Failed: Timeout (>1.0s) from pytest-timeout

against a budget those tests normally clear twenty times over: both cost 40 to
50 ms. The budget was not the problem, and neither was the signal loop the
traceback pointed at.

`socket_fn()`, which runs in a subprocess, read once, called that "Get all data
from server", set `all_read`, and then made a second read that the test
requires to raise `TIMEOUT`. The server writes the greeting as two sends:

    conn.send(self.motd)
    conn.send(self.prompt1)

so a read landing between them returns the motd alone and leaves the prompt
queued -- where it satisfies the second read, which returns data instead of
timing out. The subprocess then exits 0 without setting `timed_out`, and both
callers wait on that event with no deadline of their own:
`test_multiple_interrupts` spins `os.kill` until the budget kills it,
`test_interrupt` blocks for `_STARTUP_TIMEOUT`.

Instrumenting the spin loop showed it plainly: 18 to 19 iterations and 0.0208 s
when the subprocess reports its timeout, and a linear climb at 1.14 ms an
iteration that never ends when it does not. Forcing the short read the race
produces by chance reproduced both failures in 2.23 s. Fixed by reading until
the whole greeting is in; the greeting arriving seven bytes at a time passes.

### The prompt-change command's own echo, read as two prompts

Also not a defect in pexpect, and not numbered.
`tests/integration/test_replwrap.py::test_existing_spawn` failed about one full
`nox` in twenty-four with

    ValueError: Continuation prompt found - input was incomplete:
    echo $HOME

and not on a timeout at all -- it is under the 60 s budget of its own
directory.

The test spawned bash without `echo=False` and left it to
`REPLWrapper.__init__` to turn echo off. That is racy for a REPL which
configures the terminal itself: bash sets echo as it starts, and if that write
lands after `setecho(False)` then echo is back on when the wrapper sends

    PS1='[PEXPECT_PROMPT>' PS2='[PEXPECT_PROMPT+' PROMPT_COMMAND=''

whose text contains both of the strings `_expect_prompt()` searches for. The
echo of it is read as two prompts: `__init__` matches the PS1 being set,
leaving `[PEXPECT_PROMPT+` in the buffer, and the next `run_command()` reads
that as a continuation prompt.

Forcing echo to stay on reproduced it 40 times out of 40, while the unmodified
path passed 150 times out of 150 -- which is the shape of a narrow race rather
than evidence against one. `replwrap.bash()` spawns with `echo=False` and so
never opens the window; the test now does the same. The `if self.child.echo:`
branch it used to cover moves to a test of its own against
`tests/no_editor_repl.py`, which leaves the terminal alone.

---

## Found while adding the Windows CI legs (2026-09-09)

### The one that was passing on a coin flip

Not a defect in pexpect either, and unnumbered for the same reason as the entry
above. `.github/workflows/ci.yml` grew an `os` matrix, so `Lint` and `Test` each
run on `windows-latest` as well, and the Linux leg of the very first run failed
in `tests/test_env.py::TestCaseEnv::test_spawn_uses_env` -- on 3.14 only, with
3.10 through 3.13 green beside it, and with nothing in the branch touching a
line of code. `assert None == 0`.

```python
child.expect(pexpect.EOF)
assert child.exitstatus == 0
```

`expect(EOF)` means the pty returned EOF. It does not mean anyone has called
`waitpid` on the child, and until someone has, `spawn.exitstatus` is `None` --
so the assertion is a race between the test and the kernel, which the test
usually wins because the child is a two-line shell script that has already
exited. The two sibling tests that assert the same thing,
`test_ctrl_chars.py:78` and `test_misc.py:142`, both call `isalive()` first,
which is the call that does the reaping. This one did not.

Measured on `a7ddbe5`, the commit whose own CI run was green, in isolation on
3.14: one failure in ten runs. With `assert not child.isalive()` restored ahead
of it, none in thirty. That ratio is why it survived from `e5eb99c`, which
added the test in 2016 as `self.assertEqual(child.exitstatus, 0)` -- CI had
simply not rolled a one yet, and a second matrix leg is what made the dice get
thrown often enough.

The wider point is the one worth keeping. A test that reads a child's exit
status without reaping it first will pass on almost every run, and no amount of
running it on one platform will say so. Two platforms and five interpreters is
twenty dice per push.

---

## Dead code left in place

Not bugs, but unreachable on `requires-python >= 3.10`. Left alone because
`ruff` does not flag them and removing them is not a lint fix. All are safe to
delete.

| Location | What |
|---|---|
| `tests/qa.py` | Referenced by no test, doc or config. Was Python 2-only until the lint pass. Deletion candidate. |

Two entries have left this table. The `asyncio` and `aiounittest` `ImportError`
shims, and the `skipIf` guard that read one of them, were deleted in the typing
pass, which had to resolve every import it could not otherwise annotate; the
same pass removed `tests/deprecated_test_filedescriptor.py` and
`tests/deprecated_test_run_out_of_pty.py`, unreferenced modules whose sibling
imports had not resolved since the tests became a package.

---

## Fixed during the lint pass, for context

These three are **not** outstanding. They are recorded because two of them were
blocking the test suite and the third was caused by an autofix, so anyone
bisecting this range should know about them.

1. **`pyproject.toml`** — `[tool.coverage.run] source = "pexpect"` must be a
   list in TOML. As a bare string, `coverage` raised
   `ValueError: Option [tool.coverage.run]source is not a list: 'pexpect'` at
   interpreter startup in **every process pexpect spawned**, and the traceback
   went to stderr where the tests read it as program output. Introduced by
   commit `66c0d5b`, which moved `.coveragerc` into `pyproject.toml` without
   converting the value's type.

2. **`tests/pexpect_test_case.py`** — `COVERAGE_PROCESS_START` still pointed at
   `.coveragerc`, deleted by that same commit. Now points at `pyproject.toml`.

3. **`src/pexpect/pxssh.py`** — ruff's `E712` autofix rewrote
   `if ssh_key == True:` to `if ssh_key:`. Since `ssh_key` holds either `True`
   (forward the agent, `-A`) or a private-key *path*, and a non-empty path is
   truthy, every path took the `-A` branch and `-i <path>` was never emitted.
   Restored as `is True` with a comment explaining why the identity check
   matters. Caught by `test_ssh_key_string`.
