"""Engine tests: species rules, geo helpers, segmentation quality, optimiser, simulation, do-no-harm."""
import numpy as np
import pytest

from app import config, species as sp
from app.geo import GridSpec, rasterize_geojson
from app.pipeline import get_model, load_demo_inputs, run_analysis
from app.segmentation import iou_scores
from app.simulation import cooling_map
from app.synthetic import generate_tile


@pytest.fixture(scope="module")
def demo_run():
    img, spec, layers = load_demo_inputs()
    return run_analysis(img, spec, layers, preset="balanced", budget_sites=120), spec


# ------------------------------------------------------------------ species
def test_recommender_never_returns_rejected_species():
    rejected = {s.scientific for s in sp.SPECIES if not s.eligible}
    for soil in ("loam", "sandy", "clay"):
        for goal in sp.GOALS:
            for flood in (False, True):
                for narrow in (False, True):
                    for s, _ in sp.recommend_ranked(soil, goal, flood, narrow, n=5):
                        assert s.scientific not in rejected and s.status == "native" and s.water_demand != "high"


def test_invasives_and_thirsty_species_are_rejected_with_reason():
    rej = {r["scientific"]: r["reason"] for r in sp.rejected_species()}
    assert "Eucalyptus camaldulensis" in rej and "water" in rej["Eucalyptus camaldulensis"].lower()
    assert "Azadirachta indica" in rej and "Prosopis juliflora" in rej


def test_flood_prone_cells_get_flood_tolerant_species():
    for s, _ in sp.recommend_ranked("clay", "balanced", flood_prone=True, n=3):
        assert s.flood_tolerance != "low"


def test_growth_curve_monotonic_and_bounded():
    s = sp.BY_KEY["terminalia_superba"]
    vals = [sp.growth_fraction(s, y) for y in range(0, 31)]
    assert vals[0] == 0 and all(b >= a for a, b in zip(vals, vals[1:])) and vals[-1] <= 1.0


# --------------------------------------------------------------------- geo
def test_cell_lonlat_roundtrip():
    spec = GridSpec(config.REGION["bbox"], 800, 800)
    lon, lat = spec.cell_center_lonlat(10, 20)
    assert spec.lonlat_to_cell(float(lon), float(lat)) == (10, 20)
    assert spec.lonlat_to_cell(0.0, 0.0) is None


def test_rasterize_geojson_numeric_and_categorical():
    spec = GridSpec((0.0, 0.0, 1.0, 1.0), 80, 80, 8)  # 10x10 cells
    gj = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"v": 7, "k": "a"},
          "geometry": {"type": "Polygon", "coordinates": [[[0, 0.5], [0.5, 0.5], [0.5, 1], [0, 1], [0, 0.5]]]}}]}
    g, _ = rasterize_geojson(gj, spec, "v")
    assert np.nanmax(g) == 7 and np.isnan(g[9, 9]) and g[1, 1] == 7
    c, cats = rasterize_geojson(gj, spec, "k", categorical=True)
    assert cats == ["a"] and c[1, 1] == 0 and c[9, 9] == -1


# ------------------------------------------------------------ segmentation
def test_segmenter_meets_quality_bar_on_unseen_tile():
    t = generate_tile(9001)
    pred = get_model().predict(t.image)
    assert (pred == t.labels).mean() > 0.90
    iou = iou_scores(t.labels, pred)
    assert min(iou.values()) > 0.75, iou


def test_segmenter_handles_large_image_by_tiling():
    img = np.tile(generate_tile(9002).image, (2, 2, 1))  # 1600x1600
    pred = get_model().predict(img)
    assert pred.shape == img.shape[:2] and set(np.unique(pred)) <= {0, 1, 2}


# --------------------------------------------------------------- optimiser
def test_plan_beats_random_and_respects_budget(demo_run):
    (out, _spec) = demo_run
    r = out["result"]
    assert r["summary"]["sites"] == 120
    assert r["optimiser"]["comparison_scores"]["ga_best"] > r["optimiser"]["comparison_scores"]["random"]
    ids = [(s["row"], s["col"]) for s in r["sites"]]
    assert len(ids) == len(set(ids))


def test_do_no_harm_no_site_displaces_canopy_or_sits_in_roads_and_drains(demo_run):
    (out, _spec) = demo_run
    st = out["arrays"]["state"]
    for s in out["result"]["sites"]:
        assert st.frac[s["row"], s["col"], 1] < 0.35
        assert s["zone"] not in ("road_row", "drainage_row")
        assert st.frac[s["row"], s["col"], 2] >= 0.35
        assert s["species"] not in {x["scientific"] for x in out["result"]["species_rejected"]}


def test_egalitarian_ward_cap_and_diversity(demo_run):
    (out, _spec) = demo_run
    s = out["result"]["summary"]
    assert max(s["sites_by_ward"].values()) / s["sites"] <= 0.40
    assert s["species_diversity"]["max_species_share"] <= 0.60 and s["species_diversity"]["n_species"] >= 4


def test_weights_change_the_plan():
    img, spec, layers = load_demo_inputs()
    a = run_analysis(img, spec, layers, preset="carbon_first", budget_sites=60)["result"]
    b = run_analysis(img, spec, layers, preset="equity_first", budget_sites=60)["result"]
    assert {s["site_id"] for s in a["sites"]} != {s["site_id"] for s in b["sites"]} or \
        [(s["row"], s["col"]) for s in a["sites"]] != [(s["row"], s["col"]) for s in b["sites"]]
    assert b["summary"]["equity"]["share_of_trees_in_high_vulnerability_cells"] >= \
        a["summary"]["equity"]["share_of_trees_in_high_vulnerability_cells"] - 0.05


# -------------------------------------------------------------- simulation
def test_projection_is_monotone_and_capped(demo_run):
    (out, _spec) = demo_run
    ser = out["result"]["simulation"]["series"]
    can = [x["canopy_added_ha"] for x in ser]
    co2 = [x["tco2_cumulative"] for x in ser]
    assert all(b >= a for a, b in zip(can, can[1:])) and all(b >= a for a, b in zip(co2, co2[1:]))
    assert max(x["peak_cooling_c"] for x in ser) <= config.SIM["max_local_cooling_c"] + 1e-6
    for h in ("5", "10", "20"):
        assert out["arrays"]["sim"]["horizons"][h]["gain_grid"].max() <= 0.65 + 1e-6


def test_cooling_zero_without_trees(demo_run):
    (out, _spec) = demo_run
    st = out["arrays"]["state"]
    assert float(cooling_map(st, np.zeros((st.spec.rows, st.spec.cols), np.float32)).max()) == 0.0
