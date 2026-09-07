-- Bitmagnet 磁力向量表（建在 Bitmagnet DSN）
-- 推荐由应用 ensure-schema：python / HTTP start 时自动建

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS bitmagnet_torrent_embed (
  info_hash     text PRIMARY KEY,
  model         text NOT NULL,
  dim           smallint NOT NULL,
  content_sha   text NOT NULL,
  source_text   text NOT NULL,
  embedding     vector(1024) NOT NULL,
  updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS bitmagnet_torrent_embed_sha
  ON bitmagnet_torrent_embed (content_sha);

-- 全量灌完再建:
-- CREATE INDEX bitmagnet_torrent_embed_hnsw
--   ON bitmagnet_torrent_embed
--   USING hnsw (embedding vector_cosine_ops)
--   WITH (m = 16, ef_construction = 64);
