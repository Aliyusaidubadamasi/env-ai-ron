"""Spatial optimisation of green-infrastructure placement (memetic genetic algorithm).

Objective (maximise, each term normalised against its single-objective reference):
    cooling     saturating heat relief spread over hot cells (diminishing returns when
                trees are piled up in one place)
    carbon      20-year sequestration of the species chosen for each site
    pollinator  stepping-stone connectivity to existing canopy and to other new sites,
                weighted by the pollinator guilds the chosen species support
    equity      priority for heat-vulnerable, asthma-burdened, canopy-poor areas

Because cooling saturates and pollinator connectivity rewards clustering, the terms pull
against each other: that tension is why a GA beats a simple "top-N cells" ranking.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import ndimage as ndi

from . import config, species as sp
from .ecology import EcoState

OBJECTIVES = ("cooling", "carbon", "pollinator", "equity")
WARD_CAP = 0.30  # max share of planting sites any one ward / neighbourhood may receive


@dataclass
class Candidates:
    flat_idx: np.ndarray        # indices into rows*cols
    species: list[sp.Species]
    stems: np.ndarray
    fit: np.ndarray             # species suitability 0-1
    canopy_gain20: np.ndarray   # fraction of cell covered by new crowns at year 20
    carbon_kg20: np.ndarray     # cumulative kg CO2 over 20 years
    pollinator_w: np.ndarray    # 0-1 pollinator richness of the chosen species
    equity: np.ndarray
    heat: np.ndarray
    ward: np.ndarray            # ward index per candidate (-1 unknown)


def goal_from_weights(w: dict[str, float]) -> str:
    top = max(w, key=w.get)
    return {"cooling": "shade", "carbon": "carbon", "pollinator": "pollinator"}.get(top, "balanced")


def build_candidates(state: EcoState, weights: dict[str, float]) -> Candidates:
    rows, cols = state.spec.rows, state.spec.cols
    goal = goal_from_weights(weights)
    cell_area = state.spec.cell_area_m2
    surv = config.SIM["establishment_survival"]
    idx = np.flatnonzero(state.plantable.ravel())
    chosen, stems, fit, gain, carbon, poll = [], [], [], [], [], []
    cache: dict[tuple, list[tuple]] = {}
    cap = config.SIM["species_share_cap"]
    for fi in idx:
        r, c = divmod(int(fi), cols)
        key = (str(state.soil[r, c]), bool(state.flood_prone[r, c]), bool(state.narrow_plot[r, c]))
        if key not in cache:
            ranked = sp.recommend_ranked(key[0], goal, key[1], key[2], n=3)
            entries = []
            for s_, f_ in ranked:
                n_ = sp.stems_per_cell(s_, cell_area)
                crown = n_ * surv * math.pi * s_.mature_crown_radius_m ** 2 * sp.growth_fraction(s_, 20)
                kg = sum(n_ * surv * s_.co2_kg_per_yr_mature * sp.growth_fraction(s_, y) for y in range(1, 21))
                entries.append((s_, n_, f_, min(0.65, crown / cell_area), kg, min(len(s_.pollinators) / 4.0, 1.0)))
            # Diversity: split each context across its best species so no single species exceeds `cap`
            # (monocultures are fragile: one pest or disease can erase a whole street's canopy).
            shares = [cap, (1 - cap) * 0.6, (1 - cap) * 0.4][: len(entries)]
            tot = sum(shares)
            cum, acc = [], 0.0
            for sh in shares:
                acc += sh / tot
                cum.append(acc)
            cache[key] = list(zip(cum, entries))
        u = ((r * 7919 + c * 104729) % 1000) / 1000.0
        pick = next((e for cum_, e in cache[key] if u <= cum_), cache[key][-1][1])
        s, n, f, g, kg, pw = pick
        chosen.append(s); stems.append(n); fit.append(f); gain.append(g); carbon.append(kg); poll.append(pw)
    flat_heat = state.heat_excess.ravel()[idx]
    flat_eq = state.equity.ravel()[idx]
    return Candidates(idx, chosen, np.array(stems), np.array(fit, np.float32), np.array(gain, np.float32),
                      np.array(carbon, np.float32), np.array(poll, np.float32), flat_eq.astype(np.float32),
                      flat_heat.astype(np.float32), state.ward_idx.ravel()[idx].astype(np.int32))


class Objective:
    def __init__(self, state: EcoState, cand: Candidates):
        self.state, self.cand = state, cand
        self.rows, self.cols = state.spec.rows, state.spec.cols
        self.n = self.rows * self.cols
        self.existing = (state.frac[..., 1] > 0.30)
        self.heat = state.heat_excess
        # disc kernel ~ 100 m (5 cells) for pollinator movement
        rr = np.arange(-5, 6)
        self.disc = ((rr[:, None] ** 2 + rr[None, :] ** 2) <= 25).astype(np.float32)
        self.disc[5, 5] = 0.0
        self.disc_full = self.disc.copy()
        self.disc_full[5, 5] = 1.0
        self._scale = {k: 1.0 for k in OBJECTIVES}
        self.high_eq = state.equity > 0.55
        self._ref_sum, self._ref_cov = 1.0, 1.0

    # ------------------------------------------------------------------ terms
    def terms(self, sel: np.ndarray) -> dict[str, float]:
        c = self.cand
        g = np.zeros(self.n, np.float32)
        g[c.flat_idx[sel]] = c.canopy_gain20[sel]
        g = g.reshape(self.rows, self.cols)
        local = ndi.uniform_filter(g, 3, mode="constant")
        cooling = float((self.heat * (1.0 - np.exp(-4.0 * local))).sum())

        carbon = float(c.carbon_kg20[sel].sum())

        hab = self.existing.astype(np.float32)
        hab_flat = hab.ravel().copy()
        hab_flat[c.flat_idx[sel]] = 1.0
        nb = ndi.convolve(hab_flat.reshape(self.rows, self.cols), self.disc, mode="constant").ravel()
        nb_sel = nb[c.flat_idx[sel]]
        poll = float(((1.0 - np.exp(-nb_sel / 6.0)) * (0.4 + 0.6 * c.pollinator_w[sel])).sum())

        # Egalitarian: both *depth* (serve the most vulnerable cells, convex) and *reach*
        # (touch as many vulnerable blocks as possible within ~100 m instead of piling up).
        depth = float((c.equity[sel] ** 1.5).sum())
        sel_grid = np.zeros(self.n, np.float32)
        sel_grid[c.flat_idx[sel]] = 1.0
        reached = ndi.convolve(sel_grid.reshape(self.rows, self.cols), self.disc_full, mode="constant") > 0
        reach = float((reached & self.high_eq).sum())
        equity = 0.5 * depth / self._ref_sum + 0.5 * reach / self._ref_cov
        return {"cooling": cooling, "carbon": carbon, "pollinator": poll, "equity": equity}

    def set_reference(self, k: int, weights: dict[str, float]) -> None:
        """Normalise each term by the value a greedy single-objective plan achieves."""
        c = self.cand
        proxies = {
            "cooling": c.heat * c.canopy_gain20,
            "carbon": c.carbon_kg20,
            "pollinator": c.pollinator_w + 0.0,
            "equity": c.equity,
        }
        top_eq = np.argsort(-proxies["equity"])[:k]
        self._ref_sum = max(float((c.equity[top_eq] ** 1.5).sum()), 1e-9)
        every = np.zeros(self.n, np.float32)
        every[c.flat_idx] = 1.0
        full = ndi.convolve(every.reshape(self.rows, self.cols), self.disc_full, mode="constant") > 0
        self._ref_cov = max(float((full & self.high_eq).sum()), 1.0)
        for name in OBJECTIVES:
            top = np.argsort(-proxies[name])[:k]
            val = self.terms(top)[name]
            self._scale[name] = max(val, 1e-9)
        self.weights = weights

    def fairness_penalty(self, sel: np.ndarray) -> float:
        """Egalitarian guard: no single ward may absorb more than WARD_CAP of all sites."""
        w = self.cand.ward[sel]
        w = w[w >= 0]
        if w.size == 0:
            return 0.0
        shares = np.bincount(w) / len(sel)
        return float(1.5 * (np.maximum(shares - WARD_CAP, 0) ** 2).sum())

    def score(self, sel: np.ndarray) -> float:
        t = self.terms(sel)
        return sum(self.weights[k] * t[k] / self._scale[k] for k in OBJECTIVES) - self.fairness_penalty(sel)

    def breakdown(self, sel: np.ndarray) -> dict[str, float]:
        t = self.terms(sel)
        out = {k: round(t[k] / self._scale[k], 4) for k in OBJECTIVES}
        out["fairness_penalty"] = round(self.fairness_penalty(sel), 4)
        return out


def _greedy_linear(obj: Objective, k: int) -> np.ndarray:
    c = obj.cand
    w = obj.weights
    proxy = (w["cooling"] * c.heat * c.canopy_gain20 / max((c.heat * c.canopy_gain20).max(), 1e-9)
             + w["carbon"] * c.carbon_kg20 / max(c.carbon_kg20.max(), 1e-9)
             + w["pollinator"] * c.pollinator_w
             + w["equity"] * c.equity)
    return np.argsort(-proxy)[:k]


def optimise(state: EcoState, weights: dict[str, float], budget_sites: int = 180, *,
             population: int = 60, generations: int = 70, local_iters: int = 1500, seed: int = 42) -> dict:
    total = sum(weights.values())
    weights = {k: weights.get(k, 0.0) / total for k in OBJECTIVES}
    cand = build_candidates(state, weights)
    n_cand = len(cand.flat_idx)
    if n_cand == 0:
        return {"selected": np.array([], int), "cand": cand, "weights": weights, "history": [],
                "score": 0.0, "breakdown": {k: 0.0 for k in OBJECTIVES}, "baselines": {}}
    k = int(min(budget_sites, n_cand))
    rng = np.random.default_rng(seed)
    obj = Objective(state, cand)
    obj.set_reference(k, weights)

    greedy = _greedy_linear(obj, k)
    random_sel = rng.choice(n_cand, k, replace=False)
    baselines = {"greedy_top_n": obj.score(greedy), "random": obj.score(random_sel),
                 "greedy_top_n_no_fairness": obj.score(greedy) + obj.fairness_penalty(greedy)}

    # proxy used to bias sampling / mutation toward promising cells
    p = (0.4 * cand.equity + 0.3 * cand.heat + 0.3 * cand.pollinator_w) + 0.05
    p = p / p.sum()

    def sample_biased(m: int) -> np.ndarray:
        return rng.choice(n_cand, m, replace=False, p=p)

    pop = [greedy.copy()] + [sample_biased(k) for _ in range(population // 2)] + \
          [rng.choice(n_cand, k, replace=False) for _ in range(population - population // 2 - 1)]
    fit = np.array([obj.score(ind) for ind in pop])
    history = [float(fit.max())]

    for _gen in range(generations):
        order = np.argsort(-fit)
        new_pop = [pop[order[0]].copy(), pop[order[1]].copy()]  # elitism
        while len(new_pop) < population:
            a = max(rng.choice(population, 3, replace=False), key=lambda i: fit[i])
            b = max(rng.choice(population, 3, replace=False), key=lambda i: fit[i])
            shared = np.intersect1d(pop[a], pop[b])
            union = np.union1d(pop[a], pop[b])
            rest = np.setdiff1d(union, shared)
            need = k - len(shared)
            child = np.concatenate([shared, rng.choice(rest, need, replace=False)]) if need > 0 else shared[:k]
            # mutation
            n_mut = rng.binomial(k, 0.04)
            if n_mut:
                pos = rng.choice(k, n_mut, replace=False)
                pool = np.setdiff1d(sample_biased(min(n_cand, n_mut * 4)), child)
                if len(pool) >= n_mut:
                    child[pos] = pool[:n_mut]
            new_pop.append(child)
        pop = new_pop
        fit = np.array([obj.score(ind) for ind in pop])
        history.append(float(fit.max()))

    best = pop[int(fit.argmax())].copy()
    best_score = float(fit.max())
    # memetic local search: single-cell swaps that improve the composite score
    in_set = np.zeros(n_cand, bool)
    in_set[best] = True
    for _ in range(local_iters):
        i = int(rng.integers(k))
        new = int(rng.choice(n_cand, p=p))
        if in_set[new]:
            continue
        trial = best.copy()
        trial[i] = new
        s = obj.score(trial)
        if s > best_score:
            in_set[best[i]] = False
            in_set[new] = True
            best, best_score = trial, s
    history.append(best_score)

    return {
        "selected": best, "cand": cand, "weights": weights, "history": history,
        "score": best_score, "breakdown": obj.breakdown(best),
        "baselines": {**baselines, "ga_best": best_score},
        "baseline_breakdowns": {"greedy_top_n": obj.breakdown(greedy), "random": obj.breakdown(random_sel)},
        "budget_sites": k, "n_candidates": n_cand,
    }
