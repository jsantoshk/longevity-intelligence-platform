"""Serve the Longevity Intelligence Platform (LIP) API Gateway, Hybrid Router, and local AI engine."""

import json
import os
import re
import secrets
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import psycopg
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from falkordb import FalkorDB
from falkordb.node import Node
from pydantic import BaseModel
from schemas import MergedExtraction

from pipeline import (
    DATABASE_URL,
    FALKORDB_GRAPH,
    FALKORDB_HOST,
    FALKORDB_PORT,
    MAX_CHUNKS,
    OLLAMA_CHAT_URL,
    OLLAMA_MODEL,
    _named,
    chunk_text,
    document_exists,
    ensure_schema,
    extract_chunk,
    read_pdf,
    save_postgres,
    sha256_file,
    write_falkordb,
)

ROOT = Path(__file__).resolve().parent
DASHBOARD = ROOT / "longevity_intelligence_platform.html"
UPLOADS = ROOT / "docs" / "uploads"

# OpenAI-compatible local inference endpoint (works with Ollama today & vLLM in production)
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", OLLAMA_MODEL)
OLLAMA_EMBED_URL = os.getenv("OLLAMA_EMBED_URL", "http://localhost:11434/api/embed")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

# Optional frontier escalation keys for 20% hybrid reasoning
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
DEFAULT_DEV_KEY = "lip_dev_default_key"

STAGES = [
    "Receive",
    "Validate",
    "Fingerprint",
    "Deduplicate",
    "Parse",
    "Chunk",
    "Extract",
    "Normalize",
    "Store",
    "Graph",
    "Publish",
]

jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()
telemetry_lock = threading.Lock()
telemetry = {"calls": 0, "errors": 0, "total_ms": 0.0}


def _clean_doc_name(path_str: str) -> str:
    name = Path(path_str).name
    return re.sub(r"^[0-9a-f]{32}_", "", name)


