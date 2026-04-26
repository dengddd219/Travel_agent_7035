## author:SUN Bin
"""Lazy loader for Group C's weather/cost/hotel API module.

Group C code lives outside the travel_planner package, so we cannot import it
directly. This module injects the Group C directory into sys.path once and
returns a thin namespace object that exposes the three APIs our adapters need:
  - get_weather_api
  - estimate_cost_api
  - search_hotels_api

Usage (inside any adapter):
    from ._group_c_loader import load_group_c_weather_cost_api
    api = load_group_c_weather_cost_api()
    api.get_weather_api(city, dates)
"""
from __future__ import annotations

import sys
import types
from functools import lru_cache
from pathlib import Path

# Absolute path to Group C's source directory (4-cost/Group_C/Group_C/)
# parents[0]=tools, [1]=travel_planner, [2]=3-travel_planner, [3]=Travel_agent_7035 (project root)
_GROUP_C_DIR = (
    Path(__file__).resolve().parents[3] / "4-cost" / "Group_C" / "Group_C"
)


@lru_cache(maxsize=1)
def load_group_c_weather_cost_api() -> types.SimpleNamespace:
    """Import Group C's module (once) and return a namespace of its public APIs.

    The result is cached so the sys.path injection and module import only
    happen on the first call; subsequent calls return the same object.
    """
    group_c_dir = str(_GROUP_C_DIR)
    if group_c_dir not in sys.path:
        sys.path.insert(0, group_c_dir)

    import c_group_weather_cost_api as _mod  # noqa: PLC0415

    return types.SimpleNamespace(
        get_weather_api=_mod.get_weather_api,
        estimate_cost_api=_mod.estimate_cost_api,
        search_hotels_api=_mod.search_hotels_api,
    )
