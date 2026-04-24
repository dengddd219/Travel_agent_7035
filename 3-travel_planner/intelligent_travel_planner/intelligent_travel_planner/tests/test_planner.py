## author:SUN Bin
import unittest
from unittest.mock import patch

from travel_planner.models import POI
from travel_planner.planner import plan_itinerary, render_markdown_report, review_itinerary


class PlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user_profile = {
            "city": "Hong Kong",
            "start_date": "",
            "trip_days": 2,
            "travel_type": "leisure",
            "travelers": "friends",
            "budget_level": "medium",
            "pace": "balanced",
            "interests": ["landmarks", "local food"],
            "must_visit": ["Peak Tram", "Star Ferry"],
            "avoid": [],
            "notes": "",
            "extra_request": "",
        }
        self.city_context = {
            "city": "Hong Kong",
            "focus_tags": ["view", "local", "culture"],
            "pace_note": "Keep cross-harbour transfers simple.",
            "transport": ["Use MTR for longer jumps."],
        }
        self.weather = {
            "forecast": [
                {
                    "date": "2026-04-15",
                    "summary": "Mainly clear",
                    "temp_min": 22,
                    "temp_max": 28,
                    "precipitation_probability": 20,
                    "outdoor_suitability": "good",
                    "suggestions": ["Good for viewpoints."],
                },
                {
                    "date": "2026-04-16",
                    "summary": "Moderate rain",
                    "temp_min": 21,
                    "temp_max": 25,
                    "precipitation_probability": 75,
                    "outdoor_suitability": "poor",
                    "suggestions": ["Use indoor backups."],
                },
            ]
        }
        self.travel_tips = {
            "tips": [
                {"poi_name": "Peak Tram", "tip": "Go early for shorter queues."},
                {"poi_name": "Hong Kong Museum of History", "tip": "Great rain-safe anchor."},
            ]
        }
        self.candidate_pois = [
            {
                "name": "Peak Tram",
                "category": "attraction",
                "district": "Central",
                "lat": 22.27,
                "lon": 114.15,
                "duration_hours": 2.0,
                "ticket_price": 88,
                "price_level": 3,
                "indoor_outdoor": "outdoor",
                "tags": ["view", "landmark"],
                "source": ["test"],
            },
            {
                "name": "Star Ferry",
                "category": "attraction",
                "district": "Tsim Sha Tsui",
                "lat": 22.29,
                "lon": 114.16,
                "duration_hours": 1.0,
                "ticket_price": 6,
                "price_level": 1,
                "indoor_outdoor": "mixed",
                "tags": ["view", "transport_experience"],
                "source": ["test"],
            },
            {
                "name": "Hong Kong Museum of History",
                "category": "attraction",
                "district": "Tsim Sha Tsui",
                "lat": 22.3,
                "lon": 114.18,
                "duration_hours": 2.0,
                "ticket_price": 10,
                "price_level": 1,
                "indoor_outdoor": "indoor",
                "tags": ["culture", "museum"],
                "source": ["test"],
            },
            {
                "name": "Central Market",
                "category": "food",
                "district": "Central",
                "lat": 22.28,
                "lon": 114.15,
                "duration_hours": 1.2,
                "ticket_price": 0,
                "price_level": 2,
                "indoor_outdoor": "indoor",
                "tags": ["food", "local"],
                "source": ["test"],
            },
        ]

    @staticmethod
    def _fake_route_plan(day_candidates, must_visit_names=None, settings=None):
        leg_count = max(0, len(day_candidates) - 1)
        return {
            "ordered_indices": list(range(len(day_candidates))),
            "legs": [
                {
                    "mode": "walking",
                    "distance_m": 850,
                    "duration_min": 12,
                    "instruction": "Walk via the waterfront promenade.",
                }
                for _ in range(leg_count)
            ],
            "total_distance_m": 850 * leg_count,
            "total_duration_min": 12 * leg_count,
        }

    def test_plan_itinerary_returns_day_structure(self) -> None:
        with patch(
            "travel_planner.planner.optimize_route_order",
            side_effect=self._fake_route_plan,
        ):
            plan = plan_itinerary(
                user_profile=self.user_profile,
                candidate_pois=self.candidate_pois,
                weather=self.weather,
                city_context=self.city_context,
                travel_tips=self.travel_tips,
            )
        self.assertEqual(plan["trip_days"], 2)
        self.assertEqual(len(plan["days"]), 2)
        self.assertTrue(plan["selected_pois"])
        self.assertIn("inter_stop_duration_min", plan["days"][0])
        self.assertIn("arrival_duration_min", plan["days"][0]["items"][1])
        self.assertIn("review_summary", plan)
        self.assertIn("review_findings", plan)
        self.assertIn("replan_summary", plan)
        self.assertIn("replan_metadata", plan)

    def test_poi_model_normalizes_list_open_hours(self) -> None:
        poi = POI.model_validate(
            {
                "name": "Nanjing Museum",
                "open_hours": ["09:00-17:00", "Closed on Monday"],
            }
        )
        self.assertEqual(poi.open_hours, "09:00-17:00; Closed on Monday")

    def test_render_markdown_report_contains_expected_sections(self) -> None:
        with patch(
            "travel_planner.planner.optimize_route_order",
            side_effect=self._fake_route_plan,
        ):
            plan = plan_itinerary(
                user_profile=self.user_profile,
                candidate_pois=self.candidate_pois,
                weather=self.weather,
                city_context=self.city_context,
                travel_tips=self.travel_tips,
            )
        report = render_markdown_report(
            plan=plan,
            user_profile=self.user_profile,
            city_context=self.city_context,
            weather=self.weather,
        )
        self.assertIn("# Hong Kong Intelligent Travel Plan", report)
        self.assertIn("## Day-by-Day Itinerary", report)
        self.assertIn("## Weather Outlook", report)
        self.assertIn("## Review Summary", report)
        self.assertIn("## Replan Summary", report)
        self.assertIn("Inter-stop travel", report)

    def test_review_itinerary_flags_weather_and_budget_risk(self) -> None:
        risky_profile = {
            **self.user_profile,
            "trip_days": 1,
            "budget_level": "low",
            "pace": "slow",
            "must_visit": ["Peak Tram"],
        }
        risky_weather = {
            "forecast": [
                {
                    "date": "2026-04-15",
                    "summary": "Heavy rain",
                    "temp_min": 21,
                    "temp_max": 24,
                    "precipitation_probability": 90,
                    "outdoor_suitability": "poor",
                    "suggestions": ["Prefer indoor backups."],
                }
            ]
        }
        risky_plan = {
            "city": "Hong Kong",
            "trip_days": 1,
            "overview": "Risky one-day plan.",
            "total_estimated_cost": 188.0,
            "selected_pois": [],
            "days": [
                {
                    "day_index": 1,
                    "area": "Central",
                    "theme": "Scenic landmark day",
                    "estimated_cost": 188.0,
                    "weather_summary": "Heavy rain",
                    "inter_stop_distance_m": 3200,
                    "inter_stop_duration_min": 85,
                    "items": [
                        {
                            "time_slot": "morning",
                            "poi_name": "Peak Tram",
                            "category": "attraction",
                            "district": "Central",
                            "duration_hours": 2.0,
                            "est_cost": 88.0,
                            "reasoning": "must visit",
                            "weather_fit": "Heavy rain: outdoor plan, monitor rain risk.",
                            "transport_hint": "Start the day in Central.",
                            "arrival_mode": "start",
                            "arrival_distance_m": 0,
                            "arrival_duration_min": 0,
                        },
                        {
                            "time_slot": "afternoon",
                            "poi_name": "Victoria Peak Terrace",
                            "category": "attraction",
                            "district": "Central",
                            "duration_hours": 2.0,
                            "est_cost": 100.0,
                            "reasoning": "viewpoint",
                            "weather_fit": "Heavy rain: outdoor plan, monitor rain risk.",
                            "transport_hint": "Walk 20 min.",
                            "arrival_mode": "walking",
                            "arrival_distance_m": 1200,
                            "arrival_duration_min": 20,
                        },
                    ],
                    "notes": [],
                }
            ],
            "planning_notes": [],
            "local_tips": [],
            "review_summary": "",
            "review_findings": [],
        }

        review = review_itinerary(risky_plan, user_profile=risky_profile, weather=risky_weather)

        self.assertIn("flagged", review["summary"])
        rules = {finding["rule"] for finding in review["findings"]}
        self.assertIn("weather_fit", rules)
        self.assertIn("budget_pressure", rules)

    def test_plan_itinerary_triggers_replan_when_review_flags_risk(self) -> None:
        risky_profile = {
            **self.user_profile,
            "trip_days": 1,
            "budget_level": "low",
            "pace": "balanced",
            "must_visit": ["Peak Tram"],
        }
        risky_weather = {
            "forecast": [
                {
                    "date": "2026-04-15",
                    "summary": "Heavy rain",
                    "temp_min": 21,
                    "temp_max": 24,
                    "precipitation_probability": 90,
                    "outdoor_suitability": "poor",
                    "suggestions": ["Prefer indoor backups."],
                }
            ]
        }
        risky_candidates = [
            self.candidate_pois[0],
            self.candidate_pois[1],
            self.candidate_pois[2],
        ]

        with patch(
            "travel_planner.planner.optimize_route_order",
            side_effect=self._fake_route_plan,
        ):
            plan = plan_itinerary(
                user_profile=risky_profile,
                candidate_pois=risky_candidates,
                weather=risky_weather,
                city_context=self.city_context,
                travel_tips=self.travel_tips,
            )

        self.assertTrue(
            any("automatic replan pass" in note.lower() for note in plan["planning_notes"])
        )
        self.assertTrue(plan["review_findings"])
        self.assertTrue(plan["replan_metadata"]["attempted"])

    def test_plan_itinerary_keeps_stops_for_later_days(self) -> None:
        distributed_profile = {
            **self.user_profile,
            "city": "Chengdu",
            "trip_days": 3,
            "pace": "balanced",
            "must_visit": [],
            "interests": [],
        }
        distributed_context = {
            "city": "Chengdu",
            "focus_tags": ["culture", "local", "food"],
            "pace_note": "Keep the city stroll relaxed.",
            "transport": ["Cluster by district."],
        }
        distributed_candidates = [
            {
                "name": "Kuanzhai Alley",
                "category": "attraction",
                "district": "Qingyang",
                "lat": 30.6666,
                "lon": 104.0498,
                "duration_hours": 1.8,
                "ticket_price": 0,
                "price_level": 2,
                "indoor_outdoor": "mixed",
                "tags": ["culture", "local", "food"],
                "source": ["test"],
            },
            {
                "name": "Jinsha Site Museum",
                "category": "attraction",
                "district": "Qingyang",
                "lat": 30.6874,
                "lon": 104.0007,
                "duration_hours": 2.0,
                "ticket_price": 70,
                "price_level": 3,
                "indoor_outdoor": "indoor",
                "tags": ["museum", "history", "culture"],
                "source": ["test"],
            },
            {
                "name": "People's Park Chengdu",
                "category": "attraction",
                "district": "Qingyang",
                "lat": 30.6597,
                "lon": 104.0555,
                "duration_hours": 1.5,
                "ticket_price": 0,
                "price_level": 1,
                "indoor_outdoor": "outdoor",
                "tags": ["park", "local", "leisure"],
                "source": ["test"],
            },
            {
                "name": "Chengdu Research Base of Giant Panda Breeding",
                "category": "attraction",
                "district": "Chenghua",
                "lat": 30.7336,
                "lon": 104.1519,
                "duration_hours": 3.0,
                "ticket_price": 55,
                "price_level": 2,
                "indoor_outdoor": "outdoor",
                "tags": ["family", "panda", "landmark"],
                "source": ["test"],
            },
            {
                "name": "Wenshu Monastery",
                "category": "attraction",
                "district": "Qingyang",
                "lat": 30.6745,
                "lon": 104.0758,
                "duration_hours": 1.5,
                "ticket_price": 0,
                "price_level": 1,
                "indoor_outdoor": "mixed",
                "tags": ["culture", "history", "local"],
                "source": ["test"],
            },
        ]

        with patch(
            "travel_planner.planner.optimize_route_order",
            side_effect=self._fake_route_plan,
        ):
            plan = plan_itinerary(
                user_profile=distributed_profile,
                candidate_pois=distributed_candidates,
                weather=self.weather,
                city_context=distributed_context,
                travel_tips={"tips": []},
            )

        self.assertEqual(len(plan["days"]), 3)
        self.assertTrue(all(len(day["items"]) >= 1 for day in plan["days"]))

    def test_plan_itinerary_uses_strategy_context_to_prioritize_rag_pois(self) -> None:
        strategy_profile = {
            **self.user_profile,
            "city": "Chengdu",
            "trip_days": 2,
            "travel_type": "theme",
            "interests": [],
            "must_visit": [],
        }
        strategy_context = {
            "recommended_pois": ["Jinsha Site Museum", "Wenshu Monastery"],
            "theme_suggestions": ["history", "culture"],
            "neighborhood_notes": [{"district": "Qingyang", "note": "good historic cluster"}],
            "local_pitfalls": [],
        }
        strategy_city_context = {
            "city": "Chengdu",
            "focus_tags": ["culture", "history"],
            "pace_note": "Keep it thematic.",
            "transport": [],
        }
        strategy_candidates = [
            {
                "name": "Jinsha Site Museum",
                "category": "attraction",
                "district": "Qingyang",
                "lat": 30.6874,
                "lon": 104.0007,
                "duration_hours": 2.0,
                "ticket_price": 70,
                "price_level": 3,
                "indoor_outdoor": "indoor",
                "tags": ["museum", "history", "culture"],
                "source": ["test"],
            },
            {
                "name": "Wenshu Monastery",
                "category": "attraction",
                "district": "Qingyang",
                "lat": 30.6745,
                "lon": 104.0758,
                "duration_hours": 1.5,
                "ticket_price": 0,
                "price_level": 1,
                "indoor_outdoor": "mixed",
                "tags": ["culture", "history", "local"],
                "source": ["test"],
            },
            {
                "name": "Generic Mall",
                "category": "attraction",
                "district": "Gaoxin",
                "lat": 30.56,
                "lon": 104.06,
                "duration_hours": 1.0,
                "ticket_price": 0,
                "price_level": 1,
                "indoor_outdoor": "indoor",
                "tags": ["shopping"],
                "source": ["test"],
            },
        ]

        with patch(
            "travel_planner.planner.optimize_route_order",
            side_effect=self._fake_route_plan,
        ):
            plan = plan_itinerary(
                user_profile=strategy_profile,
                candidate_pois=strategy_candidates,
                weather=self.weather,
                city_context=strategy_city_context,
                travel_tips={"tips": []},
                strategy_context=strategy_context,
            )

        selected_names = [poi["name"] for poi in plan["selected_pois"]]
        self.assertIn("Jinsha Site Museum", selected_names)
        self.assertIn("Wenshu Monastery", selected_names)
        reason_text = " ".join(item["reasoning"] for day in plan["days"] for item in day["items"])
        self.assertIn("retrieved travel guides", reason_text)

    def test_plan_itinerary_honors_extra_request_to_enrich_specific_day(self) -> None:
        enriched_profile = {
            **self.user_profile,
            "city": "Chengdu",
            "trip_days": 3,
            "extra_request": "第三天的计划过于简单了，增加一些新的景点建议。",
        }
        enriched_context = {
            "city": "Chengdu",
            "focus_tags": ["culture", "history", "local"],
            "pace_note": "Keep it flexible.",
            "transport": [],
        }
        enriched_candidates = [
            {
                "name": "People's Park Chengdu",
                "category": "attraction",
                "district": "Qingyang",
                "lat": 30.6616,
                "lon": 104.0581,
                "duration_hours": 1.4,
                "ticket_price": 0,
                "price_level": 1,
                "indoor_outdoor": "mixed",
                "tags": ["culture", "local", "park"],
                "source": ["test"],
            },
            {
                "name": "Kuanzhai Alley",
                "category": "attraction",
                "district": "Qingyang",
                "lat": 30.6666,
                "lon": 104.0498,
                "duration_hours": 1.8,
                "ticket_price": 0,
                "price_level": 2,
                "indoor_outdoor": "mixed",
                "tags": ["culture", "local", "food"],
                "source": ["test"],
            },
            {
                "name": "Jinsha Site Museum",
                "category": "attraction",
                "district": "Qingyang",
                "lat": 30.6874,
                "lon": 104.0007,
                "duration_hours": 2.0,
                "ticket_price": 70,
                "price_level": 3,
                "indoor_outdoor": "indoor",
                "tags": ["museum", "history", "culture"],
                "source": ["test"],
            },
            {
                "name": "Wenshu Monastery",
                "category": "attraction",
                "district": "Qingyang",
                "lat": 30.6745,
                "lon": 104.0758,
                "duration_hours": 1.5,
                "ticket_price": 0,
                "price_level": 1,
                "indoor_outdoor": "mixed",
                "tags": ["culture", "history", "local"],
                "source": ["test"],
            },
            {
                "name": "Du Fu Thatched Cottage",
                "category": "attraction",
                "district": "Qingyang",
                "lat": 30.6596,
                "lon": 104.0288,
                "duration_hours": 1.8,
                "ticket_price": 50,
                "price_level": 2,
                "indoor_outdoor": "mixed",
                "tags": ["culture", "history", "poetry"],
                "source": ["test"],
            },
            {
                "name": "Chengdu Museum",
                "category": "attraction",
                "district": "Qingyang",
                "lat": 30.6599,
                "lon": 104.0667,
                "duration_hours": 1.8,
                "ticket_price": 0,
                "price_level": 1,
                "indoor_outdoor": "indoor",
                "tags": ["museum", "history", "culture"],
                "source": ["test"],
            },
        ]

        with patch(
            "travel_planner.planner.optimize_route_order",
            side_effect=self._fake_route_plan,
        ):
            plan = plan_itinerary(
                user_profile=enriched_profile,
                candidate_pois=enriched_candidates,
                weather=self.weather,
                city_context=enriched_context,
                travel_tips={"tips": []},
            )

        self.assertGreaterEqual(len(plan["days"][2]["items"]), 2)


if __name__ == "__main__":
    unittest.main()