def _ensure_vector_and_gateway_schema(conn) -> None:
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS document_chunks (
            id SERIAL PRIMARY KEY,
            document_sha256 TEXT NOT NULL REFERENCES documents(sha256) ON DELETE CASCADE,
            chunk_index INT NOT NULL,
            content TEXT NOT NULL,
            embedding vector(768) NOT NULL
        )
        """
    )
    conn.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS city TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS country TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS sector TEXT NOT NULL DEFAULT 'General'")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS api_clients (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            api_key TEXT NOT NULL UNIQUE,
            tier TEXT NOT NULL DEFAULT 'subscription',
            sector TEXT NOT NULL DEFAULT 'General',
            active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS api_usage (
            id SERIAL PRIMARY KEY,
            client_id INT REFERENCES api_clients(id) ON DELETE SET NULL,
            endpoint TEXT NOT NULL,
            status_code INT NOT NULL,
            latency_ms DOUBLE PRECISION NOT NULL,
            tokens_saved INT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    # Automatically migrate legacy starter key if present
    conn.execute(
        """
        UPDATE api_clients
        SET name = %s, api_key = %s, sector = %s
        WHERE api_key = 'lip_dev_seniorhub_key'
        """,
        ("LIP Default Client", DEFAULT_DEV_KEY, "General"),
    )
    count = conn.execute("SELECT count(*) FROM api_clients").fetchone()[0]
    if count == 0:
        conn.execute(
            """
            INSERT INTO api_clients (name, api_key, tier, sector)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (api_key) DO NOTHING
            """,
            ("LIP Default Client", DEFAULT_DEV_KEY, "subscription", "General"),
        )


def _embed_text(text: str, prefix: str = "search_document: ") -> list[float] | None:
    try:
        res = httpx.post(
            OLLAMA_EMBED_URL,
            json={"model": EMBED_MODEL, "input": f"{prefix}{text[:4000]}"},
            timeout=60,
        )
        res.raise_for_status()
        embeddings = res.json().get("embeddings") or []
        return embeddings[0] if embeddings else None
    except Exception:
        return None


def _vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def _call_local_llm(system_prompt: str, user_prompt: str) -> str:
    """Call local SLM via OpenAI-compatible API (supports both Ollama and vLLM)."""
    res = httpx.post(
        f"{LLM_BASE_URL}/chat/completions",
        json={
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        },
        timeout=180,
    )
    res.raise_for_status()
    return res.json()["choices"][0]["message"]["content"]


def _call_frontier_llm(provider: str, system_prompt: str, user_prompt: str) -> tuple[str, str] | None:
    """Escalate pre-compressed evidence packet to Claude or Mistral (20% hybrid path)."""
    p = provider.lower().strip()
    if p == "claude" and ANTHROPIC_API_KEY:
        model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
        res = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 1024,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            },
            timeout=90,
        )
        res.raise_for_status()
        return res.json()["content"][0]["text"], f"anthropic/{model}"

    if p == "mistral" and MISTRAL_API_KEY:
        model = os.getenv("MISTRAL_MODEL", "mistral-large-latest")
        res = httpx.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {MISTRAL_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.2,
            },
            timeout=90,
        )
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"], f"mistral/{model}"

    return None


def _stage_list() -> list[dict]:
    return [
        {"id": index + 1, "name": name, "state": "pending", "detail": ""}
        for index, name in enumerate(STAGES)
    ]


def _update(job_id: str, **fields) -> None:
    with jobs_lock:
        jobs[job_id].update(fields)


def _mark(job_id: str, index: int, state: str, detail: str = "") -> None:
    with jobs_lock:
        stage = jobs[job_id]["stages"][index]
        stage["state"] = state
        stage["detail"] = detail


def _job_snapshot(job_id: str) -> dict:
    with jobs_lock:
        job = jobs[job_id]
        return {
            "id": job_id,
            "status": job["status"],
            "filename": job["filename"],
            "error": job["error"],
            "duplicate": job["duplicate"],
            "sha256": job["sha256"],
            "counts": dict(job["counts"]),
            "stages": [dict(stage) for stage in job["stages"]],
        }


def _skip_rest(job_id: str, start: int, detail: str) -> None:
    for index in range(start, len(STAGES) - 1):
        _mark(job_id, index, "skipped", detail)
    _mark(job_id, len(STAGES) - 1, "done", detail)


def process_pdf(
    job_id: str,
    path: Path,
    city: str = "",
    country: str = "",
    sector: str = "General",
) -> None:
    try:
        _mark(job_id, 0, "done", _clean_doc_name(str(path)))
        data = path.read_bytes()
        _mark(job_id, 1, "active", "Checking PDF header")
        if not data.startswith(b"%PDF"):
            raise ValueError("File is not a PDF")
        _mark(job_id, 1, "done", "PDF header confirmed")

        _mark(job_id, 2, "active", "Hashing file")
        digest = sha256_file(path)
        _update(job_id, sha256=digest)
        _mark(job_id, 2, "done", digest[:16])

        _mark(job_id, 3, "active", "Looking up SHA-256")
        with psycopg.connect(DATABASE_URL) as conn:
            ensure_schema(conn)
            _ensure_vector_and_gateway_schema(conn)
            if document_exists(conn, digest):
                _mark(job_id, 3, "done", "Duplicate found")
                _update(job_id, duplicate=True, status="done")
                _skip_rest(job_id, 4, "Already stored")
                return
            _mark(job_id, 3, "done", "New document")

            _mark(job_id, 4, "active", "Reading pages")
            page_count, text = read_pdf(path)
            if not text:
                raise ValueError("PDF has no extractable text")
            _mark(job_id, 4, "done", f"{page_count} pages")

            _mark(job_id, 5, "active", "Splitting text")
            chunks = chunk_text(text)[:MAX_CHUNKS]
            _mark(job_id, 5, "done", f"{len(chunks)} chunks")

            _mark(job_id, 6, "active", f"Ollama {OLLAMA_MODEL}")
            merged = MergedExtraction()
            with httpx.Client() as client:
                for index, chunk in enumerate(chunks, start=1):
                    _mark(job_id, 6, "active", f"Chunk {index}/{len(chunks)}")
                    merged.add(extract_chunk(client, chunk, index, len(chunks)))
            _mark(job_id, 6, "done", f"{len(chunks)} chunks extracted")

            _mark(job_id, 7, "active", "Deduplicating names")
            dimensions = _named(merged.dimensions)
            kpis = _named(merged.kpis)
            interventions = _named(merged.interventions)
            counts = {
                "dimensions": len(dimensions),
                "kpis": len(kpis),
                "interventions": len(interventions),
            }
            _update(job_id, counts=counts)
            _mark(
                job_id,
                7,
                "done",
                f"{counts['dimensions']} dimensions, {counts['kpis']} KPIs, "
                f"{counts['interventions']} interventions",
            )

            _mark(job_id, 8, "active", "Writing PostgreSQL & Vectors")
            save_postgres(conn, digest, path, page_count, merged)
            conn.execute(
                "UPDATE documents SET city = %s, country = %s, sector = %s WHERE sha256 = %s",
                (city.strip(), country.strip(), sector.strip() or "General", digest),
            )
            embedded_count = 0
            for idx, chunk in enumerate(chunks, start=1):
                vec = _embed_text(chunk, prefix="search_document: ")
                if vec:
                    conn.execute(
                        "INSERT INTO document_chunks (document_sha256, chunk_index, content, embedding) VALUES (%s, %s, %s, %s::vector)",
                        (digest, idx, chunk, _vec_literal(vec)),
                    )
                    embedded_count += 1
            _mark(job_id, 8, "done", f"Rows + {embedded_count} vectors")

            _mark(job_id, 9, "active", f"Graph {FALKORDB_GRAPH}")
            write_falkordb(digest, merged)
            _mark(job_id, 9, "done", "Approved nodes written")

            conn.commit()
            _mark(job_id, 10, "done", "Published to the dashboard")
            _update(job_id, status="done")
    except Exception as exc:
        _update(job_id, status="error", error=str(exc))
        with jobs_lock:
            for stage in jobs[job_id]["stages"]:
                if stage["state"] == "active":
                    stage["state"] = "error"
                    stage["detail"] = str(exc)
                    break


def _postgres_ok() -> dict:
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        return {"ok": True, "database": "longevity_db"}
    except Exception as exc:
        return {"ok": False, "database": "longevity_db", "error": str(exc)}


def _falkordb_ok() -> dict:
    try:
        FalkorDB(host=FALKORDB_HOST, port=FALKORDB_PORT).select_graph(FALKORDB_GRAPH).query(
            "RETURN 1"
        )
        return {"ok": True, "graph": FALKORDB_GRAPH}
    except Exception as exc:
        return {"ok": False, "graph": FALKORDB_GRAPH, "error": str(exc)}


def _ollama_ok() -> dict:
    try:
        response = httpx.get("http://localhost:11434/api/tags", timeout=3)
        response.raise_for_status()
        names = [item.get("name", "") for item in response.json().get("models", [])]
        present = any(name == LLM_MODEL or name.startswith(f"{LLM_MODEL}-") for name in names)
        embed_present = any(name.startswith(EMBED_MODEL) for name in names)
        return {"ok": True, "model": LLM_MODEL, "installed": present, "embed_installed": embed_present}
    except Exception as exc:
        return {"ok": False, "model": LLM_MODEL, "error": str(exc)}


def _connect():
    conn = psycopg.connect(DATABASE_URL, connect_timeout=3)
    ensure_schema(conn)
    _ensure_vector_and_gateway_schema(conn)
    return conn


def _log_usage(client_id: int | None, endpoint: str, status_code: int, latency_ms: float, tokens_saved: int = 0) -> None:
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=2) as conn:
            conn.execute(
                """
                INSERT INTO api_usage (client_id, endpoint, status_code, latency_ms, tokens_saved)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (client_id, endpoint, status_code, latency_ms, tokens_saved),
            )
            conn.commit()
    except Exception:
        pass


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict:
    """Authenticate external/internal platform clients calling ring-fenced /api/v1/* routes."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT id, name, tier, sector FROM api_clients WHERE api_key = %s AND active = true",
                (x_api_key.strip(),),
            ).fetchone()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=403, detail="Invalid or inactive API key")
    return {"id": row[0], "name": row[1], "tier": row[2], "sector": row[3]}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    UPLOADS.mkdir(parents=True, exist_ok=True)
    try:
        with _connect() as conn:
            conn.commit()
    except Exception:
        pass
    yield


app = FastAPI(title="Longevity Intelligence Platform (LIP)", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def track_api_telemetry(request: Request, call_next):
    start = time.perf_counter()
    status = 200
    try:
        response = await call_next(request)
        status = response.status_code
    except Exception:
        status = 500
        raise
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        path = request.url.path
        if path.startswith("/api/"):
            with telemetry_lock:
                telemetry["calls"] += 1
                telemetry["total_ms"] += elapsed_ms
                if status >= 400:
                    telemetry["errors"] += 1
            if path.startswith("/api/v1/"):
                tokens_saved = getattr(request.state, "tokens_saved", None)
                if tokens_saved is None:
                    tokens_saved = 12000 if ("search" in path or "reason" in path) else 2500
                client_id = getattr(request.state, "client_id", None)
                _log_usage(client_id, path, status, elapsed_ms, tokens_saved if status < 400 else 0)
    return response


class ChatRequest(BaseModel):
    message: str


class ApprovalRequest(BaseModel):
    kind: str
    name: str
    sha256: str
    approved: bool


class ClientCreateRequest(BaseModel):
    name: str
    tier: str = "subscription"
    sector: str = "General"


class ReasonRequest(BaseModel):
    query: str
    mode: str = "local"  # "local" (80% default) or "hybrid" (20% frontier escalation)
    frontier_provider: str = "claude"  # "claude" or "mistral"
    city: str | None = None
    sector: str | None = None
    # Ephemeral SOLID-PODS personal context (processed in-memory only, never stored)
    user_context: dict[str, Any] | None = None


@app.get("/manifest.json")
def manifest():
    return FileResponse(ROOT / "manifest.json", media_type="application/manifest+json")

@app.get("/")
def dashboard():
    return FileResponse(DASHBOARD)


@app.get("/api/health")
def health():
    return {
        "postgres": _postgres_ok(),
        "falkordb": _falkordb_ok(),
        "ollama": _ollama_ok(),
        "inference_backend": LLM_BASE_URL,
    }


def _semantic_search(
    query: str,
    limit: int = 5,
    city: str | None = None,
    sector: str | None = None,
) -> list[dict]:
    vec = _embed_text(query, prefix="search_query: ")
    if not vec:
        return []
    vec_str = _vec_literal(vec)
    clauses = []
    params: list = [vec_str]
    if city:
        clauses.append("LOWER(doc.city) = LOWER(%s)")
        params.append(city.strip())
    if sector:
        clauses.append("LOWER(doc.sector) = LOWER(%s)")
        params.append(sector.strip())
    where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.extend([vec_str, limit])

    try:
        with _connect() as conn:
            rows = conn.execute(
                f"""
                SELECT doc.path, c.chunk_index, c.content,
                       1 - (c.embedding <=> %s::vector) AS similarity,
                       doc.city, doc.country, doc.sector
                FROM document_chunks c
                JOIN documents doc ON doc.sha256 = c.document_sha256
                {where_sql}
                ORDER BY c.embedding <=> %s::vector
                LIMIT %s
                """,
                tuple(params),
            ).fetchall()
        return [
            {
                "document": _clean_doc_name(r[0]),
                "chunk": r[1],
                "content": r[2][:500],
                "score": round(float(r[3]), 3),
                "city": r[4],
                "country": r[5],
                "sector": r[6],
            }
            for r in rows
        ]
    except Exception:
        return []


@app.get("/api/search")
def search(
    q: str = Query(..., min_length=2),
    limit: int = 5,
    city: str | None = None,
    sector: str | None = None,
):
    """Semantic vector search across all ingested PDF chunks using pgvector."""
    results = _semantic_search(q, limit=min(limit, 20), city=city, sector=sector)
    return {"query": q, "model": EMBED_MODEL, "results": results}


# --- RING-FENCED COMMERCIAL GATEWAY (/api/v1/*) ---

@app.get("/api/v1/clients")
def list_clients():
    """List registered B2B/B2G API clients and their billing tiers."""
    try:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT c.id, c.name, c.api_key, c.tier, c.sector, c.active, c.created_at,
                       COUNT(u.id) AS calls, COALESCE(SUM(u.tokens_saved), 0) AS tokens_saved
                FROM api_clients c
                LEFT JOIN api_usage u ON u.client_id = c.id
                GROUP BY c.id
                ORDER BY c.created_at DESC
                """
            ).fetchall()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "clients": [
            {
                "id": r[0],
                "name": r[1],
                "api_key_preview": r[2][:10] + "…" + r[2][-4:],
                "tier": r[3],
                "sector": r[4],
                "active": r[5],
                "created_at": r[6].isoformat(),
                "calls": r[7],
                "tokens_saved": r[8],
            }
            for r in rows
        ]
    }


