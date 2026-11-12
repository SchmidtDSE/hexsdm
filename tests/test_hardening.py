"""Lockdowns matching geo-query: run-id validation, https-only GeoJSON, token auth."""
import pytest
from starlette.testclient import TestClient

import server
from hexsdm import data, outputs
from hexsdm.auth import load_tokens


@pytest.mark.parametrize("rid", ["../../etc", "/etc", "abc", "0123456789ABCDEF",
                                 "0123456789abcdef/..", "０１２３４５６７８９abcdef", None, 5])
def test_bad_run_ids_are_refused(rid):
    assert not outputs.valid_run_id(rid)
    assert outputs.load_summary(rid) is None


def test_get_sdm_result_refuses_path_run_id():
    out = server.get_sdm_result("../../../tmp", wait_seconds=0)
    assert out["status"] == "unknown" and "16 hex" in out["error"]


def test_good_run_id_shape():
    assert outputs.valid_run_id("0123456789abcdef")


@pytest.mark.parametrize("url", ["http://rook-ceph-rgw-nautiluss3.rook/x.geojson",
                                 "HTTP://10.0.0.1/x", "file:///etc/passwd", "ftp://x/y"])
def test_geojson_url_must_be_https(url):
    with pytest.raises(ValueError):
        data._fetch_geojson(url)


def test_geojson_http_string_is_not_parsed_as_inline_json():
    with pytest.raises(ValueError, match="https"):
        data._points_from_geojson("http://example.org/x.geojson")


def test_https_redirect_to_http_is_refused():
    h = data._HttpsOnlyRedirects()
    with pytest.raises(ValueError):
        h.redirect_request(None, None, 302, "Found", {}, "http://kubernetes.default.svc/")


def _client(tokens):
    return TestClient(server.build_app(tokens=tokens))


def test_mcp_needs_a_token_when_auth_is_on():
    # The MCP session manager starts in the app lifespan, and only once per process.
    with _client({"apps": "s3cret"}) as c:
        _check_mcp_auth(c)


def _check_mcp_auth(c):
    assert c.post("/mcp", json={}).status_code == 401
    assert c.post("/mcp", json={}, headers={"Authorization": "Bearer wrong"}).status_code == 401
    r = c.post("/mcp", json={}, headers={"Authorization": "Bearer s3cret"})
    assert r.status_code != 401


def test_public_routes_stay_open():
    c = _client({"apps": "s3cret"})
    assert c.get("/healthz").status_code == 200
    # Unknown runs and layers 404 rather than 401.
    assert c.get("/results/0123456789abcdef/summary.json").status_code in (404, 307)
    assert c.get("/map/0123456789abcdef").status_code == 404
    assert c.get("/tiles/hex/nope/metadata.json").status_code == 404
    # POST to a public prefix is not exempt.
    assert c.post("/results/0123456789abcdef/summary.json").status_code == 401


def test_empty_token_dir_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKENS_DIR", str(tmp_path))
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        server.build_app()


def test_tokens_load_from_secret_shaped_dir(tmp_path):
    (tmp_path / "global-30x30").write_text("tok1\n")
    (tmp_path / "..data").mkdir()
    assert load_tokens(str(tmp_path)) == {"global-30x30": "tok1"}


def test_s3_geojson_path_refuses_globs():
    with pytest.raises(ValueError, match="single file"):
        data._read_s3_geojson("s3://public-output/*.geojson")


def test_public_https_prefix_maps_to_s3(monkeypatch):
    monkeypatch.setattr(data, "S3_HTTPS_PREFIXES", ["https://minio.example.org/"])
    assert data._as_s3_path("https://minio.example.org/public-output/x.geojson") == "s3://public-output/x.geojson"
    assert data._as_s3_path("https://other.example.org/public-output/x.geojson") is None
    assert data._as_s3_path("s3://b/k.geojson") == "s3://b/k.geojson"

