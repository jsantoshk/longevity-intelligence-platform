"""Read a longevity PDF, extract Dimensions, KPIs, and Interventions, and store them."""

import hashlib
import json
import sys
from pathlib import Path

import httpx
import psycopg
from falkordb import FalkorDB
from pydantic import ValidationError
from pypdf import PdfReader

from schemas import Dimension, ExtractionResult, Intervention, KPI, MergedExtraction

OLLAMA_MODEL = "qwen3:8b"
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
DATABASE_URL = "postgresql://lip_admin:lip_password@localhost:5432/longevity_db"
FALKORDB_HOST = "localhost"
FALKORDB_PORT = 6379
FALKORDB_GRAPH = "longevity_kg"
CHUNK_CHARS = 4000
MAX_CHUNKS = 32

SYSTEM_PROMPT = """You extract a longevity knowledge graph from a report excerpt.
The excerpt includes page markers like "--- PAGE 12 ---".
Return JSON only, with this exact shape:
{
  "dimensions": [{"name": "", "description": "", "approved": true}],
  "kpis": [{"name": "", "dimension": "", "unit": "", "description": "", "approved": true}],
  "interventions": [{"name": "", "target_kpi": "", "description": "", "approved": true}]
}
Rules:
- Dimensions are longevity outcome areas. KPIs are measurable indicators of a dimension.
- Interventions are actions that target a KPI.
- Prefix EVERY description with "[Evidence Grade | p. X]" using the exact page number from the page marker
  and one of these grades: Meta-Analysis, RCT, Observational, Policy Report, or Expert Consensus.
  Example: "[Policy Report | p. 14] Financial assistance for home adaptations such as grab rails."
- Set approved to true only when the excerpt clearly supports the item.
- Skip Table of Contents, copyright notices, and author lists. Use empty lists if no supported items exist.
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    sha256       TEXT PRIMARY KEY,
    path         TEXT NOT NULL,
    page_count   INTEGER NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dimensions (
    id               BIGSERIAL PRIMARY KEY,
    document_sha256  TEXT NOT NULL REFERENCES documents(sha256) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    description      TEXT NOT NULL DEFAULT '',
    approved         BOOLEAN NOT NULL DEFAULT false,
    UNIQUE (document_sha256, name)
);

CREATE TABLE IF NOT EXISTS kpis (
    id               BIGSERIAL PRIMARY KEY,
    document_sha256  TEXT NOT NULL REFERENCES documents(sha256) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    dimension        TEXT NOT NULL DEFAULT '',
    unit             TEXT NOT NULL DEFAULT '',
    description      TEXT NOT NULL DEFAULT '',
    approved         BOOLEAN NOT NULL DEFAULT false,
    UNIQUE (document_sha256, name)
);

CREATE TABLE IF NOT EXISTS interventions (
    id               BIGSERIAL PRIMARY KEY,
    document_sha256  TEXT NOT NULL REFERENCES documents(sha256) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    target_kpi       TEXT NOT NULL DEFAULT '',
    description      TEXT NOT NULL DEFAULT '',
    approved         BOOLEAN NOT NULL DEFAULT false,
    UNIQUE (document_sha256, name)
);
"""


def log(message: str) -> None:
    print(f"[pipeline] {message}", flush=True)


def read_pdf(path: Path) -> tuple[int, str]:
    log(f"Reading PDF with pypdf: {path}")
    reader = PdfReader(str(path))
    pages: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append(f"--- PAGE {index} ---\n{text}")
        log(f"  page {index}: {len(text)} characters")
    document = "\n\n".join(pages).strip()
    log(f"Extracted {len(reader.pages)} pages, {len(document)} characters")
    return len(reader.pages), document


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    log(f"SHA-256: {digest}")
    return digest


def _is_front_matter(chunk: str) -> bool:
    lower = chunk.lower()
    markers = ("table of contents", "isbn ", "all rights reserved", "acknowledgements", "cataloguing-in-publication")
    return any(marker in lower for marker in markers)