@app.post("/api/v1/clients")
def create_client(body: ClientCreateRequest):
    """Mint a new X-API-Key for an internal or external platform client."""
    tier = body.tier if body.tier in ("subscription", "per_access") else "subscription"
    api_key = f"lip_{secrets.token_hex(16)}"
    try:
        with _connect() as conn:
            row = conn.execute(
                """
                INSERT INTO api_clients (name, api_key, tier, sector)
                VALUES (%s, %s, %s, %s)
                RETURNING id, created_at
                """,
                (body.name.strip(), api_key, tier, body.sector.strip() or "General"),
            ).fetchone()
            conn.commit()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "id": row[0],
        "name": body.name.strip(),
        "api_key": api_key,
        "tier": tier,
        "sector": body.sector.strip(),
        "created_at": row[1].isoformat(),
    }


@app.get("/api/v1/search")
def v1_search(
    request: Request,
    q: str = Query(..., min_length=2),
    limit: int = 5,
    city: str | None = None,
    sector: str | None = None,
    client: dict = Depends(require_api_key),
):
    """Ring-fenced semantic search endpoint for external platforms (requires X-API-Key)."""
    request.state.client_id = client["id"]
    results = _semantic_search(q, limit=min(limit, 20), city=city, sector=sector)
    return {
        "client": client["name"],
        "tier": client["tier"],
        "query": q,
        "model": EMBED_MODEL,
        "results": results,
    }


