"""
正文清洗器

针对小红书爬取数据的噪音模式，逐条清洗正文文本。
所有清洗规则集中在此文件，方便查看和修改。
"""

import re


# ──────────────────────────────────────
#  需要整段删除的固定文本
# ──────────────────────────────────────
_REMOVE_EXACT = [
    # 广告屏蔽提示（多种变体都要覆盖）
    "温馨提示 您的浏览器似乎开启了广告屏蔽插件，可能对正常使用造成影响，"
    "请移除插件或将小红书加入插件白名单后继续使用。",
    "您的浏览器似乎开启了广告屏蔽插件",
    "请移除插件或将小红书加入插件白名单后继续使用",
    "广告屏蔽插件",
    "我知道了",
    "发送 取消",
    "温馨提示",
]

# ──────────────────────────────────────
#  正则模式：匹配需要删除的噪音行
# ──────────────────────────────────────
_NOISE_PATTERNS = [
    # "说点什么... 2932 1847 20 发送 取消" — UI 交互元素
    re.compile(r"说点什么\.*\s*[\d\s]*发送\s*取消"),
    # 也可能 "发送 取消" 被先去掉了，只剩 "说点什么... 数字"
    re.compile(r"说点什么\.*\s*\d[\d\s]*"),

    # "编辑于 2025-02-14"
    re.compile(r"编辑于\s*\d{4}-\d{2}-\d{2}"),

    # 小红书短链接
    re.compile(r"http://xhslink\.com/\S*"),

    # "复制后打开【小红书】查看笔记！"
    re.compile(r"复制后打开【小红书】查看笔记[！!]?"),

    # 纯 hashtag 行（3个及以上连续 #xxx）
    re.compile(r"^(#\S+\s*){3,}$", re.MULTILINE),

    # 评论区常见的时间+地区标记 "04-04 四川 赞 1" / "2025-12-25 湖北 51 3"
    re.compile(r"\d{2,4}-\d{2}(?:-\d{2})?\s+[\u4e00-\u9fff]{2,4}\s+(?:赞\s*)?\d+"),

    # "去首页，发现更多笔记"
    re.compile(r"去首页[，,]发现更多笔记"),

    # "展开 N 条回复"
    re.compile(r"展开\s*\d+\s*条回复"),

    # 广告屏蔽相关残留（更宽泛的匹配）
    re.compile(r"温馨提示.*?白名单.*?使用[。.]?", re.DOTALL),
    re.compile(r".*广告屏蔽插件.*"),
    re.compile(r".*移除插件.*白名单.*"),
    re.compile(r"[，,]?\s*可能对正常使用造成影响[，,]?\s*"),

    # "N 回复" 独立出现
    re.compile(r"^\d+\s*回复$", re.MULTILINE),

    # "[投票]"
    re.compile(r"\[投票\]"),

    # 孤立的 "#" 号（标题被去掉后残留）
    re.compile(r"^#\s*$", re.MULTILINE),

    # "N 赞" 独立出现
    re.compile(r"^赞$", re.MULTILINE),

    # "关注我，分享更多..." 类博主引流
    re.compile(r"关注我[，,]分享更多\S*"),

    # "置顶评论" 标记
    re.compile(r"置顶评论"),
]

# ──────────────────────────────────────
#  评论区检测：这些短语一旦出现，后续大概率是评论
#  用于截断正文，去除混入的评论内容
# ──────────────────────────────────────
_COMMENT_BOUNDARY_PHRASES = [
    "什么宝藏博主",
    "以后就跟着你",
    "假装不是本人",
    "收藏，明天去",
    "我是外地来玩的",
    "求猴哥原图",
    "每次都去那儿",
]


def clean_text(raw_body: str, title: str = "") -> str:
    """
    清洗单篇文档的正文。

    Args:
        raw_body: 从 .md 文件解析出的原始正文
        title: 文档标题（用于去除正文中重复的标题）

    Returns:
        清洗后的纯攻略文本
    """
    text = raw_body

    # 1. 去除固定噪音文本
    for noise in _REMOVE_EXACT:
        text = text.replace(noise, "")

    # 2. 去除正文中重复的标题
    if title:
        # 标题可能在正文开头重复出现，只去除开头的
        stripped_title = title.strip()
        # 最多去除2次（有些文件标题出现在开头和中间）
        for _ in range(2):
            text = text.replace(stripped_title, "", 1)

    # 3. 正则模式清洗
    for pattern in _NOISE_PATTERNS:
        text = pattern.sub("", text)

    # 4. 去除重复内容块
    text = _deduplicate_content(text)

    # 5. 去除段内重复（同一段前后半段相同）
    text = _deduplicate_within_paragraph(text)

    # 6. 清理多余空白
    text = _normalize_whitespace(text)

    return text.strip()


def _deduplicate_content(text: str, min_block_len: int = 60) -> str:
    """
    检测并去除正文中的重复内容块。

    小红书爬取数据经常会把同一段内容重复2-3遍。
    策略：按较长的子串查找重复，保留第一次出现。
    """
    # 将文本按双换行分成段落
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    seen_fingerprints = set()
    unique_paragraphs = []

    for para in paragraphs:
        # 用段落的前60个字符作为指纹（去掉空白和符号干扰）
        fingerprint = re.sub(r"\s+", "", para)[:min_block_len]

        if len(fingerprint) < 20:
            # 太短的段落不做去重，直接保留
            unique_paragraphs.append(para)
            continue

        if fingerprint not in seen_fingerprints:
            seen_fingerprints.add(fingerprint)
            unique_paragraphs.append(para)
        # 重复的段落直接丢弃

    return "\n\n".join(unique_paragraphs)


def _deduplicate_within_paragraph(text: str) -> str:
    """
    去除段内重复：小红书爬取经常把同一段话在段落内连续出现两遍。
    例如 "都是四百。我们三个人四百，有的人...都是四百。我们三个人四百，有的人..."
    策略：如果一个段落的前半段和后半段高度相似，只保留一份。
    """
    paragraphs = text.split("\n\n")
    result = []
    for para in paragraphs:
        cleaned = re.sub(r"\s+", "", para)
        length = len(cleaned)
        if length >= 40:
            half = length // 2
            # 检查前半和后半是否相同（允许少量偏移）
            for offset in range(0, min(20, half)):
                if cleaned[:half - offset] == cleaned[half - offset:2 * (half - offset)]:
                    # 前后半段相同，只保留前半段对应的原文
                    # 用原文长度的一半+一点余量来截取
                    raw_half = len(para) // 2 + 10
                    para = para[:raw_half].rstrip()
                    break
        result.append(para)
    return "\n\n".join(result)


def _normalize_whitespace(text: str) -> str:
    """清理多余的空行和空白。"""
    # 连续3个以上换行 → 2个换行
    text = re.sub(r"\n{3,}", "\n\n", text)
    # 每行首尾空白
    lines = [line.strip() for line in text.split("\n")]
    # 去掉纯空行连续出现
    cleaned = []
    prev_empty = False
    for line in lines:
        if not line:
            if not prev_empty:
                cleaned.append("")
            prev_empty = True
        else:
            cleaned.append(line)
            prev_empty = False

    return "\n".join(cleaned)
