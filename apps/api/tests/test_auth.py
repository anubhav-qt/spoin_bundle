"""Tests for the auth module and router."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.api.main import app
from spoin.auth.passwords import verify_password
from spoin.core.config import Settings, get_settings
from spoin.core.db import get_session
from spoin.domain.models import User


@pytest.fixture(autouse=True)
def override_dependencies(session: AsyncSession, settings: Settings):
    async def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_settings] = lambda: settings
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_register_and_login(session: AsyncSession, settings: Settings):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Register
        register_resp = await client.post(
            "/auth/register",
            json={
                "email": "test@example.com",
                "password": "strongpassword123",
                "display_name": "Test User",
            },
        )
        assert register_resp.status_code == 201
        data = register_resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

        # Duplicate register fails
        dup_resp = await client.post(
            "/auth/register",
            json={
                "email": "test@example.com",
                "password": "anotherpassword",
                "display_name": "Duplicate",
            },
        )
        assert dup_resp.status_code == 409

        # Verify user in db
        user = await session.scalar(select(User).where(User.email == "test@example.com"))
        assert user is not None
        assert user.display_name == "Test User"
        assert verify_password("strongpassword123", user.password_hash)

        # Login correct password
        login_resp = await client.post(
            "/auth/login",
            json={"email": "test@example.com", "password": "strongpassword123"},
        )
        assert login_resp.status_code == 200
        login_data = login_resp.json()
        access_token = login_data["access_token"]

        # Login wrong password
        wrong_login_resp = await client.post(
            "/auth/login",
            json={"email": "test@example.com", "password": "wrongpassword"},
        )
        assert wrong_login_resp.status_code == 401

        # Use token to access protected route (/auth/me)
        me_resp = await client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert me_resp.status_code == 200
        me_data = me_resp.json()
        assert me_data["email"] == "test@example.com"
        assert me_data["display_name"] == "Test User"

        # Protected route without token
        unauth_resp = await client.get("/auth/me")
        assert unauth_resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_refresh_token(session: AsyncSession, settings: Settings):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        register_resp = await client.post(
            "/auth/register",
            json={
                "email": "refresh@example.com",
                "password": "strongpassword123",
                "display_name": "Refresh User",
            },
        )
        assert register_resp.status_code == 201
        refresh_token = register_resp.json()["refresh_token"]

        refresh_resp = await client.post(
            "/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert refresh_resp.status_code == 200
        refresh_data = refresh_resp.json()
        assert "access_token" in refresh_data
        assert "refresh_token" in refresh_data

        # Use the access token
        access_token = refresh_data["access_token"]
        me_resp = await client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert me_resp.status_code == 200


@pytest.mark.asyncio
async def test_google_auth(session: AsyncSession, settings: Settings, monkeypatch):
    # Mock verify_google_id_token
    from spoin.auth import google

    def mock_verify(*args, **kwargs):
        return google.GoogleUserInfo(
            email="google@example.com",
            google_id="1234567890",
            name="Google User",
        )

    monkeypatch.setattr("spoin.api.routers.auth.verify_google_id_token", mock_verify)

    # Enable google client id in settings
    monkeypatch.setattr(settings, "google_client_id", "test-client-id")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Google sign in
        google_resp = await client.post(
            "/auth/google",
            json={"id_token": "fake-token"},
        )
        assert google_resp.status_code == 200
        data = google_resp.json()
        assert "access_token" in data

        # Check user created
        user = await session.scalar(select(User).where(User.email == "google@example.com"))
        assert user is not None
        assert user.google_id == "1234567890"

        # Subsequent sign in returns tokens (does not fail with 409)
        google_resp2 = await client.post(
            "/auth/google",
            json={"id_token": "fake-token"},
        )
        assert google_resp2.status_code == 200
