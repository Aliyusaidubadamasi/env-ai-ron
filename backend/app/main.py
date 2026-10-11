"""Env-AI-Ron API (FastAPI).

Planner endpoints require X-API-Key. Community endpoints are read-only for *published*
analyses plus geofenced photo observations, protected by rate limits and strict validation.
"""
from __future__ import annotations

import io
import json
import math
import re
import tempfile
import threading
import zipfile
from pathlib import Path

import numpy as np
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from starlette.concurrency import run_in_threadpool

from . import __version__, config, species as sp, storage
from .geo import GridSpec, read_geotiff
from .pipeline import (Layers, blueprint_geojson, load_demo_inputs, load_layers, prepare_image, run_analysis)
from .render import build_pdf, overlay_png
from .security import (Planner, analysis_limiter, open_image_safely, read_limited, security_headers, sniff,
                       upload_limiter)

DEMO_NOTE = ("The imagery and GIS layers in this analysis are synthetic, generated to exercise the platform. "
             "They are not measurements of real Lagos. Replace them with real aerial imagery and municipal data.")
OVERLAYS = ("classes", "canopy", "voids", "heat", "cooling5", "cooling10", "cooling20", "habitat20")
REGION_BOX = (2.4, 6.0, 4.6, 7.3)  # generous Lagos State envelope: lon_min, lat_min, lon_max, lat_max
_sem = threading.Semaphore(2)      # at most two heavy analyses at once per worker

app = FastAPI(title="Env-AI-Ron API", version=__version__,
              description="Urban ecological intelligence: Nature-Centred AI for planting the right native tree in the right place.")
app.add_middleware(GZipMiddleware, minimum_size=800)
app.add_middleware(CORSMiddleware, allow_origins=config.ALLOWED_ORIGINS, allow_methods=["GET", "POST"],
                   allow_headers=["X-API-Key", "Content-Type"])


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    resp = await call_next(request)
    for k, v in security_headers(request.url.path).items():
        resp.headers.setdefault(k, v)
    return resp


# ---------------------------------------------------------------- helpers

def _parse_weights(raw: str | None) -> dict[str, float] | None:
    if not raw:
        return None
    try:
        w = json.loads(raw)
        assert isinstance(w, dict) and w
        w = {k: float(v) for k, v in w.items()}
        assert set(w) <= {"cooling", "carbon", "pollinator", "equity"} and all(v >= 0 for v in w.values()) and sum(w.values()) > 0
    except Exception:  # noqa: BLE001
        raise HTTPException(422, "weights must be JSON like {\"cooling\":0.5,\"carbon\":0.1,\"pollinator\":0.1,\"equity\":0.3}")
    return w


def _parse_bbox(raw: str | None):
    if not raw:
        return None
    try:
        west, south, east, north = (float(x) for x in raw.split(","))
        assert -180 <= west < east <= 180 and -90 <= south < north <= 90
    except Exception:  # noqa: BLE001
        raise HTTPException(422, "bbox must be 'west,south,east,north' in WGS84 degrees")
    return west, south, east, north


def _check_region(bbox) -> None:
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    if not (REGION_BOX[0] <= cx <= REGION_BOX[2] and REGION_BOX[1] <= cy <= REGION_BOX[3]):
        raise HTTPException(422, "Env-AI-Ron's species and climate data currently cover Lagos State only. "
                                 "Recommendations elsewhere would not be accurate, so this area is refused.")
    area_km2 = (bbox[2] - bbox[0]) * 111.32 * math.cos(math.radians(cy)) * (bbox[3] - bbox[1]) * 110.54
    if area_km2 > 30:
        raise HTTPException(422, f"Area is {area_km2:.0f} km2; the MVP handles up to 30 km2 per analysis.")


async def _json_upload(file: UploadFile | None, name: str):
    if file is None or not file.filename:
        return None
    data = await read_limited(file, 30)
    try:
        gj = json.loads(data)
        assert gj.get("type") in ("FeatureCollection", "Feature")
    except Exception:  # noqa: BLE001
        raise HTTPException(422, f"{name} must be a GeoJSON FeatureCollection")
    return gj


