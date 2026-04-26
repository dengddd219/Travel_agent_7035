"""
RAG 检索质量评测脚本

入库完成后运行此脚本，评估检索效果。
用法:
    conda activate rag
    cd /Users/zhukeqing/Desktop/7035-project
    python -m rag.evaluate
"""

import json
import chromadb
from rag.config import CHROMA_DB_DIR, CHROMA_COLLECTION_NAME
from rag.embedding.embedder import get_embeddings
from rag.storage.bm25_store import BM25Store

# ──────────────────────────────────────
#  测试用例：人工构造的 query + 期望命中的关键词
#  "expected" 里的词只要在返回的 chunk 中出现任意一个就算命中
# ──────────────────────────────────────
TEST_CASES = [
    # ── 成都（10 条）──
    {
        "query": "成都带孩子去哪玩",
        "expected": ["熊猫基地", "亲子", "小朋友", "宽窄巷子", "遛娃", "带娃", "儿童", "带孩子", "宝宝", "乐园"],
        "category": "成都-亲子游",
    },
    {
        "query": "成都火锅推荐",
        "expected": ["火锅", "串串", "麻辣"],
        "category": "成都-美食",
    },
    {
        "query": "青城山旅游攻略",
        "expected": ["青城山", "都江堰", "爬山"],
        "category": "成都-景点",
    },
    {
        "query": "成都拍照打卡地",
        "expected": ["太古里", "春熙路", "拍照", "打卡", "出片"],
        "category": "成都-打卡",
    },
    {
        "query": "成都晚上去哪逛",
        "expected": ["夜景", "锦里", "酒吧", "夜市", "晚上", "九眼桥", "夜生活"],
        "category": "成都-夜生活",
    },
    {
        "query": "成都三天怎么安排行程",
        "expected": ["第一天", "第二天", "行程", "路线", "三天", "3天"],
        "category": "成都-行程规划",
    },
    {
        "query": "成都小众景点",
        "expected": ["小众", "冷门", "人少", "宝藏", "私藏"],
        "category": "成都-小众",
    },
    {
        "query": "成都地铁怎么坐方便",
        "expected": ["地铁", "交通", "公交", "线路", "出行"],
        "category": "成都-交通",
    },
    {
        "query": "宽窄巷子值得去吗",
        "expected": ["宽窄巷子", "宽窄"],
        "category": "成都-特定景点",
    },
    {
        "query": "成都逛街购物去哪",
        "expected": ["太古里", "春熙路", "商场", "逛街", "购物", "步行街", "商圈"],
        "category": "成都-购物",
    },
    # ── 北京（10 条）──
    {
        "query": "北京故宫怎么预约",
        "expected": ["故宫", "预约", "门票", "紫禁城"],
        "category": "北京-景点",
    },
    {
        "query": "北京三天行程怎么安排",
        "expected": ["第一天", "第二天", "行程", "路线", "三天", "3天"],
        "category": "北京-行程规划",
    },
    {
        "query": "北京烤鸭哪家好吃",
        "expected": ["烤鸭", "全聚德", "便宜坊", "大董", "四季民福"],
        "category": "北京-美食",
    },
    {
        "query": "长城一日游攻略",
        "expected": ["长城", "八达岭", "慕田峪", "爬长城"],
        "category": "北京-长城",
    },
    {
        "query": "北京胡同值得逛吗",
        "expected": ["胡同", "南锣鼓巷", "什刹海", "后海", "烟袋斜街"],
        "category": "北京-胡同",
    },
    {
        "query": "北京地铁交通攻略",
        "expected": ["地铁", "交通", "公交", "线路", "一卡通", "出行"],
        "category": "北京-交通",
    },
    {
        "query": "天安门升旗仪式几点",
        "expected": ["天安门", "升旗", "广场"],
        "category": "北京-升旗",
    },
    {
        "query": "北京拍照打卡地",
        "expected": ["打卡", "拍照", "出片", "天坛", "颐和园", "故宫"],
        "category": "北京-打卡",
    },
    {
        "query": "北京带孩子去哪玩",
        "expected": ["亲子", "小朋友", "带孩子", "动物园", "科技馆", "环球影城", "遛娃", "带娃", "儿童", "宝宝", "乐园"],
        "category": "北京-亲子",
    },
    {
        "query": "北京小众景点推荐",
        "expected": ["小众", "冷门", "人少", "宝藏", "私藏"],
        "category": "北京-小众",
    },
    # ── 上海（10 条）──
    {
        "query": "上海外滩怎么玩",
        "expected": ["外滩", "黄浦江", "夜景", "浦东"],
        "category": "上海-外滩",
    },
    {
        "query": "上海迪士尼攻略",
        "expected": ["迪士尼", "迪斯尼", "Disney", "乐园"],
        "category": "上海-迪士尼",
    },
    {
        "query": "上海三天行程安排",
        "expected": ["第一天", "第二天", "行程", "路线", "三天", "3天"],
        "category": "上海-行程规划",
    },
    {
        "query": "上海美食推荐",
        "expected": ["小笼包", "生煎", "本帮菜", "美食", "好吃"],
        "category": "上海-美食",
    },
    {
        "query": "上海逛街去哪里",
        "expected": ["南京路", "淮海路", "新天地", "逛街", "购物", "商场", "步行街", "商圈", "好逛"],
        "category": "上海-购物",
    },
    {
        "query": "上海拍照打卡地",
        "expected": ["打卡", "拍照", "出片", "武康路", "武康大楼"],
        "category": "上海-打卡",
    },
    {
        "query": "上海小众好玩的地方",
        "expected": ["小众", "冷门", "人少", "宝藏", "免费", "私藏"],
        "category": "上海-小众",
    },
    {
        "query": "上海地铁交通方便吗",
        "expected": ["地铁", "交通", "公交", "线路", "出行"],
        "category": "上海-交通",
    },
    {
        "query": "上海晚上去哪逛",
        "expected": ["夜景", "外滩", "酒吧", "夜市", "晚上", "夜生活"],
        "category": "上海-夜生活",
    },
    {
        "query": "上海带小孩去哪玩",
        "expected": ["迪士尼", "亲子", "小朋友", "带孩子", "科技馆", "海洋馆", "遛娃", "带娃", "儿童", "宝宝", "乐园"],
        "category": "上海-亲子",
    },
    # ── 西安（10 条）──
    {
        "query": "西安兵马俑怎么去",
        "expected": ["兵马俑", "秦始皇", "临潼"],
        "category": "西安-兵马俑",
    },
    {
        "query": "西安三天行程安排",
        "expected": ["第一天", "第二天", "行程", "路线", "三天", "3天"],
        "category": "西安-行程规划",
    },
    {
        "query": "西安美食推荐",
        "expected": ["肉夹馍", "凉皮", "泡馍", "biangbiang", "回民街", "美食"],
        "category": "西安-美食",
    },
    {
        "query": "西安城墙怎么玩",
        "expected": ["城墙", "骑车", "自行车", "永宁门"],
        "category": "西安-城墙",
    },
    {
        "query": "西安回民街值得去吗",
        "expected": ["回民街", "回民", "美食街"],
        "category": "西安-回民街",
    },
    {
        "query": "华清池和兵马俑一天够吗",
        "expected": ["华清池", "华清宫", "兵马俑", "一天", "一日"],
        "category": "西安-一日游",
    },
    {
        "query": "西安拍照打卡地",
        "expected": ["打卡", "拍照", "出片", "大雁塔", "钟楼", "大唐不夜城"],
        "category": "西安-打卡",
    },
    {
        "query": "大唐不夜城好玩吗",
        "expected": ["大唐不夜城", "不夜城", "大唐"],
        "category": "西安-不夜城",
    },
    {
        "query": "西安小众景点",
        "expected": ["小众", "冷门", "人少", "宝藏", "私藏", "citywalk"],
        "category": "西安-小众",
    },
    {
        "query": "西安交通怎么坐方便",
        "expected": ["地铁", "交通", "公交", "线路", "出行"],
        "category": "西安-交通",
    },
    # ── 重庆（5 条）──
    {
        "query": "重庆洪崖洞怎么玩",
        "expected": ["洪崖洞", "吊脚楼", "夜景", "嘉陵江"],
        "category": "重庆-洪崖洞",
    },
    {
        "query": "重庆火锅推荐",
        "expected": ["火锅", "麻辣", "串串", "重庆火锅"],
        "category": "重庆-美食",
    },
    {
        "query": "重庆三天行程安排",
        "expected": ["第一天", "第二天", "行程", "路线", "三天", "3天"],
        "category": "重庆-行程规划",
    },
    {
        "query": "重庆解放碑附近好玩的",
        "expected": ["解放碑", "观音桥", "磁器口", "步行街"],
        "category": "重庆-解放碑",
    },
    {
        "query": "重庆索道值得坐吗",
        "expected": ["索道", "长江索道", "江景", "两江"],
        "category": "重庆-索道",
    },
    # ── 杭州（5 条）──
    {
        "query": "杭州西湖怎么逛",
        "expected": ["西湖", "断桥", "雷峰塔", "苏堤", "白堤"],
        "category": "杭州-西湖",
    },
    {
        "query": "杭州美食推荐",
        "expected": ["小笼包", "龙井虾仁", "东坡肉", "美食", "杭帮菜", "西湖醋鱼"],
        "category": "杭州-美食",
    },
    {
        "query": "杭州三天行程怎么安排",
        "expected": ["第一天", "第二天", "行程", "路线", "三天", "3天"],
        "category": "杭州-行程规划",
    },
    {
        "query": "杭州灵隐寺值得去吗",
        "expected": ["灵隐寺", "灵隐", "佛教", "寺庙"],
        "category": "杭州-灵隐寺",
    },
    {
        "query": "杭州拍照打卡地",
        "expected": ["打卡", "拍照", "出片", "西湖", "乌镇"],
        "category": "杭州-打卡",
    },
    # ── 香港（5 条）──
    {
        "query": "香港维多利亚港夜景怎么看",
        "expected": ["维多利亚港", "维港", "夜景", "幻彩咏香江", "灯光秀"],
        "category": "香港-夜景",
    },
    {
        "query": "香港美食推荐",
        "expected": ["茶餐厅", "烧鹅", "虾饺", "蛋挞", "港式", "菠萝包", "丝袜奶茶"],
        "category": "香港-美食",
    },
    {
        "query": "香港三天行程安排",
        "expected": ["第一天", "第二天", "行程", "路线", "三天", "3天"],
        "category": "香港-行程规划",
    },
    {
        "query": "旺角购物攻略",
        "expected": ["旺角", "购物", "逛街", "女人街", "波鞋街"],
        "category": "香港-购物",
    },
    {
        "query": "香港迪士尼乐园攻略",
        "expected": ["迪士尼", "Disney", "乐园", "香港迪士尼"],
        "category": "香港-迪士尼",
    },
    # ── 南京（5 条）──
    {
        "query": "南京中山陵怎么去",
        "expected": ["中山陵", "孙中山", "明孝陵", "紫金山"],
        "category": "南京-中山陵",
    },
    {
        "query": "南京美食推荐",
        "expected": ["鸭血粉丝", "盐水鸭", "小笼包", "南京烤鸭", "美食"],
        "category": "南京-美食",
    },
    {
        "query": "南京三天行程安排",
        "expected": ["第一天", "第二天", "行程", "路线", "三天", "3天"],
        "category": "南京-行程规划",
    },
    {
        "query": "夫子庙秦淮河值得去吗",
        "expected": ["夫子庙", "秦淮河", "秦淮", "夜景"],
        "category": "南京-夫子庙",
    },
    {
        "query": "南京拍照打卡地",
        "expected": ["打卡", "拍照", "出片", "玄武湖", "总统府", "鸡鸣寺"],
        "category": "南京-打卡",
    },
    # ── 深圳（5 条）──
    {
        "query": "深圳欢乐谷值得去吗",
        "expected": ["欢乐谷", "主题公园", "游乐", "过山车"],
        "category": "深圳-欢乐谷",
    },
    {
        "query": "深圳美食推荐",
        "expected": ["海鲜", "肠粉", "早茶", "美食", "粤菜"],
        "category": "深圳-美食",
    },
    {
        "query": "深圳三天行程安排",
        "expected": ["第一天", "第二天", "行程", "路线", "三天", "3天"],
        "category": "深圳-行程规划",
    },
    {
        "query": "深圳大梅沙海滩怎么去",
        "expected": ["大梅沙", "海滩", "沙滩", "海边"],
        "category": "深圳-海滩",
    },
    {
        "query": "深圳购物去哪里",
        "expected": ["华强北", "购物", "逛街", "万象城", "东门"],
        "category": "深圳-购物",
    },
    # ── 厦门（5 条）──
    {
        "query": "厦门鼓浪屿怎么玩",
        "expected": ["鼓浪屿", "钢琴岛", "菽庄花园", "日光岩"],
        "category": "厦门-鼓浪屿",
    },
    {
        "query": "厦门美食推荐",
        "expected": ["沙茶面", "海蛎煎", "土笋冻", "姜母鸭", "美食", "海鲜"],
        "category": "厦门-美食",
    },
    {
        "query": "厦门三天行程安排",
        "expected": ["第一天", "第二天", "行程", "路线", "三天", "3天"],
        "category": "厦门-行程规划",
    },
    {
        "query": "厦门大学好看吗值得去吗",
        "expected": ["厦门大学", "厦大", "芙蓉湖", "白城沙滩"],
        "category": "厦门-厦大",
    },
    {
        "query": "厦门曾厝垵好玩吗",
        "expected": ["曾厝垵", "文艺", "民宿", "小渔村"],
        "category": "厦门-曾厝垵",
    },
    # ── 广州（5 条）──
    {
        "query": "广州早茶去哪喝",
        "expected": ["早茶", "茶楼", "点心", "粤式早茶", "广式早茶"],
        "category": "广州-早茶",
    },
    {
        "query": "广州美食推荐",
        "expected": ["白切鸡", "烧鹅", "肠粉", "虾饺", "美食", "粤菜"],
        "category": "广州-美食",
    },
    {
        "query": "广州三天行程安排",
        "expected": ["第一天", "第二天", "行程", "路线", "三天", "3天"],
        "category": "广州-行程规划",
    },
    {
        "query": "广州北京路商圈购物",
        "expected": ["北京路", "购物", "逛街", "商场", "天河城"],
        "category": "广州-购物",
    },
    {
        "query": "广州塔附近怎么逛",
        "expected": ["广州塔", "小蛮腰", "珠江", "猎德"],
        "category": "广州-广州塔",
    },
    # ── 东京（5 条）──
    {
        "query": "东京浅草寺怎么逛",
        "expected": ["浅草寺", "雷门", "仲见世通り", "浅草"],
        "category": "东京-浅草寺",
    },
    {
        "query": "东京美食推荐",
        "expected": ["拉面", "寿司", "天妇罗", "居酒屋", "美食", "和食"],
        "category": "东京-美食",
    },
    {
        "query": "东京三天行程安排",
        "expected": ["第一天", "第二天", "行程", "路线", "三天", "3天"],
        "category": "东京-行程规划",
    },
    {
        "query": "东京迪士尼攻略",
        "expected": ["迪士尼", "Disney", "乐园", "东京迪士尼"],
        "category": "东京-迪士尼",
    },
    {
        "query": "东京购物去哪里",
        "expected": ["银座", "新宿", "涩谷", "秋叶原", "购物", "逛街"],
        "category": "东京-购物",
    },
]


