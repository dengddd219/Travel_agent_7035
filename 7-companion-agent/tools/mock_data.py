from __future__ import annotations

POI_DETAILS = {
    "天安门": {
        "name": "天安门",
        "open_hours": "全天开放",
        "ticket_price": 0.0,
        "accessible": True,
        "recommended_duration_min": 90,
        "tips": ["广场区域步行量大", "如遇恶劣天气应优先调整为室内点位"],
        "source": "mock",
    },
    "颐和园": {
        "name": "颐和园",
        "open_hours": "06:00-19:00",
        "ticket_price": 30.0,
        "accessible": True,
        "recommended_duration_min": 180,
        "tips": ["优先从东宫门进入", "老人建议控制步行距离", "雨天优先长廊区域"],
        "source": "mock",
    },
    "天安门广场": {
        "name": "天安门广场",
        "open_hours": "全天开放",
        "ticket_price": 0.0,
        "accessible": True,
        "tips": ["安检和步行距离较长", "下雨或烈日体验会明显下降"],
        "source": "mock",
    },
    "故宫博物院": {
        "name": "故宫博物院",
        "open_hours": "08:30-17:00",
        "ticket_price": 60.0,
        "accessible": False,
        "recommended_duration_min": 240,
        "tips": ["院内步行量大", "建议提前规划出口", "高峰期排队明显"],
        "source": "mock",
    },
    "国家博物馆": {
        "name": "国家博物馆",
        "open_hours": "09:00-17:00",
        "ticket_price": 0.0,
        "accessible": True,
        "recommended_duration_min": 120,
        "tips": ["雨天替代天安门广场较合适", "需要预留安检时间"],
        "source": "mock",
    },
}


def get_poi_detail(name: str) -> dict:
    return POI_DETAILS.get(
        name,
        {
            "name": name,
            "open_hours": "",
            "ticket_price": None,
            "accessible": None,
            "recommended_duration_min": 60,
            "tips": [],
            "source": "mock",
        },
    )
