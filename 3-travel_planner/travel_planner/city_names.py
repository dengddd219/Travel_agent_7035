## author:SUN Bin
from __future__ import annotations

"""Centralized city-name normalization.

Why this file matters:
- users may type city names in Chinese or English
- city profiles use canonical English names
- provider APIs and RAG corpus often prefer Chinese names

So every layer should route through this registry instead of hardcoding its own
city-name mapping.
"""

# Canonical city registry used across profile loading, API calls, and UI output.
CITY_NAME_REGISTRY = {
    "Hong Kong": {"zh": "香港", "en": "Hong Kong"},
    "Tokyo": {"zh": "东京", "en": "Tokyo"},
    "Chengdu": {"zh": "成都", "en": "Chengdu"},
    "Shanghai": {"zh": "上海", "en": "Shanghai"},
    "Beijing": {"zh": "北京", "en": "Beijing"},
    "Guangzhou": {"zh": "广州", "en": "Guangzhou"},
    "Shenzhen": {"zh": "深圳", "en": "Shenzhen"},
    "Hangzhou": {"zh": "杭州", "en": "Hangzhou"},
    "Xian": {"zh": "西安", "en": "Xian"},
    "Chongqing": {"zh": "重庆", "en": "Chongqing"},
    "Xiamen": {"zh": "厦门", "en": "Xiamen"},
    "Nanjing": {"zh": "南京", "en": "Nanjing"},
}

RAG_FOLDER_REGISTRY = {
    "Hong Kong": "hongkong",
    "Tokyo": "tokyo",
    "Chengdu": "chengdu",
    "Shanghai": "shanghai",
    "Beijing": "beijing",
    "Guangzhou": "guangzhou",
    "Shenzhen": "shenzhen",
    "Hangzhou": "hangzhou",
    "Xian": "xian",
    "Chongqing": "chongqing",
    "Xiamen": "xiamen",
    "Nanjing": "nanjing",
}

CITY_ALIASES = {
    "hong kong": "Hong Kong",
    "香港": "Hong Kong",
    "tokyo": "Tokyo",
    "东京": "Tokyo",
    "chengdu": "Chengdu",
    "成都": "Chengdu",
    "shanghai": "Shanghai",
    "上海": "Shanghai",
    "beijing": "Beijing",
    "北京": "Beijing",
    "guangzhou": "Guangzhou",
    "广州": "Guangzhou",
    "shenzhen": "Shenzhen",
    "深圳": "Shenzhen",
    "hangzhou": "Hangzhou",
    "杭州": "Hangzhou",
    "xian": "Xian",
    "xi'an": "Xian",
    "西安": "Xian",
    "chongqing": "Chongqing",
    "重庆": "Chongqing",
    "xiamen": "Xiamen",
    "厦门": "Xiamen",
    "nanjing": "Nanjing",
    "南京": "Nanjing",
}

