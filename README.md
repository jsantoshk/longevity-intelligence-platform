# Longevity Intelligence Platform (LIP) — v1.0

A ring-fenced, composite B2B/B2G Longevity Intelligence Engine combining a FalkorDB Knowledge Graph, PostgreSQL `pgvector`) semantic corpus, an 80/20 Hybrid Reasoning Router, and stateless SOLID-PODS personalization.

## Architecture

- **API Gateway & Dashboard:** FastAPI `server.py`) + responsive obsidian-glass console `longevity_intelligence_platform.html`)

- **Vector & Relational Store:** PostgreSQL + `pgvector` `document_chunks`, `documents`, `api_clients`, `api_usage`)

- **Knowledge Graph:** FalkorDB `longevity_kg`)

- **Local AI Layer:** Ollama `qwen3:8b`, `nomic-embed-text`) — OpenAI-compatible `LLM_BASE_URL` for 1-line **vLLM** production scaling

## Quick Start (Local Development)

1. **Start Databases:** Ensure PostgreSQL `pgvector`) and FalkorDB Docker containers are running.

2. **Pull Local Models:**

   ```bash

   ollama pull qwen3:8b

   ollama pull nomic-embed-text