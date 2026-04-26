from __future__ import annotations

from config import Settings

# Static data for fields Amap does not provide: accessible, recommended_duration_min, tips.
# open_hours and ticket_price are fetched live from Amap and override these values when available.
_STATIC_DETAILS: dict[str, dict] = {
    # ── 北京 ──────────────────────────────────────────────────────────────
    "天安门": {
        "accessible": True,
        "recommended_duration_min": 90,
        "tips": ["广场区域步行量大", "如遇恶劣天气应优先调整为室内点位"],
    },
    "天安门广场": {
        "accessible": True,
        "recommended_duration_min": 60,
        "tips": ["安检和步行距离较长", "下雨或烈日体验会明显下降"],
    },
    "故宫博物院": {
        "accessible": False,
        "recommended_duration_min": 240,
        "tips": ["院内步行量大", "建议提前规划出口", "高峰期排队明显"],
    },
    "故宫": {
        "accessible": False,
        "recommended_duration_min": 240,
        "tips": ["院内步行量大", "建议提前规划出口", "高峰期排队明显"],
    },
    "颐和园": {
        "accessible": True,
        "recommended_duration_min": 180,
        "tips": ["优先从东宫门进入", "老人建议控制步行距离", "雨天优先长廊区域"],
    },
    "国家博物馆": {
        "accessible": True,
        "recommended_duration_min": 120,
        "tips": ["雨天替代天安门广场较合适", "需要预留安检时间"],
    },
    "天坛": {
        "accessible": True,
        "recommended_duration_min": 120,
        "tips": ["园区较大，建议从南门入", "老人步行量较大"],
    },
    "慕田峪长城": {
        "accessible": False,
        "recommended_duration_min": 180,
        "tips": ["可乘缆车减少步行", "下雨天台阶湿滑，老人慎行"],
    },
    "南锣鼓巷": {
        "accessible": True,
        "recommended_duration_min": 60,
        "tips": ["周末人流量大", "适合步行慢逛"],
    },
    "雍和宫": {
        "accessible": True,
        "recommended_duration_min": 90,
        "tips": ["节假日排队较长", "内部台阶较多"],
    },

    # ── 成都 ──────────────────────────────────────────────────────────────
    "大熊猫繁育研究基地": {
        "accessible": True,
        "recommended_duration_min": 180,
        "tips": ["上午10点前熊猫最活跃", "园区较大建议租电瓶车", "雨天熊猫仍正常展出"],
    },
    "宽窄巷子": {
        "accessible": True,
        "recommended_duration_min": 90,
        "tips": ["白天人多，傍晚氛围更好", "适合边逛边吃小吃"],
    },
    "武侯祠": {
        "accessible": True,
        "recommended_duration_min": 90,
        "tips": ["与锦里步行可达，可连游", "历史文化展区较多"],
    },
    "锦里古街": {
        "accessible": True,
        "recommended_duration_min": 60,
        "tips": ["夜晚灯光效果佳", "与武侯祠相邻"],
    },
    "杜甫草堂": {
        "accessible": True,
        "recommended_duration_min": 90,
        "tips": ["园林环境好，雨天也宜游", "老人步行量适中"],
    },

    # ── 重庆 ──────────────────────────────────────────────────────────────
    "洪崖洞": {
        "accessible": False,
        "recommended_duration_min": 60,
        "tips": ["夜景最佳，建议傍晚后前往", "台阶多，老人谨慎"],
    },
    "磁器口古镇": {
        "accessible": True,
        "recommended_duration_min": 90,
        "tips": ["周末人流量大", "小吃集中在主街两侧"],
    },
    "解放碑": {
        "accessible": True,
        "recommended_duration_min": 60,
        "tips": ["商圈步行友好", "地铁直达"],
    },
    "三峡博物馆": {
        "accessible": True,
        "recommended_duration_min": 120,
        "tips": ["免费入场，需提前预约", "雨天室内游览佳选"],
    },
    "长江索道": {
        "accessible": True,
        "recommended_duration_min": 30,
        "tips": ["高峰期排队时间较长", "两岸都有站点"],
    },

    # ── 广州 ──────────────────────────────────────────────────────────────
    "广州塔": {
        "accessible": True,
        "recommended_duration_min": 90,
        "tips": ["夜景最佳，建议日落前到达", "顶层风大"],
    },
    "永庆坊": {
        "accessible": True,
        "recommended_duration_min": 60,
        "tips": ["适合步行慢逛", "周边有正宗粤式茶楼"],
    },
    "沙面岛": {
        "accessible": True,
        "recommended_duration_min": 90,
        "tips": ["欧式建筑风格，适合拍照", "岛内步行即可"],
    },
    "陈家祠": {
        "accessible": True,
        "recommended_duration_min": 90,
        "tips": ["岭南建筑代表，雨天室内游览", "需购票"],
    },
    "广东省博物馆": {
        "accessible": True,
        "recommended_duration_min": 120,
        "tips": ["免费但需预约", "雨天首选室内景点"],
    },

    # ── 香港 ──────────────────────────────────────────────────────────────
    "太平山顶": {
        "accessible": True,
        "recommended_duration_min": 90,
        "tips": ["雾天能见度低建议查天气再去", "缆车排队较长，可步行登顶"],
    },
    "山顶缆车": {
        "accessible": True,
        "recommended_duration_min": 30,
        "tips": ["高峰期排队30分钟以上", "建议提前网上购票"],
    },
    "星光大道": {
        "accessible": True,
        "recommended_duration_min": 45,
        "tips": ["晚8点有幻彩咏香江灯光秀", "尖沙咀海滨步行可达"],
    },
    "M+博物馆": {
        "accessible": True,
        "recommended_duration_min": 120,
        "tips": ["雨天室内首选", "部分展览需另购票"],
    },
    "大馆": {
        "accessible": True,
        "recommended_duration_min": 90,
        "tips": ["历史建筑改造，免费入场", "雨天室内展览可游览"],
    },

    # ── 南京 ──────────────────────────────────────────────────────────────
    "中山陵": {
        "accessible": False,
        "recommended_duration_min": 120,
        "tips": ["台阶较多，老人建议量力而行", "步行距离较长"],
    },
    "夫子庙": {
        "accessible": True,
        "recommended_duration_min": 90,
        "tips": ["秦淮河夜景佳", "周边小吃丰富"],
    },
    "南京博物院": {
        "accessible": True,
        "recommended_duration_min": 150,
        "tips": ["免费需预约", "雨天室内首选"],
    },
    "侵华日军南京大屠杀遇难同胞纪念馆": {
        "accessible": True,
        "recommended_duration_min": 120,
        "tips": ["免费需预约", "请保持肃静"],
    },
    "明孝陵": {
        "accessible": False,
        "recommended_duration_min": 120,
        "tips": ["景区步行距离较长", "老人建议乘景区车"],
    },

    # ── 上海 ──────────────────────────────────────────────────────────────
    "外滩": {
        "accessible": True,
        "recommended_duration_min": 60,
        "tips": ["夜景最佳", "周末人流量极大"],
    },
    "豫园": {
        "accessible": False,
        "recommended_duration_min": 90,
        "tips": ["台阶多，轮椅不便", "周边小吃街可步行前往"],
    },
    "东方明珠": {
        "accessible": True,
        "recommended_duration_min": 90,
        "tips": ["建议提前网上购票", "雨雾天视野受限"],
    },
    "上海博物馆": {
        "accessible": True,
        "recommended_duration_min": 120,
        "tips": ["免费需预约", "雨天室内首选"],
    },
    "田子坊": {
        "accessible": False,
        "recommended_duration_min": 60,
        "tips": ["弄堂较窄，轮椅不便", "适合步行探索"],
    },

    # ── 深圳 ──────────────────────────────────────────────────────────────
    "深圳湾公园": {
        "accessible": True,
        "recommended_duration_min": 90,
        "tips": ["滨海步道适合散步", "傍晚观景最佳"],
    },
    "华侨城创意文化园": {
        "accessible": True,
        "recommended_duration_min": 90,
        "tips": ["周二闭园", "适合文艺慢逛"],
    },
    "大鹏古城": {
        "accessible": True,
        "recommended_duration_min": 120,
        "tips": ["距市区较远，建议开车或打车", "历史建筑保存完好"],
    },
    "世界之窗": {
        "accessible": True,
        "recommended_duration_min": 180,
        "tips": ["园区较大，建议乘景区车", "有表演需提前查时间"],
    },

    # ── 厦门 ──────────────────────────────────────────────────────────────
    "鼓浪屿": {
        "accessible": False,
        "recommended_duration_min": 240,
        "tips": ["无机动车，全程步行", "老人建议控制游览时间", "轮渡排队高峰较长"],
    },
    "日光岩": {
        "accessible": False,
        "recommended_duration_min": 90,
        "tips": ["台阶较多，老人谨慎", "山顶视野开阔"],
    },
    "南普陀寺": {
        "accessible": True,
        "recommended_duration_min": 60,
        "tips": ["与厦门大学步行可达", "免费入场"],
    },
    "曾厝垵": {
        "accessible": True,
        "recommended_duration_min": 60,
        "tips": ["文艺小吃聚集地", "傍晚氛围最好"],
    },
    "厦门大学": {
        "accessible": True,
        "recommended_duration_min": 90,
        "tips": ["校园内风景优美", "旺季需预约入校"],
    },

    # ── 西安 ──────────────────────────────────────────────────────────────
    "兵马俑": {
        "accessible": True,
        "recommended_duration_min": 180,
        "tips": ["距市区40分钟车程", "人流量大，建议早到", "讲解器或导游增加体验"],
    },
    "西安城墙": {
        "accessible": True,
        "recommended_duration_min": 120,
        "tips": ["可骑车绕城一圈约13公里", "夜晚灯光效果极佳"],
    },
    "回民街": {
        "accessible": True,
        "recommended_duration_min": 90,
        "tips": ["晚上人流量极大", "小吃集中，注意食品卫生"],
    },
    "陕西历史博物馆": {
        "accessible": True,
        "recommended_duration_min": 150,
        "tips": ["免费需提前预约，名额有限", "雨天室内首选"],
    },
    "大雁塔": {
        "accessible": True,
        "recommended_duration_min": 90,
        "tips": ["塔内可登顶", "北广场有音乐喷泉表演"],
    },
    "大唐芙蓉园": {
        "accessible": True,
        "recommended_duration_min": 120,
        "tips": ["夜间有大型灯光秀", "园区较大建议乘电瓶车"],
    },
}


def get_poi_detail(name: str, city: str = "", settings: Settings | None = None) -> dict:
    """Return POI detail, fetching open_hours and ticket_price from Amap when possible.

    Static fallback covers fields Amap does not provide (accessible, duration, tips).
    """
    from tools.amap import fetch_poi_detail_from_amap

    static = _STATIC_DETAILS.get(name, {})
    amap_data = fetch_poi_detail_from_amap(name, city=city, settings=settings)

    open_hours = amap_data.get("open_hours") or ""
    ticket_price = amap_data.get("ticket_price")
    source = amap_data.get("source", "fallback")

    if source == "fallback" and name in _STATIC_DETAILS:
        source = "static"

    return {
        "name": name,
        "open_hours": open_hours,
        "ticket_price": ticket_price,
        "accessible": static.get("accessible"),
        "recommended_duration_min": static.get("recommended_duration_min", 60),
        "tips": static.get("tips", []),
        "source": source,
    }