POI_DISPLAY_ALIASES = {
    "Forbidden City": "故宫",
    "Temple of Heaven": "天坛",
    "Jingshan Park": "景山公园",
    "National Museum of China": "中国国家博物馆",
    "Summer Palace": "颐和园",
    "798 Art District": "798艺术区",
    "Mutianyu Great Wall": "慕田峪长城",
    "Shichahai (Houhai Lake)": "什刹海（后海）",
    "Prince Gong's Mansion": "恭王府",
    "Wangfujing Street": "王府井大街",
    "Capital Museum": "首都博物馆",
    "Nanluoguxiang": "南锣鼓巷",
    "Yonghe Lama Temple": "雍和宫",
    "Chengdu Research Base of Giant Panda Breeding": "成都大熊猫繁育研究基地",
    "Kuanzhai Alley": "宽窄巷子",
    "People's Park Chengdu": "成都人民公园",
    "Jinsha Site Museum": "金沙遗址博物馆",
    "Taikoo Li Chengdu": "成都太古里",
    "Chunxi Road": "春熙路",
    "IFS International Finance Square": "IFS国际金融中心",
    "Wuhou Shrine": "武侯祠",
    "Jinli Old Street": "锦里古街",
    "Du Fu Thatched Cottage": "杜甫草堂",
    "East Suburb Memory": "东郊记忆",
    "Yulin Food Street": "玉林美食街",
    "Chengdu Museum": "成都博物馆",
    "Hongya Cave": "洪崖洞",
    "Liziba Station": "李子坝",
    "Jiefangbei": "解放碑",
    "Three Gorges Museum": "三峡博物馆",
    "Chaotianmen Square": "朝天门广场",
    "Yangtze River Cableway": "长江索道",
    "Ciqikou Ancient Town": "磁器口古镇",
    "Nanshan Scenic Area": "南山风景区",
    "Raffles City Chongqing": "重庆来福士",
    "Bayi Road Food Street": "八一路好吃街",
    "Danzishi Old Street": "弹子石老街",
    "Chongqing People's Great Hall": "重庆人民大礼堂",
    "Chongqing Hotpot Restaurant (Zhu Laoliu)": "朱老六火锅",
    "Canton Tower": "广州塔",
    "Yongqing Fang": "永庆坊",
    "Shamian Island": "沙面岛",
    "Chen Clan Ancestral Hall": "陈家祠",
    "Yuexiu Park": "越秀公园",
    "Beijing Road Pedestrian Street": "北京路步行街",
    "Chimelong Paradise": "长隆欢乐世界",
    "Guangdong Provincial Museum": "广东省博物馆",
    "Guangzhou Opera House": "广州大剧院",
    "Xiguan Mansions Area": "西关大屋",
    "Dim Sum at Taotaoju": "陶陶居早茶",
    "Zhujiang New Town (Pearl River New Town)": "珠江新城",
    "Haixinsha Island": "海心沙",
    "West Lake": "西湖",
    "City Wall": "城墙",
    "Lingyin Temple": "灵隐寺",
    "Qinghefang": "清河坊",
    "China National Tea Museum": "中国茶叶博物馆",
    "Leifeng Pagoda": "雷峰塔",
    "Longjing Tea Village": "龙井村",
    "Xixi Wetland National Park": "西溪国家湿地公园",
    "Broken Bridge (Duanqiao)": "断桥",
    "He Fang Street (Hefang Jie)": "河坊街",
    "Liangzhu Museum": "良渚博物院",
    "Song Dynasty Town (Songcheng)": "宋城",
    "Hubin Pedestrian Street": "湖滨步行街",
    "Peak Tram": "太平山缆车",
    "Central Market": "中环街市",
    "Star Ferry": "天星小轮",
    "Tsim Sha Tsui Promenade": "尖沙咀海滨长廊",
    "Tai Kwun": "大馆",
    "PMQ Hong Kong": "PMQ元创方",
    "M+ Museum": "M+博物馆",
    "Temple Street Night Market": "庙街夜市",
    "Nanjing Museum": "南京博物院",
    "Confucius Temple Nanjing": "夫子庙",
    "Laomendong": "老门东",
    "Presidential Palace": "总统府",
    "Sun Yat-sen Mausoleum": "中山陵",
    "Nanjing City Wall": "南京城墙",
    "Xuanwu Lake Park": "玄武湖公园",
    "Memorial Hall of the Victims in Nanjing Massacre": "侵华日军南京大屠杀遇难同胞纪念馆",
    "Ming Xiaoling Mausoleum": "明孝陵",
    "Qinhuai River Night Cruise": "秦淮河夜游",
    "Nanjing Salted Duck Restaurant (Guijie Duck)": "南京盐水鸭（桂记）",
    "1912 Nanjing Bar and Restaurant Street": "1912街区",
    "The Bund": "外滩",
    "Yu Garden": "豫园",
    "Wukang Road": "武康路",
    "Shanghai Natural History Museum": "上海自然博物馆",
    "Xintiandi": "新天地",
    "Oriental Pearl Tower": "东方明珠",
    "Tianzifang": "田子坊",
    "Former French Concession": "法租界",
    "Shanghai Museum": "上海博物馆",
    "Nanjing Road Pedestrian Street": "南京路步行街",
    "West Bund Museum": "西岸美术馆",
    "Jing'an Temple": "静安寺",
    "Shenzhen Bay Park": "深圳湾公园",
    "OCT Loft": "华侨城创意文化园",
    "Ping An Finance Centre": "平安金融中心",
    "Sea World Culture and Arts Center": "海上世界文化艺术中心",
    "Shenzhen Museum": "深圳博物馆",
    "Window of the World": "世界之窗",
    "Civic Center and Lotus Hill Park": "市民中心和莲花山公园",
    "Dongmen Pedestrian Street": "东门步行街",
    "Dapeng Fortress (Dapeng Ancient Town)": "大鹏所城",
    "Shenzhen Bay Park Mangrove": "深圳湾红树林公园",
    "Nantou Ancient Town": "南头古城",
    "Coco Park Shopping Mall": "COCO Park购物公园",
    "Senso-ji": "浅草寺",
    "Shibuya Sky": "涩谷SKY",
    "Tsukiji Outer Market": "筑地场外市场",
    "Meiji Shrine": "明治神宫",
    "Shinjuku Gyoen": "新宿御苑",
    "Ueno Park and Zoo": "上野公园与动物园",
    "Tokyo Skytree": "东京晴空塔",
    "Harajuku Takeshita Street": "原宿竹下通",
    "Shibuya Crossing": "涩谷十字路口",
    "Yanaka Ginza": "谷中银座",
    "Roppongi Hills and Mori Art Museum": "六本木新城与森美术馆",
    "Gulangyu": "鼓浪屿",
    "Huandao Road": "环岛路",
    "Zhongshan Road Pedestrian Street": "中山路步行街",
    "Shapowei": "沙坡尾",
    "Sunlight Rock (Sunlight Rock Scenic Area)": "日光岩",
    "Shuzhuang Garden (Gulangyu)": "菽庄花园",
    "Nanputuo Temple": "南普陀寺",
    "Xiamen University Campus Walk": "厦门大学",
    "Jimei School Village": "集美学村",
    "Baicheng Beach": "白城沙滩",
    "Xiamen Botanical Garden": "厦门园林植物园",
    "Zengcuoan Art Village": "曾厝垵",
    "Xi'an City Wall": "西安城墙",
    "Shaanxi History Museum": "陕西历史博物馆",
    "Giant Wild Goose Pagoda": "大雁塔",
    "Muslim Quarter": "回民街",
    "Terracotta Warriors": "兵马俑",
    "Bell Tower": "钟楼",
    "Drum Tower": "鼓楼",
    "Tang Paradise (Datang Furong Garden)": "大唐芙蓉园",
    "Daming Palace National Heritage Park": "大明宫国家遗址公园",
    "Yongxingfang Food Street": "永兴坊",
    "Small Wild Goose Pagoda": "小雁塔",
    "Qujiang Pool Ruins Park": "曲江池遗址公园",
}
POI_DISPLAY_ALIASES_LOWER = {key.lower(): value for key, value in POI_DISPLAY_ALIASES.items()}
LOCATION_DISPLAY_ALIASES = {
    "Hubin": "湖滨",
    "Longxiangqiao": "龙翔桥",
    "Xixi": "西溪",
    "Asakusa": "浅草",
    "Beilin": "碑林区",
    "Central": "中环",
    "Chaoyang": "朝阳区",
    "Chenghua": "成华区",
    "Dapeng": "大鹏新区",
    "Dongcheng": "东城区",
    "Futian": "福田区",
    "Haidian": "海淀区",
    "Haizhu": "海珠区",
    "Harajuku": "原宿",
    "Huairou": "怀柔区",
    "Huangpu": "黄浦区",
    "Jiangbei": "江北区",
    "Jianye": "建邺区",
    "Jimei": "集美区",
    "Jing'an": "静安区",
    "Jinjiang": "锦江区",
    "Jordan": "佐敦",
    "Lianhu": "莲湖区",
    "Lintong": "临潼区",
    "Liwan": "荔湾区",
    "Luohu": "罗湖区",
    "Nan'an": "南岸区",
    "Nanshan": "南山区",
    "Panyu": "番禺区",
    "Pudong": "浦东新区",
    "Qingyang": "青羊区",
    "Qinhuai": "秦淮区",
    "Qujiang": "曲江新区",
    "Roppongi": "六本木",
    "Shangcheng": "上城区",
    "Shapingba": "沙坪坝区",
    "Shibuya": "涩谷",
    "Shinjuku": "新宿",
    "Siming": "思明区",
    "Tianhe": "天河区",
    "Toyosu": "丰洲",
    "Tsim Sha Tsui": "尖沙咀",
    "Tsukiji": "筑地",
    "Ueno": "上野",
    "West Kowloon": "西九龙",
    "Wuhou": "武侯区",
    "Xicheng": "西城区",
    "Xihu": "西湖区",
    "Xincheng": "新城区",
    "Xuanwu": "玄武区",
    "Xuhui": "徐汇区",
    "Yanta": "雁塔区",
    "Yuexiu": "越秀区",
    "Yuhang": "余杭区",
    "Yuzhong": "渝中区",
}
LOCATION_DISPLAY_ALIASES_LOWER = {key.lower(): value for key, value in LOCATION_DISPLAY_ALIASES.items()}
RAG_QUERY_ALIASES = {
    "Hangzhou Zoo": "杭州动物园",
    "Xixi Wetland": "西溪湿地",
    "Songcheng": "宋城",
    "West Lake boat": "西湖 游船",
    "Qinghefang food": "清河坊 美食",
    "Hubin dining": "湖滨 美食",
    "Hangzhou local dishes": "杭州 本地菜",
    "Yuhang culture": "余杭 文化",
    "Civic Center Shenzhen": "深圳市民中心",
    "Splendid China": "锦绣中华",
    "Dongmen food": "东门 美食",
    "Coco Park dining": "COCO Park 美食",
    "Sea World Shenzhen": "海上世界",
    "coffee Shenzhen": "深圳 咖啡",
    "bookstores Shenzhen": "深圳 书店",
    "design Shenzhen": "深圳 设计",
    "Anshun Bridge": "安顺廊桥",
    "Dongjiao Memory": "东郊记忆",
    "Kuixinglou Street": "魁星楼街",
    "Jianshe Road food": "建设路 美食",
    "hotpot Chengdu": "成都 火锅",
    "Eastern Suburb Memory": "东郊记忆",
    "Shichahai": "什刹海",
    "Universal Beijing Resort": "北京环球影城",
    "Beijing Zoo": "北京动物园",
    "China Science and Technology Museum": "中国科学技术馆",
    "Wangfujing snacks": "王府井 小吃",
    "Niujie food": "牛街 美食",
    "Beijing roast duck": "北京 烤鸭",
    "hutong dining": "胡同 美食",
    "Shanghai Museum East": "上海博物馆东馆",
    "Shanghai Disneyland": "上海迪士尼",
    "Shanghai Ocean Aquarium": "上海海洋水族馆",
    "Century Park": "世纪公园",
    "Yuyuan food": "豫园 美食",
    "Jing'an cafe": "静安 咖啡",
    "Xintiandi dining": "新天地 美食",
    "Wukang Road cafe": "武康路 咖啡",
    "M50": "M50创意园",
    "Long Museum": "龙美术馆",
    "West Bund Museum": "西岸美术馆",
    "Gulangyu piano museum": "鼓浪屿 钢琴博物馆",
    "Xiamen Science and Technology Museum": "厦门科技馆",
    "Xiamen art spaces": "厦门 艺术空间",
    "Zhongshan Road Xiamen": "厦门中山路",
    "Zhongshan Road food": "中山路 美食",
    "beach Xiamen": "厦门 海边",
    "shacha noodles Xiamen": "厦门 沙茶面",
    "Tang-era Xi'an": "西安 大唐风格",
    "Bell Tower Xi'an": "西安 钟楼",
    "Xi'an snacks": "西安 小吃",
    "local noodles Xi'an": "西安 面食",
    "Daming Palace": "大明宫",
    "Qujiang Ocean Park": "曲江海洋公园",
    "Taotaoju": "陶陶居",
    "Beijing Road Guangzhou": "广州 北京路",
    "Beijing Road snacks": "北京路 小吃",
    "dim sum Guangzhou": "广州 早茶",
    "Xiguan food": "西关 美食",
    "Cantonese heritage": "广府 文化",
    "Jiefangbei dining": "解放碑 美食",
    "Hongya Cave night": "洪崖洞 夜景",
    "Nanbin Road night food": "南滨路 夜景 美食",
    "mountain city lane": "山城 巷子",
    "Nanshan overlook": "南山 观景台",
    "Sea World Culture and Arts Center": "海上世界文化艺术中心",
    "Ocean Park Hong Kong": "香港海洋公园",
    "West Kowloon Art Park": "西九文化区艺术公园",
    "Temple Street Night Market": "庙街夜市",
    "Depachika Tokyo": "东京 地下美食街",
    "Ameya-Yokocho": "阿美横町",
    "Kappabashi": "合羽桥",
    "Daikanyama T-Site": "代官山T-SITE",
    "Nezu Museum": "根津美术馆",
    "Omoide Yokocho": "思い出横丁",
    "Sumida Aquarium": "墨田水族馆",
    "Tokyo Disneyland": "东京迪士尼",
    "teamLab Planets": "teamLab Planets",
}
RAG_QUERY_ALIASES_LOWER = {key.lower(): value for key, value in RAG_QUERY_ALIASES.items()}