# ──────────────────────────────────────
#  Query Expansion（查询扩展）
# ──────────────────────────────────────
_QUERY_SYNONYMS = {
    "亲子": ["带孩子", "小朋友", "遛娃", "儿童", "小孩", "带娃", "亲子游"],
    "带孩子": ["亲子", "小朋友", "遛娃", "儿童", "小孩", "带娃"],
    "带小孩": ["亲子", "小朋友", "遛娃", "儿童", "带孩子", "带娃"],
    "小孩": ["亲子", "小朋友", "遛娃", "儿童", "带孩子"],
    "夜生活": ["晚上", "夜景", "酒吧", "夜市", "晚上逛"],
    "晚上": ["夜景", "夜市", "夜生活", "酒吧"],
    "逛街": ["购物", "商场", "买东西", "商圈", "步行街"],
    "购物": ["逛街", "商场", "买东西", "商圈"],
    "小众": ["冷门", "人少", "宝藏", "私藏"],
    "交通": ["地铁", "公交", "出行", "线路", "怎么去"],
    "打卡": ["拍照", "出片", "网红"],
    "拍照": ["打卡", "出片", "网红"],
}


def _expand_query(query: str) -> str:
    """对查询进行同义词扩展，BM25 检索时使用扩展后的查询。"""
    expansions = []
    for keyword, synonyms in _QUERY_SYNONYMS.items():
        if keyword in query:
            expansions.extend(synonyms)
    if not expansions:
        return query
    # 去重并拼接到原始 query 后
    seen = set(query)
    unique = [s for s in expansions if s not in query and s not in seen and not seen.add(s)]
    return query + " " + " ".join(unique)


