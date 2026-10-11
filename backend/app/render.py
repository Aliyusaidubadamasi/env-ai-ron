"""Map overlays (PNG, transparent) for the web twin, and the planner PDF report."""
from __future__ import annotations

import datetime as dt
import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib import cm  # noqa: E402
from PIL import Image  # noqa: E402

PALETTE = {"forest": "#2F5D3A", "moss": "#6B8F4E", "clay": "#B4673C", "sand": "#F3EDE0", "soil": "#3B2F26",
           "water": "#3C7A89"}
CLASS_RGB = np.array([[110, 110, 120], [47, 125, 61], [196, 150, 96]], np.uint8)


def _png(rgba: np.ndarray, scale_to: tuple[int, int] | None = None) -> bytes:
    im = Image.fromarray(rgba.astype(np.uint8), "RGBA")
    if scale_to:
        im = im.resize(scale_to, Image.NEAREST)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _ramp(values: np.ndarray, cmap: str, alpha_floor: float = 0.0, alpha_max: float = 0.75,
          vmin: float | None = None, vmax: float | None = None) -> np.ndarray:
    v = np.asarray(values, np.float32)
    lo = float(np.nanmin(v)) if vmin is None else vmin
    hi = float(np.nanmax(v)) if vmax is None else vmax
    n = np.clip((v - lo) / max(hi - lo, 1e-9), 0, 1)
    rgba = (matplotlib.colormaps[cmap](n) * 255).astype(np.uint8)
    rgba[..., 3] = (np.clip(alpha_floor + (1 - alpha_floor) * n, 0, 1) * alpha_max * 255).astype(np.uint8)
    return rgba


def overlay_png(kind: str, arrays: dict) -> bytes:
    """kind: classes | canopy | voids | heat | cooling5 | cooling10 | cooling20 | habitat20"""
    state, sim = arrays["state"], arrays["sim"]
    h, w = arrays["labels"].shape
    if kind == "classes":
        rgba = np.concatenate([CLASS_RGB[arrays["labels"]], np.full((h, w, 1), 170, np.uint8)], -1)
        return _png(rgba)
    size = (w, h)
    if kind == "canopy":
        return _png(_ramp(state.frac[..., 1], "Greens", 0.0, 0.8, 0, 1), size)
    if kind == "voids":
        rgba = _ramp(state.void_score, "YlOrRd", 0.0, 0.7, 0.3, 1.0)
        rgba[..., 3] = np.where(state.void_mask, rgba[..., 3], 0)
        return _png(rgba, size)
    if kind == "heat":
        return _png(_ramp(state.lst_c, "inferno", 0.35, 0.7), size)
    if kind.startswith("cooling"):
        grid = sim["horizons"][kind.replace("cooling", "")]["cooling_grid"]
        rgba = _ramp(grid, "Blues", 0.0, 0.85, 0, max(float(grid.max()), 0.4))
        rgba[..., 3] = np.where(grid > 0.02, rgba[..., 3], 0)
        return _png(rgba, size)
    if kind.startswith("habitat"):
        grid = sim["horizons"][kind.replace("habitat", "")]["bi_grid"]
        return _png(_ramp(grid, "YlGn", 0.1, 0.75, 0, 100), size)
    raise KeyError(kind)


# --------------------------------------------------------------------------
# Figures for the PDF
# --------------------------------------------------------------------------

