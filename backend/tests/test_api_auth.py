"""API tests: authentication."""
from __future__ import annotations

from app.models import User


async def test_login_success(client, admin_user: User) -> None:
    """Valid credentials return a token pair and the user record."""
    response = await client.post(
        "/api/v1/auth/login", json={"username": "tester", "password": "Secret123!"}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["access"] and payload["refresh"]
    assert payload["token_type"] == "bearer"
    assert payload["user"]["username"] == "tester"
    assert payload["user"]["role"] == "admin"


async def test_login_wrong_password(client, admin_user: User) -> None:
    """An incorrect password returns 401."""
    response = await client.post(
        "/api/v1/auth/login", json={"username": "tester", "password": "nope"}
    )
    assert response.status_code == 401


async def test_login_unknown_user(client) -> None:
    """An unknown username returns 401."""
    response = await client.post(
        "/api/v1/auth/login", json={"username": "ghost", "password": "whatever"}
    )
    assert response.status_code == 401


async def test_login_validation_error(client) -> None:
    """A malformed payload returns 422."""
    response = await client.post("/api/v1/auth/login", json={"username": ""})
    assert response.status_code == 422


async def test_me_requires_auth(client) -> None:
    """``/auth/me`` rejects anonymous requests."""
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_me_returns_profile(client, auth_headers) -> None:
    """``/auth/me`` returns the authenticated user."""
    response = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["username"] == "tester"


async def test_me_rejects_invalid_token(client) -> None:
    """A garbage bearer token returns 401."""
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer garbage"}
    )
    assert response.status_code == 401


async def test_refresh_token_flow(client, admin_user: User) -> None:
    """A refresh token mints a new access token."""
    login = await client.post(
        "/api/v1/auth/login", json={"username": "tester", "password": "Secret123!"}
    )
    refresh = login.json()["refresh"]
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert response.status_code == 200
    access = response.json()["access"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200


async def test_refresh_rejects_access_token(client, admin_user: User) -> None:
    """An access token cannot be used as a refresh token."""
    from app.security import create_access_token

    access = create_access_token(str(admin_user.id))
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": access})
    assert response.status_code == 401


async def test_refresh_rejects_invalid(client) -> None:
    """Garbage refresh tokens return 401."""
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": "nope"})
    assert response.status_code == 401


async def test_logout(client, auth_headers) -> None:
    """Logout acknowledges success."""
    response = await client.post("/api/v1/auth/logout", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["success"] is True


async def test_inactive_user_cannot_login(client, db, admin_user: User) -> None:
    """A disabled account cannot authenticate."""
    admin_user.is_active = False
    await db.commit()
    response = await client.post(
        "/api/v1/auth/login", json={"username": "tester", "password": "Secret123!"}
    )
    assert response.status_code == 403


async def test_root_and_health(client) -> None:
    """The service banner and liveness probe respond."""
    assert (await client.get("/")).status_code == 200
    assert (await client.get("/healthz")).json()["status"] == "ok"
