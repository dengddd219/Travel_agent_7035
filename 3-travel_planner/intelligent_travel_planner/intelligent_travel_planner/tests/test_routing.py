## author:SUN Bin
import unittest
from unittest.mock import patch

from travel_planner.tools.routing import optimize_route_order


class RoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pois = [
            {"name": "A", "district": "Central", "lat": 22.2800, "lon": 114.1500},
            {"name": "B", "district": "Central", "lat": 22.2810, "lon": 114.1520},
            {"name": "C", "district": "Central", "lat": 22.2850, "lon": 114.1600},
        ]

    def test_optimize_route_order_uses_lowest_total_duration(self) -> None:
        durations = {
            ("A", "B"): {"mode": "walking", "distance_m": 700, "duration_min": 9, "instruction": "A-B", "provider": "test"},
            ("B", "A"): {"mode": "walking", "distance_m": 700, "duration_min": 9, "instruction": "B-A", "provider": "test"},
            ("B", "C"): {"mode": "walking", "distance_m": 900, "duration_min": 12, "instruction": "B-C", "provider": "test"},
            ("C", "B"): {"mode": "walking", "distance_m": 900, "duration_min": 12, "instruction": "C-B", "provider": "test"},
            ("A", "C"): {"mode": "driving", "distance_m": 3500, "duration_min": 28, "instruction": "A-C", "provider": "test"},
            ("C", "A"): {"mode": "driving", "distance_m": 3500, "duration_min": 28, "instruction": "C-A", "provider": "test"},
        }

        def fake_leg(origin: dict, destination: dict, settings=None) -> dict:
            return durations[(origin["name"], destination["name"])]

        with patch("travel_planner.tools.routing.get_leg_route", side_effect=fake_leg):
            route = optimize_route_order(self.pois, must_visit_names=set())

        ordered_names = [self.pois[index]["name"] for index in route["ordered_indices"]]
        self.assertEqual(ordered_names, ["A", "B", "C"])
        self.assertEqual(route["total_duration_min"], 21)


if __name__ == "__main__":
    unittest.main()
