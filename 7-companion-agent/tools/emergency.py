from __future__ import annotations

from typing import Any

from config import Settings
from tools.amap import get_route, retrieve_candidates


SCENE_KEYWORDS = {
    "mobility": ["走不动", "走不动了", "累了", "有点累", "需要休息", "体力不支"],
    "medical": ["受伤", "摔倒", "腿疼", "脚疼", "不舒服", "头晕", "疼", "外伤"],
    "toilet": ["尿急", "厕所", "卫生间", "母婴室"],
    "power": ["没电", "充电", "联系同伴", "手机关机"],
    "network": ["网吧", "上网", "网络", "wifi"],
    "help": ["走散", "迷路", "求助", "保安", "派出所"],
    "evacuate": ["赶时间", "撤离", "回酒店", "离开", "打车"],
}

SCENE_QUERIES = {
    "mobility": ["休息区", "游客中心", "出口", "打车点"],
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
    query_results: dict[str, dict[str, Any]] = {}

    for keyword in SCENE_QUERIES.get(scene, SCENE_QUERIES["help"]):
        query = f"{location_name} {keyword}"
        candidates = retrieve_candidates(
            query=query,
            city=city,
            current_location=location,
            settings=settings,
            limit=3,
        )
        if not candidates:
            continue

        best = candidates[0]
        query_results[keyword] = best
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

    evacuation_route: dict[str, Any] | None = None
    if base_location and base_location.get("lat") and base_location.get("lon"):
        try:
            route = get_route(location, base_location, mode="driving", settings=settings)
            evacuation_route = route
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

    safety_notes: list[str] = []
    if scene == "mobility":
        safety_notes.append("如果只是体力不支，优先休息、减少步行，并尽快决定是否回撤。")
    elif scene == "medical":
        safety_notes.append("如有明显外伤、剧烈疼痛或意识异常，应优先线下求助。")
    elif scene == "toilet":
        safety_notes.append("优先前往游客中心、商场或交通枢纽，命中率通常高于景区内部设施搜索。")
    else:
        safety_notes.append("如地图候选不可靠，优先找游客中心、保安亭或最近出口。")

    immediate_action = _build_immediate_action(scene, query_results)
    evacuation_plan = _build_evacuation_plan(scene, query_results, evacuation_route, base_location)
    group_split_plan = _build_group_split_plan(scene)

    return {
        "scene": scene,
        "primary_actions": primary_actions,
        "backup_actions": backup_actions,
        "safety_notes": safety_notes,
        "warnings": warnings,
        "immediate_action": immediate_action,
        "evacuation_plan": evacuation_plan,
        "group_split_plan": group_split_plan,
    }


def _build_immediate_action(scene: str, query_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if scene == "mobility":
        rest = query_results.get("休息区") or query_results.get("游客中心") or query_results.get("出口")
        if rest:
            return {
                "title": "立即动作",
                "summary": f"先停止继续游览，优先去 `{rest.get('name', '')}` 坐下休息，减少继续步行。",
                "reason": "体力不支时，先休息比继续找医疗点更合理。",
            }
        return {
            "title": "立即动作",
            "summary": "先原地坐下休息，不要继续走动，优先联系同行人靠拢。",
            "reason": "当前未命中可靠休息点。",
        }

    if scene == "medical":
        medical = query_results.get("医务室") or query_results.get("医院") or query_results.get("药店")
        if medical:
            return {
                "title": "立即动作",
                "summary": f"先去 `{medical.get('name', '')}` 处理当前不适或外伤。",
                "reason": "医疗场景下，先做线下处置比继续移动更重要。",
            }
    return {
        "title": "立即动作",
        "summary": "先停止继续游览，优先找最近游客中心、保安亭或出口。",
        "reason": "先稳住现场，再决定下一步。",
    }


def _build_evacuation_plan(
    scene: str,
    query_results: dict[str, dict[str, Any]],
    evacuation_route: dict[str, Any] | None,
    base_location: dict[str, Any] | None,
) -> dict[str, Any]:
    exit_point = query_results.get("出口") or query_results.get("打车点") or query_results.get("游客中心")
    if evacuation_route and base_location:
        return {
            "title": "回撤方案",
            "summary": (
                f"如果休息后仍无法继续，就从 `{exit_point.get('name', '最近出口') if exit_point else '最近出口'}` "
                f"回撤，直接返回 `{base_location.get('name') or base_location.get('address') or '集合点'}`，"
                f"预计约 {evacuation_route.get('duration_min', '?')} 分钟。"
            ),
            "reason": "当前场景下，及时结束行程通常比强撑更稳。",
        }

    if scene == "mobility":
        return {
            "title": "回撤方案",
            "summary": "如果老人休息 10-15 分钟后仍明显走不动，就不要继续逛，优先从最近出口离开并打车回酒店。",
            "reason": "体力恢复不确定时，应尽早止损。",
        }

    return {
        "title": "回撤方案",
        "summary": "如果现场情况没有缓解，应优先离开景区，转向更稳妥的线下资源。",
        "reason": "把场景从景区内部转到更稳定的外部环境更安全。",
    }


def _build_group_split_plan(scene: str) -> dict[str, Any]:
    if scene == "mobility":
        return {
            "title": "同行人分工",
            "summary": "由一名同行者陪同老人休息，另一名同行者去确认出口或打车点，其余人不要分散太远。",
            "reason": "先把“陪同”和“找路/叫车”拆开，效率更高。",
        }

    if scene == "medical":
        return {
            "title": "同行人分工",
            "summary": "由一名同行者陪同处理不适，另一名同行者负责联系车或更完整的医疗资源。",
            "reason": "医疗场景中，分工能减少慌乱。",
        }

    return {
        "title": "同行人分工",
        "summary": "先让一名同行者陪同当事人，其他人就近等待，不要继续分散行动。",
        "reason": "应急场景下先收拢队伍。",
    }