def normalize_city_name(city: str | None) -> str:
    """Normalize free-form user input into one canonical city key."""
    raw = (city or "").strip()
    if not raw:
        return ""
    return CITY_ALIASES.get(raw.lower(), raw)


def city_name_bundle(city: str | None) -> dict[str, str]:
    """Return all useful name variants for one city.

    The planner mainly stores the canonical English name, while:
    - RAG often needs a folder name or Chinese city
    - UI sometimes wants Chinese display text
    - some providers work better with English
    """
    canonical = normalize_city_name(city)
    bundle = CITY_NAME_REGISTRY.get(canonical)
    if bundle:
        return {
            "canonical": canonical,
            "city_en": bundle["en"],
            "city_zh": bundle["zh"],
        }
    return {
        "canonical": canonical,
        "city_en": canonical,
        "city_zh": canonical,
    }


def provider_city_name(city: str | None, provider: str = "zh") -> str:
    """Return the city name in the format preferred by a downstream provider."""
    bundle = city_name_bundle(city)
    if provider == "en":
        return bundle["city_en"]
    return bundle["city_zh"]


def normalize_poi_display_name(name: str | None) -> str:
    raw = (name or "").strip()
    if not raw:
        return ""
    return POI_DISPLAY_ALIASES_LOWER.get(raw.lower(), raw)


def normalize_location_display_name(name: str | None) -> str:
    raw = (name or "").strip()
    if not raw:
        return ""
    return LOCATION_DISPLAY_ALIASES_LOWER.get(raw.lower(), raw)


def normalize_rag_query_text(text: str | None) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    text = normalize_poi_display_name(raw)
    text = normalize_location_display_name(text)
    return RAG_QUERY_ALIASES_LOWER.get(text.lower(), text)


def rag_city_folder(city: str | None) -> str | None:
    """Map a city to the folder name used by the delivered RAG corpus."""
    canonical = normalize_city_name(city)
    if not canonical:
        return None
    return RAG_FOLDER_REGISTRY.get(canonical)
