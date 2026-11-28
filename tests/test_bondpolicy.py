"""The bond sleeve's mix by the Bank of Russia's regime (bondpolicy.py): the regime from the key rate, the walk-forward
optimum that sees only past months, the cost of moving between kinds."""
from __future__ import annotations

import numpy as np
import pytest

from ram import bondpolicy as bp


def test_the_regime_follows_the_last_move_of_the_key_rate() -> None:
    days = [f"w{i}" for i in range(80)]
    key = np.full(80, 0.10)
    key[:5] = np.nan  # before the key rate existed
    key[10:] = 0.12  # a hike at week 10
    key[50:] = 0.11  # a cut at week 50
    g = bp.regimes(days, key)
    assert g[3] == "hold" and g[9] == "hold"
    # the move between weeks 9 and 10 is inside the last POLICY_WEEKS weeks' changes up to week 9 + POLICY_WEEKS
    assert g[10] == "tight" and g[9 + bp.POLICY_WEEKS] == "tight" and g[10 + bp.POLICY_WEEKS] == "hold"
    assert g[50] == "ease" and g[49 + bp.POLICY_WEEKS] == "ease" and g[79] == "hold", "no move for half a year: a pause"


def test_the_optimum_uses_only_past_months_of_the_regime_and_starts_at_the_prior() -> None:
    T = 4 * 60 + 1
    ends = list(range(0, T, 4))
    regime = ["tight"] * T
    rng = np.random.default_rng(1)
    series = {k: rng.normal(0.002, 0.001, T) for k in bp.CANDIDATES}
    series["ofz_float"] = rng.normal(0.006, 0.001, T)  # the best kind by far
    for x in series.values():
        x[0] = np.nan
    rules, opts = bp.walk_forward(series, ends, regime)
    first = ends[1]
    assert opts[first] == rules[first] == pytest.approx(bp.PRIOR["tight"]), "no history of the regime yet: the prior"
    last = ends[-1]
    assert opts[last]["ofz_float"] > 0.2 and "ofz_float" not in bp.PRIOR["tight"], "the optimum learned the best kind"
    assert sum(opts[last].values()) == pytest.approx(1.0)
    assert opts[last]["ofz_float"] <= (1 - bp.TO_PRIOR) * bp.CAP + 1e-9, "half the cap at most: the rest is the prior's"


def test_moving_between_kinds_pays_its_cost() -> None:
    T = 9
    series = {"a": np.full(T, 0.01), "b": np.full(T, 0.01)}
    out = bp.dynamic_blend(series, {0: {"a": 1.0}, 4: {"b": 1.0}}, T, cost=0.001)
    assert out[1] == pytest.approx(0.01) and out[4] == pytest.approx(0.01)
    assert out[5] == pytest.approx(0.01 - 2 * 0.001), "all of a sold and b bought"
    assert np.isnan(out[0])
