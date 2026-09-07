-- 刮削库向量表（元库 SNS_META_DSN / :5439 nextweb）
-- 推荐：由应用按当前向量维度建表
--   python -m app.scrap_library_embed_job ensure-schema
-- 默认模型 intfloat/multilingual-e5-large → vector(1024)
-- 若改用 bge-small-zh 等，维度需与模型一致（或删表重建）

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS scrap_library_embed (
  item_id       text PRIMARY KEY,
  region        text NOT NULL DEFAULT '',
  prefix        text NOT NULL DEFAULT '',
  code          text NOT NULL DEFAULT '',
  rel_path      text NOT NULL DEFAULT '',
  title         text NOT NULL DEFAULT '',
  poster_path   text NOT NULL DEFAULT '',
  thumb_path    text NOT NULL DEFAULT '',
  fanart_path   text NOT NULL DEFAULT '',
  cover_url     text NOT NULL DEFAULT '',
  model         text NOT NULL,
  dim           smallint NOT NULL,
  content_sha   text NOT NULL,
  source_text   text NOT NULL,
  embedding     vector(1024) NOT NULL,
  updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS scrap_library_embed_sha
  ON scrap_library_embed (content_sha);

CREATE INDEX IF NOT EXISTS scrap_library_embed_code
  ON scrap_library_embed (code);