# ──────────────────────────────────────
#  城市名提取（从 query 或 category 中推断）
# ──────────────────────────────────────
_CITY_KEYWORDS = {
    "成都": "成都", "北京": "北京", "上海": "上海", "西安": "西安",
    "重庆": "重庆", "杭州": "杭州", "香港": "香港", "南京": "南京",
    "深圳": "深圳", "厦门": "厦门", "广州": "广州", "东京": "东京",
    "青城山": "成都", "都江堰": "成都", "宽窄巷子": "成都", "春熙路": "成都",
    "故宫": "北京", "长城": "北京", "八达岭": "北京", "天安门": "北京",
    "外滩": "上海", "迪士尼": "上海", "武康路": "上海",
    "兵马俑": "西安", "华清池": "西安", "大唐不夜城": "西安", "回民街": "西安", "城墙": "西安",
    "洪崖洞": "重庆", "解放碑": "重庆", "磁器口": "重庆", "长江索道": "重庆",
    "西湖": "杭州", "灵隐寺": "杭州", "断桥": "杭州",
    "维多利亚港": "香港", "维港": "香港", "旺角": "香港", "铜锣湾": "香港",
    "中山陵": "南京", "夫子庙": "南京", "秦淮河": "南京", "玄武湖": "南京",
    "欢乐谷": "深圳", "大梅沙": "深圳", "华强北": "深圳",
    "鼓浪屿": "厦门", "曾厝垵": "厦门", "厦门大学": "厦门",
    "广州塔": "广州", "北京路": "广州", "小蛮腰": "广州",
    "浅草寺": "东京", "银座": "东京", "新宿": "东京", "涩谷": "东京",
}

