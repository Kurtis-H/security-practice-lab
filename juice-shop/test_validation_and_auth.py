"""A04:2021 Insecure Design and A07:2021 Identification and Authentication Failures."""


def test_log_in_with_the_admins_weak_password(shop, solves):
    with solves("Password Strength"):
        response = shop.login("admin@juice-sh.op", "admin123")
    assert response.status_code == 200


def test_give_a_zero_star_rating(shop, solves):
    # The UI only allows 1-5 stars; the API doesn't check.
    captcha = shop.captcha()
    with solves("Zero Stars"):
        response = shop.post("/api/Feedbacks/", json={
            "comment": "zero", "rating": 0, "captchaId": captcha["captchaId"], "captcha": captcha["answer"],
        })
    assert response.status_code == 201


def test_register_with_an_empty_email_and_password(shop, solves):
    # The form requires both; the API accepts neither.
    with solves("Empty User Registration"):
        response = shop.post("/api/Users/", json={"email": "", "password": ""})
    assert response.status_code == 201