def _store(result: dict, arrays: dict, image: np.ndarray, spec: GridSpec, owner: str, source: str,
           synthetic: bool) -> dict:
    aid = storage.new_id()
    d = storage.analysis_dir(aid, create=True)
    result["id"] = aid
    result["synthetic"] = synthetic
    result["data_note"] = DEMO_NOTE if synthetic else None
    for kind in OVERLAYS:
        (d / "overlays" / f"{kind}.png").write_bytes(overlay_png(kind, arrays))
    Image.fromarray(image).save(d / "image.jpg", quality=78, optimize=True)
    storage.save_json(d / "result.json", result)
    storage.save_json(d / "blueprint.geojson", blueprint_geojson(result, spec))
    build_pdf(result, arrays, image, d / "report.pdf", data_note=DEMO_NOTE if synthetic else None)
    meta = {"id": aid, "created": storage.now(), "region": result["region"], "source": source, "owner": owner,
            "synthetic": synthetic, "published": False, "bbox": list(spec.bbox),
            "trees": result["summary"]["trees"], "sites": result["summary"]["sites"],
            "preset": result["params"]["preset"]}
    storage.save_json(d / "meta.json", meta)
    return meta


def _public_links(aid: str) -> dict:
    base = f"/api/v1/analyses/{aid}"
    return {"result": base, "blueprint_geojson": f"{base}/blueprint.geojson", "report_pdf": f"{base}/report.pdf",
            "gis_gpkg": f"{base}/blueprint?format=gpkg", "gis_shapefile": f"{base}/blueprint?format=shp",
            "image": f"{base}/image.jpg", "overlays": {k: f"{base}/overlays/{k}.png" for k in OVERLAYS}}


def _analysis_or_404(aid: str) -> Path:
    try:
        return storage.analysis_dir(aid)
    except KeyError:
        raise HTTPException(404, "Analysis not found")


def _published_or_404(aid: str) -> tuple[Path, dict]:
    d = _analysis_or_404(aid)
    meta = storage.load_json(d / "meta.json")
    if not meta.get("published"):
        raise HTTPException(404, "Analysis not found")  # same answer as missing: do not leak private ids
    return d, meta


# ---------------------------------------------------------------- public info

@app.get("/api/v1/health")
def health():
    from .pipeline import get_model

    try:
        get_model()
        ok = True
    except FileNotFoundError:
        ok = False
    return {"status": "ok" if ok else "model_missing", "version": __version__}


@app.get("/api/v1/meta")
def meta():
    return {"name": "Env-AI-Ron", "version": __version__, "region": config.REGION,
            "principles": list(config.PRINCIPLES), "presets": config.PRESETS,
            "sim_assumptions": {k: v for k, v in config.SIM.items()}}


@app.get("/api/v1/species")
def species_catalog():
    return {"eligible": [{"scientific": s.scientific, "common": s.common, "water_demand": s.water_demand,
                          "soils": s.soils, "flood_tolerance": s.flood_tolerance,
                          "mature_crown_radius_m": s.mature_crown_radius_m, "notes": s.notes,
                          "pollinators": s.pollinators} for s in sp.eligible_species()],
            "rejected": sp.rejected_species(),
            "note": "Provisional planning values; to be verified by local botanists."}


# ---------------------------------------------------------------- planner