def _fig_bytes(fig, photo: bool = False) -> io.BytesIO:
    """Maps over imagery are saved as JPEG (small); line charts as PNG (crisp)."""
    buf = io.BytesIO()
    if photo:
        fig.savefig(buf, format="jpeg", dpi=120, bbox_inches="tight", facecolor="white",
                    pil_kwargs={"quality": 78, "optimize": True})
    else:
        fig.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _map_figure(image: np.ndarray, result: dict, arrays: dict, mode: str) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(6.2, 6.2))
    ax.imshow(image)
    h, w = image.shape[:2]
    spec = result["grid"]
    cell = spec["cell_px"]
    if mode == "voids":
        st = arrays["state"]
        v = np.ma.masked_where(~np.kron(st.void_mask, np.ones((cell, cell), bool)), np.kron(st.void_score, np.ones((cell, cell))))
        ax.imshow(v, cmap="YlOrRd", alpha=0.65, vmin=0.3, vmax=1.0)
        ax.set_title("Ecological voids: hot, canopy-poor, concrete-dominated ground", fontsize=9, color=PALETTE["soil"])
    else:
        palette = ["#1b9e77", "#d95f02", "#7570b3", "#e7298a", "#66a61e", "#e6ab02", "#a6761d", "#1f78b4"]
        names = sorted({s["species"] for s in result["sites"]})
        for k, n in enumerate(names):
            xs = [(s["col"] + 0.5) * cell for s in result["sites"] if s["species"] == n]
            ys = [(s["row"] + 0.5) * cell for s in result["sites"] if s["species"] == n]
            ax.scatter(xs, ys, s=30, c=palette[k % len(palette)], edgecolors="white", linewidths=0.6, label=n)
        ax.legend(loc="lower left", fontsize=6.5, frameon=True, framealpha=0.9, title="Native species", title_fontsize=7)
        ax.set_title("Recommended planting sites", fontsize=9, color=PALETTE["soil"])
    ax.set_xlim(0, w); ax.set_ylim(h, 0)
    ax.axis("off")
    return _fig_bytes(fig, photo=True)


def _projection_figure(result: dict) -> io.BytesIO:
    ser = result["simulation"]["series"]
    yrs = [s["year"] for s in ser]
    fig, axes = plt.subplots(1, 3, figsize=(9.2, 2.7))
    axes[0].fill_between(yrs, [s["mean_cooling_100m_c"] for s in ser], color=PALETTE["water"], alpha=0.25)
    axes[0].plot(yrs, [s["mean_cooling_planted_c"] for s in ser], color=PALETTE["water"], lw=2, label="planted cells")
    axes[0].plot(yrs, [s["mean_cooling_100m_c"] for s in ser], color=PALETTE["water"], lw=1.2, ls="--", label="100 m neighbourhood")
    axes[0].set_title("Air-temperature relief (°C)", fontsize=9); axes[0].legend(fontsize=6.5, frameon=False)
    axes[1].plot(yrs, [s["canopy_added_ha"] for s in ser], color=PALETTE["forest"], lw=2)
    axes[1].set_title("New canopy (ha)", fontsize=9)
    axes[2].plot(yrs, [s["tco2_cumulative"] for s in ser], color=PALETTE["clay"], lw=2)
    axes[2].set_title("Carbon stored, cumulative (tCO2)", fontsize=9)
    for a in axes:
        a.set_xlabel("years after planting", fontsize=7.5); a.tick_params(labelsize=7)
        for sp_ in ("top", "right"):
            a.spines[sp_].set_visible(False)
        for h in (5, 10, 20):
            a.axvline(h, color="#00000015", lw=0.8)
    fig.tight_layout()
    return _fig_bytes(fig)


def _convergence_figure(result: dict) -> io.BytesIO:
    o = result["optimiser"]
    fig, ax = plt.subplots(figsize=(4.6, 2.4))
    ax.plot(o["history"], color=PALETTE["forest"], lw=2, label="genetic algorithm")
    for name, col in (("greedy_top_n", PALETTE["clay"]), ("random", "#999999")):
        ax.axhline(o["comparison_scores"][name], color=col, ls="--", lw=1, label=name.replace("_", " "))
    ax.set_xlabel("generation", fontsize=7.5); ax.set_ylabel("composite score", fontsize=7.5)
    ax.tick_params(labelsize=7); ax.legend(fontsize=6.5, frameon=False)
    for sp_ in ("top", "right"):
        ax.spines[sp_].set_visible(False)
    fig.tight_layout()
    return _fig_bytes(fig)


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------

