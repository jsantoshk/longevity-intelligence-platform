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
