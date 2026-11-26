from __future__ import annotations

import json

from fastapi.testclient import TestClient

from ram.api import app
from ram.study import run_study

REQ = {"assets": [{"id": "test:A0", "label": "рост"}, {"id": "test:A1", "label": "падение", "short_cap": 0.5},
                  {"id": "test:A2", "label": "шум", "cbr": True}],
       "params": {"risk": 0.1, "lookbacks": [20, 60]}, "control": 7, "bootstrap_paths": 500}


def test_study_has_every_section_and_is_json(fake_sources):
    res = run_study(REQ)
    for key in ("meta", "overview", "rule", "crises", "scenarios", "tails", "drawdown", "regimes", "allocation", "sizing"):
        assert key in res
    json.dumps(res, allow_nan=False)
    assert res["meta"]["labels"] == ["рост", "падение", "шум"]
    assert len(res["rule"]["lookbacks"]["rows"]) == 4
    assert res["drawdown"]["rows"][7]["chosen"]
    assert res["rule"]["book"]["sharpe"] > 0  # two of three trend


def test_api(fake_sources):
    client = TestClient(app)
    assert client.get("/api/health").json()["ok"]
    meta = client.get("/api/meta").json()
    assert meta["presets"][0]["key"] == "main" and len(meta["controls"]) == 9
    r = client.post("/api/study", json=REQ)
    assert r.status_code == 200 and r.json()["meta"]["period"]["years"] > 5
    bad = client.post("/api/study", json={"assets": [{"id": "test:nope"}]})
    assert bad.status_code == 404
    empty = client.post("/api/study", json={"assets": []})
    assert empty.status_code == 400