@app.post("/api/v1/reason")
def v1_reason(
    request: Request,
    body: ReasonRequest,
    client: dict = Depends(require_api_key),
):
    """80/20 Hybrid Reasoning Engine with stateless SOLID-PODS user_context injection."""
    request.state.client_id = client["id"]
    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is empty")

    hits = _semantic_search(query, limit=4, city=body.city, sector=body.sector)
    ontology_ctx = _context()
    passages_txt = (
        "\n\n".join(
            f"[{h['document']} | chunk {h['chunk']} | match {h['score']}]\n{h['content']}"
            for h in hits
        )
        if hits
        else "No vector passages indexed yet."
    )

    solid_block = ""
    if body.user_context:
        solid_block = (
            "\n\nEphemeral User Context (from consented SOLID Pod — personalize guidance "
            "responsibly and do not fabricate clinical diagnoses):\n"
            + json.dumps(body.user_context, ensure_ascii=False)[:1500]
        )

    system_prompt = (
        "You are the Longevity Intelligence Platform (LIP) composite reasoning engine. "
        "Provide evidence-grounded, actionable guidance strictly using the approved ontology "
        "and retrieved passages below. Always cite exact source filenames in brackets—e.g. [report.pdf]. "
        "If ephemeral user context is supplied, tailor recommendations to it safely.\n\n"
        f"Approved Longevity Ontology:\n{ontology_ctx}\n\n"
        f"Top Semantic Passages:\n{passages_txt}"
        f"{solid_block}"
    )

    mode_requested = body.mode.lower().strip()
    mode_executed = "local"
    model_used = f"local/{LLM_MODEL}"
    fallback_note = ""

    try:
        if mode_requested == "hybrid":
            frontier = _call_frontier_llm(body.frontier_provider, system_prompt, query)
            if frontier:
                answer, model_used = frontier
                mode_executed = "hybrid"
            else:
                answer = _call_local_llm(system_prompt, query)
                fallback_note = f"Frontier key for '{body.frontier_provider}' not configured; executed locally."
        else:
            answer = _call_local_llm(system_prompt, query)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Inference error: {exc}") from exc

    tokens_saved = 45000 if mode_executed == "local" else 38000
    request.state.tokens_saved = tokens_saved

    return {
        "client": client["name"],
        "tier": client["tier"],
        "mode_requested": mode_requested,
        "mode_executed": mode_executed,
        "model_used": model_used,
        "fallback_note": fallback_note or None,
        "pii_stored": False,
        "solid_pod_context_used": bool(body.user_context),
        "evidence_hits": len(hits),
        "tokens_saved_estimate": tokens_saved,
        "answer": answer,
    }


