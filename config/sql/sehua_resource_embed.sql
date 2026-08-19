-- 色花资源向量表（独立表，不改 ed2k_resources / resource_sources）
-- 试点：先建表灌几十条；全库 70 万灌完后再建 HNSW（见文末）
--
-- 用法:
--   python -m app.sehua_embed_job ensure-schema --dsn "$DSN"
--   或: psql "$DSN" -f config/sql/sehua_resource_embed.sql

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS sehua_resource_embed (
  hash          text PRIMARY KEY REFERENCES ed2k_resources(hash) ON DELETE CASCADE,
  model         text NOT NULL,
  dim           smallint NOT NULL,
  content_sha   text NOT NULL,
  source_text   text NOT NULL,
  embedding     vector(1024) NOT NULL,
  updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS sehua_resource_embed_sha
  ON sehua_resource_embed (content_sha);

-- 全量灌完再执行（70 万条建 HNSW 时建议 Postgres 临时提到 4G）:
-- CREATE INDEX sehua_resource_embed_hnsw
--   ON sehua_resource_embed
--   USING hnsw (embedding vector_cosine_ops)
--   WITH (m = 16, ef_construction = 64);
