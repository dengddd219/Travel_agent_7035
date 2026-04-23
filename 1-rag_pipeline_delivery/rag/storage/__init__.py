# 延迟导入，避免 dry-run 模式下需要安装所有依赖
def get_chroma_store():
    from .chroma_store import ChromaStore
    return ChromaStore

def get_bm25_store():
    from .bm25_store import BM25Store
    return BM25Store
