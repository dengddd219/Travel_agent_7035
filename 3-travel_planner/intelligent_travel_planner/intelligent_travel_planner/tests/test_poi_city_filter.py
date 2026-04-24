## author:SUN Bin
import unittest
from unittest.mock import Mock, patch

from travel_planner.config import Settings
from travel_planner.tools.poi import search_batch_pois


class PoiCityFilterTests(unittest.TestCase):
    @patch("travel_planner.tools.poi.requests.get")
    def test_search_batch_pois_filters_out_other_city_amap_hits(self, mock_get) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "pois": [
                {
                    "name": "宽窄巷子",
                    "location": "104.0498,30.6666",
                    "type": "风景名胜",
                    "adname": "青羊区",
                    "cityname": "成都市",
                    "pname": "四川省",
                    "address": "宽窄巷子",
                    "biz_ext": {"open_time": "Open"},
                },
                {
                    "name": "Japan's wardrobe(宽花店)",
                    "location": "116.4074,39.9042",
                    "type": "购物服务",
                    "adname": "朝阳区",
                    "cityname": "北京市",
                    "pname": "北京市",
                    "address": "北京市朝阳区",
                    "biz_ext": {"open_time": "Open"},
                },
            ]
        }
        mock_get.return_value = response

        payload = search_batch_pois(
            city="Chengdu",
            queries=["宽窄巷子"],
            limit_per_query=3,
            settings=Settings(amap_api_key="demo-key"),
        )

        names = [item["name"] for item in payload["results"]]
        self.assertIn("宽窄巷子", names)
        self.assertNotIn("Japan's wardrobe(宽花店)", names)

    @patch("travel_planner.tools.poi.requests.get")
    def test_search_batch_pois_filters_out_faraway_same_language_hits(self, mock_get) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "pois": [
                {
                    "name": "成都大熊猫繁育研究基地",
                    "location": "104.1519,30.7336",
                    "type": "风景名胜",
                    "adname": "成华区",
                    "cityname": "成都市",
                    "pname": "四川省",
                    "address": "熊猫大道",
                    "biz_ext": {"open_time": "Open"},
                },
                {
                    "name": "小米之家(河西区和悦汇专卖店)",
                    "location": "116.4074,39.9042",
                    "type": "购物服务",
                    "adname": "海淀区",
                    "cityname": "北京市",
                    "pname": "北京市",
                    "address": "和悦汇",
                    "biz_ext": {"open_time": "Open"},
                },
            ]
        }
        mock_get.return_value = response

        payload = search_batch_pois(
            city="Chengdu",
            queries=["熊猫"],
            limit_per_query=3,
            settings=Settings(amap_api_key="demo-key"),
        )

        names = [item["name"] for item in payload["results"]]
        self.assertIn("成都大熊猫繁育研究基地", names)
        self.assertNotIn("小米之家(河西区和悦汇专卖店)", names)


if __name__ == "__main__":
    unittest.main()
