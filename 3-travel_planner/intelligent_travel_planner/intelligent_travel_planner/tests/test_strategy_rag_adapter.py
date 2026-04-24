## author:SUN Bin
import unittest
from unittest.mock import patch

from travel_planner.tools.strategy_rag_adapter import get_strategy_context


class StrategyRagAdapterTests(unittest.TestCase):
    @patch(
        "travel_planner.tools.strategy_rag_adapter._rank_city_chunks",
        side_effect=[
            [
                {
                    "chunk_id": "c1",
                    "score": 0.91,
                    "chunk_text": "熊猫基地建议早上去，下午可以安排宽窄巷子。",
                    "metadata": {
                        "poi_names": ["成都大熊猫繁育研究基地", "宽窄巷子"],
                        "districts": ["成华区", "青羊区"],
                        "content_type": "family_guide",
                        "tags": ["亲子", "熊猫基地"],
                        "travel_type_tags": ["family"],
                    },
                }
            ],
            [
                {
                    "chunk_id": "c2",
                    "score": 0.84,
                    "chunk_text": "下雨天可以优先去博物馆和茶馆，避开长时间户外排队。",
                    "metadata": {
                        "poi_names": ["成都博物馆"],
                        "districts": ["青羊区"],
                        "content_type": "pitfall_warning",
                        "tags": ["雨天", "避坑"],
                        "travel_type_tags": ["leisure"],
                    },
                }
            ],
        ],
    )
    def test_get_strategy_context_returns_agent_ready_structure(self, _mock_rank) -> None:
        result = get_strategy_context(
            city="Chengdu",
            queries=["熊猫基地 亲子", "雨天 博物馆"],
            travel_type="family",
            top_k=3,
        )

        self.assertEqual(result["city"], "Chengdu")
        self.assertEqual(result["provider_city"], "成都")
        self.assertEqual(result["travel_type"], "family")
        self.assertTrue(result["results"])
        self.assertIn("recommended_pois", result)
        self.assertIn("theme_suggestions", result)
        self.assertIn("local_pitfalls", result)
        self.assertIn("neighborhood_notes", result)
        self.assertIn("成都大熊猫繁育研究基地", result["recommended_pois"])
        self.assertTrue(any(note["district"] == "青羊区" for note in result["neighborhood_notes"]))


if __name__ == "__main__":
    unittest.main()
