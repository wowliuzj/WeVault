from app.services.weread_login_driver import build_login_credentials


def test_build_login_credentials_keeps_refresh_token_and_complete_cookies() -> None:
    credentials = build_login_credentials(
        {
            "data": {
                "succeed": True,
                "webLoginVid": "test-vid",
                "accessToken": "test-access",
                "refreshToken": "web@test-refresh",
            }
        },
        {"wr_gid": "gid", "wr_fp": "fp", "wr_skey": "cookie-skey"},
    )

    assert credentials == {
        "vid": "test-vid",
        "skey": "cookie-skey",
        "refresh_token": "web@test-refresh",
        "cookies": {
            "wr_gid": "gid",
            "wr_fp": "fp",
            "wr_skey": "cookie-skey",
            "wr_vid": "test-vid",
            "wr_rt": "web%40test-refresh",
        },
    }
