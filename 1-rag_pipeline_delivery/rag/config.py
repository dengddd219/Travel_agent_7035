"""
RAG 离线摄取管道 — 全局配置

所有可调参数集中在此，方便实验对比和调参。
修改参数后重新运行 ingest.py 即可生效。
"""

from pathlib import Path

# ──────────────────────────────────────
#  路径配置
# ──────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent  # 7035-project/
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"           # 原始 .md 文件按城市存放
CLEANED_DATA_DIR = PROJECT_ROOT / "data" / "cleaned"   # 清洗后输出（可选，调试用）
CHROMA_DB_DIR = PROJECT_ROOT / "data" / "db" / "chroma"
BM25_INDEX_DIR = PROJECT_ROOT / "data" / "db" / "bm25"

# ──────────────────────────────────────
#  支持的城市列表
# ──────────────────────────────────────
SUPPORTED_CITIES = [
    "成都", "上海", "北京", "西安", "杭州",
    "重庆", "厦门", "广州", "深圳", "香港",
]

# 原始数据文件夹名 → 城市名的映射
CITY_FOLDER_MAP = {
    "chengdu": "成都",
    "shanghai": "上海",
    "beijing": "北京",
    "xian": "西安",
    "hangzhou": "杭州",
    "chongqing": "重庆",
    "xiamen": "厦门",
    "guangzhou": "广州",
    "shenzhen": "深圳",
    "hongkong": "香港",
}

# ──────────────────────────────────────
#  Chunking 参数（决策点1）
# ──────────────────────────────────────
CHUNK_SIZE = 300          # 每个 chunk 的目标字符数
CHUNK_OVERLAP = 50        # 相邻 chunk 重叠字符数
MIN_CHUNK_LENGTH = 30     # 太短的 chunk 丢弃
SHORT_DOC_THRESHOLD = 300 # 短于此值的文档不切分，整条作为一个 chunk

# ──────────────────────────────────────
#  Embedding 参数（决策点2）
# ──────────────────────────────────────
# 选项: "openai" | "bge" | "chroma_default"
EMBEDDING_PROVIDER = "bge"

# OpenAI embedding
OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
OPENAI_EMBEDDING_DIM = 1536

# 开源中文 embedding（备选方案）
# large: 精度最高，1.3GB，CPU 上慢
# small: 精度略低（~4%），95MB，快 5-8 倍
# BGE_MODEL_NAME = "BAAI/bge-large-zh-v1.5"
BGE_MODEL_NAME = "BAAI/bge-small-zh-v1.5"
BGE_EMBEDDING_DIM = 512  # large=1024, small=512

# 批处理大小（避免 API 限流）
EMBEDDING_BATCH_SIZE = 64

# ──────────────────────────────────────
#  ChromaDB 存储参数（决策点3）
# ──────────────────────────────────────
# 所有城市放一个 collection（数据量 ~700 篇，不需要拆分）
CHROMA_COLLECTION_NAME = "travel_guides"

# ──────────────────────────────────────
#  BM25 参数
# ──────────────────────────────────────
BM25_INDEX_FILE = BM25_INDEX_DIR / "bm25_index.pkl"
