"""Brand voice: retrieve similar past posts so writers can match their style.

Two embedders (local fastembed model, or a keyword hash for tests/demo) and two
stores (in-memory, or Postgres + pgvector). Both stores share one interface.
"""

import hashlib
import json
import logging
import math
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from repurpose_agent.config import Settings
from repurpose_agent.schemas import Platform

log = logging.getLogger(__name__)


class BrandPost(BaseModel):
    platform: Platform
    text: str


# ------------------------------------------------------------------ embedders


class Embedder(Protocol):
    dim: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class FastEmbedder:
    """Local ONNX embedding model (downloaded once, ~70 MB). No API key, no cost."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", dim: int = 384) -> None:
        self.model_name, self.dim = model_name, dim
        self._model = None

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(self.model_name)
        return [v.tolist() for v in self._model.embed(list(texts))]


class HashEmbedder:
    """Bag-of-words hashed into a fixed vector. Lexical, not semantic, but instant
    and deterministic: used by tests and demo mode."""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out = []
        for text in texts:
            v = [0.0] * self.dim
            for word in re.findall(r"[a-z0-9]+", text.lower()):
                h = int.from_bytes(hashlib.md5(word.encode()).digest()[:4], "little")
                v[h % self.dim] += 1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out


def make_embedder(settings: Settings) -> Embedder:
    if settings.demo or settings.embeddings == "hash":
        return HashEmbedder()
    return FastEmbedder(settings.embedding_model, settings.embedding_dim)


# --------------------------------------------------------------------- stores


class VoiceStore(Protocol):
    def add(self, posts: Sequence[BrandPost]) -> int:
        """Store posts, skipping exact duplicates. Returns how many were new."""
        ...

    def search(self, query: str, platform: Platform, k: int) -> list[str]: ...

    def count(self, platform: Platform | None = None) -> int: ...


class MemoryVoiceStore:
    def __init__(self, embedder: Embedder) -> None:
        self.embedder = embedder
        self._rows: list[tuple[BrandPost, list[float]]] = []

    def add(self, posts: Sequence[BrandPost]) -> int:
        seen = {(p.platform, p.text) for p, _ in self._rows}
        new = [p for p in posts if (p.platform, p.text) not in seen]
        new = list({(p.platform, p.text): p for p in new}.values())  # dedupe within batch
        if new:
            vectors = self.embedder.embed([p.text for p in new])
            self._rows += list(zip(new, vectors, strict=True))
        return len(new)

    def search(self, query: str, platform: Platform, k: int) -> list[str]:
        rows = [(p, v) for p, v in self._rows if p.platform == platform]
        if not rows or k <= 0:
            return []
        (q,) = self.embedder.embed([query])
        scored = sorted(rows, key=lambda r: -sum(a * b for a, b in zip(q, r[1], strict=True)))
        return [p.text for p, _ in scored[:k]]

    def count(self, platform: Platform | None = None) -> int:
        return sum(1 for p, _ in self._rows if platform is None or p.platform == platform)


class PgVoiceStore:
    """Postgres + pgvector. Cosine distance with an HNSW index."""

    def __init__(self, pool, embedder: Embedder, table: str = "brand_posts") -> None:
        if not re.fullmatch(r"[a-z_]+", table):
            raise ValueError("invalid table name")
        self.pool, self.embedder, self.table = pool, embedder, table

    def setup(self) -> None:
        with self.pool.connection() as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(
                f"""CREATE TABLE IF NOT EXISTS {self.table} (
                    id bigserial PRIMARY KEY,
                    platform text NOT NULL,
                    text text NOT NULL,
                    text_hash text GENERATED ALWAYS AS (md5(text)) STORED,
                    embedding vector({self.embedder.dim}) NOT NULL,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    UNIQUE (platform, text_hash)
                )"""
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS {self.table}_embedding_idx "
                f"ON {self.table} USING hnsw (embedding vector_cosine_ops)"
            )

    @staticmethod
    def _vec(v: list[float]) -> str:
        return "[" + ",".join(f"{x:.6f}" for x in v) + "]"

    def add(self, posts: Sequence[BrandPost]) -> int:
        if not posts:
            return 0
        vectors = self.embedder.embed([p.text for p in posts])
        added = 0
        with self.pool.connection() as conn:
            for post, vec in zip(posts, vectors, strict=True):
                cur = conn.execute(
                    f"INSERT INTO {self.table} (platform, text, embedding) "
                    "VALUES (%s, %s, %s::vector) ON CONFLICT DO NOTHING",
                    (str(post.platform), post.text, self._vec(vec)),
                )
                added += cur.rowcount
        return added

    def search(self, query: str, platform: Platform, k: int) -> list[str]:
        if k <= 0:
            return []
        (q,) = self.embedder.embed([query])
        with self.pool.connection() as conn:
            rows = conn.execute(
                f"SELECT text FROM {self.table} WHERE platform = %s "
                "ORDER BY embedding <=> %s::vector LIMIT %s",
                (str(platform), self._vec(q), k),
            ).fetchall()
        return [r["text"] if isinstance(r, dict) else r[0] for r in rows]

    def count(self, platform: Platform | None = None) -> int:
        with self.pool.connection() as conn:
            if platform is None:
                row = conn.execute(f"SELECT count(*) AS n FROM {self.table}").fetchone()
            else:
                row = conn.execute(
                    f"SELECT count(*) AS n FROM {self.table} WHERE platform = %s",
                    (str(platform),),
                ).fetchone()
        return row["n"] if isinstance(row, dict) else row[0]


# ------------------------------------------------------------------- helpers


def load_posts(path: Path) -> list[BrandPost]:
    """Read posts from a JSON list or JSON Lines file of {"platform", "text"} objects."""
    raw = path.read_text().strip()
    items = json.loads(raw) if raw.startswith("[") else [json.loads(x) for x in raw.splitlines()]
    return [BrandPost.model_validate(i) for i in items if i]


@contextmanager
def open_voice_store(settings: Settings) -> Iterator[VoiceStore]:
    embedder = make_embedder(settings)
    if not settings.database_url:
        store: VoiceStore = MemoryVoiceStore(embedder)
        _seed(store, settings)
        yield store
        return

    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    with ConnectionPool(
        settings.database_url, max_size=5, kwargs={"autocommit": True, "row_factory": dict_row}
    ) as pool:
        table = "brand_posts" if isinstance(embedder, FastEmbedder) else "brand_posts_hash"
        pg = PgVoiceStore(pool, embedder, table=table)  # separate tables: dims differ
        pg.setup()
        _seed(pg, settings)
        yield pg


def _seed(store: VoiceStore, settings: Settings) -> None:
    if settings.brand_file and settings.brand_file.exists():
        added = store.add(load_posts(settings.brand_file))
        log.info("Loaded %d brand posts from %s", added, settings.brand_file)
