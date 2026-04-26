from __future__ import annotations

from typing import Any


KNOWN_POIS_BY_CITY: dict[str, list[str]] = {
    "北京": [
        "天安门广场", "天安门", "颐和园", "故宫博物院", "故宫",
        "国家博物馆", "中国美术馆", "王府井", "天坛", "景山公园",
        "圆明园", "鸟巢", "水立方", "南锣鼓巷", "什刹海", "雍和宫",
        "国家大剧院", "长城", "慕田峪长城", "首都博物馆",
    ],
    "成都": [
        "大熊猫繁育研究基地", "宽窄巷子", "人民公园", "锦里古街",
        "武侯祠", "杜甫草堂", "金沙遗址博物馆", "太古里",
        "春熙路", "东郊记忆", "玉林路", "成都博物馆",
    ],
    "重庆": [
        "洪崖洞", "解放碑", "三峡博物馆", "朝天门广场",
        "长江索道", "磁器口古镇", "南山景区", "来福士",
        "弹子石老街", "人民大礼堂", "李子坝站",
    ],
    "广州": [
        "广州塔", "永庆坊", "沙面岛", "陈家祠", "越秀公园",
        "北京路步行街", "长隆欢乐世界", "广东省博物馆",
        "广州大剧院", "西关大屋", "珠江新城", "海心沙岛",
    ],
    "香港": [
        "太平山顶", "山顶缆车", "中环", "星光大道", "尖沙咀海滨",
        "大馆", "PMQ元创方", "M+博物馆", "庙街夜市",
        "维多利亚港", "香港迪士尼乐园", "西九龙文化区",
    ],
    "南京": [
        "南京博物院", "夫子庙", "老门东", "总统府",
        "中山陵", "南京城墙", "玄武湖公园", "侵华日军南京大屠杀遇难同胞纪念馆",
        "明孝陵", "秦淮河", "1912街区",
    ],
    "上海": [
        "外滩", "豫园", "武康路", "上海自然博物馆",
        "新天地", "东方明珠", "田子坊", "法租界",
        "上海博物馆", "南京路步行街", "西岸博物馆", "静安寺",
    ],
    "深圳": [
        "深圳湾公园", "华侨城创意文化园", "平安金融中心",
        "海上世界文化艺术中心", "深圳博物馆", "世界之窗",
        "市民中心", "东门步行街", "大鹏古城", "南头古城",
    ],
    "厦门": [
        "鼓浪屿", "环岛路", "中山路步行街", "沙坡尾",
        "日光岩", "菽庄花园", "南普陀寺", "厦门大学",
        "集美学村", "白城沙滩", "厦门植物园", "曾厝垵",
    ],
    "西安": [
        "西安城墙", "陕西历史博物馆", "大雁塔", "回民街",
        "兵马俑", "钟楼", "鼓楼", "大唐芙蓉园",
        "大明宫遗址公园", "永兴坊", "小雁塔", "曲江池遗址公园",
    ],
}

# Flat set for fast membership checks regardless of city
_ALL_KNOWN_POIS: set[str] = {poi for pois in KNOWN_POIS_BY_CITY.values() for poi in pois}


def get_known_pois(city: str) -> list[str]:
    """Return known POI names for a city, falling back to all cities if not found."""
    for key, pois in KNOWN_POIS_BY_CITY.items():
        if key in city or city in key:
            return pois
    return list(_ALL_KNOWN_POIS)


def classify_intent(text: str) -> str:
    lowered = text.strip().lower()
    if any(token in lowered for token in ["下雨", "关闭", "换吗", "能换", "排队", "不想去了", "淋雨"]):
        return "replan"
    if any(token in lowered for token in ["来得及", "时间够吗", "赶得上", "最晚几点"]):
        return "coordinate"
    if any(token in lowered for token in ["腿疼", "走不动", "受伤", "尿急", "网吧", "迷路", "求助", "回酒店"]):
        return "emergency"
    return "search"


