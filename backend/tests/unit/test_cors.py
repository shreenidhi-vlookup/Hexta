"""Unit tests for CORS configuration (app/main.py).

Regression coverage: allow_credentials=True combined with a wildcard
origin is invalid per the CORS spec — browsers reject
`Access-Control-Allow-Origin: *` on credentialed requests. The app never
uses cookies (auth is a Bearer header), so the wildcard/development case
must not advertise credentialed CORS at all.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


class TestCorsWildcardIsNotCredentialed:
    def test_wildcard_origin_has_no_allow_credentials_header(self):
        from app.config import settings
        from app.main import app

        # Test env leaves HEXA_CORS_ORIGINS unset -> default wildcard "*".
        assert settings.cors_origins == "*"

        client = TestClient(app)
        response = client.options(
            "/api/v1/health",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.headers.get("access-control-allow-origin") == "*"
        assert "access-control-allow-credentials" not in response.headers
