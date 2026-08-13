"""色花堂中文标题清洗：正则去掉版块标签 / 破解字幕 / 清晰度等非标题噪声。"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Iterable

# —— 热路径高频静态正则（禁止在 is_fake/clean 里现编）——
_WS_RE = re.compile(r"\s+")
_COMPACT_SEP_RE = re.compile(r"[\s_\-]+")
_CODE_NEEDLE_PARSE_RE = re.compile(r"([A-Z0-9]+)-0*(\d+)", re.I)
_GENERIC_CODE_TOKEN_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:FC2(?:[-_]?PPV)?[-_]?\d{4,10}|"
    r"[A-Z]{2,12}[-_\s]?\d{1,6})(?![A-Za-z0-9])"
)
_NON_DIGIT_RE = re.compile(r"\D")
_WS_NICK_RE = re.compile(r"[\s　·・]")
_SHORT_KANA_FULL_RE = re.compile(
    r"[\u3040-\u30ff\u31f0-\u31ffー·・\s　]{1,10}"
)
_AI_SHELL_COMPACT_RE = re.compile(r"[\s_./|·・\-–—:：]+")
_AI_SHELL_TECH_ONLY_RE = re.compile(
    r"(?i)(?:ed2k|ai|mp4|mkv|avi|fhd|hd|4k|uhd|1080p?|720p?|2160p?)+"
)
_CODE_MEDIA_ONLY_RE = re.compile(
    r"[A-Z0-9]{2,12}[\s\-_]?0*\d{1,6}(?:\s*(?:MP4|MKV|AVI|FHD|HD|4K|UHD))?",
    re.I,
)
_CLIP_SHELL_RE = re.compile(
    r"(?:^|[\s\-–—])(?:4K(?:60)?\s*)?修复片段|修復片段|剪辑片段|合集片段|"
    r"C-4K修复片段|片段\s*\d+\s*$",
    re.I,
)
_CLIP_ONLY_RE = re.compile(r"剪辑片段|修复片段|修復片段", re.I)
_PACK_EXTRA_RE = re.compile(
    r"橙子整理|含单体|DMM原档|截止\s*$|合集更新至|作品合集|系列合集|"
    r"-999汇总|汇总【",
    re.I,
)
_TB_PACK_RE = re.compile(
    r"\d+(?:\.\d+)?\s*TB\s*/|\d{2,}\s*V\s*/\s*\d|"
    r"【\s*\d+(?:\.\d+)?\s*TB",
    re.I,
)
_MAGNET_SHELL_RE = re.compile(
    r"磁力链接无资源|补个有资源的链接|论坛上有另一个帖子的磁力|"
    r"只有磁力|无种子|死链",
    re.I,
)
_MAGNET_CODE_ONLY_RE = re.compile(
    r"(?:【?\s*(?:磁力|磁链|BT)[^】\]]{0,12}】?\s*)+"
    r"[A-Z0-9][A-Z0-9\-_ ]{2,20}"
    r"(?:\s*【?\s*(?:FHD|HD|4K|MP4)[^】\]]{0,8}】?)?",
    re.I,
)
_MEDIA_ONLY_RE = re.compile(
    r"(?:MP4|MKV|AVI|ISO|FHD|HD|4K|UHD|1080[Pp]|720[Pp]|2160[Pp])"
    r"(?:\s*/\s*\S+)?",
    re.I,
)
_CJK_KANA_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff]")
_BARE_META_STRIP_RE = re.compile(
    r"(?i)(?:亚洲无码|亞洲無碼|日本无码|日本無碼|"
    r"【[^】]{0,40}】|\[[^\]]{0,40}\]|"
    r"\d+(?:\.\d+)?\s*(?:GB|MB|G|M)(?:B)?|"
    r"\d+\s*V|\d+\s*分|[FHDC4KUhdPp]+)"
)
_BARE_EDGE_STRIP = " .·・-–—_/|"
_CHINA_91_FANS_RE = re.compile(r"(?i)\s*x?\s*91\s*fans?\b")
_CHINA_PRODUCE_RE = re.compile(r"^(?:最新)?(?:出品|上映)[\s　\-–—_]*")
_MP4_SLASH_TAG_RE = re.compile(
    r"[【\[]\s*(?:MP4|MKV|AVI|ISO)\s*/\s*[^】\]]{1,20}[】\]]\s*",
    re.I,
)
_LEADING_4K_BOOST_RE = re.compile(r"^4K(?:60(?:fps)?)?增强[\s\-–—_]*", re.I)
_GENERIC_PREFIX_CODE_RE = re.compile(
    r"^[A-Z]{2,15}[-_ ]?\d{2,5}[A-Z]?\s*[-_:：.]?\s*",
    re.I,
)
_BOARD_DATE_CODE_RE = re.compile(
    r"\b[A-Z]{1,6}\d{0,4}\s+[A-Za-z]{0,4}\d{5,10}\b",
    re.I,
)
_META_TAIL_BROKEN_RE = re.compile(
    r"[【\[]\s*(?:\d+\s*V\s*/\s*)?\d+(?:\.\d+)?\s*(?:GB|MB|G|M)(?:B)?"
    r"[\d\s./V分帧幀KkUuHhDdPp]*[】\]]?\s*$",
    re.I,
)
_META_TAIL_V_RE = re.compile(
    r"[【\[]\s*\d+\s*V\s*/\s*\d+(?:\.\d+)?\s*(?:GB|MB|G|M)(?:B)?"
    r"[\w\s./分帧幀]*[】\]]?\s*$",
    re.I,
)
_SHORT_CJK_TITLE_RE = re.compile(r"[\u4e00-\u9fff]{2,3}")
_ZONE_ONLY_RE = re.compile(r"(?:无码|有码|無碼|有碼|中字|字幕|破解|增强|合集)", re.I)
_PLUS_SLASH_RE = re.compile(r"[+\uff0b/｜|]")
_PAREN_INNER_RE = re.compile(r"[（(]([^）)]{4,80})[）)]")
_KANA_RE = re.compile(r"[\u3040-\u30ff]")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_KANA_EXT_RE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff]")
_NO_CODE_NEW_PAREN_RE = re.compile(
    r"（\s*无码新片\s*）|\(\s*无码新片\s*\)", re.I
)
_TRAILING_BANG_RE = re.compile(r"[！!]+\s*$")
_TRAILING_PUNCT_RE = re.compile(r"[、,，\s/｜|。．.\-_:：]+$")
_LEADING_PUNCT_CLEAN_RE = re.compile(r"^[\s\-_:：.]+")
# 题首孤立分集序号：1片名 / 2.片名 / -1片名（勿伤 18岁/91制片/2024）
_LEADING_EPISODE_ORD_RE = re.compile(
    r"^[-–—]?[1-9](?![0-9岁歲天日号號期禁届屆部集章篇制片製片])"
    r"[\s　.\-、:：)·）]*"
    r"(?=[\u4e00-\u9fff《「『])"
)
# 表情/装饰后的分集残号：❤ -1极品嫂子
_EMOJI_EPISODE_ORD_RE = re.compile(
    r"(?:[\u2600-\u27BF\U0001F300-\U0001FAFF❤♥♡⭐✨]+)\s*[-–—]?\d{1,2}"
    r"[\s　.\-、:：)·）]*"
    r"(?=[\u4e00-\u9fff《「『])"
)
_LEADING_ZONE_STRIP_RE = re.compile(
    r"^(?:[（(]\s*)?(?:无码|有码|無碼|有碼)(?:\s*[）)])?[\s\-–—_]*",
    re.I,
)
_RES_P_TAIL_RE = re.compile(
    r"(?i)[\s\-–—_]*\d{3,4}\s*[Pp]?\s*(?:高清|蓝光|藍光)?版?\s*$",
)
_VERSION_TAIL_RE = re.compile(
    r"(?:"
    # 破解/听译/修正（可带字幕），勿单独剥剧情「流出/字幕」
    r"(?:无码|有码|無碼|有碼)?(?:破解|听译|聽譯|修正){1,3}(?:字幕|中字)?版?|"
    r"(?:无码|有码|無碼|有碼)(?:流出|字幕|中字)版?|"
    r"(?:破解|听译|聽譯|修正)(?:字幕|中字)?版?"
    r")\s*$",
    re.I,
)
_LEADING_KANA_LATIN_RE = re.compile(
    r"^[\u3040-\u30ff\u31f0-\u31ffA-Za-z0-9\s　·・]+",
)
_SPACE_SPLIT_RE = re.compile(r"[\s　]+")

# 色花堂帖题噪声：版块标签 / 介质版本 / 清晰度 / 体积
_FORUM_BOARD_TAG_RE = re.compile(
    r"^[\s　]*[【\[](?:BT(?:种子|種子|/磁力|/磁链|/磁力链接|/磁力鏈接)?|"
    r"磁链|磁力(?:链接|鏈接)?|今日新番|有码|无码|素人|"
    r"高清中文字幕|中文字幕|破解|合集|打包|自转|自购|自扒|转载|自译中字|"
    r"AI\s*画质修复|AI\s*畫质修复|画质修复|畫质修复|"
    r"(?:原汁原味\+?)?(?:AI\s*)?(?:增强|加強|畫质增强|画质增强|無碼增强|无码增强)"
    r"(?:4K|4k|60(?:fps|幀|帧)?)?(?:[丨+/]?(?:ED2K|115(?:网盘|sha1)?|磁力|磁链|4K(?:60(?:FPS|fps)?)?)){0,4}|"
    r"4K(?:60(?:fps|幀|帧)?)?(?:画质|畫质|无码|無碼)?(?:增强|加強)?(?:[丨+/]?(?:ED2K|115(?:网盘|sha1)?)){0,3}|"
    r"115(?:网盘|ED2K|sha1)?)[】\]]\s*[:：]?\s*",
    re.I,
)
_FORUM_BRACKET_NOISE_RE = re.compile(
    r"[【\[]\s*(?:"
    r"AI\s*破解(?:版)?|破解(?:版)?|无码(?:流出|破解|新片)?|有码|"
    r"中文字幕|字幕版|听译(?:修正)?版?|修正版|完整版|自译中字|"
    r"高清|蓝光(?:版)?|藍光(?:版)?|蓝光iso底版|4K|UHD|1080[Pp]|720[Pp]|HD|FHD|"
    r"无修正|中字|繁中|简中|"
    r"BT(?:种子|種子|/磁力|/磁链|/磁力链接|/磁力鏈接)?|磁链|磁力(?:链接|鏈接)?|"
    r"自转|自购|自扒|转载|"
    r"AI\s*画质修复|AI\s*畫质修复|画质修复|畫质修复|"
    r"(?:原汁原味\+?)?(?:AI\s*)?(?:增强|加強|畫质增强|画质增强|無碼增强|无码增强)"
    r"(?:4K|4k|60(?:fps|幀|帧)?)?(?:[丨+/]?(?:ED2K|115(?:网盘|sha1)?|磁力|磁链|4K(?:60(?:FPS|fps)?)?)){0,4}|"
    r"4K(?:60(?:fps|幀|帧)?)?(?:画质|畫质|无码|無碼)?(?:增强|加強)?(?:[丨+/]?(?:ED2K|115(?:网盘|sha1)?)){0,3}|"
    r"115(?:网盘|ED2K|sha1)?"
    r")\s*[】\]]\s*[:：]?",
    re.I,
)
_FORUM_MEDIA_SUFFIX_RE = re.compile(
    r"[\s　]*[（(【\[]?\s*(?:"
    r"蓝光(?:光盘|碟|版)?|藍光(?:光碟|版)?|ブルーレイ(?:ディスク)?|"
    r"Blu-?ray|BD|DVD|4K|UHD|1080[Pp]|720[Pp]|HD|高清|"
    r"無碼流出|无码(?:流出|破解)?|有码|破解(?:版)?|AI\s*破解(?:版)?|"
    r"中文字幕|字幕版|听译(?:修正)?版?|修正版|完整版|中字|繁中|简中"
    r")\s*[）)】\]]?\s*$",
    re.I,
)
_FORUM_SIZE_TAIL_RE = re.compile(
    r"[\s　]*\d+(?:\.\d+)?\s*(?:GB|MB|G|M)(?:B)?\s*$",
    re.I,
)
_FORUM_DATE_PREFIX_RE = re.compile(
    r"^[\s　]*(?:20\d{6}|20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}|"
    r"\d{1,2}/\d{1,2})\s*[★☆*]?\s*",
)
_FORUM_ACTOR_AGE_ONLY_RE = re.compile(
    r"^[\u4e00-\u9fffA-Za-z·・\s　]{2,20}\d{2}\s*歳\s*$",
)
_FORUM_BROKEN_BRACKET_TAIL_RE = re.compile(
    r"[【\[][^】\]]{0,20}$",
)
_FORUM_EMPTY_PAREN_RE = re.compile(
    r"[（(]\s*[）)]|[（(]\s*(?:果冻传媒|星空传媒|蜜桃传媒|麻豆传媒|香蕉视频)\s*[）)]",
)
# 剥厂牌/番号后残留：) (20230104)片名 → 片名
_ORPHAN_LEADING_PAREN_RE = re.compile(r"^[）)\s　]+")
_LEADING_DATE_PAREN_RE = re.compile(
    r"^[（(]\s*(?:20\d{6}|20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})\s*[）)][\s　]*"
)
# 题首「SA國際傳媒) (20230105)片名」：短片商 + 残 ) + 日期壳
_LEADING_BRAND_ORPHAN_DATE_RE = re.compile(
    r"^[A-Za-z0-9\u4e00-\u9fff·・\s　]{1,28}[）)]\s*"
    r"[（(]\s*(?:20\d{6}|20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})\s*[）)][\s　]*"
)
_FORUM_PACK_NOISE_RE = re.compile(
    r"(?:黑客最新發[布佈]|最新發布\d+部|合集打包|共\d+部|打包合集|"
    r"汇总|合集更新至|作品合集|系列合集|\d+\s*部合集|"
    r"二楼彩蛋|计\s*\d+\s*部|"
    r"橙子整理|截止[A-Z]{2,15}[-_]?\d+|"
    r"含单体\s*\+\s*共演|DMM原档|"
    r"MOODYZ\s*DIVA|"
    # 大容量合集：2.6TB、2.6TB/986V；勿把单片【1V/8.1G】当合集壳
    r"\d+(?:\.\d+)?\s*TB(?:\s*/\s*\d+\s*V)?|"
    r"\d{2,}\s*V\s*/\s*\d+(?:\.\d+)?\s*(?:TB|GB|G)\b)",
    re.I,
)
# 合集壳伪中文（复合特征，禁止「写真/共演/合集/封面」裸词误杀正片名）
_FORUM_META_ZH_JUNK_RE = re.compile(
    r"(?:"
    r"含单体|含單體|"
    r"单体\s*[+＋]|單體\s*[+＋]|"
    r"共演\s*[+＋]\s*写真|写真\s*[+＋]\s*共演|"
    r"共演\s*[+＋]\s*寫真|寫真\s*[+＋]\s*共演|"
    r"(?:竖版|橫版|横版|竖版)\s*[+＋/|丨].*(?:原档|原檔|封面)|"
    r"(?:原档|原檔|封面)\s*[+＋/|丨].*(?:竖版|橫版|横版)|"
    r"日亚封面|日亞封面|"
    r"(?:截止|整理至?)\s*[A-Za-z0-9]|"
    r"合集更新至|作品合集|合集打包|打包合集|"
    r"共演\s*[+＋].{0,12}写真|写真.{0,12}共演\s*[+＋]"
    r")",
    re.I,
)
# 假壳长度：与 clean/打分对齐，仅对合集壳特征生效
_META_SHELL_FAKE_LEN = 28
_META_SHELL_CLEAN_LEN = 28
_META_SHELL_SCORE_LEN = 28
# 前缀体积/清晰度：[HD/926MB] 【HD版/3.15GB】 【磁 力】[HD/3.21G]
_FORUM_LEADING_HD_SIZE_RE = re.compile(
    r"^(?:[【\[]\s*磁\s*力\s*[】\]]\s*)?"
    r"[【\[]\s*(?:HD(?:版)?|FHD|FHDC|4K|UHD|BT|磁力|磁链)\s*"
    r"(?:[/丨|]\s*\d+(?:\.\d+)?\s*(?:GB|MB|G|M)(?:B)?)?\s*[】\]]\s*",
    re.I,
)
# 题首区标 / 质量括号：亚洲无码、[FHDC]、［BT磁力］
_FORUM_LEADING_REGION_QUALITY_RE = re.compile(
    r"^(?:"
    r"(?:亚洲无码|亞洲無碼|日本无码|日本無碼|国产无码|國產無碼|欧美无码|歐美無碼)"
    r"|[【\[]\s*(?:FHDC|FHD|HD|4K|UHD|BT(?:\s*磁力)?|磁力|磁链)\s*[】\]]"
    r"|［\s*(?:BT(?:\s*磁力)?|磁力|磁链|FHDC|FHD)\s*］"
    r")[\s　\-–—_:：]*",
    re.I,
)
# 残缺尾括号：【4.39 GB/1V/26分钟（无右括号）
_FORUM_BROKEN_META_TAIL_RE = re.compile(
    r"[【\[]\s*\d+(?:\.\d+)?\s*(?:GB|MB|G|M)(?:B)?"
    r"(?:\s*/\s*\d+\s*V)?"
    r"(?:\s*/\s*\d+\s*(?:分|分钟|分鐘))?"
    r"[^】\]]*$",
    re.I,
)
# 仅厂牌/无实质片名
_FORUM_GENERIC_ONLY_RE = re.compile(
    r"^(?:一本道|加勒比|东京热|東京熱|パコパコママ|人妻斩|人妻斬|"
    r"果冻传媒|星空传媒|蜜桃传媒|香蕉视频|麻豆传媒|"
    r"天美传媒|杏吧传媒|爱豆传媒|愛豆傳媒|扣扣传媒|猫爪影像|"
    r"精东影业|起点传媒|色控传媒|性视界传媒|大象传媒|萝莉社|蘿莉社|"
    r"91制片厂|皇家华人|兔子先生|绝对领域|"
    r"亚洲无码|亞洲無碼|日本无码|日本無碼|"
    r"有码|无码|素人|中文字幕)$",
    re.I,
)
# 国产无码：标题里粘贴的片商名（短词必须带厂牌后缀，避免误伤「不见星空」「蜜桃臀」）
_CHINA_STUDIO_BRAND_RE = re.compile(
    r"(?:"
    r"麻豆(?:传媒|傳媒)(?:映画|最新(?:出品|上映))?|"
    r"果冻(?:传媒|傳媒)(?:最新出品)?|"
    r"星空(?:无限|無限)?(?:传媒|傳媒)|"
    r"蜜桃影像(?:传媒|傳媒)?|蜜桃(?:传媒|傳媒)|"
    r"天美(?:传媒|傳媒)|"
    r"杏吧(?:传媒|傳媒)|"
    r"香蕉(?:视频|視頻|传媒|傳媒|秀)|"
    r"皇家华人|皇家華人|"
    r"爱豆(?:传媒|傳媒)|愛豆(?:传媒|傳媒)|"
    r"扣扣(?:传媒|傳媒)|"
    r"猫爪(?:影像|传媒|傳媒)|"
    r"精东影业|精東影業|"
    r"起点(?:传媒|傳媒)|"
    r"色控(?:传媒|傳媒)|"
    r"性视界(?:传媒|傳媒)|"
    r"大象(?:传媒|傳媒)|大像(?:传媒|傳媒)|"
    r"萝莉社|蘿莉社|"
    r"91制片厂|91製片廠"
    r")"
    # 帖题常见「麻豆傳媒)(mdwp-0033)」破括号，顺带吃掉后随 )
    r"[\s　\-–—_·・✨❤]*[）)]?",
    re.I,
)
# 仅题首可剥的歧义厂牌（文中可能是剧情词）
_CHINA_STUDIO_LEADING_ONLY_RE = re.compile(
    r"^(?:绝对领域|絕對領域|性世界|焦点(?:传媒|傳媒)?|色控|兔子先生)"
    r"[\s　\-–—_·・✨❤]*",
    re.I,
)
# 复合技术标签：【破解/调色/ED2K/Lada0.90】【CPU自转码H265/115ED2K链接】
_FORUM_TECH_SLASH_TAG_RE = re.compile(
    r"[【\[][^】\]]{0,60}?(?:"
    r"ED2K|115|破解|调色|轉码|转码|H\.?265|H\.?264|Lada|自整理|自购|"
    r"增强|加強|磁力|磁链|BT种子|CPU"
    r")[^】\]]{0,60}?[】\]]\s*",
    re.I,
)
_FORUM_STAR_NOISE_RE = re.compile(r"[★☆].*?[★☆]")
# 帖题/描述里任意位置的版块、介质、字幕标签
_FORUM_INLINE_TAG_RE = re.compile(
    r"[【\[]\s*(?:"
    r"BT(?:种子|種子|/种子|/種子|/磁力|/磁链|/磁力链接|/磁力鏈接)?|磁链|磁力(?:链接|鏈接)?|今日新番|有码|无码|素人|"
    r"高清中文字幕|中文字幕|字幕(?:版)?|破解(?:版)?|合集|打包|"
    r"自购|自扒|自转|转载|首发|独家|分享|福利|自译中字|"
    r"AI\s*破解(?:版)?|无码(?:流出|破解|新片)?|无修正|"
    r"AI\s*画质修复|AI\s*畫质修复|画质修复|畫质修复|"
    r"Topaz(?:\s*AI)?(?:\s*\d{3,4}[Pp]?)?|"
    r"最新素人无码|日本素人|最新素人|"
    r"高清|蓝光(?:版)?|藍光(?:版)?|蓝光iso底版|Blu-?ray|BD|DVD|"
    r"HD版|MP4|MKV|"
    r"4K|UHD|1080[Pp]|720[Pp]|HD|FHD|"
    r"听译(?:修正)?版?|修正版|完整版|中字|繁中|简中|"
    r"(?:原汁原味\+?)?(?:AI\s*)?(?:增强|加強|畫质增强|画质增强|無碼增强|无码增强)"
    r"(?:4K|4k|60(?:fps|幀|帧)?)?(?:[丨+/]?(?:ED2K|115(?:网盘|sha1)?|磁力|磁链|4K(?:60(?:FPS|fps)?)?)){0,4}|"
    r"4K(?:60(?:fps|幀|帧)?)?(?:无码|無碼)?(?:增强|加強)?(?:[丨+/]?(?:ED2K|115(?:网盘|sha1)?)){0,3}|"
    r"115(?:网盘|ED2K|sha1)?"
    r")\s*[】\]]\s*[:：]?",
    re.I,
)
# 缺左括号 / 无括号增强前缀
_FORUM_ORPHAN_TAG_RE = re.compile(
    r"^(?:[+\-]?\s*)?(?:增强|加強|AI\s*增强|AI\s*加強|4K(?:60(?:fps)?)?增强)"
    r"[丨+/]?(?:ED2K|115)?[】\]]?\s*",
    re.I,
)
# 尾部 [4K.60fps/MKV/8.84GB] 技术括号
_FORUM_TECH_TAIL_RE = re.compile(
    r"[\s]*[【\[][^】\]]{0,40}(?:\d+(?:\.\d+)?\s*(?:GB|MB|G)|4K|60(?:fps|幀|帧)|MKV|MP4|ISO)[^】\]]{0,40}[】\]]\s*$",
    re.I,
)
# 尾部体积/时长/分集：【3.18G/1V/19分/4K】【1V/702M】
_FORUM_META_TAIL_BRACKET_RE = re.compile(
    r"[【\[]\s*\d+(?:\.\d+)?\s*(?:GB|MB|G|M)(?:B)?"
    r"(?:\s*/\s*\d+\s*V)?"
    r"(?:\s*/\s*\d+\s*分)?"
    r"(?:\s*/\s*(?:4K|UHD|1080[Pp]|720[Pp]|HD|FHD))?"
    r"\s*[】\]]\s*$",
    re.I,
)
_FORUM_META_TAIL_BRACKET_ALT_RE = re.compile(
    r"[【\[]\s*\d+\s*V\s*/\s*\d+(?:\.\d+)?\s*(?:GB|MB|G|M)(?:B)?\s*[】\]]\s*$",
    re.I,
)
_FORUM_SOURCE_PREFIX_RE = re.compile(
    r"^[\s　]*(?:"
    r"自购|自扒|自转|转载|首发|独家|福利|分享|"
    # 「最新」仅当后接发布/上架等来源词，避免误剥「最新女友…」
    r"最新(?:发布|發佈|上架|资源|資源|放送|投稿|出品)"
    r")[\s:：\-–—]*",
    re.I,
)
_FORUM_FILE_EXT_TAIL_RE = re.compile(
    r"[\s.]*\.(?:mp4|mkv|avi|wmv|mov|ts|m2ts|rar|zip|7z|iso)\s*$",
    re.I,
)
_FORUM_RES_TAIL_RE = re.compile(
    r"[\s_]*\d{3,4}\s*[xX×]\s*\d{3,4}"
    r"(?:\s*[（(]?\s*(?:1080|720|2160|4K|UHD)?[Pp]?[^）)]{0,20}[）)]?)?\s*$",
    re.I,
)
_FORUM_DASH_QUALITY_TAIL_RE = re.compile(
    r"[\s\-–—_]+(?:1080[Pp]?|720[Pp]?|2160[Pp]?|4K|UHD|HD|FHD|MP4|MKV|AVI)\s*$",
    re.I,
)
_FORUM_LEADING_QUALITY_RE = re.compile(
    r"^(?:1080[Pp]?|720[Pp]?|2160[Pp]?|4K|UHD|HD|FHD|MP4|MKV|AVI)[\s\-–—_]+",
    re.I,
)
_FORUM_LEADING_PUNCT_RE = re.compile(r"^[\s\-–—_·・:：.–]+")
_FORUM_EM_DASH_SPLIT_RE = re.compile(r"\s*[–—]\s*|\s+-\s+")
_TRAILING_CJK_RE = re.compile(r"([\u4e00-\u9fff\u3040-\u30ff]{2,8})$")

# 女优名常见异体字（帖题简繁/新旧字与库内【出演女优】不一致时仍剥尾）
_ACTOR_VARIANT_PAIRS: tuple[tuple[str, str], ...] = (
    ("薫", "薰"),
    ("薰", "薫"),
    ("熏", "薰"),
    ("凪", "澪"),
    ("澪", "凪"),
    ("咲", "笑"),
    ("笑", "咲"),
)


def _actor_strip_variants(name: str) -> set[str]:
    raw = str(name or "").strip()
    if not raw:
        return set()
    out = {raw, unicodedata.normalize("NFKC", raw)}
    pool = list(out)
    for base in pool:
        for a, b in _ACTOR_VARIANT_PAIRS:
            if a in base:
                out.add(base.replace(a, b))
            if b in base:
                out.add(base.replace(b, a))
    return {x for x in out if len(x) >= 2}


def _actor_names_match(a: str, b: str) -> bool:
    aa = str(a or "").strip()
    bb = str(b or "").strip()
    if not aa or not bb:
        return False
    if aa == bb:
        return True
    va = _actor_strip_variants(aa)
    vb = _actor_strip_variants(bb)
    return bool(va & vb)


def _strip_trailing_actor_name(t: str, actors: Iterable[str]) -> str:
    names = [str(a).strip() for a in actors if str(a or "").strip()]
    if not t or not names:
        return t
    all_variants: set[str] = set()
    for name in names:
        all_variants |= _actor_strip_variants(name)
    ordered = sorted(all_variants, key=len, reverse=True)
    for _ in range(4):
        changed = False
        for name in ordered:
            if len(name) < 2:
                continue
            nxt = _actor_trailing_re(name).sub("", t).strip()
            if nxt != t and len(nxt) >= 4:
                t = nxt
                changed = True
        if not changed:
            break
    tail = _TRAILING_CJK_RE.search(t)
    if tail and any(_actor_names_match(tail.group(1), n) for n in names):
        t = t[: tail.start()].strip()
    return t


@lru_cache(maxsize=4096)
def _code_specific_res(needle: str) -> tuple[re.Pattern[str] | None, re.Pattern[str] | None]:
    """按番号缓存剥码正则（含补零变体 / FC2）。"""
    n = str(needle or "").strip().upper()
    if not n:
        return None, None
    code_re: re.Pattern[str] | None = None
    fc2_re: re.Pattern[str] | None = None
    m = _CODE_NEEDLE_PARSE_RE.fullmatch(n)
    if m:
        pref, num_i = m.group(1), int(m.group(2))
        code_re = re.compile(
            rf"(?i)(?:[（(]\s*)?(?<![A-Za-z0-9])(?:\d{{2,3}})?{re.escape(pref)}"
            rf"[-_\s]?0*{num_i}(?!\d)(?:\s*[）)])?"
        )
    if n.startswith("FC2"):
        digits = _NON_DIGIT_RE.sub("", n)
        if digits:
            fc2_re = re.compile(
                rf"(?i)(?<![A-Za-z0-9])FC2(?:[-_]?PPV)?[-_]?{digits}(?!\d)"
            )
    return code_re, fc2_re


@lru_cache(maxsize=4096)
def _needle_clean_res(
    needle: str,
) -> tuple[re.Pattern[str], re.Pattern[str], re.Pattern[str], re.Pattern[str]]:
    """清洗阶段：题首/文中/括号内剥番号。"""
    esc = re.escape(str(needle or "").strip())
    return (
        re.compile(rf"^(?:[【\[]\s*)?{esc}(?:\s*[】\]])?[\s\-_:：.]*", re.I),
        re.compile(rf"(?:^|[\s\-–—]){esc}(?=[\s\-–—]|$)", re.I),
        re.compile(rf"(?<![A-Za-z0-9]){esc}(?![A-Za-z0-9])", re.I),
        re.compile(rf"\({esc}\)|（{esc}）", re.I),
    )


@lru_cache(maxsize=4096)
def _needle_ext_re(needle: str) -> re.Pattern[str]:
    esc = re.escape(str(needle or "").strip())
    return re.compile(rf"{esc}\.(?:mp4|mkv|avi|iso)", re.I)


@lru_cache(maxsize=4096)
def _actor_trailing_re(name: str) -> re.Pattern[str]:
    esc = re.escape(name)
    return re.compile(rf"(?:[\s　]*[、,，/｜|。．.·・][\s　]*)?{esc}\s*$")


def _strip_orphan_meta_prefix(t: str) -> str:
    """清题首残括号 / 日期壳：`) (20230104)片名` → `片名`。"""
    s = str(t or "").strip()
    if not s:
        return ""
    for _ in range(6):
        nxt = _LEADING_BRAND_ORPHAN_DATE_RE.sub("", s)
        nxt = _ORPHAN_LEADING_PAREN_RE.sub("", nxt)
        nxt = _LEADING_DATE_PAREN_RE.sub("", nxt)
        nxt = _FORUM_EMPTY_PAREN_RE.sub(" ", nxt)
        nxt = _FORUM_DATE_PREFIX_RE.sub("", nxt).strip()
        nxt = _WS_RE.sub(" ", nxt).strip()
        if nxt == s:
            break
        s = nxt
    return s


def _strip_inline_forum_tags(t: str) -> str:
    """去掉字符串任意位置的版块/介质/字幕括号标签。"""
    for _ in range(6):
        nxt = _FORUM_INLINE_TAG_RE.sub(" ", t)
        nxt = _WS_RE.sub(" ", nxt).strip()
        if nxt == t:
            break
        t = nxt
    return t


def _strip_china_studio_and_code(t: str, code: str = "") -> str:
    """国产无码：剥片商名（题首+残留厂牌后缀）；代号交由 _strip_code_tokens。"""
    s = str(t or "").strip()
    if not s:
        return ""
    for _ in range(4):
        m = _CHINA_STUDIO_LEADING_ONLY_RE.match(s) or _CHINA_STUDIO_BRAND_RE.match(s)
        if not m:
            break
        s = s[m.end() :].strip()
    s = _CHINA_STUDIO_BRAND_RE.sub(" ", s)
    s = _CHINA_91_FANS_RE.sub(" ", s)
    s = _CHINA_PRODUCE_RE.sub("", s).strip()
    return _strip_code_tokens(s, code)


def _strip_code_tokens(t: str, code: str = "") -> str:
    """剥题内番号/FC2 代号（含补零变体）；全区分共用。"""
    s = str(t or "").strip()
    if not s:
        return ""
    needle = str(code or "").strip().upper()
    if needle:
        code_re, fc2_re = _code_specific_res(needle)
        if code_re is not None:
            s = code_re.sub(" ", s)
        if fc2_re is not None:
            s = fc2_re.sub(" ", s)
    s = _GENERIC_CODE_TOKEN_RE.sub(" ", s)
    return _WS_RE.sub(" ", s).strip(" .·・-–—")


def _is_short_kana_nick(title: str) -> bool:
    """素人短假名昵称（ゆあ / みう）— 不当正片标题。"""
    s = str(title or "").strip()
    if not s or not _SHORT_KANA_FULL_RE.fullmatch(s):
        return False
    core = _WS_NICK_RE.sub("", s)
    return 1 <= len(core) <= 6


# AI增强 / 分辨率 / ed2k 技术壳（剥完无正片名则拒）
_AI_RES_NOISE_RE = re.compile(
    r"(?i)"
    r"[【\[]\s*(?:AI\s*)?(?:增强|加強|画质|畫质|修复|修復)"
    r"[^】\]]{0,24}[】\]]|"
    r"[【\[]\s*(?:ed2k|115(?:网盘|sha1)?|磁力|磁链|BT)[^】\]]{0,16}[】\]]|"
    r"[【\[]\s*(?:1080|720|2160|4K|UHD|FHD|HD)\s*[Pp]?[^】\]]{0,12}[】\]]|"
    r"[【\[]\s*\d+\s*V\s*/\s*\d+(?:\.\d+)?\s*(?:GB|MB|G|M)(?:B)?[^】\]]{0,20}[】\]]|"
    # 下划线也是字词字符，不用 \\b，改用数字边界
    r"(?<![A-Za-z0-9])\d{3,4}\s*[xX×]\s*\d{3,4}(?![A-Za-z0-9])|"
    r"[（(]\s*(?:1080|720|2160)\s*[Pp]?\s*(?:全高清|高清)?\s*[）)]|"
    r"(?:^|[\s_/\-])(?:1080|720|2160)\s*[Pp]?(?:\s*全高清)?(?=[\s_/\-]|$)|"
    r"(?:^|[\s_])(?:AI\s*)?(?:增强|加強|画质增强|畫质增强)(?=[\s_/【\[]|$)"
)


def _strip_ai_resolution_noise(t: str) -> str:
    """剥 AI增强 / 分辨率 / ed2k 技术标签。"""
    s = str(t or "").strip()
    if not s:
        return ""
    for _ in range(5):
        nxt = _AI_RES_NOISE_RE.sub(" ", s)
        nxt = _WS_RE.sub(" ", nxt).strip(_BARE_EDGE_STRIP)
        if nxt == s:
            break
        s = nxt
    return s


def _is_ai_resolution_shell(title: str, code: str = "") -> bool:
    """整题只剩 AI增强+分辨率+番号/ed2k/片商，无正片片名。"""
    s = _strip_ai_resolution_noise(title)
    s = _strip_china_studio_and_code(s, code)
    s = _AI_SHELL_COMPACT_RE.sub("", s)
    if not s or len(s) < 2:
        return True
    if _AI_SHELL_TECH_ONLY_RE.fullmatch(s):
        return True
    return False


def is_fake_forum_title_fast(title: str | None, code: str = "") -> bool:
    """热路径廉价假壳判断：不做 AI 全量剥码 / bare 剥码。

    用于收帖打分；最终写入仍走完整 is_fake / clean。
    """
    t = str(title or "").strip()
    if not t:
        return True
    needle = str(code or "").strip().upper()
    compact = _COMPACT_SEP_RE.sub("", t).upper()
    needle_compact = _COMPACT_SEP_RE.sub("", needle) if needle else ""
    if needle_compact and (
        compact == needle_compact
        or compact == needle_compact + "MP4"
        or compact == needle_compact + "MKV"
        or compact == needle_compact + "AVI"
        or compact == needle_compact + "FHD"
        or compact == needle_compact + "HD"
        or compact == needle_compact + "4K"
    ):
        return True
    if _CODE_MEDIA_ONLY_RE.fullmatch(t):
        return True
    if needle and _needle_ext_re(needle).fullmatch(t):
        return True
    if _CLIP_SHELL_RE.search(t) or _CLIP_ONLY_RE.fullmatch(t):
        return True
    if _FORUM_PACK_NOISE_RE.search(t) or _PACK_EXTRA_RE.search(t):
        return True
    if _FORUM_META_ZH_JUNK_RE.search(t) and (
        len(t) < _META_SHELL_FAKE_LEN or t.count("+") >= 2 or t.count("＋") >= 2
    ):
        return True
    # 「截止」仅在像合集目录时（邻近番号）才当壳
    if "截止" in t and re.search(r"[A-Za-z]{2,}\s*-?\s*\d{2,}", t):
        return True
    if _TB_PACK_RE.search(t):
        return True
    if _MAGNET_SHELL_RE.search(t) or _MAGNET_CODE_ONLY_RE.fullmatch(t):
        return True
    if _MEDIA_ONLY_RE.fullmatch(t) or _FORUM_GENERIC_ONLY_RE.fullmatch(t):
        return True
    if len(t) < 2:
        return True
    if len(t) <= 3 and not _CJK_KANA_RE.search(t):
        return True
    if _is_short_kana_nick(t):
        return True
    return False


def is_fake_forum_title(title: str | None, code: str = "") -> bool:
    """明显不是正片片名的假标题（番号壳/合集壳/片段壳/磁力壳等）。

    索引写入时应视为空标题，宁缺毋假。
    """
    t = str(title or "").strip()
    if not t:
        return True
    # 先走廉价路径；命中则不必做 AI/bare 重剥
    if is_fake_forum_title_fast(t, code):
        return True
    needle = str(code or "").strip().upper()

    # AI增强 / 分辨率 / ed2k 壳（无正片片名）
    if _is_ai_resolution_shell(t, needle):
        return True

    # 剥代号/体积后几乎无实质（亚洲无码 + 番号 + 【1V/…】）
    bare = _BARE_META_STRIP_RE.sub(" ", t)
    bare = _strip_code_tokens(bare, code)
    bare = _WS_RE.sub(" ", bare).strip(_BARE_EDGE_STRIP)
    if len(bare) < 2:
        return True

    return False


def clean_forum_zh_title(
    raw: str,
    code: str = "",
    *,
    actors: Iterable[str] | None = None,
    allow_weak: bool = False,
) -> str:
    """安全清洗色花堂标题：去番号 / 版块标签 / 破解字幕 / 清晰度 / 体积等噪声。

    - 索引聚合调用时 actors=None：不剥女优（女优只从描述字段取）。
    - 显式传入 actors 时：仅剥与名单匹配的末尾女优名。
    - allow_weak=True：合集/过短也可继续洗；假壳（番号MP4/片段/汇总）仍返回空。
    """
    t = str(raw or "").strip()
    if not t:
        return ""
    t = _WS_RE.sub(" ", t).strip()
    needle = str(code or "").strip().upper()
    raw_keep = t

    # 合集/黑客打包帖：不当作单片标题（弱模式仍继续洗，避免索引空题）
    if _FORUM_PACK_NOISE_RE.search(t) and not allow_weak:
        return ""

    # [HD/926MB] 【HD版/3.15GB】【磁 力】前缀
    for _ in range(3):
        nxt = _FORUM_LEADING_HD_SIZE_RE.sub("", t).strip()
        if nxt == t:
            break
        t = nxt

    # 亚洲无码 / [FHDC] / ［BT磁力］
    for _ in range(4):
        nxt = _FORUM_LEADING_REGION_QUALITY_RE.sub("", t).strip()
        if nxt == t:
            break
        t = nxt

    # AI增强 / 分辨率 / ed2k 技术标签
    t = _strip_ai_resolution_noise(t)

    # 复合技术标签（破解/调色/ED2K…）整段剥掉
    for _ in range(4):
        nxt = _FORUM_TECH_SLASH_TAG_RE.sub(" ", t)
        nxt = _WS_RE.sub(" ", nxt).strip()
        if nxt == t:
            break
        t = nxt

    # 【MP4/无码】【MP4/中文字幕】类斜杠标签
    t = _MP4_SLASH_TAG_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()

    # 反复剥前缀版块标签
    for _ in range(4):
        nxt = _FORUM_BOARD_TAG_RE.sub("", t).strip()
        if nxt == t:
            break
        t = nxt

    # 任意位置的中括号标签（帖标题常见）
    t = _strip_inline_forum_tags(t)
    for _ in range(3):
        nxt = _FORUM_ORPHAN_TAG_RE.sub("", t).strip()
        if nxt == t:
            break
        t = nxt
    t = _LEADING_4K_BOOST_RE.sub("", t).strip()

    # 自购/转载等来源前缀
    for _ in range(3):
        nxt = _FORUM_SOURCE_PREFIX_RE.sub("", t).strip()
        if nxt == t:
            break
        t = nxt

    # 国产片商名 + 全场番号/FC2 代号
    t = _strip_china_studio_and_code(t, needle)
    t = _strip_code_tokens(t, needle)
    t = _strip_orphan_meta_prefix(t)

    # 题首/装饰后的孤立分集序号（1片名、❤-1片名）
    for _ in range(2):
        nxt = _LEADING_EPISODE_ORD_RE.sub("", t).strip()
        nxt = _EMOJI_EPISODE_ORD_RE.sub(" ", nxt)
        nxt = _WS_RE.sub(" ", nxt).strip()
        if nxt == t:
            break
        t = nxt

    # ★…★ 装饰噪声
    t = _FORUM_STAR_NOISE_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()
    # 剥星号后再清一轮序号残渣
    t = _LEADING_EPISODE_ORD_RE.sub("", t).strip()
    t = _EMOJI_EPISODE_ORD_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()
    # 日期前缀
    t = _FORUM_DATE_PREFIX_RE.sub("", t).strip()
    t = _FORUM_EMPTY_PAREN_RE.sub(" ", t)
    t = _strip_orphan_meta_prefix(t)
    t = _WS_RE.sub(" ", t).strip()

    # 开头番号（含 [HEYZO-3291] 形态）
    if needle:
        lead_re, mid_re, bare_re, paren_re = _needle_clean_res(needle)
        t = lead_re.sub("", t).strip()
        t = _GENERIC_PREFIX_CODE_RE.sub("", t).strip()
        # 文中残留番号（清洗标签后常见）
        t = mid_re.sub(" ", t)
        t = bare_re.sub(" ", t)
        t = paren_re.sub(" ", t)
        # C0930 ki231024 / 板号+日期串
        t = _BOARD_DATE_CODE_RE.sub(" ", t)
        t = _WS_RE.sub(" ", t).strip()

    # 括号内版本/字幕噪声（可多段）
    for _ in range(4):
        nxt = _FORUM_BRACKET_NOISE_RE.sub(" ", t)
        nxt = _WS_RE.sub(" ", nxt).strip()
        if nxt == t:
            break
        t = nxt

    # 尾部体积标签先剥（避免媒体后缀先吃掉 /4K】 留下残缺括号）
    t = _FORUM_SIZE_TAIL_RE.sub("", t).strip()
    for _ in range(3):
        nxt = _FORUM_META_TAIL_BRACKET_RE.sub("", t).strip()
        nxt = _FORUM_META_TAIL_BRACKET_ALT_RE.sub("", nxt).strip()
        if nxt == t:
            break
        t = nxt
    # 残缺体积尾巴：…！【3.18G/1V/19分  或 【1V/12.7G/57分/4K60帧】
    t = _META_TAIL_BROKEN_RE.sub("", t).strip()
    t = _META_TAIL_V_RE.sub("", t).strip()

    # 尾部介质/版本后缀
    for _ in range(4):
        nxt = _FORUM_MEDIA_SUFFIX_RE.sub("", t).strip()
        if nxt == t:
            break
        t = nxt

    # 开头残留「无码/有码」及括号形态
    t = _LEADING_ZONE_STRIP_RE.sub("", t).strip()

    # 文件后缀 / -1080P 类尾巴
    t = _FORUM_FILE_EXT_TAIL_RE.sub("", t).strip()
    t = _FORUM_DASH_QUALITY_TAIL_RE.sub("", t).strip()
    t = _FORUM_RES_TAIL_RE.sub("", t).strip()
    t = _RES_P_TAIL_RE.sub("", t).strip()
    t = _FORUM_TECH_TAIL_RE.sub("", t).strip()
    t = _FORUM_BROKEN_META_TAIL_RE.sub("", t).strip()
    t = _TRAILING_BANG_RE.sub("", t).strip()
    for _ in range(3):
        nxt = _FORUM_LEADING_QUALITY_RE.sub("", t).strip()
        if nxt == t:
            break
        t = nxt

    # 无括号粘连的版本尾巴：…无码破解听译修正版
    t = _VERSION_TAIL_RE.sub("", t).strip()
    t = _NO_CODE_NEW_PAREN_RE.sub("", t).strip()

    # 末尾女优名（可带顿号/句号/空格分隔；含简繁异体字）
    t = _strip_trailing_actor_name(t, actors or [])

    # 破折号 / 全角括号：有中文译名则优先中文
    t = _prefer_chinese_segment(t)

    t = _TRAILING_PUNCT_RE.sub("", t).strip()
    t = _LEADING_PUNCT_CLEAN_RE.sub("", t).strip()
    t = _FORUM_LEADING_PUNCT_RE.sub("", t).strip()
    t = _LEADING_EPISODE_ORD_RE.sub("", t).strip()
    t = _strip_orphan_meta_prefix(t)
    # 再剥一轮残留括号标签（番号剥离后露出的）
    t = _strip_inline_forum_tags(t)
    if len(t) > 100:
        t = t[:100].rstrip()
    if needle and t.upper() == needle:
        return ""
    if _FORUM_GENERIC_ONLY_RE.fullmatch(t) and not allow_weak:
        return ""
    if _FORUM_ACTOR_AGE_ONLY_RE.fullmatch(t) and not allow_weak:
        return ""
    t = _FORUM_BROKEN_BRACKET_TAIL_RE.sub("", t).strip()
    # 合集元信息被抠成「标题」时丢掉（宁缺毋假，弱模式也不保留壳）
    if t and _FORUM_META_ZH_JUNK_RE.search(t) and len(t) < _META_SHELL_CLEAN_LEN:
        return ""
    if len(t) < 4:
        # 短中文正片名（上海滩 / 绿帽）保留；其它过短宁缺
        if _SHORT_CJK_TITLE_RE.fullmatch(t):
            if is_fake_forum_title(t, needle):
                return ""
            return t
        if allow_weak:
            # 弱兜底：保留剥标签后的原文片段；假壳仍清空
            weak = _WS_RE.sub(" ", raw_keep).strip()
            if needle:
                weak = _needle_clean_res(needle)[0].sub("", weak).strip()
            weak = _strip_inline_forum_tags(weak)
            weak = weak[:80].strip()
            if (
                weak
                and weak.upper() != needle
                and not is_fake_forum_title(weak, needle)
            ):
                return weak
        return ""
    if is_fake_forum_title(t, needle):
        return ""
    return t


def _prefer_chinese_segment(t: str) -> str:
    """同一帖题里：中文括号译名 / 破折号右侧中文 优先于日文原文。"""
    raw = str(t or "").strip()
    if not raw:
        return ""

    def _usable_zh(s: str) -> bool:
        s = str(s or "").strip()
        if not is_likely_chinese(s):
            return False
        # 排除纯分区词 / 过短女优名 / 合集元信息
        if _ZONE_ONLY_RE.fullmatch(s):
            return False
        if _FORUM_META_ZH_JUNK_RE.search(s):
            return False
        # 人名形短串不当译名（避免「（花咲澪）」盖掉日文）
        try:
            from .forum_seed import _looks_like_bare_actor_title

            if _looks_like_bare_actor_title(s):
                return False
        except Exception:
            pass
        # 短纯中文译名可取（绿帽/上海滩）；过短拉丁/混排仍拒
        if len(s) < 8:
            return bool(re.fullmatch(r"[\u4e00-\u9fff]{2,7}", s))
        # 真译名一般较长，短壳「含单体+共演+写真」不要
        if len(s) < 12 and _PLUS_SLASH_RE.search(s):
            return False
        return True

    # （中文译名）或 (中文译名)
    for m in _PAREN_INNER_RE.finditer(raw):
        inner = m.group(1).strip()
        if _usable_zh(inner):
            return inner

    if _FORUM_EM_DASH_SPLIT_RE.search(raw):
        left, right = _FORUM_EM_DASH_SPLIT_RE.split(raw, maxsplit=1)
        left, right = left.strip(), right.strip()
        # 右侧整段是中文片名（够长，非女优短名）
        if _usable_zh(right):
            return right
        # 右侧里再挖括号中文
        for m in _PAREN_INNER_RE.finditer(right):
            inner = m.group(1).strip()
            if _usable_zh(inner):
                return inner
        # 右侧去假名女优前缀后仍是中文
        right_stripped = _LEADING_KANA_LATIN_RE.sub("", right).strip(" （()）")
        if _usable_zh(right_stripped):
            return right_stripped
        # 右侧只是女优名：保留左侧日文片名
        if len(left) >= 4:
            return left

    # 日文名 + 空格 + 中文译名：取无假名的中文段
    if _KANA_RE.search(raw) and _CJK_RE.search(raw):
        parts = _SPACE_SPLIT_RE.split(raw)
        zh_parts = [p for p in parts if _usable_zh(p)]
        if zh_parts:
            joined = " ".join(zh_parts)
            if _usable_zh(joined) or is_likely_chinese(joined):
                return joined

    return raw


def is_likely_chinese(title: str | None) -> bool:
    """简体/繁体中文片名（无假名）— 对齐 scrape util.isLikelyChinese。"""
    t = str(title or "").strip()
    if not t or not _CJK_RE.search(t):
        return False
    # 忽略中点・等标点，勿把「教室・厕所」判成日文（・属假名区 U+30FB）
    body = re.sub(r"[\s・･·‧\-–—:：|/／～~]", "", t)
    if _KANA_RE.search(body):
        return False
    # 英文片名末尾挂女优中文名不算中文题
    cjk = sum(1 for ch in t if "\u4e00" <= ch <= "\u9fff")
    if cjk / max(len(t), 1) < 0.35 and cjk < 8:
        return False
    return True


# 本地索引 titleZh 可复用门槛：壳题 / 截断壳不合格 → 仍走网络
_TITLE_ZH_TRUNC_TAIL_RE = re.compile(r"[、，,…]+$")
_TITLE_ZH_BROKEN_LEAD_RE = re.compile(r"^.{1,4}[、，,]")
_TITLE_ZH_WESTERN_NAME_RE = re.compile(
    r"^[\u4e00-\u9fff]{2,8}[-·・‧][\u4e00-\u9fff]{2,12}$"
)
_TITLE_ZH_AV_SHELL_RE = re.compile(
    r"^(?:AV)?(?:隐退作|引退作|出道作|解禁作|引退|隐退)$|"
    r"^AV初[体體][験驗].{0,6}$",
    re.I,
)


def is_quality_chinese_title(title: str | None, code: str = "") -> bool:
    """刮削本地复用门：真中文 + 非假壳/截断壳。

    质量差的索引中文题视为不合格，须网上补 titleZh。
    """
    t = str(title or "").strip()
    if not t or not is_likely_chinese(t):
        return False
    if is_fake_forum_title(t, code):
        return False
    if _TITLE_ZH_TRUNC_TAIL_RE.search(t):
        return False
    if _TITLE_ZH_BROKEN_LEAD_RE.match(t) and len(t) < 16:
        return False
    if _TITLE_ZH_AV_SHELL_RE.fullmatch(t):
        return False
    if _TITLE_ZH_WESTERN_NAME_RE.fullmatch(t) and len(t) <= 14:
        return False
    try:
        from .forum_seed import _looks_like_bare_actor_title

        if _looks_like_bare_actor_title(t):
            return False
    except Exception:
        pass
    return True


def is_likely_japanese(title: str | None) -> bool:
    """含假名的日文片名（非纯中文）— 对齐 scrape util.isLikelyJapanese。"""
    t = str(title or "").strip()
    if not t or is_likely_chinese(t):
        return False
    return bool(_KANA_EXT_RE.search(t))


def is_indexable_forum_title(
    title: str | None,
    code: str = "",
    *,
    assume_not_fake: bool = False,
) -> bool:
    """索引可写标题：中文优先候选 / 日文正片兜底；假壳与纯拉丁壳不可写。

    正常：合格中文，或含汉字/假名的日文正片名（非短昵称）。
    非正常：假壳、合集壳、番号+介质、纯英文罗马字、短假名昵称等 → 宁缺毋假。
    assume_not_fake=True：调用方已确认非假壳（如刚过 clean），跳过完整 is_fake。
    """
    t = str(title or "").strip()
    if not t:
        return False
    if not assume_not_fake and is_fake_forum_title(t, code):
        return False
    if _is_short_kana_nick(t):
        return False
    if is_likely_chinese(t):
        return True
    if is_likely_japanese(t):
        # 日文正片至少要有一定长度；纯短昵称已在上面拒绝
        core = _WS_NICK_RE.sub("", t)
        return len(core) >= 5
    # 少量汉字题（无假名、不够 is_likely_chinese 阈值）仍可作兜底
    if _CJK_RE.search(t) and len(t) >= 4:
        return True
    return False


# 兼容旧名
_clean_forum_zh_title = clean_forum_zh_title
