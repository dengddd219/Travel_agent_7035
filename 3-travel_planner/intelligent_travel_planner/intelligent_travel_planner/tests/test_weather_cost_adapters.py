## author:SUN Bin
import unittest
from unittest.mock import patch

from travel_planner.config import Settings
from travel_planner.tools.cost_adapter import get_group_c_cost_summary
from travel_planner.tools.weather_adapter import get_group_c_weather_forecast


class GroupCAdapterTests(unittest.TestCase):
    @patch("travel_planner.tools.weather_adapter.get_weather_api")
    def test_weather_adapter_converts_group_c_shape(self, mock_get_weather_api) -> None:
        mock_get_weather_api.return_value = [
            {
                "date": "2026-05-01",
                "condition": "中雨",
                "advice": "建议带伞并安排室内活动",
                "temp_max": "27°C",
                "temp_min": "20°C",
                "precip": "N/A",
                "source": "amap_api",
            },
            {
                "date": "2026-05-02",
                "condition": "晴",
                "advice": "适合户外活动",
                "temp_max": "30°C",
                "temp_min": "22°C",
                "precip": "10",
                "source": "amap_api",
            },
        ]

        payload = get_group_c_weather_forecast(
            city="Shanghai",
            trip_days=2,
            start_date="2026-05-01",
            settings=Settings(amap_api_key="demo-key"),
        )

        self.assertEqual(payload["provider_city"], "上海")
        self.assertEqual(len(payload["forecast"]), 2)
        self.assertEqual(payload["forecast"][0]["outdoor_suitability"], "mixed")
        self.assertEqual(payload["forecast"][1]["outdoor_suitability"], "good")
        self.assertEqual(payload["forecast"][0]["temp_min"], 20.0)
        self.assertEqual(payload["best_outdoor_days"], ["2026-05-02"])

    @patch("travel_planner.tools.cost_adapter.estimate_cost_api")
    def test_cost_adapter_normalizes_ranges_and_totals(self, mock_estimate_cost_api) -> None:
        mock_estimate_cost_api.return_value = {
            "酒店每晚": "350-550元",
            "餐饮每天": "180-280元",
            "交通合计": "100-180元",
            "总计最低": 1690,
            "总计最高": 2670,
        }

        payload = get_group_c_cost_summary(
            city="Shanghai",
            days=3,
            budget_level="medium",
            user_budget=2000,
        )

        self.assertEqual(payload["provider_city"], "上海")
        self.assertEqual(payload["breakdown"]["hotel_per_night"]["min"], 350.0)
        self.assertEqual(payload["breakdown"]["food_per_day"]["max"], 280.0)
        self.assertEqual(payload["totals"]["mid"], 2180.0)
        self.assertFalse(payload["budget_fit"]["within_budget"])
        self.assertTrue(payload["budget_fit"]["minimum_feasible"])


if __name__ == "__main__":
    unittest.main()
