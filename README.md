# security-practice-lab

[![Juice Shop](https://github.com/Kurtis-H/security-practice-lab/actions/workflows/juice-shop.yml/badge.svg)](https://github.com/Kurtis-H/security-practice-lab/actions/workflows/juice-shop.yml)
[![CodeQL](https://github.com/Kurtis-H/security-practice-lab/actions/workflows/codeql.yml/badge.svg)](https://github.com/Kurtis-H/security-practice-lab/actions/workflows/codeql.yml)

Security testing practice, automated so every result is repeatable and checked in CI:

1. **[Juice Shop, automated](#1-owasp-juice-shop-automated):** attacks against OWASP's deliberately vulnerable shop, each proven by the shop's own scoreboard.
2. **Fuzzing with Atheris:** coming next.
3. **A test runner from scratch:** coming after.

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
