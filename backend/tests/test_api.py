"""API tests: auth, validation, region lock, exports, community privacy and geofencing."""
import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.synthetic import generate_tile

H = {"X-API-Key": "dev-planner-key"}
client = TestClient(app)


@pytest.fixture(scope="module")
def aid():
    r = client.post("/api/v1/analyses", headers=H, data={"use_demo": "true", "budget_sites": "60"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _png(arr) -> bytes:
    b = io.BytesIO(); Image.fromarray(arr).save(b, "PNG"); return b.getvalue()


def test_planner_endpoints_require_key(aid):
    for path in (f"/api/v1/analyses/{aid}", "/api/v1/analyses", f"/api/v1/analyses/{aid}/report.pdf",
                 f"/api/v1/analyses/{aid}/blueprint.geojson", f"/api/v1/analyses/{aid}/overlays/voids.png"):
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.post("/api/v1/analyses", data={"use_demo": "true"}).status_code == 401


def test_analysis_result_contents(aid):
    j = client.get(f"/api/v1/analyses/{aid}", headers=H).json()
    assert j["summary"]["sites"] == 60 and j["synthetic"] is True and "synthetic" in j["data_note"].lower()
    assert all(k in j["summary"]["cooling_planted_cells_c"] for k in ("5", "10", "20"))
    assert j["clusters"][0]["roi_statement"].startswith("Planting")


def test_exports(aid):
    pdf = client.get(f"/api/v1/analyses/{aid}/report.pdf", headers=H)
    assert pdf.content[:5] == b"%PDF-" and len(pdf.content) < 2_000_000
    gj = client.get(f"/api/v1/analyses/{aid}/blueprint.geojson", headers=H).json()
    assert len(gj["features"]) == 60 and gj["features"][0]["geometry"]["type"] == "Polygon"
    assert client.get(f"/api/v1/analyses/{aid}/blueprint?format=gpkg", headers=H).content[:6] == b"SQLite"
    assert client.get(f"/api/v1/analyses/{aid}/blueprint?format=shp", headers=H).content[:2] == b"PK"
    assert client.get(f"/api/v1/analyses/{aid}/blueprint?format=exe", headers=H).status_code == 422


def test_path_traversal_and_bad_ids_are_rejected():
    for bad in ("../../etc/passwd", "..%2F..%2Fetc", "x" * 32, "G" * 32):
        assert client.get(f"/api/v1/analyses/{bad}", headers=H).status_code == 404
    assert client.get(f"/api/v1/analyses/{'0' * 32}/overlays/../../meta.png", headers=H).status_code in (404, 422)


def test_upload_validation():
    tile = _png(generate_tile(31).image)
    ok_bbox = "3.350,6.490,3.3685,6.508"
    # not an image
    r = client.post("/api/v1/analyses", headers=H, files={"image": ("x.png", b"not an image at all", "image/png")}, data={"bbox": ok_bbox})
    assert r.status_code == 415
    # missing bbox
    assert client.post("/api/v1/analyses", headers=H, files={"image": ("t.png", tile, "image/png")}).status_code == 422
    # outside Lagos: region lock
    r = client.post("/api/v1/analyses", headers=H, files={"image": ("t.png", tile, "image/png")}, data={"bbox": "-0.2,51.4,-0.1,51.5"})
    assert r.status_code == 422 and "Lagos" in r.json()["detail"]
    # too large an area
    assert client.post("/api/v1/analyses", headers=H, files={"image": ("t.png", tile, "image/png")}, data={"bbox": "3.0,6.2,3.6,6.8"}).status_code == 422
    # bad weights / preset / budget (reset the limiter: this test deliberately sends many requests)
    from app.security import analysis_limiter; analysis_limiter.hits.clear()
    assert client.post("/api/v1/analyses", headers=H, data={"use_demo": "true", "weights": "{\"evil\":1}"}).status_code == 422
    assert client.post("/api/v1/analyses", headers=H, data={"use_demo": "true", "preset": "nope"}).status_code == 422
    assert client.post("/api/v1/analyses", headers=H, data={"use_demo": "true", "budget_sites": "999999"}).status_code == 422


def test_real_upload_end_to_end_without_gis_layers():
    tile = _png(generate_tile(32).image)
    r = client.post("/api/v1/analyses", headers=H, files={"image": ("t.png", tile, "image/png")},
                    data={"bbox": "3.350,6.490,3.3685,6.508", "budget_sites": "40"})
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["synthetic"] is False and j["summary"]["sites"] == 40
    full = client.get(f"/api/v1/analyses/{j['id']}", headers=H).json()
    joined = " ".join(full["notes"])
    assert "No soil layer" in joined and "No zoning layer" in joined and "No elevation layer" in joined


def test_community_privacy_and_geofenced_photos(aid):
    assert client.get(f"/api/v1/community/{aid}/blueprint").status_code == 404      # unpublished = invisible
    assert client.post(f"/api/v1/analyses/{aid}/publish").status_code == 401
    assert client.post(f"/api/v1/analyses/{aid}/publish", headers=H).json()["published"] is True
    bp = client.get(f"/api/v1/community/{aid}/blueprint").json()
    f = bp["features"][0]; sid = f["properties"]["id"]; lon, lat = f["geometry"]["coordinates"]
    assert set(f["properties"]) == {"id", "sp", "cn", "n", "c20", "why", "obs"}       # nothing private leaks
    green = np.zeros((300, 400, 3), np.uint8); green[..., 1] = 160; green[..., 0] = 40; green[..., 2] = 40
    photo = lambda: {"photo": ("p.png", _png(green), "image/png")}
    url = f"/api/v1/community/{aid}/sites/{sid}/observations"
    far = client.post(url, files=photo(), data={"lat": lat + 0.01, "lon": lon, "accuracy_m": 10})
    assert far.status_code == 422 and "closer" in far.json()["detail"]
    ok = client.post(url, files=photo(), data={"lat": lat, "lon": lon, "accuracy_m": 10, "note": "<script>x</script> new leaves"})
    assert ok.status_code == 201, ok.text
    assert ok.json()["status"] == "leafy" and "<" not in ok.json()["note"]
    assert client.post(url, files={"photo": ("p.png", b"GIF89a....", "image/png")}, data={"lat": lat, "lon": lon}).status_code == 415
    obs = client.get(url).json()["observations"]
    assert len(obs) == 1 and client.get(obs[0]["photo"]).headers["content-type"] == "image/webp"
    assert client.post(f"/api/v1/community/{aid}/sites/S99999/observations", files=photo(), data={"lat": lat, "lon": lon}).status_code == 404
    assert client.post(f"/api/v1/community/{aid}/sites/..%2Fx/observations", files=photo(), data={"lat": lat, "lon": lon}).status_code in (404, 422)


def test_security_headers_and_frontends():
    r = client.get("/api/v1/meta")
    assert r.headers["x-content-type-options"] == "nosniff" and "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"
    assert client.get("/planner/").status_code == 200 and client.get("/community/manifest.webmanifest").status_code == 200


def test_rate_limit_blocks_bursts():
    codes = [client.post("/api/v1/analyses", headers=H, data={"preset": "nope"}).status_code for _ in range(8)]
    assert codes[:6] == [422] * 6 and codes[6:] == [429, 429]
