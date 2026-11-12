"""Regulatory PDFs -> chunks -> embedded Chroma (folder CHROMA_PATH). Embeds each PDF once.

docs/SOURCES.yaml lists the documents:
    - doc_id: fatf_ml_tf_indicators
      title: "..."
      url: "https://..."
      retrieved_on: 2026-11-12
      file: fatf_ml_tf_indicators.pdf        # local name under data/reg_docs/
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from app.config import get_settings
from pipeline.common import S3_DOCS_PREFIX, config_hash, log, recorded_run, sha256_file, should_skip, sources_yaml

CHUNK_SIZE, CHUNK_OVERLAP, BATCH = 900, 150, 32
REQUIRED_KEYS = ("doc_id", "title", "url", "retrieved_on", "file")


@dataclass
class Chunk:
    chunk_id: str
    text: str
    metadata: dict


def load_sources(path: Optional[Path] = None) -> list[dict]:
    path = path or sources_yaml()
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; list the 3 to 5 approved PDFs there")
    docs = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    for d in docs:
        missing = [k for k in REQUIRED_KEYS if not d.get(k)]
        if missing:
            raise ValueError(f"SOURCES.yaml entry {d.get('doc_id')} is missing {missing}")
    return docs


def docs_dir() -> Path:
    return get_settings().data_dir / "reg_docs"


def extract_pages(pdf: Path) -> list[str]:
    from pypdf import PdfReader
    return [(p.extract_text() or "") for p in PdfReader(str(pdf)).pages]


def chunk_pages(doc: dict, pages: list[str]) -> tuple[list[Chunk], list[int]]:
    """Pure. Returns chunks and the 1-based numbers of empty pages (skipped)."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    chunks, empty = [], []
    for page_no, text in enumerate(pages, start=1):
        if not text.strip():
            empty.append(page_no)
            continue
        for n, piece in enumerate(splitter.split_text(text)):
            cid = f"c_{doc['doc_id']}_{page_no:04d}_{n:03d}"
            chunks.append(Chunk(cid, piece, {"doc_id": doc["doc_id"], "title": doc["title"],
                                             "source_url": doc["url"], "page": page_no, "chunk_id": cid}))
    return chunks, empty


def estimate_tokens(chunks: list[Chunk]) -> int:
    return sum(len(c.text) for c in chunks) // 4


def get_store(embeddings=None):
    from langchain_chroma import Chroma
    from app.llm import get_embeddings
    s = get_settings()
    return Chroma(collection_name=s.chroma_collection, persist_directory=str(s.chroma_path),
                  embedding_function=embeddings or get_embeddings({"node": "ingest_docs"}))


def ingest(store, doc: dict, chunks: list[Chunk], ledger) -> int:
    """Replace this doc's chunks (idempotent). Refuses before any call if the budget would be exceeded."""
    est = estimate_tokens(chunks)
    if ledger.used_input + est > ledger.max_input:
        from app.budget import TokenBudgetExceeded
        raise TokenBudgetExceeded(f"embedding {doc['doc_id']} needs ~{est} tokens; "
                                  f"remaining {ledger.max_input - ledger.used_input}")
    store.delete(where={"doc_id": doc["doc_id"]})
    for i in range(0, len(chunks), BATCH):
        batch = chunks[i:i + BATCH]
        store.add_texts([c.text for c in batch], metadatas=[c.metadata for c in batch],
                        ids=[c.chunk_id for c in batch])
    return est


def run_docs(db, force: bool = False) -> Optional[dict]:
    from app.llm import get_embed_ledger
    from pipeline import s3io
    s = get_settings()
    sources = load_sources()
    checksums = {}
    for d in sources:
        local = docs_dir() / d["file"]
        key = f"{S3_DOCS_PREFIX}{d['doc_id']}.pdf"
        if local.exists():
            checksums[d["doc_id"]] = s3io.upload_if_needed(local, key)
        else:
            s3io.ensure_local(local, key)
            checksums[d["doc_id"]] = sha256_file(local)
    chash = config_hash(checksums, {"embed_id": s.bedrock_embed_id, "dims": s.embed_dimensions,
                                    "chunk": [CHUNK_SIZE, CHUNK_OVERLAP]})
    if should_skip(db, "docs", chash, force):
        return None
    with recorded_run(db, "docs", chash) as rec:
        store = get_store()
        ledger = get_embed_ledger()
        totals = {"documents": 0, "pages": 0, "chunks": 0, "characters": 0, "estimated_tokens": 0}
        per_doc = {}
        for d in sources:
            pages = extract_pages(docs_dir() / d["file"])
            chunks, empty = chunk_pages(d, pages)
            if empty:
                rec.note(f"{d['doc_id']}: skipped empty pages {empty[:20]}")
            if not chunks:
                raise RuntimeError(f"{d['doc_id']}: no text extracted (scanned PDF?). Use text PDFs only.")
            est = ingest(store, d, chunks, ledger)
            per_doc[d["doc_id"]] = len(chunks)
            totals["documents"] += 1; totals["pages"] += len(pages); totals["chunks"] += len(chunks)
            totals["characters"] += sum(len(c.text) for c in chunks); totals["estimated_tokens"] += est
            log.info("doc_ingested", doc_id=d["doc_id"], pages=len(pages), chunks=len(chunks), est_tokens=est)
        rec.row_counts = totals
        rec.extra = {"chunks_per_doc": per_doc, "checksums": checksums}
        return totals