def _extract_food_constraints(text: str) -> list[str]:
    found: list[str] = []
    for token in ["不吃辣", "不喜欢北京菜", "清淡", "不要北京菜", "不吃海鲜", "素食", "不吃牛肉", "不吃猪肉"]:
        if token in text and token not in found:
            found.append(token)
    return found


def _extract_budget_level(text: str) -> str:
    if any(token in text for token in ["预算高", "预算高一点", "高预算", "预算不是问题", "贵一点也行"]):
        return "high"
    if any(token in text for token in ["预算低", "便宜点", "省钱", "低预算"]):
        return "low"
    if any(token in text for token in ["预算中等", "适中", "一般预算"]):
        return "medium"
    return ""


def _extract_avoid_pois(text: str, city: str = "") -> list[str]:
    avoid: list[str] = []
    negative_markers = ["不想去", "不去", "不想逛", "不想淋雨", "不考虑"]
    if not any(marker in text for marker in negative_markers):
        return avoid
    known_pois = get_known_pois(city)
    for poi_name in known_pois:
        if poi_name in text and poi_name not in avoid:
            avoid.append(poi_name)
    return avoid


def _extract_party_updates(text: str) -> dict[str, int]:
    updates: dict[str, int] = {}
    if any(token in text for token in ["老人", "长辈", "爸妈"]):
        updates["elderly"] = 1
    if any(token in text for token in ["小孩", "孩子", "亲子", "娃"]):
        updates["children"] = 1
    return updates


def _extract_mobility_risk(text: str) -> str:
    if any(token in text for token in ["走不动", "腿疼", "受伤", "摔倒", "头晕", "不舒服"]):
        return "high"
    if any(token in text for token in ["有点累", "累了", "老人", "带小孩"]):
        return "medium"
    return "normal"


def _extract_current_goal(text: str, intent: str) -> str:
    if intent == "search":
        if any(token in text for token in ["午饭", "吃饭", "餐厅", "找个吃饭的"]):
            return "meal"
        return "search_nearby"
    if intent == "coordinate":
        return "time_coordination"
    if intent == "replan":
        return "replan_today"
    if intent == "emergency":
        return "emergency_support"
    return ""


def extract_constraints(text: str, previous_state: dict[str, Any] | None = None) -> dict[str, Any]:
    previous_state = previous_state or {}
    city = previous_state.get("city", "")
    intent = classify_intent(text)

    food_constraints = list(previous_state.get("food_constraints", []))
    for constraint in _extract_food_constraints(text):
        if constraint not in food_constraints:
            food_constraints.append(constraint)

    avoid_pois = list(previous_state.get("avoid_pois", []))
    for poi_name in _extract_avoid_pois(text, city=city):
        if poi_name not in avoid_pois:
            avoid_pois.append(poi_name)

    party_updates = _extract_party_updates(text)
    current_party = dict(previous_state.get("party", {"adults": 2, "elderly": 0, "children": 0}))
    for key, value in party_updates.items():
        current_party[key] = max(int(current_party.get(key, 0) or 0), value)

    prefer_indoor = bool(previous_state.get("prefer_indoor", False))
    if any(token in text for token in ["下雨", "淋雨", "室内", "别淋雨"]):
        prefer_indoor = True

    weather_preference = previous_state.get("weather_preference", "")
    if prefer_indoor:
        weather_preference = "indoor_preferred"

    replan_reason = previous_state.get("replan_reason", "")
    if "下雨" in text or "淋雨" in text:
        replan_reason = "rain"

    budget_level = _extract_budget_level(text) or previous_state.get("budget_level", "")
    mobility_risk = _extract_mobility_risk(text)
    if previous_state.get("mobility_risk") == "high":
        mobility_risk = "high"

    return {
        "intent": intent,
        "current_goal": _extract_current_goal(text, intent),
        "avoid_pois": avoid_pois,
        "prefer_indoor": prefer_indoor,
        "party": current_party,
        "budget_level": budget_level,
        "food_constraints": food_constraints,
        "mobility_risk": mobility_risk,
        "weather_preference": weather_preference,
        "replan_reason": replan_reason,
    }