@app.post("/api/v1/analyses", status_code=201, dependencies=[Depends(analysis_limiter)])
async def create_analysis(
    owner: str = Planner,
    image: UploadFile | None = File(None, description="Aerial/drone/satellite image: JPEG, PNG or GeoTIFF"),
    bbox: str | None = Form(None, description="west,south,east,north (required for JPEG/PNG)"),
    use_demo: bool = Form(False, description="Run on the built-in synthetic Lagos demo tile"),
    preset: str = Form("balanced"),
    weights: str | None = Form(None),
    budget_sites: int = Form(180, ge=10, le=1500),
    soil_geojson: UploadFile | None = File(None),
    zoning_geojson: UploadFile | None = File(None),
    wards_geojson: UploadFile | None = File(None),
    elevation_tif: UploadFile | None = File(None),
):
    if preset not in config.PRESETS:
        raise HTTPException(422, f"preset must be one of {sorted(config.PRESETS)}")
    w = _parse_weights(weights)

    if use_demo or image is None:
        img, spec, layers = await run_in_threadpool(load_demo_inputs)
        source, synthetic, extra_notes = "demo", True, []
    else:
        data = await read_limited(image)
        kind = sniff(data[:12])
        bb = _parse_bbox(bbox)
        if kind == "tiff":
            with tempfile.NamedTemporaryFile(suffix=".tif") as tmp:
                tmp.write(data); tmp.flush()
                try:
                    arr, geo_bb = await run_in_threadpool(read_geotiff, tmp.name)
                except Exception as e:  # noqa: BLE001
                    raise HTTPException(400, f"Unreadable GeoTIFF: {type(e).__name__}")
            bb = bb or geo_bb
        else:
            arr = np.asarray(open_image_safely(data))
        if bb is None:
            raise HTTPException(422, "bbox is required for JPEG/PNG (or upload a georeferenced GeoTIFF)")
        _check_region(bb)
        try:
            arr, spec, extra_notes = prepare_image(arr, bb)
        except ValueError as e:
            raise HTTPException(422, str(e))
        img = arr
        soil_gj = await _json_upload(soil_geojson, "soil_geojson")
        zone_gj = await _json_upload(zoning_geojson, "zoning_geojson")
        ward_gj = await _json_upload(wards_geojson, "wards_geojson")
        elev_path = None
        tmp_elev = None
        if elevation_tif is not None and elevation_tif.filename:
            ed = await read_limited(elevation_tif)
            if sniff(ed[:12]) != "tiff":
                raise HTTPException(415, "elevation_tif must be a GeoTIFF")
            tmp_elev = tempfile.NamedTemporaryFile(suffix=".tif"); tmp_elev.write(ed); tmp_elev.flush()
            elev_path = tmp_elev.name
        try:
            layers = await run_in_threadpool(lambda: load_layers(spec, soil_geojson=soil_gj, zoning_geojson=zone_gj,
                                                                 wards_geojson=ward_gj, elevation_path=elev_path))
        except Exception as e:  # noqa: BLE001
            raise HTTPException(422, f"Could not read GIS layers: {e}")
        finally:
            if tmp_elev:
                tmp_elev.close()
        source, synthetic = "upload", False

    def work():
        with _sem:
            out = run_analysis(img, spec, layers, weights=w, preset=preset, budget_sites=budget_sites)
            out["result"]["notes"] = extra_notes + out["result"]["notes"]
            return out, _store(out["result"], out["arrays"], img, spec, owner, source, synthetic)

    try:
        out, meta_ = await run_in_threadpool(work)
    except FileNotFoundError as e:
        raise HTTPException(503, str(e))
    r = out["result"]
    return {"id": meta_["id"], "summary": r["summary"], "baseline": r["baseline"], "clusters": r["clusters"][:5],
            "timings": r["timings"], "links": _public_links(meta_["id"]), "synthetic": synthetic}


@app.get("/api/v1/analyses")
def list_analyses(owner: str = Planner):
    return {"analyses": storage.list_analyses()}


@app.get("/api/v1/analyses/{aid}")
def get_analysis(aid: str, owner: str = Planner):
    d = _analysis_or_404(aid)
    return JSONResponse({**storage.load_json(d / "result.json"), "meta": storage.load_json(d / "meta.json"),
                         "links": _public_links(aid)})


@app.get("/api/v1/analyses/{aid}/blueprint.geojson")
def get_blueprint(aid: str, owner: str = Planner):
    return FileResponse(_analysis_or_404(aid) / "blueprint.geojson", media_type="application/geo+json",
                        filename=f"envairon_blueprint_{aid[:8]}.geojson")