@app.get("/api/v1/usage")
def v1_usage(request: Request, client: dict = Depends(require_api_key)):
    """Return persistent usage and frontier token cost savings for the authenticated client."""
    request.state.client_id = client["id"]
    try:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*), COALESCE(AVG(latency_ms), 0), COALESCE(SUM(tokens_saved), 0)
                FROM api_usage
                WHERE client_id = %s
                """,
                (client["id"],),
            ).fetchone()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    tokens_saved = int(row[2])
    est_usd_saved = round((tokens_saved / 1_000_000) * 10.0, 4)
    return {
        "client": client["name"],
        "tier": client["tier"],
        "total_calls": row[0],
        "avg_latency_ms": round(float(row[1]), 1),
        "tokens_saved": tokens_saved,
        "est_frontier_cost_saved_usd": est_usd_saved,
    }


@app.get("/api/metrics")
def metrics():
    """Return stable LIP component health, maturity, and telemetry for web & mobile apps."""
    doc_count = page_count = dim_count = kpi_count = int_count = approved_count = 0
    edge_count = vector_count = client_count = total_tokens_saved = 0

    try:
        with _connect() as conn:
            doc_count, page_count = conn.execute(
                "SELECT count(*), COALESCE(sum(page_count), 0) FROM documents"
            ).fetchone()
            dim_count = conn.execute("SELECT count(*) FROM dimensions").fetchone()[0]
            kpi_count = conn.execute("SELECT count(*) FROM kpis").fetchone()[0]
            int_count = conn.execute("SELECT count(*) FROM interventions").fetchone()[0]
            vector_count = conn.execute("SELECT count(*) FROM document_chunks").fetchone()[0]
            client_count = conn.execute("SELECT count(*) FROM api_clients WHERE active = true").fetchone()[0]
            total_tokens_saved = conn.execute("SELECT COALESCE(SUM(tokens_saved), 0) FROM api_usage").fetchone()[0]
            approved_count = conn.execute(
                """
                SELECT
                    (SELECT count(*) FROM dimensions WHERE approved = true) +
                    (SELECT count(*) FROM kpis WHERE approved = true) +
                    (SELECT count(*) FROM interventions WHERE approved = true)
                """
            ).fetchone()[0]
    except Exception:
        pass

    try:
        selected = FalkorDB(host=FALKORDB_HOST, port=FALKORDB_PORT).select_graph(FALKORDB_GRAPH)
        res = selected.query("MATCH ()-[r]->() RETURN count(r)").result_set
        edge_count = int(res[0][0]) if res else 0
    except Exception:
        pass

    entities = dim_count + kpi_count + int_count
    coverage = round((approved_count / entities) * 100) if entities else 0
    est_tokens = int(page_count) * 450

    with telemetry_lock:
        calls = telemetry["calls"]
        avg_latency = round(telemetry["total_ms"] / calls) if calls else 0
        error_rate = round((telemetry["errors"] / calls) * 100, 1) if calls else 0.0

    ollama = _ollama_ok()
    models_count = (1 if ollama.get("installed") else 0) + (1 if ollama.get("embed_installed") else 0)

    ontology_pct = min(100, 20 + min(80, entities * 4)) if entities else 10
    corpus_pct = min(100, 20 + min(60, doc_count * 15) + (20 if vector_count > 0 else 0)) if doc_count else 10
    ai_pct = 70 if models_count >= 2 else (40 if ollama.get("ok") else 10)
    app_pct = 75 if (client_count > 0 and error_rate < 5.0 and doc_count > 0) else 40
    maturity = round((ontology_pct + corpus_pct + ai_pct + app_pct) / 4)

    return {
        "maturity": maturity,
        "ontology": {
            "entities": entities,
            "relationships": edge_count,
            "coverage": coverage,
            "roadmap": ontology_pct,
        },
        "corpus": {
            "documents": doc_count,
            "pages": page_count,
            "tokens": est_tokens,
            "vectors": vector_count,
            "avg_quality": coverage if entities else 0,
            "roadmap": corpus_pct,
        },
        "ai_layer": {
            "models": models_count,
            "active_model": LLM_MODEL,
            "embed_model": EMBED_MODEL,
            "evaluations": 1 if entities else 0,
            "avg_score": coverage if entities else 0,
            "roadmap": ai_pct,
        },
        "applications": {
            "api_calls": calls,
            "active_clients": client_count,
            "tokens_saved": int(total_tokens_saved),
            "avg_latency_ms": avg_latency,
            "error_rate": error_rate,
            "roadmap": app_pct,
        },
    }


@app.get("/api/extractions")
def extractions():
    query = """
        SELECT kind, name, detail, extra, approved, path, sha256
        FROM (
            SELECT 'Dimension' AS kind, d.name, d.description AS detail, '' AS extra,
                   d.approved, doc.path, doc.sha256
            FROM dimensions d
            JOIN documents doc ON doc.sha256 = d.document_sha256
            UNION ALL
            SELECT 'KPI', k.name, k.description, trim(both ' · ' FROM concat_ws(' · ', k.dimension, k.unit)),
                   k.approved, doc.path, doc.sha256
            FROM kpis k
            JOIN documents doc ON doc.sha256 = k.document_sha256
            UNION ALL
            SELECT 'Intervention', i.name, i.description, i.target_kpi,
                   i.approved, doc.path, doc.sha256
            FROM interventions i
            JOIN documents doc ON doc.sha256 = i.document_sha256
        ) rows
        ORDER BY kind, name
    """
    try:
        with _connect() as conn:
            rows = conn.execute(query).fetchall()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "items": [
            {
                "kind": row[0],
                "name": row[1],
                "detail": row[2],
                "extra": row[3],
                "approved": row[4],
                "document": _clean_doc_name(row[5]),
                "sha256": row[6],
            }
            for row in rows
        ]
    }


@app.post("/api/extractions/approve")
def toggle_approval(body: ApprovalRequest):
    table_map = {
        "Dimension": "dimensions",
        "KPI": "kpis",
        "Intervention": "interventions",
    }
    table = table_map.get(body.kind)
    if not table:
        raise HTTPException(status_code=400, detail="Invalid kind")

    try:
        with _connect() as conn:
            conn.execute(
                f"UPDATE {table} SET approved = %s WHERE document_sha256 = %s AND name = %s",
                (body.approved, body.sha256, body.name),
            )
            still_approved = conn.execute(
                f"SELECT count(*) FROM {table} WHERE name = %s AND approved = true",
                (body.name,),
            ).fetchone()[0]

            row = None
            if body.approved:
                if body.kind == "Dimension":
                    row = conn.execute(
                        "SELECT description FROM dimensions WHERE document_sha256 = %s AND name = %s",
                        (body.sha256, body.name),
                    ).fetchone()
                elif body.kind == "KPI":
                    row = conn.execute(
                        "SELECT dimension, unit, description FROM kpis WHERE document_sha256 = %s AND name = %s",
                        (body.sha256, body.name),
                    ).fetchone()
                elif body.kind == "Intervention":
                    row = conn.execute(
                        "SELECT target_kpi, description FROM interventions WHERE document_sha256 = %s AND name = %s",
                        (body.sha256, body.name),
                    ).fetchone()
            conn.commit()

        graph = FalkorDB(host=FALKORDB_HOST, port=FALKORDB_PORT).select_graph(FALKORDB_GRAPH)
        if not body.approved and still_approved == 0:
            graph.query(
                f"MATCH (n:{body.kind} {{name: $name}}) DETACH DELETE n",
                {"name": body.name},
            )
        elif body.approved and row is not None:
            if body.kind == "Dimension":
                graph.query(
                    "MERGE (d:Dimension {name: $name}) SET d.description = $desc, d.document_sha256 = $sha",
                    {"name": body.name, "desc": row[0], "sha": body.sha256},
                )
            elif body.kind == "KPI":
                dim, unit, desc = row
                graph.query(
                    "MERGE (k:KPI {name: $name}) SET k.dimension = $dim, k.unit = $unit, k.description = $desc, k.document_sha256 = $sha",
                    {"name": body.name, "dim": dim, "unit": unit, "desc": desc, "sha": body.sha256},
                )
                if dim.strip():
                    graph.query(
                        "MATCH (k:KPI {name: $kpi}), (d:Dimension {name: $dim}) MERGE (k)-[:BELONGS_TO]->(d)",
                        {"kpi": body.name, "dim": dim.strip()},
                    )
            elif body.kind == "Intervention":
                target_kpi, desc = row
                graph.query(
                    "MERGE (i:Intervention {name: $name}) SET i.target_kpi = $kpi, i.description = $desc, i.document_sha256 = $sha",
                    {"name": body.name, "kpi": target_kpi, "desc": desc, "sha": body.sha256},
                )
                if target_kpi.strip():
                    graph.query(
                        "MATCH (i:Intervention {name: $iv}), (k:KPI {name: $kpi}) MERGE (i)-[:TARGETS]->(k)",
                        {"iv": body.name, "kpi": target_kpi.strip()},
                    )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"ok": True, "approved": body.approved}


@app.get("/api/documents")
def documents():
    query = """
        SELECT doc.sha256, doc.path, doc.page_count, doc.created_at,
               doc.city, doc.country, doc.sector,
               (SELECT count(*) FROM dimensions d WHERE d.document_sha256 = doc.sha256),
               (SELECT count(*) FROM kpis k WHERE k.document_sha256 = doc.sha256),
               (SELECT count(*) FROM interventions i WHERE i.document_sha256 = doc.sha256)
        FROM documents doc
        ORDER BY doc.created_at DESC
    """
    try:
        with _connect() as conn:
            rows = conn.execute(query).fetchall()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "documents": [
            {
                "sha256": row[0],
                "name": _clean_doc_name(row[1]),
                "pages": row[2],
                "created_at": row[3].isoformat(),
                "city": row[4],
                "country": row[5],
                "sector": row[6],
                "dimensions": row[7],
                "kpis": row[8],
                "interventions": row[9],
            }
            for row in rows
        ]
    }


@app.delete("/api/documents/{sha256}")
def delete_document(sha256: str):
    """Remove a document and its nodes from PostgreSQL and FalkorDB."""
    try:
        with _connect() as conn:
            conn.execute("DELETE FROM documents WHERE sha256 = %s", (sha256,))
            conn.commit()
        graph = FalkorDB(host=FALKORDB_HOST, port=FALKORDB_PORT).select_graph(FALKORDB_GRAPH)
        graph.query("MATCH (n {document_sha256: $sha}) DETACH DELETE n", {"sha": sha256})
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True}


def _node_payload(node: Node) -> dict:
    labels = node.labels or ["Entity"]
    properties = {}
    for key, value in (node.properties or {}).items():
        if isinstance(value, bytes):
            value = value.decode()
        properties[str(key)] = value
    return {
        "id": node.id,
        "label": labels[0],
        "name": str(properties.get("name") or node.id),
        "properties": properties,
    }


@app.get("/api/graph")
def graph():
    try:
        selected = FalkorDB(host=FALKORDB_HOST, port=FALKORDB_PORT).select_graph(FALKORDB_GRAPH)
        nodes: dict[int, dict] = {}
        for row in selected.query("MATCH (n) RETURN n").result_set:
            if isinstance(row[0], Node):
                payload = _node_payload(row[0])
                nodes[payload["id"]] = payload
        edges = []
        for row in selected.query("MATCH (a)-[r]->(b) RETURN a, r, b").result_set:
            source, relation, target = row
            if not isinstance(source, Node) or not isinstance(target, Node):
                continue
            edges.append(
                {
                    "source": source.id,
                    "target": target.id,
                    "type": getattr(relation, "relation", str(relation)),
                }
            )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"nodes": list(nodes.values()), "edges": edges}


@app.post("/api/upload")
async def upload(
    file: UploadFile = File(...),
    city: str = Form(default=""),
    country: str = Form(default=""),
    sector: str = Form(default="General"),
):
    name = Path(file.filename or "report.pdf").name
    if not name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Upload a PDF file")
    job_id = uuid.uuid4().hex
    path = UPLOADS / f"{job_id}_{name}"
    path.write_bytes(await file.read())
    with jobs_lock:
        jobs[job_id] = {
            "status": "running",
            "filename": name,
            "error": "",
            "duplicate": False,
            "sha256": "",
            "counts": {"dimensions": 0, "kpis": 0, "interventions": 0},
            "stages": _stage_list(),
        }
    _mark(job_id, 0, "active", name)
    threading.Thread(
        target=process_pdf,
        args=(job_id, path, city, country, sector),
        daemon=True,
    ).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job(job_id: str):
    with jobs_lock:
        if job_id not in jobs:
            raise HTTPException(status_code=404, detail="Job not found")
    return _job_snapshot(job_id)


def _context() -> str:
    try:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT 'Dimension' AS kind, d.name, '' AS link, d.description, doc.path
                FROM dimensions d
                JOIN documents doc ON doc.sha256 = d.document_sha256
                WHERE d.approved = true
                UNION ALL
                SELECT 'KPI', k.name, k.dimension, k.description, doc.path
                FROM kpis k
                JOIN documents doc ON doc.sha256 = k.document_sha256
                WHERE k.approved = true
                UNION ALL
                SELECT 'Intervention', i.name, i.target_kpi, i.description, doc.path
                FROM interventions i
                JOIN documents doc ON doc.sha256 = i.document_sha256
                WHERE i.approved = true
                ORDER BY kind, name
                LIMIT 60
                """
            ).fetchall()
    except Exception as exc:
        return f"Stored extractions are unavailable: {exc}"
    if not rows:
        return "No approved extractions are stored yet."
    lines = [
        f"[{_clean_doc_name(path)}] {kind}: {name}"
        + (f" (linked to: {link})" if link else "")
        + f" — {description}"
        for kind, name, link, description, path in rows
    ]
    return "\n".join(lines)


