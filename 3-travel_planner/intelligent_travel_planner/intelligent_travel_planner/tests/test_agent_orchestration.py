## author:SUN Bin
import unittest

from travel_planner.agent import TravelPlanningAgent


class AgentOrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user_profile = {
            "city": "Hong Kong",
            "start_date": "",
            "trip_days": 3,
            "travel_type": "leisure",
            "travelers": "friends",
            "budget_level": "medium",
            "pace": "balanced",
            "interests": ["landmarks", "local food", "viewpoints"],
            "must_visit": ["Peak Tram", "Central Market"],
            "avoid": [],
            "notes": "Try one harbour walk and one classic cha chaan teng.",
            "extra_request": "Keep transfers reasonable.",
        }
        self.tool_results = {
            "_logs": [{"tool_name": "get_city_context", "arguments": {"city": "Hong Kong"}}],
            "get_strategy_context": {
                "recommended_pois": ["Star Ferry", "PMQ Hong Kong"],
                "theme_suggestions": ["leisure", "view", "food"],
                "local_pitfalls": ["Peak Tram queues get long after late morning."],
                "neighborhood_notes": [{"district": "Central", "note": "Good district for relaxed walking and food clustering."}],
                "results": [
                    {
                        "chunk_id": "hk_001",
                        "score": 0.88,
                        "chunk_text": "Peak Tram建议早上去，下午可以接Central Market和PMQ。",
                        "metadata": {
                            "poi_names": ["Peak Tram", "Central Market", "PMQ Hong Kong"],
                            "districts": ["Central"],
                            "content_type": "route_plan",
                            "tags": ["view", "food"],
                        },
                    }
                ],
            },
            "get_city_context": {
                "focus_tags": ["viewpoints", "local food"],
                "suggested_queries": ["Hong Kong skyline", "Hong Kong cha chaan teng"],
                "transport": ["Use the MTR for cross-harbour hops."],
            },
            "search_batch_pois": {
                "results": [
                    {
                        "name": "Peak Tram",
                        "ticket_price": 88,
                        "district": "Central",
                    },
                    {
                        "name": "Central Market",
                        "ticket_price": 0,
                        "district": "Central",
                    },
                ]
            },
            "get_weather_forecast": {
                "forecast": [
                    {"date": "2026-04-21", "summary": "Cloudy", "outdoor_suitability": "good"},
                ]
            },
            "get_cost_summary": {
                "totals": {"min": 1200, "max": 1800, "mid": 1500},
                "budget_fit": {"user_budget": None, "within_budget": None, "minimum_feasible": None},
                "breakdown": {
                    "hotel_per_night": {"min": 300, "max": 450},
                    "food_per_day": {"min": 150, "max": 220},
                    "local_transport_total": {"min": 80, "max": 120},
                },
                "pricing_notes": ["Budget covers hotel, food, and local transport."],
            },
            "get_travel_tips": {
                "tips": [
                    {"poi_name": "Peak Tram", "tip": "Go early for shorter queues."},
                ]
            },
            "get_hotel_candidates": {
                "recommended_areas": [{"district": "Central", "reason": "Matches the itinerary's highest-frequency districts."}],
                "hotel_candidates": [
                    {
                        "hotel_id": "h1",
                        "name": "Central Hotel",
                        "district": "Central",
                        "address": "1 Queen's Road",
                        "business": "Central",
                        "star_rate": 4,
                        "min_price": 420,
                        "source": "hotel_init_data",
                        "source_url": "https://example.com/hotel",
                        "price_note": None,
                    }
                ],
                "selection_notes": ["Hotels are ranked by itinerary district match first."],
            },
        }
        self.plan = {
            "city": "Hong Kong",
            "trip_days": 3,
            "overview": "A 3-day leisure itinerary in Hong Kong with a balanced pace and medium budget profile.",
            "total_estimated_cost": 188.0,
            "selected_pois": [],
            "days": [],
            "planning_notes": [],
            "local_tips": [],
        }
        self.decomposition = {
            "original_request": "Plan a 3-day Hong Kong trip with food and viewpoints.",
            "strategy_queries": ["Hong Kong viewpoint", "Hong Kong local food route"],
            "geo_queries": ["Peak Tram", "Central Market"],
            "condition_queries": {
                "weather": {"city": "Hong Kong", "trip_days": 3, "start_date": "", "focus": "general"},
                "cost": {"city": "Hong Kong", "days": 3, "budget_level": "medium", "travelers": "friends", "user_budget": None},
            },
            "planning_constraints": ["Pace target: balanced"],
            "synthesis_goal": "Produce one executable 3-day itinerary JSON for Hong Kong.",
        }

    def test_build_strategy_queries_combines_multiple_signal_types(self) -> None:
        queries = TravelPlanningAgent._build_strategy_queries(
            self.user_profile,
            self.tool_results["get_city_context"],
        )
        self.assertIn("Peak Tram", queries)
        self.assertIn("Hong Kong skyline", queries)
        self.assertTrue(any("food market" in query.lower() for query in queries))

    def test_decompose_request_creates_separate_subtask_buckets(self) -> None:
        decomposition = TravelPlanningAgent._decompose_request(
            "Plan a 3-day Hong Kong trip with local food, harbour views, and rainy day backups.",
            self.user_profile,
            self.tool_results["get_city_context"],
        )
        self.assertIn("strategy_queries", decomposition)
        self.assertIn("geo_queries", decomposition)
        self.assertIn("condition_queries", decomposition)
        self.assertTrue(any("rainy day" in query.lower() for query in decomposition["strategy_queries"]))
        self.assertEqual(decomposition["condition_queries"]["weather"]["city"], "Hong Kong")

    def test_build_orchestration_payload_has_team_facing_sections(self) -> None:
        agent = TravelPlanningAgent.__new__(TravelPlanningAgent)
        payload = agent._build_orchestration_payload(
            user_profile=self.user_profile,
            decomposition=self.decomposition,
            tool_results=self.tool_results,
            plan=self.plan,
            report="# Hong Kong Plan",
        )

        self.assertEqual(payload.itinerary_json["city"], "Hong Kong")
        self.assertEqual(payload.decomposition["geo_queries"], ["Peak Tram", "Central Market"])
        self.assertIn("group_a_strategy", payload.upstream_requests)
        self.assertIn("group_b_geo", payload.upstream_requests)
        self.assertIn("group_c_conditions", payload.upstream_requests)
        self.assertEqual(
            payload.collected_context["handoff_for_delivery_group"]["itinerary_json"]["total_estimated_cost"],
            188.0,
        )
        self.assertIn("request_breakdown", payload.collected_context)
        self.assertIn("cost_summary", payload.collected_context["conditions_context"])
        self.assertEqual(payload.collected_context["strategy_context"]["rag_context"]["recommended_pois"][0], "Star Ferry")
        self.assertEqual(payload.collected_context["lodging_context"]["hotel_candidates"][0]["name"], "Central Hotel")
        self.assertEqual(
            payload.collected_context["conditions_context"]["budget_summary"]["budget_level"],
            "medium",
        )
        self.assertEqual(
            payload.collected_context["conditions_context"]["budget_summary"]["trip_budget_estimate"]["max"],
            1800,
        )

    def test_merge_preference_memory_applies_follow_up_without_dropping_old_preferences(self) -> None:
        merged = TravelPlanningAgent._merge_preference_memory(
            self.user_profile,
            "改成低预算，不要太赶，加上 Hong Kong Disneyland，删掉 Peak Tram，避开 Temple Street Night Market。",
        )

        self.assertEqual(merged["budget_level"], "low")
        self.assertEqual(merged["pace"], "slow")
        self.assertIn("Hong Kong Disneyland", merged["must_visit"])
        self.assertNotIn("Peak Tram", merged["must_visit"])
        self.assertIn("Temple Street Night Market", merged["avoid"])

    def test_continue_conversation_carries_preference_memory_forward(self) -> None:
        agent = TravelPlanningAgent.__new__(TravelPlanningAgent)

        def fake_execute(user_request: str, max_rounds: int = 8, stored_preferences: dict | None = None):
            default_city = stored_preferences.get("city", "Hong Kong") if stored_preferences else "Hong Kong"
            profile = TravelPlanningAgent._resolve_user_profile(
                user_request,
                default_city=default_city,
                stored_preferences=stored_preferences,
            )
            plan = {
                "city": profile["city"],
                "trip_days": profile["trip_days"],
                "selected_pois": [],
                "days": [],
            }
            return profile, {"_logs": [{"tool_name": "fake_execute"}], "_decomposition": {}}, plan, "stub report"

        agent._execute = fake_execute

        turn_one = agent.start_conversation("Plan a 3-day Hong Kong trip with Peak Tram and local food.")
        turn_two = agent.continue_conversation(
            turn_one.state,
            "改成低预算，不要太赶，加上 Hong Kong Disneyland。",
        )

        self.assertEqual(turn_two.state.preference_memory["city"], "Hong Kong")
        self.assertEqual(turn_two.state.preference_memory["budget_level"], "low")
        self.assertEqual(turn_two.state.preference_memory["pace"], "slow")
        self.assertIn("Peak Tram", turn_two.state.preference_memory["must_visit"])
        self.assertIn("Hong Kong Disneyland", turn_two.state.preference_memory["must_visit"])
        self.assertEqual(len(turn_two.state.turn_history), 2)

    def test_city_switch_clears_city_specific_memory(self) -> None:
        merged = TravelPlanningAgent._merge_preference_memory(
            {
                "city": "Nanjing",
                "trip_days": 3,
                "travel_type": "leisure",
                "travelers": "friends",
                "budget_level": "medium",
                "pace": "balanced",
                "interests": ["culture", "local food"],
                "must_visit": ["南京博物院", "夫子庙", "老门东"],
                "avoid": ["太远的郊区点"],
                "notes": "优先老城路线",
                "extra_request": "晚上去秦淮河",
            },
            "改成去成都玩3天，预算不变，不要太赶，想吃本地美食。",
        )

        self.assertEqual(merged["city"], "Chengdu")
        self.assertEqual(merged["must_visit"], [])
        self.assertEqual(merged["avoid"], [])
        self.assertEqual(merged["notes"], "")
        self.assertEqual(merged["extra_request"], "")
        self.assertIn("local food", merged["interests"])

    def test_render_budget_section_appends_cost_context_to_report(self) -> None:
        budget_summary = TravelPlanningAgent._summarize_budget(
            self.user_profile,
            self.plan,
            self.tool_results["search_batch_pois"],
            cost_summary=self.tool_results["get_cost_summary"],
        )

        section = TravelPlanningAgent._render_budget_section(
            self.tool_results["get_cost_summary"],
            budget_summary,
        )

        self.assertIn("## Budget Envelope", section)
        self.assertIn("Trip estimate: CNY 1200-1800", section)
        self.assertIn("Hotel per night: CNY 300-450", section)

    def test_render_hotel_section_includes_area_and_candidate(self) -> None:
        section = TravelPlanningAgent._render_hotel_section(self.tool_results["get_hotel_candidates"])

        self.assertIn("## Stay Suggestions", section)
        self.assertIn("Area: Central", section)
        self.assertIn("Hotel: Central Hotel", section)

    def test_merge_strategy_into_travel_tips_adds_rag_recommendations(self) -> None:
        merged = TravelPlanningAgent._merge_strategy_into_travel_tips(
            self.tool_results["get_travel_tips"],
            self.tool_results["get_strategy_context"],
        )

        poi_names = [item["poi_name"] for item in merged["tips"]]
        self.assertIn("PMQ Hong Kong", poi_names)
        self.assertIn("Peak Tram", poi_names)

    def test_extract_user_profile_pulls_chinese_must_visit_places_from_first_turn(self) -> None:
        profile = TravelPlanningAgent._extract_user_profile(
            "我想去成都玩三天，必须去太古，春熙路",
            default_city="Chengdu",
        )

        self.assertEqual(profile["city"], "Chengdu")
        self.assertIn("太古里", profile["must_visit"])
        self.assertIn("春熙路", profile["must_visit"])

    def test_extract_user_profile_handles_multiple_generic_cn_places_without_city_bleed(self) -> None:
        profile = TravelPlanningAgent._extract_user_profile(
            "我想去上海玩两天，想去武康路和安福路，再去外滩。",
            default_city="Shanghai",
        )

        self.assertEqual(profile["city"], "Shanghai")
        self.assertIn("武康路", profile["must_visit"])
        self.assertIn("安福路", profile["must_visit"])
        self.assertIn("外滩", profile["must_visit"])
        self.assertNotIn("上海玩两天", profile["must_visit"])

    def test_decompose_request_expands_city_prefixed_geo_queries_for_must_visit(self) -> None:
        profile = {
            "city": "Chengdu",
            "start_date": "",
            "trip_days": 3,
            "travel_type": "leisure",
            "travelers": "friends",
            "budget_level": "medium",
            "pace": "balanced",
            "interests": [],
            "must_visit": ["太古里", "春熙路"],
            "avoid": [],
            "notes": "",
            "extra_request": "",
        }
        decomposition = TravelPlanningAgent._decompose_request(
            "我想去成都玩三天，必须去太古，春熙路",
            profile,
            {"suggested_queries": [], "focus_tags": [], "transport": []},
        )

        self.assertIn("成都 太古里", decomposition["geo_queries"])
        self.assertIn("成都 春熙路", decomposition["geo_queries"])

    def test_decompose_request_blends_city_defaults_even_when_must_visit_exists(self) -> None:
        profile = {
            "city": "Chengdu",
            "start_date": "",
            "trip_days": 3,
            "travel_type": "leisure",
            "travelers": "friends",
            "budget_level": "medium",
            "pace": "balanced",
            "interests": [],
            "must_visit": ["太古里", "春熙路"],
            "avoid": [],
            "notes": "",
            "extra_request": "",
        }
        decomposition = TravelPlanningAgent._decompose_request(
            "我想去成都玩三天，必须去太古，春熙路",
            profile,
            {"suggested_queries": ["Taikoo Li Chengdu", "People's Park Chengdu"], "focus_tags": [], "transport": []},
        )

        self.assertIn("太古里", decomposition["geo_queries"])
        self.assertIn("People's Park Chengdu", decomposition["geo_queries"])

    def test_augment_poi_results_backfills_missing_must_visit_queries(self) -> None:
        agent = TravelPlanningAgent.__new__(TravelPlanningAgent)
        agent.settings = object()

        def fake_search_batch_pois(*, city: str, queries: list[str], limit_per_query: int = 3):
            return {
                "results": [
                    {"name": "太古里", "district": "Jinjiang"},
                    {"name": "春熙路", "district": "Jinjiang"},
                ]
            }

        agent._search_batch_pois = fake_search_batch_pois
        user_profile = {
            "city": "Chengdu",
            "must_visit": ["太古里", "春熙路"],
        }
        poi_result = {"results": [{"name": "Chengdu Research Base of Giant Panda Breeding", "district": "Chenghua"}]}

        merged = agent._augment_poi_results_with_strategy(
            user_profile,
            poi_result,
            {"recommended_pois": ["People's Park Chengdu"]},
        )

        merged_names = [item["name"] for item in merged["results"]]
        self.assertIn("太古里", merged_names)
        self.assertIn("春熙路", merged_names)
        self.assertIn("太古里", merged["strategy_augmented_queries"])


if __name__ == "__main__":
    unittest.main()
