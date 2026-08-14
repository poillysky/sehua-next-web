-- 色花资源库搜索加速（在资源库 Postgres 上执行一次）
-- 解决：SONS / SSIS 等短前缀在「时间=不限」时 ILIKE 全表扫极慢
--
-- 用法（局域网 DSN 对应库）:
--   psql "$DSN" -f config/sql/search_indexes.sql

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- filename / title 模糊匹配
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ed2k_resources_filename_trgm
  ON ed2k_resources USING gin (filename gin_trgm_ops);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_resource_sources_title_trgm
  ON resource_sources USING gin (title gin_trgm_ops);

-- 默认排序：按时间倒序取最新
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ed2k_resources_created_at_desc
  ON ed2k_resources (created_at DESC);
