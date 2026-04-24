## author:SUN Bin
import unittest
from unittest.mock import patch

from travel_planner.tools.hotel_adapter import get_hotel_candidates


class HotelAdapterTests(unittest.TestCase):
    @patch("travel_planner.tools.hotel_adapter.search_hotels_api")
    def test_hotel_adapter_returns_ranked_candidates(self, mock_search_hotels_api) -> None:
        mock_search_hotels_api.return_value = [
            {
                "hotel_id": "1",
                "name": "Central Hotel",
                "district": "Central",
                "address": "1 Queen's Road",
                "business": "Central",
                "star_rate": 4,
                "min_price": 420,
                "source": "hotel_init_data",
                "source_url": "https://example.com/h1",
                "price_note": None,
            },
            {
                "hotel_id": "2",
                "name": "Far Hotel",
                "district": "Kowloon",
                "address": "2 Nathan Road",
                "business": "Tsim Sha Tsui",
                "star_rate": 4,
                "min_price": 380,
                "source": "hotel_scraper",
                "source_url": "https://example.com/h2",
                "price_note": None,
            },
        ]

        payload = get_hotel_candidates(
            city="Hong Kong",
            trip_days=3,
            start_date="2026-05-01",
            target_districts=["Central"],
            budget_level="medium",
            cost_summary={"breakdown": {"hotel_per_night": {"min": 300, "max": 450}}},
        )

        self.assertEqual(payload["hotel_candidates"][0]["name"], "Central Hotel")
        self.assertEqual(payload["provider_city"], "香港")
        self.assertEqual(payload["recommended_areas"][0]["district"], "Central")
        self.assertEqual(payload["check_in_date"], "2026-05-01")
        self.assertEqual(payload["check_out_date"], "2026-05-03")

    @patch("travel_planner.tools.hotel_adapter.search_hotels_api")
    def test_hotel_adapter_falls_back_to_area_guidance_when_empty(self, mock_search_hotels_api) -> None:
        mock_search_hotels_api.return_value = []

        payload = get_hotel_candidates(
            city="Shanghai",
            trip_days=2,
            start_date="2026-05-01",
            target_districts=["黄浦区", "静安区"],
            budget_level="medium",
            cost_summary={"breakdown": {"hotel_per_night": {"min": 350, "max": 550}}},
        )

        self.assertEqual(payload["hotel_candidates"], [])
        self.assertEqual(payload["recommended_areas"][0]["district"], "黄浦区")
        self.assertTrue(any("fallback" in note.lower() for note in payload["selection_notes"]))


if __name__ == "__main__":
    unittest.main()
