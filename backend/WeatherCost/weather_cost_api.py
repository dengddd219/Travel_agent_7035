"""Re-export all public APIs from the actual Group C module."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "4-cost" / "Group_C" / "Group_C"))

from c_group_weather_cost_api import (  # noqa: F401
    estimate_cost_api,
    search_hotels_api,
    get_weather_api,
)
