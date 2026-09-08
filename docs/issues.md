# Known issues

Bugs and latent defects found while running a full `ruff` lint pass over the
repository, later while taking the test suite to 100% line and branch coverage,
later still while annotating the package for `mypy`, and last while getting the
suite to run clean on 3.10 through 3.14. Every entry was left
alone at the time it was found, because fixing it would change runtime
behaviour and that was out of scope for all three passes — the lint work was
required to be behaviour-preserving, the coverage work to add tests rather than
change the library, and the typing work to add annotations rather than either.

**Four are now fixed**, and are marked as such where they appear: 21, 27, 29
and 30. The annotations could not describe those four without either stating
something untrue about the code or preserving the defect behind a cast, so they
were fixed first, separately. Number 31 is fixed too, for a different reason:
it stopped `replwrap.zsh()` from working at all on a machine that had not been
configured for it, and the test that should have caught it was supplying the
missing configuration itself. Everything else here is still outstanding.

Line numbers refer to the tree as of the lint pass and were each verified
against the source, not inferred from the rule that surfaced them. The
library paths are given under `src/pexpect/`, its location since the switch
to the src layout; that move was a pure rename, so the line numbers are
unaffected by it.

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

**`tests/test_destructor.py:38`, `tests/test_isalive.py:63`**

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

### 32. `replwrap.zsh()` cannot detect incomplete input

**`src/pexpect/replwrap.py:183` (`run_command`)**

On bash, an unterminated quote produces the continuation prompt, `run_command`
sees it as match index 1, sends SIGINT and raises `ValueError`. On zsh the same
input matches neither prompt: `run_command("echo '5 6")` waits out its timeout
and raises `TIMEOUT` instead. This is not a `PS2` that failed to arrive — a zsh
child started by `_repl_sh` reports both `PS2` and `PROMPT2` as the expected
marker — so what zsh emits in that state has not been established.

Nothing covers it. `test_zsh` exercises the empty-input branch,
`run_command("")`, which raises `ValueError` before any shell is involved;
`test_multiline`, the only test of the continuation path, runs bash alone.

**Fix:** find what zsh prints for an incomplete command and match it too, or
document continuation handling as bash-only.

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
