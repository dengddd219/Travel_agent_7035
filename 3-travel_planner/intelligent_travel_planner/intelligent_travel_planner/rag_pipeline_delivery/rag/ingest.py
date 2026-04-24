from pathlib import Path
import json

from rag.cleaning import clean_text
from rag.chunking import chunk_document
from rag.utils import load_all_documents


def ingest_raw_folder(raw_root: Path) -> list[dict]:
    documents = load_all_documents(raw_root)
    chunks: list[dict] = []
    for doc in documents:
        cleaned = clean_text(doc["text"])
        chunks.extend(chunk_document(cleaned, doc["metadata"]))
    return chunks


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    raw_root = root / "data" / "raw"
    out_root = root / "data" / "db"
    out_root.mkdir(parents=True, exist_ok=True)
    chunks = ingest_raw_folder(raw_root)
    output = out_root / "chunks.json"
    output.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(chunks)} chunks to {output}")


if __name__ == "__main__":
    main()
