## author:SUN Bin
import unittest

from travel_planner.data_store import load_city_profile


class CityProfileTests(unittest.TestCase):
    TARGET_CITIES = [
        "Chengdu",
        "Shanghai",
        "Beijing",
        "Xian",
        "Hangzhou",
        "Chongqing",
        "Xiamen",
        "Guangzhou",
        "Shenzhen",
        "Nanjing",
    ]

    REQUIRED_KEYS = {
        "city",
        "aliases",
        "recommended_areas",
        "transport",
        "bad_weather_fallbacks",
        "signature_foods",
        "travel_type_guidance",
        "indoor_keywords",
        "outdoor_keywords",
        "seed_pois",
    }

    def test_target_city_profiles_load_with_required_keys(self) -> None:
        for city in self.TARGET_CITIES:
            with self.subTest(city=city):
                profile = load_city_profile(city)
                self.assertTrue(self.REQUIRED_KEYS.issubset(profile.keys()))
                self.assertEqual(profile["city"], city)
                self.assertTrue(profile["aliases"])
                self.assertTrue(profile["recommended_areas"])
                self.assertTrue(profile["transport"])
                self.assertTrue(profile["travel_type_guidance"])
                self.assertTrue(profile["seed_pois"])

    def test_target_city_profiles_cover_core_travel_modes(self) -> None:
        expected_modes = {"leisure", "family", "food", "theme"}
        for city in self.TARGET_CITIES:
            with self.subTest(city=city):
                profile = load_city_profile(city)
                self.assertTrue(expected_modes.issubset(profile["travel_type_guidance"].keys()))

    def test_seed_pois_have_minimum_planning_fields(self) -> None:
        required_poi_keys = {
            "name",
            "category",
            "district",
            "lat",
            "lon",
            "duration_hours",
            "ticket_price",
            "price_level",
            "indoor_outdoor",
            "tags",
        }
        for city in self.TARGET_CITIES:
            profile = load_city_profile(city)
            for poi in profile["seed_pois"]:
                with self.subTest(city=city, poi=poi.get("name")):
                    self.assertTrue(required_poi_keys.issubset(poi.keys()))


if __name__ == "__main__":
    unittest.main()