@app.get("/api/v1/analyses/{aid}/blueprint")
def get_blueprint_gis(aid: str, format: str = "gpkg", owner: str = Planner):
    """GIS-compatible export: GeoPackage (.gpkg) or zipped ESRI Shapefile."""
    import geopandas as gpd

    d = _analysis_or_404(aid)
    if format not in ("gpkg", "shp", "geojson"):
        raise HTTPException(422, "format must be gpkg, shp or geojson")
    if format == "geojson":
        return get_blueprint(aid, owner)
    gdf = gpd.read_file(d / "blueprint.geojson")
    gdf = gdf.set_crs(4326, allow_override=True)
    with tempfile.TemporaryDirectory() as tmp:
        if format == "gpkg":
            out = Path(tmp) / "blueprint.gpkg"
            gdf.to_file(out, driver="GPKG", layer="planting_blueprint")
            return Response(out.read_bytes(), media_type="application/geopackage+sqlite3",
                            headers={"Content-Disposition": f'attachment; filename="envairon_{aid[:8]}.gpkg"'})
        short = {"site_id": "site_id", "cluster_id": "cluster", "species": "species", "common_name": "common",
                 "stems": "stems", "soil": "soil", "zone": "zone", "equity_priority": "equity",
                 "heat_excess": "heat", "tco2_20yr": "tco2_20", "cooling_5yr_c": "cool_5",
                 "cooling_10yr_c": "cool_10", "cooling_20yr_c": "cool_20", "rationale": "why"}
        sub = gdf[[c for c in short if c in gdf.columns] + ["geometry"]].rename(columns=short)
        if "why" in sub.columns:
            sub["why"] = sub["why"].str.slice(0, 250)  # shapefile text fields cap at 254 chars
        shp = Path(tmp) / "shp"
        shp.mkdir()
        sub.to_file(shp / "planting_blueprint.shp", driver="ESRI Shapefile", encoding="utf-8")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in shp.iterdir():
                z.write(f, f.name)
        return Response(buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="envairon_{aid[:8]}_shp.zip"'})


@app.get("/api/v1/analyses/{aid}/report.pdf")
def get_report(aid: str, owner: str = Planner):
    return FileResponse(_analysis_or_404(aid) / "report.pdf", media_type="application/pdf",
                        filename=f"envairon_report_{aid[:8]}.pdf")


@app.get("/api/v1/analyses/{aid}/image.jpg")
def get_image(aid: str, owner: str = Planner):
    return FileResponse(_analysis_or_404(aid) / "image.jpg", media_type="image/jpeg")


@app.get("/api/v1/analyses/{aid}/overlays/{kind}.png")
def get_overlay(aid: str, kind: str, owner: str = Planner):
    if kind not in OVERLAYS:
        raise HTTPException(404, "Unknown overlay")
    return FileResponse(_analysis_or_404(aid) / "overlays" / f"{kind}.png", media_type="image/png")


@app.post("/api/v1/analyses/{aid}/publish")
def publish(aid: str, published: bool = True, owner: str = Planner):
    _analysis_or_404(aid)
    return storage.set_meta(aid, published=bool(published))


# ---------------------------------------------------------------- community (public, read-mostly)

@app.get("/api/v1/community/published")
def community_list():
    return {"analyses": [{k: m[k] for k in ("id", "region", "bbox", "trees", "sites", "synthetic", "created")}
                         for m in storage.list_analyses() if m.get("published")]}


@app.get("/api/v1/community/{aid}/blueprint")
def community_blueprint(aid: str):
    """Compact blueprint for phones: points + a few short properties, 5-decimal coordinates."""
    d, meta_ = _published_or_404(aid)
    res = storage.load_json(d / "result.json")
    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(s["lon"], 5), round(s["lat"], 5)]},
              "properties": {"id": s["site_id"], "sp": s["species"], "cn": s["common_name"], "n": s["stems"],
                             "c20": s["horizons"]["20"]["cooling_c"], "why": s["rationale"],
                             "obs": len(storage.load_observations(aid, s["site_id"]))}} for s in res["sites"]]
    return {"type": "FeatureCollection", "features": feats,
            "meta": {"id": aid, "region": meta_["region"], "bbox": meta_["bbox"], "synthetic": meta_["synthetic"],
                     "trees": res["summary"]["trees"], "cooling20": res["summary"]["cooling_100m_c"]["20"],
                     "tco2_20": res["summary"]["tco2_by_year"]["20"]}}


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(a))


