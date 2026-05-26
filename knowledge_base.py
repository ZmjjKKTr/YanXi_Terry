"""
RAG 知识库模块 — 文档加载、Embedding、Chroma 向量存储与检索
缓存策略：向量库存在则直接加载，避免每次重启重建
"""
import shutil
from pathlib import Path

from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document

from config import (
    KNOWLEDGE_FILE, CHROMA_DIR, EMBEDDING_MODEL, EMBEDDING_DEVICE,
    RAG_TOP_K, DEBUG
)

_embeddings = None
_vectorstore = None


def get_embeddings():
    global _embeddings
    if _embeddings is None:
        if DEBUG:
            print("[Embedding] 加载模型中...")
        _embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={'device': EMBEDDING_DEVICE},
            encode_kwargs={'normalize_embeddings': True},
        )
    return _embeddings


def load_documents(file_path: Path | None = None) -> list[Document]:
    path = Path(file_path) if file_path else KNOWLEDGE_FILE
    if not path.exists():
        raise FileNotFoundError(f"知识库文件不存在: {path}")

    chunks = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("编号,内容,分类,规则标签"):
                continue
            parts = line.split(',', 3)
            if len(parts) >= 4:
                doc = Document(
                    page_content=parts[1].strip(),
                    metadata={
                        "id": parts[0].strip(),
                        "category": parts[2].strip(),
                        "rule": parts[3].strip(),
                    },
                )
            else:
                doc = Document(page_content=line)
            chunks.append(doc)

    print(f"[OK] 加载 {len(chunks)} 条知识记录")
    return chunks


def init_vectorstore(force_rebuild: bool = False, user_id: str | None = None) -> Chroma:
    global _vectorstore
    embeddings = get_embeddings()
    _ = user_id  # v3.0 预留：将来 per-user Chroma 需传入 user_id

    if _vectorstore is not None and not force_rebuild:
        return _vectorstore

    if force_rebuild and CHROMA_DIR.exists():
        shutil.rmtree(CHROMA_DIR)
        print("[WARN] 旧向量库已删除，重建中...")

    if CHROMA_DIR.exists():
        print("[LOAD] 从磁盘加载已有向量库...")
        _vectorstore = Chroma(
            persist_directory=str(CHROMA_DIR),
            embedding_function=embeddings,
        )
    else:
        print("[BUILD] 构建向量库（首次启动较慢）...")
        docs = load_documents()
        _vectorstore = Chroma.from_documents(
            documents=docs,
            embedding=embeddings,
            persist_directory=str(CHROMA_DIR),
        )

    print(f"[OK] 向量库就绪，集合数量: {_vectorstore._collection.count()}")
    return _vectorstore


def search_knowledge(
    query: str, k: int = RAG_TOP_K,
    category_filter: str | None = None,
    user_id: str | None = None,
) -> list[dict]:
    _ = user_id  # v3.0 预留：将来 per-user 知识库
    vs = init_vectorstore()

    if category_filter:
        results = vs.similarity_search_with_score(
            query, k=k * 2,
            filter={"category": category_filter},
        )
    else:
        results = vs.similarity_search_with_score(query, k=k)

    out = []
    for doc, score in results[:k]:
        out.append({
            "content": doc.page_content,
            "category": doc.metadata.get("category", "未知"),
            "rule": doc.metadata.get("rule", ""),
            "id": doc.metadata.get("id", ""),
            "score": round(score, 4),
        })
    return out
