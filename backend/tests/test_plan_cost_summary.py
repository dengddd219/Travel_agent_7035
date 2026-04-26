from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "3-travel_planner"))

from travel_planner.ui_backend import build_plan_cost_summary


def test_plan_cost_summary_adds_final_itinerary_costs_and_guide_alignment():
    itinerary = {
        "city": "Shanghai",
        "trip_days": 3,
        "guide_references": ["攻略里建议把外滩和陆家嘴串成一条线"],
        "strategy_summary": {"recommended_pois": ["Shanghai Tower"]},
        "conditions_context": {
            "cost_summary": {
                "city": "Shanghai",
                "days": 3,
                "budget_level": "medium",
                "currency": "CNY",
                "breakdown": {
                    "hotel_per_night": {"min": 300, "max": 400},
                    "food_per_day": {"min": 100, "max": 150},
                    "local_transport_total": {"min": 80, "max": 120},
                },
                "pricing_notes": ["Budget currently covers hotel, food, and local transport only."],
                "source": "group_c_cost_adapter",
            }
        },
        "days": [
            {
                "day_index": 1,
                "area": "Huangpu",
                "theme": "Culture",
                "inter_stop_distance_m": 1500,
                "inter_stop_duration_min": 20,
                "items": [
                    {
                        "poi_name": "Museum",
                        "est_cost": 100,
                        "reasoning": "攻略《Shanghai Guide》里提到“Museum is worth visiting”",
                        "arrival_mode": "start",
                    },
                    {
                        "poi_name": "Park",
                        "est_cost": 0,
                        "reasoning": "主要基于地理顺路",
                        "arrival_mode": "walking",
                        "arrival_distance_m": 1500,
                    },
                ],
            },
            {
                "day_index": 2,
                "area": "Pudong",
                "theme": "Landmark",
                "inter_stop_distance_m": 0,
                "inter_stop_duration_min": 0,
                "items": [
                    {
                        "poi_name": "Shanghai Tower",
                        "est_cost": 50,
                        "reasoning": "主要基于地理顺路",
                        "arrival_mode": "start",
                    }
                ],
            },
        ],
    }

    summary = build_plan_cost_summary(
        itinerary,
        hotel_recommendations={"recommended_areas": [{"district": "Huangpu"}]},
    )

    assert summary["totals"]["attraction_tickets"] == 150
    assert summary["totals"]["guide_aligned_attraction_tickets"] == 150
    assert summary["totals"]["min"] == 1130
    assert summary["totals"]["max"] == 1520
    assert summary["guide_alignment"]["guide_aligned_count"] == 2
    assert summary["itinerary_costs"]["daily"][0]["attraction_cost"] == 100
    assert summary["hotel_context"]["recommended_areas"] == ["Huangpu"]