@app.post("/api/chat")
def chat(body: ChatRequest):
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is empty")

    hits = _semantic_search(message, limit=4)
    passages = (
        "\n\n".join(
            f"[{h['document']} | chunk {h['chunk']} | match {h['score']}]\n{h['content']}"
            for h in hits
        )
        if hits
        else "No vector passages indexed yet."
    )
    system_prompt = (
        "You are the Longevity Intelligence Platform assistant. "
        "Answer strictly using the approved stored extractions and semantic passages below. "
        "Always cite the exact source document name in brackets—e.g. [report.pdf]—"
        "next to every fact, KPI, or intervention you mention. "
        "Never attribute facts from one document to a different document. "
        "If the provided context does not contain the answer, say so clearly.\n\n"
        f"Approved stored extractions:\n{_context()}\n\n"
        f"Top semantic passages from PDFs:\n{passages}"
    )

    try:
        reply = _call_local_llm(system_prompt, message)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"reply": reply, "model": LLM_MODEL, "semantic_hits": len(hits)}

    # --- SPRINT 3: GAP & POLICY INTELLIGENCE + SLM TRAINING EXPORT ---

class GapAnalysisRequest(BaseModel):
    entity_name: str  # e.g., "Cardiff City Council" or "Oakwood Care Group"
    sector: str = "Local Government"
    city: str = ""
    country: str = ""
    current_state: str = ""  # Summary of current infrastructure, metrics, or services
    challenges: list[str] = []  # e.g., ["high fall rates", "social isolation"]
    mode: str = "local"  # "local" or "hybrid"
    frontier_provider: str = "claude"