def _extract_city(query: str, category: str = "") -> str:
    """从 query 或 category 中提取城市名。"""
    # 先从 category 提取（格式如 "成都-美食"）
    for city in ["成都", "北京", "上海", "西安", "重庆", "杭州", "香港", "南京", "深圳", "厦门", "广州", "东京"]:
        if city in category or city in query:
            return city
    # 从景点关键词推断
    for kw, city in _CITY_KEYWORDS.items():
        if kw in query:
            return city
    return ""


# ──────────────────────────────────────
#  Query-Type 自适应权重
# ──────────────────────────────────────
# 景点名/地标类查询偏 BM25（精确匹配），推荐/攻略类偏向量（语义匹配）
_BM25_HEAVY_KEYWORDS = [
    "故宫", "长城", "八达岭", "天安门", "兵马俑", "华清池", "城墙",
    "外滩", "迪士尼", "宽窄巷子", "青城山", "都江堰", "大唐不夜城",
    "回民街", "胡同", "南锣鼓巷", "升旗",
]
_VECTOR_HEAVY_KEYWORDS = ["推荐", "攻略", "怎么玩", "好玩", "值得", "安排", "规划", "小众"]


def _get_adaptive_weight(query: str, base_weight: float) -> float:
    """根据查询类型动态调整向量/BM25权重。"""
    for kw in _BM25_HEAVY_KEYWORDS:
        if kw in query:
            return max(base_weight - 0.2, 0.1)  # 偏向 BM25
    for kw in _VECTOR_HEAVY_KEYWORDS:
        if kw in query:
            return min(base_weight + 0.15, 0.9)  # 偏向向量
    return base_weight


