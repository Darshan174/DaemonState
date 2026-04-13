from __future__ import annotations

from io import BytesIO
from urllib import error

import pytest

from app.cli import http as cli_http


def _http_error(url: str, status_code: int, body: str, reason: str = "Bad Request") -> error.HTTPError:
    return error.HTTPError(url, status_code, reason, hdrs=None, fp=BytesIO(body.encode("utf-8")))


class TestCLIHTTP:
    def test_api_request_maps_http_error_details(self, monkeypatch):
        def fake_urlopen(request_obj, timeout):
            raise _http_error(
                request_obj.full_url,
                422,
                '{"detail":"workspace_id is required"}',
                reason="Unprocessable Entity",
            )

        monkeypatch.setattr(cli_http.request, "urlopen", fake_urlopen)

        with pytest.raises(cli_http.APIError) as exc_info:
            cli_http.api_request("http://example.test", "POST", "/api/imports", payload={"documents": []})

        err = exc_info.value
        assert str(err) == "POST /api/imports failed with 422: workspace_id is required"
        assert err.status_code == 422
        assert err.method == "POST"
        assert err.path == "/api/imports"
        assert err.detail == "workspace_id is required"

    def test_api_request_surfaces_network_failures_with_url(self, monkeypatch):
        def fake_urlopen(request_obj, timeout):
            raise error.URLError("connection refused")

        monkeypatch.setattr(cli_http.request, "urlopen", fake_urlopen)

        with pytest.raises(cli_http.APIError) as exc_info:
            cli_http.api_request("http://example.test", "GET", "/health/ready")

        assert str(exc_info.value) == "Unable to reach http://example.test/health/ready: connection refused"

    def test_api_request_rejects_invalid_json_success_responses(self, monkeypatch):
        class DummyResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"<html>not json</html>"

        monkeypatch.setattr(cli_http.request, "urlopen", lambda request_obj, timeout: DummyResponse())

        with pytest.raises(cli_http.APIError) as exc_info:
            cli_http.api_request("http://example.test", "GET", "/api/workspaces")

        err = exc_info.value
        assert str(err) == "GET /api/workspaces returned invalid JSON: <html>not json</html>"
        assert err.method == "GET"
        assert err.path == "/api/workspaces"
        assert err.detail == "invalid JSON response"
