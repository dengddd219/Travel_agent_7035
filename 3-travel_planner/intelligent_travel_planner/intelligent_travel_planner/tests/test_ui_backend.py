## author:SUN Bin
import unittest

from travel_planner.agent import ConversationRunResult, ConversationState
from travel_planner.ui_backend import (
    build_frontend_response,
    build_map_payload,
    deserialize_conversation_state,
    serialize_conversation_state,
)


class UiBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = {
            "city": "Hong Kong",
            "trip_days": 1,
            "overview": "One-day city highlight plan.",
            "total_estimated_cost": 88.0,
            "selected_pois": [
                {
                    "name": "Peak Tram",
                    "category": "attraction",
                    "district": "Central",
                    "lat": 22.27,
                    "lon": 114.15,
                    "address": "Central Peak Tram Terminus",
                    "open_hours": "07:00-22:00",
                    "ticket_price": 88,
                },
                {
                    "name": "Central Market",
                    "category": "food",
                    "district": "Central",
                    "lat": 22.283,
                    "lon": 114.154,
                    "address": "80 Des Voeux Rd Central",
                    "open_hours": "10:00-22:00",
                    "ticket_price": 0,
                },
            ],
            "days": [
                {
                    "day_index": 1,
                    "area": "Central",
                    "theme": "Scenic landmark day",
                    "estimated_cost": 88.0,
                    "weather_summary": "Cloudy",
                    "inter_stop_distance_m": 1679,
                    "inter_stop_duration_min": 22,
                    "items": [
                        {
                            "time_slot": "morning",
                            "poi_name": "Peak Tram",
                            "category": "attraction",
                            "district": "Central",
                            "duration_hours": 2.0,
                            "est_cost": 88.0,
                            "reasoning": "matches interests",
                            "weather_fit": "Cloudy: outdoor plan, monitor rain risk.",
                            "transport_hint": "Start the day in Central.",
                            "arrival_mode": "start",
                            "arrival_distance_m": 0,
                            "arrival_duration_min": 0,
                        },
                        {
                            "time_slot": "afternoon",
                            "poi_name": "Central Market",
                            "category": "food",
                            "district": "Central",
                            "duration_hours": 1.0,
                            "est_cost": 0.0,
                            "reasoning": "supported by local tip signals",
                            "weather_fit": "Cloudy: indoor-friendly choice.",
                            "transport_hint": "Walking about 22 min (1.7 km).",
                            "arrival_mode": "walking",
                            "arrival_distance_m": 1679,
                            "arrival_duration_min": 22,
                        },
                    ],
                    "notes": [],
                }
            ],
            "planning_notes": [],
            "local_tips": [],
            "review_summary": "Review passed without major routing, weather, or budget issues.",
            "review_findings": [],
            "replan_summary": "No automatic replan was needed because the first draft passed the review threshold.",
            "replan_metadata": {"attempted": False, "applied": False, "trigger_rules": []},
        }
        self.state = ConversationState(
            preference_memory={"city": "Hong Kong", "budget_level": "medium"},
            latest_user_profile={"city": "Hong Kong", "budget_level": "medium"},
            latest_plan=self.plan,
            latest_hotel_recommendations={"recommended_areas": [{"district": "Central", "reason": "Close to the itinerary."}]},
            latest_report="# Hong Kong Plan",
            turn_history=[{"user_message": "Plan a trip."}],
        )

    def test_conversation_state_round_trip(self) -> None:
        payload = serialize_conversation_state(self.state)
        restored = deserialize_conversation_state(payload)

        self.assertEqual(restored.preference_memory["city"], "Hong Kong")
        self.assertEqual(restored.latest_report, "# Hong Kong Plan")
        self.assertEqual(restored.latest_hotel_recommendations["recommended_areas"][0]["district"], "Central")
        self.assertEqual(len(restored.turn_history), 1)

    def test_build_map_payload_contains_stops_and_legs(self) -> None:
        payload = build_map_payload(self.plan)

        self.assertEqual(len(payload["days"]), 1)
        self.assertEqual(len(payload["days"][0]["stops"]), 2)
        self.assertEqual(payload["days"][0]["legs"][0]["mode"], "walking")
        self.assertIsNotNone(payload["center"]["lat"])
        self.assertEqual(payload["all_stops"][0]["poi_name"], "Peak Tram")
        self.assertEqual(payload["city"], "Hong Kong")
        self.assertEqual(payload["city_zh"], "香港")

    def test_build_frontend_response_exposes_ui_fields(self) -> None:
        run_result = ConversationRunResult(
            state=self.state,
            answer="# Hong Kong Plan",
            tool_logs=[{"tool_name": "fake"}],
            plan={
                **self.plan,
                "weather_payload": {
                    "forecast": [
                        {
                            "date": "2026-04-15",
                            "summary": "Cloudy",
                            "temp_min": 22,
                            "temp_max": 28,
                            "precipitation_probability": 20,
                            "suggestions": ["Good for viewpoints."],
                        }
                    ]
                },
                "strategy_summary": {"recommended_pois": ["Peak Tram"], "theme_suggestions": ["viewpoints"]},
                "guide_references": ["攻略里反复提到太平山顶适合和中环放在一起。"],
            },
        )

        response = build_frontend_response(
            conversation_id="conv_test",
            run_result=run_result,
        )

        self.assertEqual(response["conversation_id"], "conv_test")
        self.assertEqual(response["user_profile"]["city"], "Hong Kong")
        self.assertIn("map_payload", response)
        self.assertIn("hotel_recommendations", response)
        self.assertIn("user_friendly_report", response)
        self.assertIn("weather_payload", response)
        self.assertIn("strategy_summary", response)
        self.assertIn("guide_references", response)
        self.assertEqual(response["review_summary"], self.plan["review_summary"])
        self.assertEqual(response["replan_summary"], self.plan["replan_summary"])
        self.assertEqual(response["replan_metadata"]["attempted"], False)
        self.assertEqual(response["map_payload"]["city_zh"], "香港")

    def test_build_frontend_response_surfaces_guide_references_in_user_report(self) -> None:
        guided_plan = {
            **self.plan,
            "guide_references": ["攻略里反复提到太平山顶适合和中环一线放在同一天。"],
            "strategy_summary": {"recommended_pois": ["Peak Tram", "Central Market"]},
            "weather_payload": {
                "forecast": [
                    {
                        "date": "2026-04-15",
                        "summary": "Cloudy",
                        "temp_min": 22,
                        "temp_max": 28,
                        "precipitation_probability": 20,
                        "suggestions": ["Good for viewpoints."],
                    }
                ]
            },
        }
        run_result = ConversationRunResult(
            state=self.state,
            answer="# Hong Kong Plan",
            tool_logs=[],
            plan=guided_plan,
        )

        response = build_frontend_response(
            conversation_id="conv_test",
            run_result=run_result,
        )

        self.assertIn("攻略", response["user_friendly_report"])
        self.assertIn("Peak Tram", response["user_friendly_report"])
        self.assertIn("中午可以优先吃", response["user_friendly_report"])
        self.assertIn("天气大概是", response["user_friendly_report"])


if __name__ == "__main__":
    unittest.main()