def _greenness(im: Image.Image) -> tuple[float, str]:
    """Share of leafy-green pixels in the central crop: a screening indicator, not a diagnosis."""
    a = np.asarray(im.convert("RGB").resize((160, 160)), np.float32)
    c = a[32:128, 32:128]
    exg = 2 * c[..., 1] - c[..., 0] - c[..., 2]
    share = float((exg > 18).mean())
    status = "leafy" if share >= 0.30 else "sparse" if share >= 0.10 else "bare_or_stressed"
    return round(share, 3), status


@app.post("/api/v1/community/{aid}/sites/{site_id}/observations", status_code=201,
          dependencies=[Depends(upload_limiter)])
async def add_observation(aid: str, site_id: str, photo: UploadFile = File(...), lat: float = Form(...),
                          lon: float = Form(...), accuracy_m: float = Form(30.0), note: str = Form("")):
    d, _ = _published_or_404(aid)
    if not storage.valid_site(site_id):
        raise HTTPException(404, "Unknown site")
    res = storage.load_json(d / "result.json")
    site = next((s for s in res["sites"] if s["site_id"] == site_id), None)
    if site is None:
        raise HTTPException(404, "Unknown site")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(422, "Invalid coordinates")
    dist = _haversine_m(lat, lon, site["lat"], site["lon"])
    allowed = 60 + min(max(accuracy_m, 0), 100)
    if dist > allowed:
        raise HTTPException(422, f"You appear to be {dist:.0f} m from this planting site; move closer and retry.")
    im = open_image_safely(await read_limited(photo, 12))
    im.thumbnail((640, 640))
    share, status = _greenness(im)
    oid = storage.new_id()
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=55, method=4)  # re-encoding also strips EXIF (privacy)
    (d / "observations" / f"{oid}.webp").write_bytes(buf.getvalue())
    clean_note = re.sub(r"[\x00-\x1f<>]", " ", note)[:280].strip()
    rec = {"id": oid, "ts": storage.now(), "lat": round(lat, 6), "lon": round(lon, 6), "distance_m": round(dist, 1),
           "greenness": share, "status": status, "note": clean_note, "bytes": len(buf.getvalue())}
    storage.append_observation(aid, site_id, rec)
    return {**rec, "photo": f"/api/v1/community/{aid}/observations/{oid}.webp",
            "message": "Thank you for tending this site. A steward will review the photo."}


@app.get("/api/v1/community/{aid}/sites/{site_id}/observations")
def list_observations(aid: str, site_id: str):
    _published_or_404(aid)
    if not storage.valid_site(site_id):
        raise HTTPException(404, "Unknown site")
    obs = storage.load_observations(aid, site_id)
    return {"site_id": site_id, "observations": [
        {k: o[k] for k in ("id", "ts", "status", "greenness", "note")} | {"photo": f"/api/v1/community/{aid}/observations/{o['id']}.webp"}
        for o in obs]}


@app.get("/api/v1/community/{aid}/observations/{oid}.webp")
def observation_photo(aid: str, oid: str):
    d, _ = _published_or_404(aid)
    if not storage.valid_id(oid):
        raise HTTPException(404, "Not found")
    p = d / "observations" / f"{oid}.webp"
    if not p.exists():
        raise HTTPException(404, "Not found")
    return FileResponse(p, media_type="image/webp")


# ---------------------------------------------------------------- front-ends

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/planner/")


for _name in ("planner", "community"):
    _dir = config.FRONTEND_DIR / _name
    if _dir.exists():
        app.mount(f"/{_name}", StaticFiles(directory=_dir, html=True), name=_name)
_vendor = config.FRONTEND_DIR / "vendor"
if _vendor.exists():
    app.mount("/vendor", StaticFiles(directory=_vendor), name="vendor")