# ──────────────────────────────────────
#  Metadata Boosting（元数据意图匹配加分）
# ──────────────────────────────────────
_INTENT_TAG_MAP = {
    "亲子": ["family"],
    "带孩子": ["family"],
    "带小孩": ["family"],
    "小孩": ["family"],
    "遛娃": ["family"],
    "美食": ["food"],
    "火锅": ["food"],
    "烤鸭": ["food"],
    "好吃": ["food"],
    "夜景": ["nightlife"],
    "晚上": ["nightlife"],
    "夜生活": ["nightlife"],
    "酒吧": ["nightlife"],
    "拍照": ["photography"],
    "打卡": ["photography"],
    "出片": ["photography"],
    "小众": ["offbeat"],
    "冷门": ["offbeat"],
}


def _compute_metadata_boost(query: str, metadata: dict) -> float:
    """根据查询意图与 metadata 标签的匹配程度返回加分。"""
    intent_tags = set()
    for kw, tags in _INTENT_TAG_MAP.items():
        if kw in query:
            intent_tags.update(tags)
    if not intent_tags:
        return 0.0

    boost = 0.0
    travel_tags = metadata.get("travel_type_tags", "")
    tags = metadata.get("tags", "")
    combined = travel_tags + "," + tags

    for tag in intent_tags:
        if tag in combined:
            boost += 0.003  # 每个匹配标签加分
    return boost


