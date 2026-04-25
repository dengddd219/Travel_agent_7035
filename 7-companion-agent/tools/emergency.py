from __future__ import annotations

from typing import Any

from config import Settings
from tools.amap import get_route, retrieve_candidates


SCENE_KEYWORDS = {
    "medical": ["受伤", "摔倒", "腿疼", "脚疼", "不舒服", "头晕", "疼", "走不动"],
    "toilet": ["尿急", "厕所", "卫生间", "母婴室"],
    "power": ["没电", "充电", "联系同伴", "手机关机"],
    "network": ["网吧", "上网", "网络", "wifi"],
    "help": ["走散", "迷路", "求助", "保安", "派出所"],
    "evacuate": ["赶时间", "撤离", "回酒店", "离开", "打车"],
}

SCENE_QUERIES = {
    "medical": ["医务室", "医院", "药店", "休息区", "出口"],
    "toilet": ["卫生间", "厕所", "母婴室", "游客中心"],
    "power": ["充电宝", "便利店", "咖啡店", "服务台"],
    "network": ["网吧", "咖啡店", "营业厅", "商场"],
    "help": ["游客中心", "保安亭", "派出所", "地铁站"],
    "evacuate": ["出口", "地铁站", "打车点", "车站"],
}


def classify_emergency_scene(text: str) -> str:
    lowered = text.strip().lower()
    for scene, keywords in SCENE_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return scene
    return "help"


def resolve_emergency_resources(
    scene: str,
    location: dict[str, Any],
    base_location: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or Settings.from_env()
    scene = scene or "help"
    city = location.get("city") or settings.default_city
    location_name = location.get("name") or location.get("address") or city
    primary_actions: list[dict[str, Any]] = []
    backup_actions: list[dict[str, Any]] = []
    warnings: list[str] = []

    for keyword in SCENE_QUERIES.get(scene, SCENE_QUERIES["help"]):
        query = f"{location_name} {keyword}"
        candidates = retrieve_candidates(query=query, city=city, current_location=location, settings=settings, limit=3)
        if not candidates:
            continue
        best = candidates[0]
        action = {
            "action_type": keyword,
            "name": best.get("name", ""),
            "address": best.get("address", ""),
            "distance_m": best.get("distance_m"),
            "phone": best.get("phone", ""),
        }
        if len(primary_actions) < 2:
            primary_actions.append(action)
        elif len(backup_actions) < 3:
            backup_actions.append(action)

    if base_location and base_location.get("lat") and base_location.get("lon"):
        try:
            route = get_route(location, base_location, mode="driving", settings=settings)
            primary_actions.append(
                {
                    "action_type": "return_to_base",
                    "name": base_location.get("name") or base_location.get("address") or "集合点",
                    "distance_m": route.get("distance_m"),
                    "duration_min": route.get("duration_min"),
                    "instruction": route.get("instruction"),
                }
            )
        except Exception as exc:
            warnings.append(f"回撤路线计算失败: {exc}")

    if not primary_actions:
        warnings.append("地图数据不足，建议优先前往最近出口、游客中心或拨打官方求助电话。")

    safety_notes = []
    if scene == "medical":
        safety_notes.append("如有明显外伤、剧烈疼痛或意识异常，应优先线下求助。")
    elif scene == "toilet":
        safety_notes.append("优先前往游客中心、商场或交通枢纽，命中率通常高于景区内部设施搜索。")
    else:
        safety_notes.append("如地图候选不可靠，优先找游客中心、保安亭或最近出口。")

    return {
        "scene": scene,
        "primary_actions": primary_actions,
        "backup_actions": backup_actions,
        "safety_notes": safety_notes,
        "warnings": warnings,
    }