@app.post("/api/v1/analyze/gaps")
def v1_analyze_gaps(
    request: Request,
    body: GapAnalysisRequest,
    client: dict = Depends(require_api_key),
):
    """Compare a client's profile against the global LIP corpus to output structured gap & policy intelligence."""
    request.state.client_id = client["id"]
    search_query = " ".join(
        filter(None, [body.sector, body.city, body.current_state, " ".join(body.challenges)])
    ).strip() or "age-friendly healthy ageing policy interventions"

    hits = _semantic_search(search_query, limit=6)
    ontology_ctx = _context()
    passages_txt = (
        "\n\n".join(
            f"[{h['document']} | chunk {h['chunk']} | match {h['score']}]\n{h['content']}"
            for h in hits
        )
        if hits
        else "No vector passages indexed yet."
    )

    system_prompt = (
        "You are the Longevity Intelligence Platform (LIP) Gap & Policy Analysis Engine. "
        "Analyze the client profile against the approved global longevity ontology and corpus passages below. "
        "Return ONLY valid JSON with exactly these four keys:\n"
        '  "key_gaps": [{"gap": str, "evidence": str, "source": str}],\n'
        '  "priority_interventions": [{"intervention": str, "target_kpi": str, "expected_impact": str, "source": str}],\n'
        '  "service_opportunities": [{"opportunity": str, "target_group": str, "rationale": str}],\n'
        '  "policy_recommendations": [{"recommendation": str, "level": str, "source": str}]\n'
        "Cite exact source filenames from the provided context. Do not wrap the JSON in markdown fences.\n\n"
        f"Approved Longevity Ontology:\n{ontology_ctx}\n\n"
        f"Relevant Global Corpus Passages:\n{passages_txt}"
    )

    user_prompt = (
        f"Entity: {body.entity_name}\n"
        f"Sector: {body.sector}\n"
        f"Location: {body.city}, {body.country}\n"
        f"Current State: {body.current_state or 'Not specified'}\n"
        f"Reported Challenges: {', '.join(body.challenges) if body.challenges else 'General age-friendliness assessment'}"
    )

    mode_requested = body.mode.lower().strip()
    mode_executed = "local"
    model_used = f"local/{LLM_MODEL}"

    try:
        if mode_requested == "hybrid":
            frontier = _call_frontier_llm(body.frontier_provider, system_prompt, user_prompt)
            if frontier:
                raw_output, model_used = frontier
                mode_executed = "hybrid"
            else:
                raw_output = _call_local_llm(system_prompt, user_prompt)
        else:
            raw_output = _call_local_llm(system_prompt, user_prompt)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Gap analysis error: {exc}") from exc

    # Parse structured JSON cleanly (strip markdown fences if the model adds them)
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_output.strip(), flags=re.IGNORECASE)
    try:
        structured = json.loads(cleaned)
    except Exception:
        structured = {"raw_analysis": raw_output}

    tokens_saved = 55000 if mode_executed == "local" else 46000
    request.state.tokens_saved = tokens_saved

    return {
        "client": client["name"],
        "entity_analyzed": body.entity_name,
        "sector": body.sector,
        "mode_executed": mode_executed,
        "model_used": model_used,
        "evidence_hits": len(hits),
        "tokens_saved_estimate": tokens_saved,
        "analysis": structured,
    }