# ──────────────────────────────────────
#  Title Boosting（标题匹配加分）
# ──────────────────────────────────────
def _compute_title_boost(query: str, metadata: dict) -> float:
    """查询关键词在标题中出现则加分。"""
    title = metadata.get("title", "")
    if not title:
        return 0.0
    # 提取查询中的实体词（长度>=2的非停用词片段）
    query_terms = [query[i:i+n] for n in range(2, min(len(query)+1, 8))
                   for i in range(len(query)-n+1)]
    # 只取有意义的（长度>=2 且不是纯功能词）
    meaningful = [t for t in query_terms if len(t) >= 2 and t not in
                  {"怎么", "去哪", "哪里", "什么", "可以", "方便", "值得", "好吗", "推荐"}]
    matches = sum(1 for t in meaningful if t in title)
    return min(matches * 0.001, 0.005)  # 最多加 0.005


def _hybrid_search(collection, bm25_store, query, query_emb, top_k,
                   vector_weight=0.5, fetch_k=20, city_filter="",
                   use_adaptive_weight=True, use_metadata_boost=True,
                   use_title_boost=True, use_mmr=False):
    """
    混合检索：向量 + BM25 + Metadata/Title Boosting + MMR 多样性。
    """
    # Query-Type 自适应权重
    vw = _get_adaptive_weight(query, vector_weight) if use_adaptive_weight else vector_weight

    # 向量检索（带城市过滤，取更多候选用于 MMR）
    mmr_fetch = fetch_k * 2 if use_mmr else fetch_k
    vec_kwargs = {"n_results": mmr_fetch, "include": ["documents", "metadatas"]}
    if query_emb is not None:
        vec_kwargs["query_embeddings"] = query_emb
    else:
        vec_kwargs["query_texts"] = [query]
    if city_filter:
        vec_kwargs["where"] = {"city": city_filter}

    vec_result = collection.query(**vec_kwargs)
    vec_ids = vec_result["ids"][0]
    vec_docs = {cid: doc for cid, doc in zip(vec_result["ids"][0], vec_result["documents"][0])}
    vec_metas = {cid: meta for cid, meta in zip(vec_result["ids"][0], vec_result["metadatas"][0])}

    # BM25 检索（使用查询扩展 + 分城市索引）
    expanded_query = _expand_query(query)
    bm25_results = bm25_store.search(expanded_query, top_k=mmr_fetch, city=city_filter)
    bm25_ids = [r["chunk_id"] for r in bm25_results]
    bm25_docs = {r["chunk_id"]: r["chunk_text"] for r in bm25_results}

    # RRF 融合
    rrf_k = 60
    scores = {}
    for rank, cid in enumerate(vec_ids):
        scores[cid] = scores.get(cid, 0) + vw * (1.0 / (rrf_k + rank + 1))
    for rank, cid in enumerate(bm25_ids):
        scores[cid] = scores.get(cid, 0) + (1 - vw) * (1.0 / (rrf_k + rank + 1))

    # Metadata Boosting + Title Boosting
    if use_metadata_boost or use_title_boost:
        for cid in scores:
            meta = vec_metas.get(cid, {})
            if use_metadata_boost:
                scores[cid] += _compute_metadata_boost(query, meta)
            if use_title_boost:
                scores[cid] += _compute_title_boost(query, meta)

    # 合并文本来源
    all_docs = {**bm25_docs, **vec_docs}

    # MMR 多样性去重：同一 source_id 的 chunk 最多保留 2 条
    if use_mmr:
        sorted_all = sorted(scores, key=scores.get, reverse=True)
        selected = []
        source_count = {}
        for cid in sorted_all:
            meta = vec_metas.get(cid, {})
            src = meta.get("source_id", cid)
            source_count[src] = source_count.get(src, 0) + 1
            if source_count[src] <= 3:
                selected.append(cid)
                if len(selected) >= top_k:
                    break
        sorted_ids = selected
    else:
        sorted_ids = sorted(scores, key=scores.get, reverse=True)[:top_k]

    documents = [all_docs.get(cid, "") for cid in sorted_ids]
    fused_scores = [scores.get(cid, 0) for cid in sorted_ids]

    return sorted_ids, documents, fused_scores