def select_chunks(chunks: list[str], limit: int = MAX_CHUNKS) -> list[str]:
    if len(chunks) <= limit:
        return chunks

    # Filter out obvious front-matter/TOC chunks when we have plenty of content
    body = [c for c in chunks if not _is_front_matter(c)]
    if len(body) < limit:
        body = chunks

    # Skip the very first 10% of chunks on very large reports (covers/forewords)
    if len(body) > limit * 2:
        skip = max(1, len(body) // 10)
        body = body[skip:]

    # Evenly sample across the body of the document
    step = (len(body) - 1) / max(limit - 1, 1)
    selected = [body[round(i * step)] for i in range(limit)]
    log(f"Selected {len(selected)} evenly spaced body chunks from {len(chunks)} total chunks")
    return selected


def chunk_text(text: str, size: int = CHUNK_CHARS) -> list[str]:
    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + size, length)
        if end < length:
            split = text.rfind("\n", start, end)
            if split <= start:
                split = text.rfind(" ", start, end)
            if split > start:
                end = split
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        start = end
    log(f"Split text into {len(chunks)} chunks of up to {size} characters")
    return select_chunks(chunks, MAX_CHUNKS)


def parse_extraction(content: str) -> ExtractionResult:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        fence = text.rfind("```")
        if fence >= 0:
            text = text[:fence]
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        return ExtractionResult.model_validate_json(text)
    except ValidationError:
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            return ExtractionResult()
        if not isinstance(raw, dict):
            return ExtractionResult()

        def _clean(items, model):
            valid = []
            for item in items if isinstance(items, list) else []:
                if isinstance(item, dict):
                    try:
                        valid.append(model.model_validate(item))
                    except ValidationError:
                        continue
            return valid

        return ExtractionResult(
            dimensions=_clean(raw.get("dimensions"), Dimension),
            kpis=_clean(raw.get("kpis"), KPI),
            interventions=_clean(raw.get("interventions"), Intervention),
        )


def extract_chunk(client: httpx.Client, chunk: str, index: int, total: int) -> ExtractionResult:
    log(f"Sending chunk {index}/{total} to Ollama {OLLAMA_MODEL} at {OLLAMA_CHAT_URL}")
    response = client.post(
        OLLAMA_CHAT_URL,
        json={
            "model": OLLAMA_MODEL,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": chunk},
            ],
        },
        timeout=180,
    )
    response.raise_for_status()
    content = response.json()["message"]["content"]
    result = parse_extraction(content)
    log(
        f"  chunk {index}: {len(result.dimensions)} dimensions, "
        f"{len(result.kpis)} KPIs, {len(result.interventions)} interventions"
    )
    return result


def ensure_schema(conn: psycopg.Connection) -> None:
    log(f"Ensuring PostgreSQL tables exist at {DATABASE_URL}")
    conn.execute(SCHEMA_SQL)
    conn.commit()


def document_exists(conn: psycopg.Connection, digest: str) -> bool:
    log("Checking PostgreSQL for an existing document with this SHA-256")
    row = conn.execute("SELECT path FROM documents WHERE sha256 = %s", (digest,)).fetchone()
    if row is None:
        log("No duplicate found. Continuing.")
        return False

    counts = conn.execute(
        """
        SELECT
            (SELECT count(*) FROM dimensions WHERE document_sha256 = %s) +
            (SELECT count(*) FROM kpis WHERE document_sha256 = %s) +
            (SELECT count(*) FROM interventions WHERE document_sha256 = %s)
        """,
        (digest, digest, digest),
    ).fetchone()
    if counts and counts[0] == 0:
        log(f"Document {row[0]} has 0 extractions. Clearing empty record to retry.")
        conn.execute("DELETE FROM documents WHERE sha256 = %s", (digest,))
        conn.commit()
        return False

    log(f"Duplicate document already stored as {row[0]}. Skipping extraction.")
    return True


def _named(items: list[Dimension] | list[KPI] | list[Intervention]):
    seen: set[str] = set()
    unique = []
    for item in items:
        name = item.name.strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        item.name = name
        unique.append(item)
    return unique