def _pdf_text(t: str) -> str:
    return (t.replace("₂", "2").replace("–", "-").replace("→", "to")
             .replace("≥", ">=").replace("≤", "<="))


def build_pdf(result: dict, arrays: dict, image: np.ndarray, path: Path, *, data_note: str | None = None) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (Image as RLImage, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)

    forest, moss, clay, sand, soil = (colors.HexColor(PALETTE[k]) for k in ("forest", "moss", "clay", "sand", "soil"))
    ss = getSampleStyleSheet()
    H1 = ParagraphStyle("H1", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=22, textColor=forest, alignment=TA_LEFT, leading=26)
    H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=13, textColor=forest, spaceBefore=12, spaceAfter=4)
    B = ParagraphStyle("B", parent=ss["BodyText"], fontName="Helvetica", fontSize=9.2, leading=13, textColor=soil)
    SM = ParagraphStyle("SM", parent=B, fontSize=7.8, leading=10.5, textColor=colors.HexColor("#5b4e44"))
    Q = ParagraphStyle("Q", parent=B, fontName="Helvetica-Oblique", fontSize=10.5, leading=15, textColor=moss)

    def P(t, st=B):
        return Paragraph(_pdf_text(t), st)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#8a7d70"))
        canvas.drawString(18 * mm, 10 * mm, "Env-AI-Ron  |  Nature-Centred AI: do no harm, be regenerative, be egalitarian")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"page {doc.page}")
        canvas.restoreState()

    r, s, b = result, result["summary"], result["baseline"]
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=18 * mm,
                            title="Env-AI-Ron Planting Blueprint", author="Env-AI-Ron")
    story = [P("Env-AI-Ron", H1),
             P(f"Ecological planting blueprint: {r['region']}", ParagraphStyle("sub", parent=B, fontSize=11.5, textColor=moss)),
             P(f"Generated {dt.date.today().isoformat()}  |  {r['grid']['rows']}x{r['grid']['cols']} cells of "
               f"{int(r['grid']['cell_area_m2'] ** 0.5)} m  |  objective: "
               + ", ".join(f"{k} {v:.0%}" for k, v in r["params"]["weights"].items()), SM),
             Spacer(1, 6)]
    if data_note:
        story += [Table([[P("<b>Demonstration data.</b> " + data_note, SM)]], colWidths=[174 * mm],
                        style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FBEFD9")),
                                          ("BOX", (0, 0), (-1, -1), 0.6, clay), ("LEFTPADDING", (0, 0), (-1, -1), 6),
                                          ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)])),
                  Spacer(1, 6)]

    story.append(P("The success measure here is not how the city looks. It is how much life, shade, clean air and carbon "
                   "this land can hold, and who benefits first.", Q))
    story.append(P("Ecological return at a glance", H2))
    kp = [["Native trees to plant", f"{s['trees']:,}", "across", f"{s['sites']} sites / {s['planted_area_ha']} ha"],
          ["Air cooling at planted sites", f"{s['cooling_planted_cells_c']['20']:.2f} C", "by year 20", f"{s['cooling_planted_cells_c']['5']:.2f} (y5), {s['cooling_planted_cells_c']['10']:.2f} (y10)"],
          ["Cooling, 100 m neighbourhood", f"{s['cooling_100m_c']['20']:.2f} C", "by year 20", f"peak {s['peak_cooling_c']['20']:.2f} C"],
          ["Carbon stored", f"{s['tco2_by_year']['20']:.0f} tCO2", "by year 20", f"{s['tco2_by_year']['10']:.0f} (y10)"],
          ["New canopy", f"{s['canopy_added_ha']['20']:.1f} ha", "by year 20", f"cover {s['canopy_cover_pct_before']}% to {s['canopy_cover_pct_after_20yr']}%"],
          ["Habitat quality index", f"{s['habitat_index']['20']:.1f}", "by year 20", f"from {s['habitat_index']['baseline']:.1f} today"],
          ["Pollinator groups supported", f"{s['pollinator_taxa_supported']}", "of 12 tracked", "from the species palette"],
          ["Health equity", f"{s['equity']['share_of_trees_in_high_vulnerability_cells']:.0%}", "of trees", f"in high-vulnerability areas (only {s['equity']['share_of_plantable_cells_high_vulnerability']:.0%} of plantable land is)"],
          ["Species diversity", f"{s['species_diversity']['n_species']} species", f"Shannon {s['species_diversity']['shannon_index']:.2f}", f"no species above {s['species_diversity']['max_species_share']:.0%}"]]
    kp = [[row[0], row[1], row[2], P(row[3], ParagraphStyle("kpc", parent=SM, fontSize=8.2, leading=10))] for row in kp]
    t = Table(kp, colWidths=[50 * mm, 25 * mm, 24 * mm, 75 * mm])
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 8.8), ("FONT", (1, 0), (1, -1), "Helvetica-Bold", 10.5),
                           ("TEXTCOLOR", (1, 0), (1, -1), forest), ("TEXTCOLOR", (0, 0), (0, -1), soil),
                           ("TEXTCOLOR", (2, 0), (3, -1), colors.HexColor("#6b5d52")),
                           ("ROWBACKGROUNDS", (0, 0), (-1, -1), [sand, colors.white]),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story += [t, Spacer(1, 8)]

    story.append(P("Reading the land: what is there now", H2))
    story.append(P(f"Over {b['area_ha']} ha, the imagery reads as {b['cover_pct']['concrete_impervious']}% concrete and other hard surface, "
                   f"{b['cover_pct']['canopy']}% tree canopy and {b['cover_pct']['bare_soil']}% bare soil. "
                   f"Roughly {b['ecological_void_ha']} ha qualify as <b>ecological voids</b>: the hottest cells (a modelled surface-heat proxy, "
                   f"mean {b['mean_lst_proxy_c']} C, hottest decile {b['hottest_decile_lst_c']} C) where canopy is thin and concrete dominates. "
                   f"About {b['plantable_ha']} ha of bare ground is plantable without removing any existing tree, building, road or drainage channel.", B))
    story.append(RLImage(_map_figure(image, r, arrays, "voids"), width=88 * mm, height=88 * mm))
    story.append(PageBreak())

    story.append(P("The blueprint: where to plant", H2))
    story.append(P("Sites were chosen by a genetic algorithm that balances cooling, carbon, pollinator connectivity and health equity. "
                   "Cooling saturates (a hundred trees in one place help less than the same trees spread across hot ground) while pollinators "
                   "need stepping stones, so the objectives pull against each other, and the search finds the compromise.", B))
    story.append(RLImage(_map_figure(image, r, arrays, "sites"), width=118 * mm, height=118 * mm))
    o = r["optimiser"]
    story.append(P(f"Composite score: genetic algorithm {o['comparison_scores']['ga_best']:.3f} vs greedy top-N {o['comparison_scores']['greedy_top_n']:.3f} "
                   f"({o['comparison_scores'].get('greedy_top_n_no_fairness', o['comparison_scores']['greedy_top_n']):.3f} before the fairness penalty) "
                   f"vs random {o['comparison_scores']['random']:.3f} (1.0 = matches a plan that chases each goal alone; a fairness penalty applies if one ward would receive over 30% of sites).", SM))
    story.append(PageBreak())

    story.append(P("Ecological ROI by planting cluster", H2))
    rows = [["Cluster", "Trees", "Dominant native species", "Cooling y20", "tCO2 y20", "Pollinator groups"]]
    for c in r["clusters"][:8]:
        rows.append([c["cluster_id"], str(c["trees"]), c["dominant_species"], f"{c['mean_cooling_c']['20']:.2f} C",
                     f"{c['tco2_20yr']:.1f}", str(c["n_pollinator_taxa"])])
    t = Table(rows, colWidths=[18 * mm, 15 * mm, 62 * mm, 24 * mm, 20 * mm, 30 * mm], repeatRows=1)
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.3), ("BACKGROUND", (0, 0), (-1, 0), forest),
                           ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONT", (0, 1), (-1, -1), "Helvetica", 8.3),
                           ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, sand]),
                           ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5)]))
    story += [t, Spacer(1, 6)]
    for c in r["clusters"][:3]:
        story.append(P(f"<b>{c['cluster_id']}.</b> " + c["roi_statement"], B))
        story.append(Spacer(1, 3))

    story.append(P("Projected recovery over 20 years", H2))
    story.append(RLImage(_projection_figure(r), width=174 * mm, height=51 * mm))
    story.append(P("Shaded range on the cooling chart reflects the stated uncertainty of the cooling coefficient; see assumptions.", SM))
    story.append(PageBreak())

    story.append(P("Species chosen, and species refused", H2))
    story.append(P("Every recommended tree is native, matched to the cell's soil and flood risk, and the palette is split so that no single "
                   "species dominates (a monoculture is one disease away from losing its canopy).", B))
    rows = [["Species", "Trees", "Common name"]]
    from . import species as spmod
    by_sci = {s_.scientific: s_ for s_ in spmod.SPECIES}
    for n, k in s["species_diversity"]["trees_by_species"].items():
        rows.append([n, str(k), by_sci[n].common])
    t = Table(rows, colWidths=[70 * mm, 20 * mm, 84 * mm], repeatRows=1)
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.3), ("BACKGROUND", (0, 0), (-1, 0), moss),
                           ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONT", (0, 1), (-1, -1), "Helvetica-Oblique", 8.3),
                           ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, sand])]))
    story += [t, Spacer(1, 8), P("<b>Refused by the engine</b> (kept in the database so the refusal is auditable):", B)]
    rows = [["Species", "Why it was rejected"]] + [[x["scientific"], P(x["reason"], SM)] for x in r["species_rejected"]]
    t = Table(rows, colWidths=[56 * mm, 118 * mm], repeatRows=1)
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.3), ("BACKGROUND", (0, 0), (-1, 0), clay),
                           ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONT", (0, 1), (-1, -1), "Helvetica", 8.3),
                           ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, sand])]))
    story.append(t)

    story.append(P("Method, assumptions and honest limits", H2))
    a = r["simulation"]["assumptions"]
    lim = [
        f"Cover classes come from a gradient-boosted pixel classifier (concrete / canopy / bare soil). Surface heat is a <b>proxy</b> modelled from cover fractions, not a thermal measurement.",
        f"Cooling uses {a['cooling_c_per_10pct_canopy']} C per +10 percentage points of canopy averaged over about {a['cooling_window_m']} m, capped at {a['max_local_cooling_c']} C, "
        f"with a +/-{a['cooling_uncertainty_pct']}% range. These are planning assumptions to calibrate with local temperature loggers.",
        f"Planting survival is assumed at {int(a['establishment_survival'] * 100)}%. Crown growth is a logistic curve per species.",
        "Species traits and pollinator associations are provisional and need review by local botanists before real planting.",
        "Native versus ornamental classification of <i>existing</i> greenery is not in this MVP; existing canopy is treated as habitat.",
        "Existing trees, buildings, roads and drainage channels are never displaced (do no harm). Street-tree planting needs a separate right-of-way workflow.",
    ] + r["notes"]
    for x in lim:
        story.append(P("- " + x, SM))
        story.append(Spacer(1, 2))
    story.append(RLImage(_convergence_figure(r), width=100 * mm, height=52 * mm))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return path