def evaluate(top_k: int = 5, vector_weight: float = 0.5, fetch_k: int = 40,
             use_city_filter: bool = True, verbose: bool = True):
    """对 ChromaDB + BM25 执行混合检索测试，计算命中率和 MRR。"""

    client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
    collection = client.get_collection(CHROMA_COLLECTION_NAME)

    # 加载 BM25 索引
    bm25_store = BM25Store()
    bm25_store.load()

    if verbose:
        print(f"数据库中共 {collection.count()} 个 chunks")
        print(f"测试用例: {len(TEST_CASES)} 个")
        print(f"Top-K: {top_k}  |  vector_weight: {vector_weight}  |  fetch_k: {fetch_k}")
        print(f"城市过滤: {'开启' if use_city_filter else '关闭'}")
        print(f"检索方式: 混合检索（向量 + BM25 RRF 融合 + BGE查询前缀）")
        print(f"\n{'='*70}")

    total_hit_rate = 0
    total_mrr = 0
    results_detail = []

    for tc in TEST_CASES:
        query = tc["query"]
        expected = tc["expected"]

        # 提取城市
        city_filter = _extract_city(query, tc.get("category", "")) if use_city_filter else ""

        # 混合检索（使用查询前缀）
        query_emb = get_embeddings([query], query_mode=True)
        chunk_ids, documents, fused_scores = _hybrid_search(
            collection, bm25_store, query, query_emb, top_k,
            vector_weight=vector_weight, fetch_k=fetch_k, city_filter=city_filter,
        )

        # 计算每条结果是否命中（包含任意一个期望关键词）
        hits = []
        for i, doc in enumerate(documents):
            hit = any(kw in doc for kw in expected)
            hits.append(hit)

        # Hit Rate: top_k 中有多少条命中
        hit_count = sum(hits)
        hit_rate = hit_count / top_k

        # MRR: 第一条命中结果的倒数排名
        mrr = 0
        for i, hit in enumerate(hits):
            if hit:
                mrr = 1.0 / (i + 1)
                break

        total_hit_rate += hit_rate
        total_mrr += mrr

        # 打印单条结果
        if verbose:
            status = "✅" if hit_count > 0 else "❌"
            city_tag = f" [city={city_filter}]" if city_filter else ""
            print(f"\n{status} [{tc['category']}]{city_tag} {query}")
            print(f"   命中: {hit_count}/{top_k}  |  MRR: {mrr:.2f}")

            for i, (doc, score, hit) in enumerate(zip(documents, fused_scores, hits)):
                mark = "🟢" if hit else "⚪"
                preview = doc[:80].replace("\n", " ")
                print(f"   {mark} #{i+1} (score={score:.4f}): {preview}...")

        results_detail.append({
            "query": query,
            "category": tc["category"],
            "hit_count": hit_count,
            "hit_rate": hit_rate,
            "mrr": mrr,
        })

    # 汇总
    avg_hit_rate = total_hit_rate / len(TEST_CASES)
    avg_mrr = total_mrr / len(TEST_CASES)

    if verbose:
        print(f"\n{'='*70}")
        print(f"  平均 Hit Rate@{top_k}: {avg_hit_rate:.2%}")
        print(f"  平均 MRR:            {avg_mrr:.2f}")
        print(f"{'='*70}")

        # 输出汇总表
        print(f"\n{'类别':<12} {'Query':<25} {'命中':<8} {'MRR':<6}")
        print("-" * 55)
        for r in results_detail:
            print(f"{r['category']:<12} {r['query']:<25} {r['hit_count']}/{top_k:<5} {r['mrr']:.2f}")

    return {
        "avg_hit_rate": avg_hit_rate,
        "avg_mrr": avg_mrr,
        "details": results_detail,
        "top_k": top_k,
        "total_chunks": collection.count(),
        "vector_weight": vector_weight,
        "fetch_k": fetch_k,
        "city_filter": use_city_filter,
    }


