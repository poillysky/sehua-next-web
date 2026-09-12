# 数据目录说明（运行时生成，勿提交大文件）
#
# 元数据（用户/会话/设置）在 Postgres（SNS_META_DSN，默认 nextweb）
# lemon-session.json  柠檬过盾 Cookie（运行时，可删）
# scrape_maps/     演员/标签映射（可选）
#   actors.zh-CN.json  女优标准名；drop/role/sex 可排除导演·男优·原作
#   tags.zh-CN.json    标签简中标准名；同义合并；drop 可丢噪声
#   缺省时回退 apps/api/app/scrape_maps_seed/
# prefix-code-ranges.json  前缀范围缓存（可选）
# prefix_catalog/  七区前缀→真实番号目录（网络校验；API /api/prefix-catalog）
#
# 片库类目录已迁到仓库根 media/（见 media/README.md）：
#   media/strm-library/   七区 STRM 输出
#   media/scrap-library/  刮削库（NFO→向量）
