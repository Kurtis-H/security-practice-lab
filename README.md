# security-practice-lab

[![Juice Shop](https://github.com/Kurtis-H/security-practice-lab/actions/workflows/juice-shop.yml/badge.svg)](https://github.com/Kurtis-H/security-practice-lab/actions/workflows/juice-shop.yml)
[![Fuzzing](https://github.com/Kurtis-H/security-practice-lab/actions/workflows/fuzzing.yml/badge.svg)](https://github.com/Kurtis-H/security-practice-lab/actions/workflows/fuzzing.yml)
[![Test runner](https://github.com/Kurtis-H/security-practice-lab/actions/workflows/runner.yml/badge.svg)](https://github.com/Kurtis-H/security-practice-lab/actions/workflows/runner.yml)
[![CodeQL](https://github.com/Kurtis-H/security-practice-lab/actions/workflows/codeql.yml/badge.svg)](https://github.com/Kurtis-H/security-practice-lab/actions/workflows/codeql.yml)

Security testing practice, automated so every result is repeatable and checked in CI:

1. **[Juice Shop, automated](#1-owasp-juice-shop-automated):** attacks against OWASP's deliberately vulnerable shop, each proven by the shop's own scoreboard.
2. **[Fuzzing with Atheris](#2-fuzzing-with-atheris):** a fuzzer finds two bugs that a passing unit-test suite missed, and CI proves it finds them every run.
3. **[A test runner from scratch](#3-a-test-runner-from-scratch):** a pytest-style runner in one standard-library file, tested against pytest itself and checked with planted bugs.

## 1. OWASP Juice Shop, automated

[OWASP Juice Shop](https://owasp.org/www-project-juice-shop/) is a shop built to be hacked for practice. CI starts a fresh, pinned Juice Shop container (`v20.4.0`, reachable only inside the job), and each test in [`juice-shop/`](juice-shop/):

1. checks the challenge starts **unsolved**,
2. runs the attack and checks the evidence (for example, the forged login token really belongs to the admin),
3. checks Juice Shop now counts the challenge as **solved**.

| Challenge | OWASP Top 10 (2021) | The attack | The fix |
|---|---|---|---|
| Login Admin | A03 Injection | `' OR 1=1--` as the email makes the login query's `WHERE` always true | Parameterised queries |
| Login Jim | A03 Injection | `jim@juice-sh.op'--` comments out the password check | Parameterised queries |
| Database Schema | A03 Injection | `UNION SELECT sql FROM sqlite_master` through product search | Parameterised queries; least-privilege DB user |
| User Credentials | A03 Injection | `UNION SELECT id,email,password FROM Users`, which exposes unsalted MD5 hashes too | Parameterised queries; a slow, salted hash (bcrypt, Argon2) |
| View Basket | A01 Broken Access Control | A new customer reads `/rest/basket/1` (the admin's) by changing the id | Check the basket belongs to the caller |
| Forged Feedback | A01 Broken Access Control | `UserId` in the body is trusted, so feedback posts in someone else's name | Take the author from the session, never the body |
| Admin Registration | A01 / A04 | `"role": "admin"` in a sign-up body is copied onto the new user (mass assignment) | Allow-list the fields a client may set |
| Confidential Document | A05 Misconfiguration | `/ftp` is browsable over HTTP and holds an internal memo | Don't serve internal files; no directory listings |
| Poison Null Byte | A05 Misconfiguration | `package.json.bak%2500.md` passes the `.md` filter, but the file system stops at the null byte | Reject null bytes; check the real resolved path |
| Error Handling | A05 Misconfiguration | An unknown route returns a stack trace | Generic errors to clients, details only in logs |
| Exposed Metrics | A05 Misconfiguration | Prometheus `/metrics` is public | Keep metrics on an internal network or behind auth |
| Password Strength | A07 Authentication Failures | The admin's password is `admin123` | Password policy, breached-password checks, MFA |
| Zero Stars | A04 Insecure Design | The UI allows 1–5 stars, but the API accepts 0 | Validate on the server, not only in the UI |
| Empty User Registration | A04 Insecure Design | The API accepts an empty email and password | Server-side validation |

Two more were solved as side effects: **Forgotten Developer Backup** (the null-byte attack downloads `package.json.bak`) and **Repetitive Registration** (the empty registration has no password confirmation). That's 16 challenges in total.

### What CI taught me

The first run passed 9 of 14 tests. The failures were real lessons, not flakiness:

* **Attacks have side effects.** Logging in as the admin to test basket access *also* solved "Login Admin" and "Password Strength" before their own tests ran. The basket test now uses a fresh, ordinary customer, which is a fairer test of the access-control bug anyway.
* **UNION injection needs the exact column count.** Juice Shop's product table gained a column (`alternateImages`, 10 in all), and a wrong count is an SQL error. That error *also* solved "Error Handling" early. The tests now try the likeliest count first, then nearby ones, the way a real attacker probes.

### Run it

```bash
docker run --rm -p 3000:3000 bkimminich/juice-shop:v20.4.0
pip install --require-hashes -r requirements.txt
JUICE_SHOP_FRESH=1 python -m pytest juice-shop -v
```

Only ever point these tests at your own local Juice Shop.

## 2. Fuzzing with Atheris

[`fuzzing/`](fuzzing/) fuzzes a small parser for seat lists like `R1-1, R2-3..R2-5` (the kind of input the booking app takes). [Atheris](https://github.com/google/atheris) is Google's coverage-guided Python fuzzer, built on libFuzzer.

The harness checks the parser's contract, not just "it didn't crash":

- only `SeatParseError` may escape, never a raw exception,
- at most 100 seats come back (no denial of service),
- every label returned parses back to exactly itself.

### What it found

The repo keeps each version so CI can show the fuzzer finding the bug, not just say it did. All three versions pass the same 13 example-based tests.

| Version | Bug the fuzzer found | Time to find it (local) | Fix |
|---|---|---|---|
| `buggy_seats_v1.py` | `R2-5..R2-2444…442` asks for far more seats than exist and runs out of memory | 1 to 4 s | Cap the seat count before building the list |
| `buggy_seats_v2.py` | `R2-³..R2-5` raises a raw `ValueError`: `"³".isdigit()` is true, but `int("³")` fails | 14 s to 5 min | Match `[0-9]` instead of trusting `isdigit()` |
| `seats.py` | Nothing: 12.9 million inputs in 2 minutes | | |

Both findings are kept in [`fuzzing/regressions/`](fuzzing/regressions/), and pytest runs them against the fixed parser on every push. In CI, [`check_finding.py`](fuzzing/check_finding.py) confirms each finding is the planted bug, so an unrelated crash can't pass as a catch.

### What fuzzing taught me

- **How the harness turns bytes into text matters more than run time.** My first harness used `ConsumeUnicodeNoSurrogates`, and five minutes found nothing in version 2. Reading the raw bytes as UTF-8 let ordinary byte mutations turn a `1` into the two bytes of `³`, and the same bug fell out in seconds to minutes.
- **Time to find is luck, so measure it before setting a budget.** v2's bug took 16 s in my first run, then 179 s in CI against a 180 s limit. Across seeds it ranged from 14 s to over 5 minutes. CI now forks a worker per core and allows 8 minutes.
- **libFuzzer stops at the first finding.** Version 1 has both bugs, but the memory blowup is found first and hides the other, so fixing one bug and fuzzing again is part of the loop.
- **Run the harness as an executable for fork mode.** With `python fuzz_seats.py -fork=2`, every forked job died at once (134,000 "crashes", none real): libFuzzer re-runs `argv[0]`, the script, as if it were a binary. A shebang plus `./fuzz_seats.py` fixed it, and now the fuzzer uses every core.
- **Example tests check the cases you thought of.** Every bug here survived a passing suite, because the suite never tried a range that big or a digit that isn't ASCII.

### Run it

```bash
cd fuzzing
pip install --require-hashes -r requirements.txt
python -m pytest -v
FUZZ_TARGET=seats ./fuzz_seats.py corpus/ -fork=2 -max_total_time=60
FUZZ_TARGET=buggy_seats_v2 ./fuzz_seats.py corpus/ -fork=2 -ignore_crashes=0 -max_total_time=300
```

## 3. A test runner from scratch

[`runner/minitest.py`](runner/minitest.py) is a pytest-style test runner in about 470 lines of standard-library Python. I built it to understand what a runner actually does between "collect" and "report".

| Feature | How it works |
|---|---|
| Discovery | `test_*.py` files (skipping hidden folders), `test_*` functions, `Test*` classes with a fresh instance per test |
| Fixtures | `@fixture` functions injected by parameter name, can use other fixtures, `function` or `session` scope, teardown after `yield` (newest first), shared through `conftest.py` |
| Marks | `@parametrize` (stacking multiplies the cases), `@skip`, `@skip_if`, strict `@xfail`, and `raises()` |
| Failure report | The failing line plus the local values it uses: `total = 100`, `prices = [100, 250]` |
| CI output | JUnit XML, and pytest's exit codes: 0 passed, 1 failed, 2 import error, 4 usage error, 5 no tests |
| Fixture problems | A missing fixture, a cycle (`a -> b -> a`), a session fixture using a per-test one, or a failing teardown is an **error**, not a test failure |

### How it's tested

- **[`test_runner.py`](runner/test_runner.py) (pytest, 25 tests):** each test writes a small project into a temp folder and runs minitest on it. A broken runner could pass its own tests, so a different runner does the judging.
- **Differential test:** the same plain-assert suite runs under minitest and real pytest, and every test must get the same verdict.
- **[Mutation check](runner/mutation_check.py):** CI plants 12 realistic bugs, one at a time (teardown order reversed, xfail no longer strict, errors exiting 0, and so on), and fails if the suite misses any. All 12 are caught.
- **Self-test:** [`selftest/`](runner/selftest/) uses minitest's own API, and CI runs it with minitest and checks the JUnit file.

### What building it taught me

- **The tests found two real bugs in the first run.** With no paths given, it crashed: argparse doesn't apply `type=Path` to a list default. And an assert message with a control character (`\x1b` from coloured output) made the JUnit XML invalid. That would break the CI report for the whole suite over one message, so the runner now escapes those characters.
- **Mutation testing found a gap a green suite hid.** The first mutation run caught 11 of 12. Nothing checked that teardowns run newest-first, which matters whenever a connection must close before its database. One new test closed it.
- **A script is `__main__`, not its module name.** Test files that `import minitest` would load a second copy with an empty fixture registry. The runner registers itself under its own name first.
- **Fixture errors and test failures are different results.** "Your code is wrong" and "your test setup is wrong" need different fixes, so they are reported differently, as pytest does.

### Run it

```bash
cd runner
python minitest.py selftest --junit results.xml   # minitest running its self-test
pip install --require-hashes -r ../requirements.txt
python -m pytest test_runner.py                    # pytest testing minitest
python mutation_check.py
```