def save_postgres(
    conn: psycopg.Connection,
    digest: str,
    path: Path,
    page_count: int,
    merged: MergedExtraction,
) -> None:
    dimensions = _named(merged.dimensions)
    kpis = _named(merged.kpis)
    interventions = _named(merged.interventions)
    log(
        "Saving to PostgreSQL: "
        f"{len(dimensions)} dimensions, {len(kpis)} KPIs, {len(interventions)} interventions"
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents (sha256, path, page_count)
            VALUES (%s, %s, %s)
            ON CONFLICT (sha256) DO UPDATE SET path = EXCLUDED.path, page_count = EXCLUDED.page_count
            """,
            (digest, str(path), page_count),
        )
        for item in dimensions:
            cur.execute(
                """
                INSERT INTO dimensions (document_sha256, name, description, approved)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (document_sha256, name) DO NOTHING
                """,
                (digest, item.name, item.description, item.approved),
            )
        for item in kpis:
            cur.execute(
                """
                INSERT INTO kpis (document_sha256, name, dimension, unit, description, approved)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (document_sha256, name) DO NOTHING
                """,
                (digest, item.name, item.dimension, item.unit, item.description, item.approved),
            )
        for item in interventions:
            cur.execute(
                """
                INSERT INTO interventions (document_sha256, name, target_kpi, description, approved)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (document_sha256, name) DO NOTHING
                """,
                (digest, item.name, item.target_kpi, item.description, item.approved),
            )
    log("PostgreSQL rows staged")


def write_falkordb(digest: str, merged: MergedExtraction) -> None:
    dimensions = [item for item in _named(merged.dimensions) if item.approved]
    kpis = [item for item in _named(merged.kpis) if item.approved]
    interventions = [item for item in _named(merged.interventions) if item.approved]
    log(
        f"Writing approved nodes to FalkorDB {FALKORDB_HOST}:{FALKORDB_PORT} "
        f"graph {FALKORDB_GRAPH}: {len(dimensions)} dimensions, {len(kpis)} KPIs, "
        f"{len(interventions)} interventions"
    )
    graph = FalkorDB(host=FALKORDB_HOST, port=FALKORDB_PORT).select_graph(FALKORDB_GRAPH)
    for item in dimensions:
        log(f"  Dimension: {item.name}")
        graph.query(
            """
            MERGE (d:Dimension {name: $name})
            SET d.description = $description, d.document_sha256 = $sha256
            """,
            {"name": item.name, "description": item.description, "sha256": digest},
        )
    for item in kpis:
        log(f"  KPI: {item.name}")
        graph.query(
            """
            MERGE (k:KPI {name: $name})
            SET k.dimension = $dimension, k.unit = $unit,
                k.description = $description, k.document_sha256 = $sha256
            """,
            {
                "name": item.name,
                "dimension": item.dimension,
                "unit": item.unit,
                "description": item.description,
                "sha256": digest,
            },
        )
        if item.dimension.strip():
            graph.query(
                """
                MATCH (k:KPI {name: $kpi}), (d:Dimension {name: $dimension})
                MERGE (k)-[:BELONGS_TO]->(d)
                """,
                {"kpi": item.name, "dimension": item.dimension.strip()},
            )
    for item in interventions:
        log(f"  Intervention: {item.name}")
        graph.query(
            """
            MERGE (i:Intervention {name: $name})
            SET i.target_kpi = $target_kpi, i.description = $description,
                i.document_sha256 = $sha256
            """,
            {
                "name": item.name,
                "target_kpi": item.target_kpi,
                "description": item.description,
                "sha256": digest,
            },
        )
        if item.target_kpi.strip():
            graph.query(
                """
                MATCH (i:Intervention {name: $intervention}), (k:KPI {name: $kpi})
                MERGE (i)-[:TARGETS]->(k)
                """,
                {"intervention": item.name, "kpi": item.target_kpi.strip()},
            )
    log("FalkorDB write complete")


def run(pdf_path: str) -> None:
    path = Path(pdf_path)
    log(f"Starting pipeline for {path}")
    if not path.is_file():
        raise FileNotFoundError(f"PDF not found: {path}")

    page_count, text = read_pdf(path)
    if not text:
        log("PDF has no extractable text. Stopping.")
        return

    digest = sha256_file(path)
    with psycopg.connect(DATABASE_URL) as conn:
        ensure_schema(conn)
        if document_exists(conn, digest):
            return

        chunks = chunk_text(text)
        log(f"Sending {len(chunks)} chunk(s) to Ollama")
        merged = MergedExtraction()
        with httpx.Client() as client:
            for index, chunk in enumerate(chunks, start=1):
                merged.add(extract_chunk(client, chunk, index, len(chunks)))

        save_postgres(conn, digest, path, page_count, merged)
        write_falkordb(digest, merged)
        conn.commit()
        log("PostgreSQL commit complete")
    log("Finished")


def main() -> None:
    if len(sys.argv) != 2:
        print('Usage: python pipeline.py "docs/report.pdf"', file=sys.stderr)
        raise SystemExit(2)
    run(sys.argv[1])


if __name__ == "__main__":
    main()