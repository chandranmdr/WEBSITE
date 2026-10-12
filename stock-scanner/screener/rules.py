"""Apply the setups from config.yaml to an indicator snapshot."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

log = logging.getLogger(__name__)


@dataclass
class Setup:
    name: str
    description: str
    condition: str
    rank_by: str = "rs_rank"
    ascending: bool = False
    trigger: str = "high"
    stop: str = "low"
    limit: int = 15


@dataclass
class Config:
    universe: list[str]
    base_filter: str
    setups: list[Setup]


def load_config(path: str | Path) -> Config:
    raw = yaml.safe_load(Path(path).read_text())
    setups = [Setup(name=name, **{k: (" ".join(v.split()) if isinstance(v, str) else v) for k, v in body.items()})
              for name, body in raw["setups"].items()]
    return Config(universe=raw.get("universe", ["sp500", "nasdaq100"]), base_filter=raw.get("base_filter", ""), setups=setups)


def run_setups(snap: pd.DataFrame, config: Config) -> pd.DataFrame:
    """Return one row per (symbol, setup) hit with entry trigger, stop and risk."""
    base = snap.query(config.base_filter, engine="python") if config.base_filter else snap
    log.info("%d of %d stocks pass the base filter", len(base), len(snap))

    hits = []
    for s in config.setups:
        try:
            matched = base.query(s.condition, engine="python")
        except Exception as exc:
            raise ValueError(f"setup '{s.name}': bad condition: {exc}") from exc
        matched = matched.sort_values(s.rank_by, ascending=s.ascending).head(s.limit).copy()
        if matched.empty:
            continue
        matched["setup"] = s.name
        matched["trigger"] = matched.eval(s.trigger, engine="python").round(2)
        matched["stop"] = matched.eval(s.stop, engine="python").round(2)
        matched["risk_pct"] = ((matched["trigger"] - matched["stop"]) / matched["trigger"] * 100).round(2)
        matched["rank"] = range(1, len(matched) + 1)
        hits.append(matched)

    if not hits:
        return pd.DataFrame(columns=["symbol", "setup", "rank", "trigger", "stop", "risk_pct"])
    return pd.concat(hits, ignore_index=True)