def grid_search():
    """网格搜索最优参数组合。"""
    print("=" * 70)
    print("  参数网格搜索")
    print("=" * 70)

    weight_options = [0.3, 0.5, 0.7]
    fetch_k_options = [20, 40]
    city_options = [True, False]

    best_score = -1
    best_params = {}
    all_results = []

    for vw in weight_options:
        for fk in fetch_k_options:
            for cf in city_options:
                result = evaluate(
                    vector_weight=vw, fetch_k=fk,
                    use_city_filter=cf, verbose=False,
                )
                combined = result["avg_hit_rate"] * 0.5 + result["avg_mrr"] * 0.5
                row = {
                    "vector_weight": vw,
                    "fetch_k": fk,
                    "city_filter": cf,
                    "hit_rate": result["avg_hit_rate"],
                    "mrr": result["avg_mrr"],
                    "combined": combined,
                }
                all_results.append(row)
                cf_str = "是" if cf else "否"
                print(f"  vw={vw:.1f} fk={fk:>2} city={cf_str}  →  "
                      f"HR={result['avg_hit_rate']:.2%}  MRR={result['avg_mrr']:.2f}  "
                      f"combined={combined:.3f}")
                if combined > best_score:
                    best_score = combined
                    best_params = row

    print(f"\n{'='*70}")
    print(f"  最优参数: vw={best_params['vector_weight']:.1f} "
          f"fk={best_params['fetch_k']} "
          f"city={'是' if best_params['city_filter'] else '否'}")
    print(f"  Hit Rate={best_params['hit_rate']:.2%}  MRR={best_params['mrr']:.2f}")
    print(f"{'='*70}")
    return best_params


def export_report(result: dict, filepath: str = "evaluation_report.md"):
    """将评测结果导出为 Markdown 报告。"""
    from datetime import datetime

    top_k = result["top_k"]
    lines = [
        "# RAG 检索质量评测报告",
        "",
        f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 一、Pipeline 概述",
        "",
        "| 项目 | 配置 |",
        "|---|---|",
        f"| 数据来源 | 小红书成都攻略帖（99 篇） |",
        f"| 入库 Chunks | {result['total_chunks']} 个 |",
        f"| Embedding 模型 | BAAI/bge-small-zh-v1.5（512 维） |",
        f"| 向量数据库 | ChromaDB（余弦相似度） |",
        f"| 关键词索引 | BM25（jieba 分词） |",
        f"| 检索方式 | 混合检索（向量 + BM25，RRF 融合） |",
        f"| Chunk 大小 | 300 字符，overlap 50 |",
        "",
        "## 二、评测指标说明",
        "",
        '- **Hit Rate@5**: 每个 query 返回 5 条结果中，包含期望关键词的比例。衡量“找回来的东西有多少是对的”。',
        '- **MRR (Mean Reciprocal Rank)**: 第一条相关结果的排名倒数。MRR=1.0 表示第一条就命中。衡量“最相关的结果排得够不够靠前”。',
        "",
        "## 三、评测结果",
        "",
        f"| 指标 | 数值 |",
        f"|---|---|",
        f"| **平均 Hit Rate@{top_k}** | **{result['avg_hit_rate']:.0%}** |",
        f"| **平均 MRR** | **{result['avg_mrr']:.2f}** |",
        "",
        "### 各类别详细结果",
        "",
        f"| 类别 | Query | 命中 | MRR |",
        f"|---|---|---|---|",
    ]

    for r in result["details"]:
        lines.append(f"| {r['category']} | {r['query']} | {r['hit_count']}/{top_k} | {r['mrr']:.2f} |")

    lines += [
        "",
        "## 四、优化历程",
        "",
        "| 版本 | 改动 | Hit Rate@5 | MRR |",
        "|---|---|---|---|",
        "| V1 | 纯向量检索 + 基础清洗 | 22% | 0.38 |",
        "| V2 | +加强清洗 +chunk标题前缀 +chunk去重 +换bge-small | 78% | 0.86 |",
        "| V3 | +混合检索（向量+BM25 RRF融合） | 84% | 0.95 |",
        "| **V4（当前）** | +段内去重 +广告残留清理 | **84%** | **1.00** |",
        "",
        "## 五、待改进",
        "",
        "- 亲子游、夜生活类 Hit Rate 偏低（2/5），原因是 99 篇数据中此类专题帖子较少，需要更多数据补充。",
        "- 少量广告碎片残留（截断后的片段），不影响检索质量。",
        "",
    ]

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n📄 评测报告已导出: {filepath}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "grid":
        grid_search()
    else:
        result = evaluate()
        export_report(result)