@app.get("/api/v1/export/jsonl", response_class=PlainTextResponse)
def v1_export_jsonl(request: Request, client: dict = Depends(require_api_key)):
    """Export all human-approved ontology items as instruction/response JSONL for SLM LoRA fine-tuning."""
    request.state.client_id = client["id"]
    try:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT 'Dimension' AS kind, d.name, d.description, '' AS extra, doc.path
                FROM dimensions d
                JOIN documents doc ON doc.sha256 = d.document_sha256
                WHERE d.approved = true
                UNION ALL
                SELECT 'KPI', k.name, k.description, concat_ws(' | ', k.dimension, k.unit), doc.path
                FROM kpis k
                JOIN documents doc ON doc.sha256 = k.document_sha256
                WHERE k.approved = true
                UNION ALL
                SELECT 'Intervention', i.name, i.description, i.target_kpi, doc.path
                FROM interventions i
                JOIN documents doc ON doc.sha256 = i.document_sha256
                WHERE i.approved = true
                ORDER BY kind, name
                """
            ).fetchall()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    lines = []
    for kind, name, desc, extra, path in rows:
        doc_name = _clean_doc_name(path)
        record = {
            "messages": [
                {
                    "role": "system",
                    "content": "You are the Longevity Intelligence Platform (LIP) SLM. Provide evidence-grounded longevity guidance with source citations.",
                },
                {
                    "role": "user",
                    "content": f"Explain the longevity {kind.lower()} '{name}' and its role in healthy ageing.",
                },
                {
                    "role": "assistant",
                    "content": f"{name} ({kind}): {desc}"
                    + (f" Linked context: {extra}." if extra else "")
                    + f" [{doc_name}]",
                },
            ]
        }
        lines.append(json.dumps(record, ensure_ascii=False))

    return PlainTextResponse(
        content="\n".join(lines) + ("\n" if lines else ""),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="lip_slm_training_data.jsonl"'},
    )