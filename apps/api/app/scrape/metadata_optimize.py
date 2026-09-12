"""刮削后元数据优化（色花堂中文标题 / 演员·标签映射 / 简介换行）。"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.db import ROOT

MAPPING_LANGS = frozenset({"zh-CN", "zh-TW", "ja", "en"})
_MULTI_NL_RE = re.compile(r"\n{2,}")
# 色花堂字段偶发装饰：首尾 +/-/~ / 全角～
_ACTOR_DIRTY_RE = re.compile(r"^[\+\-\~\～\s　]+|[\+\-\~\～\s　]+$")

# 促销 / 活动 / 临时性标签：源站常把「セール」「%オフ」当 genre，统一当噪声丢弃。
_TAG_PROMO_RE = re.compile(
    r"(セール|％オフ|%オフ|オフセール|クーポン|キャンペーン|アウトレット|バーゲン|"
    r"\bsale\b|\boff\b|セット商品|第[0-9０-９]+弾|期間限定|特別価格|奉仕価格|"
    r"ポイント還元|早割)",
    re.IGNORECASE,
)

# 年代 / 厂牌分类等元标签（如 `2010年代前半（DOD）`）：不是题材，统一丢弃。
_TAG_META_RE = re.compile(
    r"(?:19|20)\d{2}年代(?:前半|後半|中盤|初期|末期)?|"
    r"[（(](?:DOD|MGS|SOD)[）)]",
    re.IGNORECASE,
)

# 前缀恰好等于这些「有意义缩写」时不做前缀噪声处理（避免误伤题材标签）。
_TAG_PREFIX_KEEP = frozenset(
    {"SM", "VR", "OL", "POV", "JK", "AV", "NTR", "BD", "DVD", "HD", "FHD", "UHD"}
)

# 繁 / 日 → 简 常用变体对（空格分隔，每对 2 字）。仅作**映射兜底**：精确命中仍优先，
# 故不会改变既有正确结果；但能根治「繁简分裂」——映射表只写了 `義母` 时，源站的
# `义母` 也能收敛到同一标准名，不必逐字往表里补（历史反复踩此坑）。
_TAG_VARIANT_PAIR_TEXT = """
義义 體体 後后 國国 興兴 專专 質质 畫画 婦妇 獨独 數数 碼码 溫温 亂乱 戀恋 顏颜 觀观
恥耻 縛缚 緊紧 絲丝 腳脚 誘诱 襪袜 鈴铃 愛爱 學学 級级 樂乐 業业 餘余 東东 車车 馬马
鳥鸟 頭头 臉脸 髮发 發发 麼么 點点 團团 島岛 夢梦 龍龙 龜龟 賣卖 讀读 說说 課课 註注
預预 順顺 願愿 類类 風风 飛飞 飯饭 養养 齊齐 齒齿 齡龄 龐庞 彙汇 徑径 從从 懲惩 懷怀
戲戏 戶户 攜携 敘叙 斷断 時时 曆历 書书 會会 極极 構构 樣样 樹树 機机 檢检 權权 歡欢
歲岁 歷历 殺杀 氣气 決决 沒没 淚泪 淨净 涼凉 淺浅 測测 準准 滿满 潔洁 濃浓 濕湿 濟济
濱滨 濫滥 瀉泻 燈灯 營营 燦灿 爭争 爾尔 牆墙 猶犹 獲获 現现 產产 疇畴 瘋疯 療疗 監监
盡尽 睞睐 矯矫 確确 礙碍 偽伪 禮礼 種种 積积 稱称 穩稳 窮穷 竊窃 競竞 筆笔 節节 範范 築筑
篩筛 簡简 簽签 糧粮 紀纪 約约 紅红 純纯 紙纸 細细 終终 組组 結结 給给 統统 經经 綠绿
維维 綱纲 網网 線线 練练 總总 績绩 織织 繡绣 繼继 續续 纖纤 罰罚 羅罗 聯联 聽听 肅肃
膚肤 臨临 舉举 舊旧 藝艺 處处 號号 蟲虫 補补 裝装 褲裤 見见 規规 視视 親亲 覺觉 訂订
計计 討讨 記记 訓训 訊讯 評评 詞词 試试 詩诗 話话 該该 詳详 語语 誠诚 誤误 認认 調调
談谈 請请 論论 諒谅 謂谓 講讲 謝謝 證证 識识 譯译 議议 護护 變变 讓让 豐丰 豬猪 貓猫
貝贝 負负 財财 責责 貴贵 買买 貸贷 費费 賀贺 資资 賓宾 賢贤 賬账 購购 賽赛 賞赏 賜赐
賺赚 贈赠 贊赞 贏赢 跡迹 蹤踪 軌轨 軍军 軒轩 軟软 較较 載载 輪轮 轉转 辦办 辭辞 農农
迴回 過过 達达 違违 遠远 適适 選选 遺遗 邊边 邏逻 鄉乡 醫医 釀酿 釋释 裡里 裏里 針针
釘钉 釣钓 銀银 銅铜 銷销 鎖锁 鏡镜 鐵铁 鑄铸 長长 門门 閉闭 開开 間间 關关 陽阳 陰阴
陣阵 階阶 際际 隨随 險险 隱隐 隻只 難难 雛雏 雲云 電电 霧雾 靈灵 靜静 韻韵 頁页 頂顶
須须 頗颇 領领 頰颊 頸颈 頻频 顆颗 題题 額额 顧顾 顯显 駕驾 騎骑 驚惊 驗验 鬥斗 鳴鸣
雞鸡 麗丽 黃黄 黨党
實实 變变 氣气 單单 發发 顔颜 齢龄 験验 権权 総总 戦战 対对 団团 応应 帰归 広广 経经
続续 読读 売卖 児儿 説说 覚觉 楽乐 薬药 沢泽 浜滨 縄绳 検检 険险 顕显 辺边 剣剑 圏圈
増增 徳德 歩步 歴历 挙举 拠据 営营 壊坏 亜亚 髪发 滝泷 鹽盐 獻献
澤泽 齋斋 蠻蛮 橫横 蠟蜡 驅驱 鬆松 実实 紗纱 倉仓 淺浅 優优 恵惠 進进
連连 屬属 們们 務务 動动 員员 標标 與与 於于 卻却 寬宽 閒闲 導导 術术 製制 獎奖 蓋盖
壓压 髒脏 鳳凤 億亿 衝冲 継继 執执 勢势 勝胜 區区 館馆 圍围 園园 圓圆 圖图 場场 壞坏
媽妈 姊姐 寶寶 宮宫 寫写 審审 層层 帥帅 師师 帳帐 帶带 幫帮 幾几 廣广 廳厅 張张 強强
彈弹 徹彻 態态 擴扩 攝摄 擺摆 敗败 敵敌 橋桥 歐欧 歸归 尋寻 對对 屆届 岡冈 巔巅 幀帧
恆恒 慮虑 慶庆 憲宪 懸悬 懶懒 拋抛 捨舍 掃扫 掛挂 採采 換换 揚扬 損损 搖摇 搶抢 榮荣
樸朴 櫃柜 殘残 毆殴 慘惨 慚惭 應应 懼惧 攔拦 攔拦 攤摊 斃毙 斷断 晝昼 暫暂 檔档 檢检
權权 歐欧 歸归 歲岁 殘残 殺杀 毆殴 氣气 決决 沒没 淚泪 淨净 涼凉 淺浅 測测 準准 滿满
潔洁 濃浓 濕湿 濟济 濱滨 濫滥 瀉泻 燈灯 營营 燦灿 爭争 爾尔 牆墙 猶犹 獲获 現现 產产
疇畴 瘋疯 療疗 監监 盡尽 睞睐 矯矫 確确 礙碍 禮礼 種种 積积 稱称 穩稳 窮穷 竊窃 競竞
筆笔 節节 範范 築筑 篩筛 簡简 簽签 糧粮 紀纪 約约 紅红 純纯 紙纸 細细 終终 組组 結结
給给 統统 經经 綠绿 維维 綱纲 網网 線线 練练 總总 績绩 織织 繡绣 繼继 續续 纖纤 罰罚
羅罗 聯联 聽听 肅肃 膚肤 臨临 舉举 舊旧 藝艺 處处 號号 蟲虫 補补 裝装 褲裤 見见 規规
視视 親亲 覺觉 訂订 計计 討讨 記记 訓训 訊讯 評评 詞词 試试 詩诗 話话 該该 詳详 語语
誠诚 誤误 認认 調调 談谈 請请 論论 諒谅 謂谓 講讲 謝謝 證证 識识 譯译 議议 護护 變变
讓让 豐丰 豬猪 貓猫 貝贝 負负 財财 責责 貴贵 買买 貸贷 費费 賀贺 資资 賓宾 賢贤 賬账
購购 賽赛 賞赏 賜赐 賺赚 贈赠 贊赞 贏赢 跡迹 蹤踪 軌轨 軍军 軒轩 軟软 較较 載载 輪轮
轉转 辦办 辭辞 農农 迴回 過过 達达 違违 遠远 適适 選选 遺遗 邊边 邏逻 鄉乡 醫医 釀酿
釋释 裡里 裏里 針针 釘钉 釣钓 銀银 銅铜 銷销 鎖锁 鏡镜 鐵铁 鑄铸 長长 門门 閉闭 開开
間间 關关 陽阳 陰阴 陣阵 階阶 際际 隨随 險险 隱隐 隻只 難难 雛雏 雲云 電电 霧雾 靈灵
靜静 韻韵 頁页 頂顶 須须 頗颇 領领 頰颊 頸颈 頻频 顆颗 題题 額额 顧顾 顯显 駕驾 騎骑
驚惊 驗验 鬥斗 鳴鸣 雞鸡 麗丽 黃黄 黨党
來来 棲栖 両两 傳传 傷伤 傾倾 價价 儀仪 凍冻 凱凯 劃划 劉刘 剛刚 劇剧 勁劲 協协 參参
叢丛 吳吴 呂吕 墊垫 夠够 奪夺 奮奋 妝妆 娛娱 孫孙 寧宁 寢寝 廢废 廚厨 廈厦 廁厕 廟庙
彌弥 彎弯 惡恶 悶闷 憐怜 懇恳 烏乌 煙烟 熱热 疊叠 盤盘 萬万 虛虚 蘭兰 蝦虾 蠟蜡 捲卷
覽览 誌志 誰谁 諾诺 謀谋 謎谜 謹谨 趨趋 躍跃 輔辅 輕轻 輛辆 輝辉 輩辈 輯辑 輸输 轟轰
轎轿 貞贞 貢贡 貧贫 貨货 販贩 貪贪 貫贯 貼贴 賊贼 賭赌 趕赶 燄焰 癮瘾 禪禅 聳耸 脅胁
脈脉 舖铺 紮扎 綁绑 綜综 縫缝 縮缩 罷罢 翹翘 瑩莹 甦苏 瓊琼 遼辽 齋斋 齒齿 亂乱
幹干 砲炮 褻亵 著着 鬧闹 鬱郁 莊庄 蘇苏 傑杰 爐炉 冊册 兇凶 臥卧 腎肾 腫肿 擊击
嚐尝 嚥咽 婁娄 嫵妩 嬌娇 瓏珑 癢痒 睜睁 矇蒙 碼码 稈秆 稜棱 竄窜 窩窝 窮穷
無无 竜龙 歳岁 亞亚 臺台 灣湾 撿捡 寶宝 兒儿 兩两 聲声 錄录 鍾钟 錢钱 闆板
雖虽 驕骄 麥麦 嚴严 繩绳 鹹咸 骯肮 臟脏 腦脑 屍尸 內内 峯峰 巖岩 巒峦 嶇岖 齣出
"""

_TAG_VARIANT_FOLD: dict[str, str] = {}
for _p in _TAG_VARIANT_PAIR_TEXT.split():
    if len(_p) == 2 and _p[0] != _p[1]:
        _TAG_VARIANT_FOLD.setdefault(_p[0], _p[1])
del _p
# str.translate 需要「码位 → 码位」映射
_TAG_VARIANT_TRANS = str.maketrans(_TAG_VARIANT_FOLD) if _TAG_VARIANT_FOLD else {}


def code_prefix(code: str) -> str:
    """番号 → 前缀（`NDRA-117` → `NDRA`）。用于清理被当 genre 的系列前缀。"""
    m = re.match(r"^\s*([A-Za-z]+)", str(code or ""))
    return m.group(1).upper() if m else ""


def tag_is_noise(name: str, *, prefix: str = "") -> bool:
    """通用噪声标签：促销/活动词、番号前缀（源站常误当 genre）。

    这是「批量也不会踩」的根本防线——无需逐条往映射表里补前缀。
    """
    s = str(name or "").strip()
    if not s:
        return True
    if _TAG_PROMO_RE.search(s) or _TAG_META_RE.search(s):
        return True
    p = str(prefix or "").strip().upper()
    if p and p not in _TAG_PREFIX_KEEP:
        if re.fullmatch(
            rf"{re.escape(p)}[0-9]*(?:\s*-\s*[0-9]+)?", s, re.IGNORECASE
        ):
            return True
    return False

DEFAULT_METADATA_OPTIMIZE: dict[str, Any] = {
    "useForumZhTitle": False,
    "enableActorMapping": True,
    "enableTagMapping": True,
    "compactOutlineNewlines": True,
    "mappingLanguage": "zh-CN",
}

_MAPS_DIR = ROOT / "data" / "scrape_maps"


def _clean_actor_raw(name: str) -> str:
    s = str(name or "").strip()
    if not s:
        return ""
    # 半角片假名等：倉本ｽﾐﾚ → 倉本すみれ，便于映射命中
    s = unicodedata.normalize("NFKC", s)
    s = _ACTOR_DIRTY_RE.sub("", s).strip()
    # 完整括号备注：愛染恭子（青山涼子）
    s = re.sub(r"\s*[\(（][^)）]*[\)）]\s*$", "", s).strip()
    # 半截开括号（JavBus span 截断）：愛染恭子（
    s = re.sub(r"\s*[\(（][^)）]*$", "", s).strip()
    s = s.rstrip("（(").strip()
    return re.sub(r"\s+", " ", s)


_CACHED_MAPPING_LANG: str | None = None
_SETTING_MAP_ENABLED: bool | None = None


def mapping_language_from_settings() -> str:
    """读 library / 旧 scrape 配置里的 mappingLanguage，失败则 zh-CN。"""
    global _CACHED_MAPPING_LANG
    if _CACHED_MAPPING_LANG is not None:
        return _CACHED_MAPPING_LANG
    try:
        import app.core.settings_store as settings_store

        raw = settings_store.get_setting(settings_store.LIBRARY_KEY) or settings_store.get_setting("scrape") or {}
        if not isinstance(raw, dict):
            lang = str(DEFAULT_METADATA_OPTIMIZE["mappingLanguage"])
        else:
            opt = normalize_metadata_optimize(
                raw.get("metadataOptimize") or raw.get("metadata_optimize")
            )
            lang = str(opt["mappingLanguage"])
    except Exception:
        lang = str(DEFAULT_METADATA_OPTIMIZE["mappingLanguage"])
    _CACHED_MAPPING_LANG = lang
    return lang


def normalize_actor_names(
    actors: list[str] | None,
    *,
    lang: str | None = None,
    enable: bool | None = None,
) -> list[str]:
    """索引/聚合后把女优名规范成映射表标准名（去重保序）。

    enable=None 时跟刮削「启用演员映射」；索引展示默认开映射。
    """
    raw_list = [str(a).strip() for a in (actors or []) if str(a or "").strip()]
    if not raw_list:
        return []

    use_map = True if enable is None else bool(enable)
    if enable is None:
        try:
            import app.core.settings_store as settings_store

            raw = settings_store.get_setting(settings_store.LIBRARY_KEY) or settings_store.get_setting("scrape") or {}
            if isinstance(raw, dict):
                opt = normalize_metadata_optimize(
                    raw.get("metadataOptimize") or raw.get("metadata_optimize")
                )
                use_map = bool(opt["enableActorMapping"])
        except Exception:
            use_map = True

    if not use_map:
        # 仍清脏装饰并去重
        out: list[str] = []
        seen: set[str] = set()
        for a in raw_list:
            name = _clean_actor_raw(a) or a
            if name in seen:
                continue
            seen.add(name)
            out.append(name)
        return out

    return polish_actress_names(
        raw_list, lang=lang or mapping_language_from_settings(), enable_mapping=True
    )


def normalize_metadata_optimize(raw: Any) -> dict[str, Any]:
    src = raw if isinstance(raw, dict) else {}
    lang = str(
        src.get("mappingLanguage")
        or src.get("mapping_language")
        or DEFAULT_METADATA_OPTIMIZE["mappingLanguage"]
    ).strip()
    if lang in {"zh", "zh_cn", "zh-cn", "cn", "hans", "简体", "简体中文"}:
        lang = "zh-CN"
    elif lang in {"zh_tw", "zh-tw", "tw", "hant", "繁体", "繁體", "繁体中文"}:
        lang = "zh-TW"
    elif lang in {"jp", "japanese", "日文", "日本語"}:
        lang = "ja"
    elif lang in {"eng", "english", "英文"}:
        lang = "en"
    if lang not in MAPPING_LANGS:
        lang = "zh-CN"

    def _b(key: str, *alts: str, default: bool = True) -> bool:
        for k in (key, *alts):
            if k in src and src[k] is not None:
                return bool(src[k])
        return default

    return {
        "useForumZhTitle": _b(
            "useForumZhTitle", "use_forum_zh_title", "useSehuatangTitle", default=True
        ),
        "enableActorMapping": _b(
            "enableActorMapping", "enable_actor_mapping", default=True
        ),
        "enableTagMapping": _b(
            "enableTagMapping", "enable_tag_mapping", default=True
        ),
        "compactOutlineNewlines": _b(
            "compactOutlineNewlines",
            "compact_outline_newlines",
            "trimOutlineNewlines",
            default=True,
        ),
        "mappingLanguage": lang,
    }


def _lang_file_stem(lang: str) -> str:
    return {
        "zh-CN": "zh-CN",
        "zh-TW": "zh-TW",
        "ja": "ja",
        "en": "en",
    }.get(lang, "zh-CN")


@lru_cache(maxsize=16)
def _load_json_map(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


_CASEFOLD_INDEX: dict[int, dict[str, Any]] = {}


_SETTING_MAP_ENABLED: bool | None = None


def clear_map_cache() -> None:
    global _SETTING_MAP_ENABLED, _CACHED_MAPPING_LANG
    _load_json_map.cache_clear()
    _CASEFOLD_INDEX.clear()
    _VARIANT_INDEX.clear()
    _SETTING_MAP_ENABLED = None
    _CACHED_MAPPING_LANG = None


def _actor_mapping_enabled() -> bool:
    global _SETTING_MAP_ENABLED
    if _SETTING_MAP_ENABLED is not None:
        return _SETTING_MAP_ENABLED
    use_map = True
    try:
        import app.core.settings_store as settings_store

        raw = (
            settings_store.get_setting(settings_store.LIBRARY_KEY)
            or settings_store.get_setting("scrape")
            or {}
        )
        if isinstance(raw, dict):
            opt = normalize_metadata_optimize(
                raw.get("metadataOptimize") or raw.get("metadata_optimize")
            )
            use_map = bool(opt["enableActorMapping"])
    except Exception:
        use_map = True
    _SETTING_MAP_ENABLED = use_map
    return use_map


def _actor_maps(lang: str) -> dict[str, Any]:
    stem = _lang_file_stem(lang)
    # 优先用户 data/scrape_maps，再回退仓库内 seed
    roots = (
        _MAPS_DIR,
        Path(__file__).resolve().parent / "scrape_maps_seed",
    )
    for root in roots:
        for name in (f"actors.{stem}.json", "actors.json"):
            m = _load_json_map(str(root / name))
            if m:
                return m
    return {}


def _tag_maps(lang: str) -> dict[str, Any]:
    stem = _lang_file_stem(lang)
    roots = (
        _MAPS_DIR,
        Path(__file__).resolve().parent / "scrape_maps_seed",
    )
    for root in roots:
        for name in (f"tags.{stem}.json", "tags.json"):
            m = _load_json_map(str(root / name))
            if m:
                return m
    return {}


def actor_maps_loaded(lang: str | None = None) -> dict[str, Any]:
    """供任务状态展示：映射表条目数。"""
    table = _actor_maps(lang or mapping_language_from_settings())
    return {"count": len(table), "lang": lang or mapping_language_from_settings()}


def _casefold_index(table: dict[str, Any]) -> dict[str, Any]:
    tid = id(table)
    hit = _CASEFOLD_INDEX.get(tid)
    if hit is not None:
        return hit
    idx: dict[str, Any] = {}
    for k, v in table.items():
        raw = str(k).strip()
        if not raw:
            continue
        idx[raw.casefold()] = v
        folded = _kana_fold(raw)
        if folded and folded.casefold() not in idx:
            idx[folded.casefold()] = v
    _CASEFOLD_INDEX[tid] = idx
    return idx


def _kana_fold(s: str) -> str:
    """片假名 → 平假名，便于 倉本スミレ / 倉本すみれ 命中同一映射。"""
    out: list[str] = []
    for ch in str(s or ""):
        o = ord(ch)
        if 0x30A1 <= o <= 0x30F6:  # ァ-ヶ
            out.append(chr(o - 0x60))
        else:
            out.append(ch)
    return "".join(out)


def _fold_variant(s: str) -> str:
    """繁/日 → 简 折叠（仅用于映射兜底，解繁简分裂）。"""
    if not _TAG_VARIANT_TRANS:
        return str(s or "")
    return str(s or "").translate(_TAG_VARIANT_TRANS)


_VARIANT_INDEX: dict[int, dict[str, Any]] = {}


def _variant_index(table: dict[str, Any]) -> dict[str, Any]:
    """折叠索引：键与标准名（value）都折叠后建索引，供模糊兜底命中。

    先索引键（原始/折叠/假名折叠），再索引标准名——故「键」优先级始终高于
    「别的条目的标准名」，不会误改既有正确结果。
    """
    tid = id(table)
    hit = _VARIANT_INDEX.get(tid)
    if hit is not None:
        return hit
    idx: dict[str, Any] = {}
    for k in table:
        raw = str(k).strip()
        if not raw:
            continue
        v = table[k]
        idx.setdefault(raw.casefold(), v)
        idx.setdefault(_fold_variant(raw).casefold(), v)
        idx.setdefault(_kana_fold(_fold_variant(raw)).casefold(), v)
    # 标准名（如 `继母` 是 `義母` 的目标）也纳入，使 繁/日 写法都能收敛
    for v in table.values():
        name = v
        if isinstance(v, dict):
            name = v.get("name") or v.get("zh") or v.get("title") or ""
        if isinstance(name, str) and name.strip():
            idx.setdefault(_fold_variant(name).casefold(), v)
            idx.setdefault(_kana_fold(_fold_variant(name)).casefold(), v)
    _VARIANT_INDEX[tid] = idx
    return idx


def _lookup_actor_hit(raw_name: str, table: dict[str, Any]) -> Any:
    key = str(raw_name or "").strip()
    if not key:
        return None
    cleaned = _clean_actor_raw(key)
    variants: list[str] = []
    for cand in (key, cleaned, _kana_fold(key), _kana_fold(cleaned)):
        c = str(cand or "").strip()
        if c and c not in variants:
            variants.append(c)
    for cand in variants:
        hit = table.get(cand)
        if hit is not None:
            return hit
    low = _casefold_index(table)
    for cand in variants:
        hit = low.get(cand.casefold())
        if hit is not None:
            return hit
    # 繁/日 折叠兜底：表里只有 `藤宮櫻花` 时，`藤宫樱花` 也能命中（解女优名繁简分裂）
    vidx = _variant_index(table)
    for cand in variants:
        hit = vidx.get(_fold_variant(cand).casefold())
        if hit is not None:
            return hit
    return None


def _actor_should_drop(hit: Any) -> bool:
    """映射表标记男优 / 导演 / 原作等非女优 → 丢弃。"""
    if hit is None or isinstance(hit, str):
        return False
    if not isinstance(hit, dict):
        return False
    if hit.get("drop") is True or hit.get("exclude") is True:
        return True
    role = str(hit.get("role") or hit.get("type") or "").strip().casefold()
    if role in {
        "director",
        "导演",
        "監督",
        "male",
        "男优",
        "男優",
        "author",
        "writer",
        "原作",
        "漫画家",
        "artist",
        "作画",
        "staff",
    }:
        return True
    sex = str(hit.get("sex") or hit.get("gender") or "").strip().casefold()
    if sex in {"m", "male", "man", "男"}:
        return True
    return False


def _map_actor_entry(raw_name: str, table: dict[str, Any]) -> tuple[str, str]:
    """返回 (显示名, javdb链接)。drop 条目返回空名。"""
    key = str(raw_name or "").strip()
    if not key:
        return "", ""
    cleaned = _clean_actor_raw(key)
    display_fallback = cleaned or key
    hit = _lookup_actor_hit(key, table)
    if _actor_should_drop(hit):
        return "", ""
    if hit is None:
        return display_fallback, ""
    if isinstance(hit, str):
        return (hit.strip() or display_fallback), ""
    if isinstance(hit, dict):
        name = str(
            hit.get("name") or hit.get("zh") or hit.get("title") or ""
        ).strip()
        link = str(
            hit.get("javdb")
            or hit.get("javdbUrl")
            or hit.get("url")
            or hit.get("link")
            or ""
        ).strip()
        return (name or display_fallback), link
    return display_fallback, ""


def polish_actress_names(
    names: list[str] | None,
    *,
    exclude: list[str] | None = None,
    lang: str | None = None,
    enable_mapping: bool | None = None,
) -> list[str]:
    """女优名单优化：映射标准中文名 + 排除导演/男优/映射 drop。"""
    raw_list = [str(a).strip() for a in (names or []) if str(a or "").strip()]
    if not raw_list:
        return []

    ban = {
        str(x).strip().casefold()
        for x in (exclude or [])
        if str(x or "").strip()
    }

    use_map = True if enable_mapping is None else bool(enable_mapping)
    if enable_mapping is None:
        use_map = _actor_mapping_enabled()

    table = _actor_maps(lang or mapping_language_from_settings()) if use_map else {}
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_list:
        cleaned = _clean_actor_raw(raw) or raw
        if cleaned.casefold() in ban:
            continue
        if use_map and table:
            hit = _lookup_actor_hit(cleaned, table)
            if _actor_should_drop(hit):
                continue
            name, _ = _map_actor_entry(cleaned, table)
        else:
            name = cleaned
        name = str(name or "").strip()
        if not name or name.casefold() in ban:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def _map_tag(raw: str, table: dict[str, Any]) -> str:
    key = str(raw or "").strip()
    if not key:
        return ""
    import unicodedata

    key_n = unicodedata.normalize("NFKC", key)
    hit = table.get(key)
    if hit is None and key_n != key:
        hit = table.get(key_n)
    if hit is None:
        low = _casefold_index(table)
        hit = low.get(key.casefold()) or low.get(key_n.casefold())
    if hit is None:
        # 繁/日 折叠兜底：映射表只写了繁体键时，简体/日文写法也能命中（解繁简分裂）
        vidx = _variant_index(table)
        hit = (
            vidx.get(_fold_variant(key).casefold())
            or vidx.get(_fold_variant(key_n).casefold())
            or vidx.get(_kana_fold(_fold_variant(key)).casefold())
        )
    if hit is None:
        return key_n or key
    if isinstance(hit, dict) and (
        hit.get("drop") is True or hit.get("exclude") is True
    ):
        return ""
    if isinstance(hit, str):
        return hit.strip() or key_n
    if isinstance(hit, dict):
        return (
            str(hit.get("name") or hit.get("zh") or hit.get("title") or "").strip()
            or key_n
        )
    return key_n


_PAREN_SUFFIX_RE = re.compile(r"[（(][^）)]{0,40}[）)]\s*$")


def _strip_paren_suffix(s: str) -> str:
    """去掉末尾的（别名）/(别名)：用于识别「女优名（旧名）」类 bleed。"""
    return _PAREN_SUFFIX_RE.sub("", str(s or "")).strip()


def polish_tag_names(
    tags: list[str] | None,
    *,
    lang: str | None = None,
    enable_mapping: bool | None = None,
    exclude: list[str] | None = None,
    prefix: str = "",
) -> list[str]:
    """标签优化：映射简中标准名 + 同义合并 + drop 噪声/女优名串入/番号前缀/促销词。"""
    raw_list = [str(t).strip() for t in (tags or []) if str(t or "").strip()]
    if not raw_list:
        return []

    ban = {
        str(x).strip().casefold()
        for x in (exclude or [])
        if str(x or "").strip()
    }

    use_map = True if enable_mapping is None else bool(enable_mapping)
    if enable_mapping is None:
        try:
            import app.core.settings_store as settings_store

            raw = settings_store.get_setting(settings_store.LIBRARY_KEY) or settings_store.get_setting("scrape") or {}
            if isinstance(raw, dict):
                opt = normalize_metadata_optimize(
                    raw.get("metadataOptimize") or raw.get("metadata_optimize")
                )
                use_map = bool(opt["enableTagMapping"])
        except Exception:
            use_map = True

    table = _tag_maps(lang or mapping_language_from_settings()) if use_map else {}
    try:
        a_table = _actor_maps(lang or mapping_language_from_settings())
        extra_ban: set[str] = set()
        for x in exclude or []:
            hit = _lookup_actor_hit(str(x), a_table)
            if isinstance(hit, dict) and hit.get("name"):
                extra_ban.add(str(hit.get("name") or "").casefold())
                extra_ban.add(str(hit.get("zh") or "").casefold())
            elif isinstance(hit, str) and hit:
                extra_ban.add(hit.casefold())
            extra_ban.add(str(x).strip().casefold())
        # 映射表里指向同一人的键也禁
        canons = {b for b in extra_ban if b}
        if canons:
            for k, hit in a_table.items():
                name = ""
                if isinstance(hit, dict):
                    name = str(hit.get("name") or hit.get("zh") or "")
                elif isinstance(hit, str):
                    name = hit
                if name.casefold() in canons:
                    extra_ban.add(str(k).casefold())
                    extra_ban.add(name.casefold())
        ban |= {b for b in extra_ban if b}
    except Exception:
        pass
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_list:
        s_raw = str(raw).strip()
        if s_raw.casefold() in ban:
            continue
        # 「女优名（别名）」串入标签（如「日高ゆりあ（青山ひより）」）→ 按女优名 drop
        _base = _strip_paren_suffix(s_raw)
        if _base and _base != s_raw and _base.casefold() in ban:
            continue
        # 过短噪声（如「高」）
        if len(s_raw) <= 1:
            continue
        # 促销/活动词、番号前缀（源站常误当 genre）→ 通用丢弃
        if tag_is_noise(s_raw, prefix=prefix):
            continue
        name = _map_tag(raw, table) if table else raw
        name = str(name or "").strip()
        if not name or name.casefold() in ban:
            continue
        _nbase = _strip_paren_suffix(name)
        if _nbase and _nbase != name and _nbase.casefold() in ban:
            continue
        if len(name) <= 1:
            continue
        if tag_is_noise(name, prefix=prefix):
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def compact_outline(text: str) -> str:
    s = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not s:
        return ""
    s = _MULTI_NL_RE.sub("\n", s)
    return s.strip()


def apply_metadata_optimize(
    meta: dict[str, Any],
    cfg: dict[str, Any] | None,
    *,
    forum_title: str = "",
    forum_actors: list[str] | None = None,
) -> dict[str, Any]:
    """就地优化副本后返回。"""
    opt = normalize_metadata_optimize(cfg)
    out = dict(meta or {})
    lang = str(opt["mappingLanguage"])

    # 色花堂帖题/女优：字段优先级已在 scrape 阶段按配置选取；此处不再强制盖题
    forum = str(forum_title or "").strip()

    # 色花堂女优：帖内【出演女优】优先覆盖
    forum_acts = [
        str(a).strip()
        for a in (forum_actors or [])
        if str(a or "").strip()
    ]
    if forum_acts:
        out["actors"] = forum_acts
        fs = out.get("fieldSources") if isinstance(out.get("fieldSources"), dict) else {}
        fs = dict(fs)
        fs["actors"] = "forum"
        out["fieldSources"] = fs

    # 简介换行
    if opt["compactOutlineNewlines"]:
        for key in ("outline", "plot"):
            if key in out and out[key]:
                out[key] = compact_outline(str(out[key]))

    # 演员映射（中文标准名 + 排除男优/导演）
    if opt["enableActorMapping"]:
        directors: list[str] = []
        d0 = str(out.get("director") or "").strip()
        if d0:
            directors.append(d0)
        for d in out.get("directors") or []:
            if isinstance(d, dict):
                n = str(d.get("name") or "").strip()
            else:
                n = str(d or "").strip()
            if n:
                directors.append(n)
        actors = out.get("actors") if isinstance(out.get("actors"), list) else []
        if actors:
            mapped = polish_actress_names(
                actors,
                exclude=directors,
                lang=lang,
                enable_mapping=True,
            )
            out["actors"] = mapped
            table = _actor_maps(lang)
            links = [
                _map_actor_entry(a, table)[1] for a in mapped
            ]
            if any(links):
                out["actorLinks"] = links

    # 标题不再剥末尾女优名（女优只认描述字段）
    # actors 映射已在上方完成；title/titleZh 保持原清洗结果

    # 标签映射（带上女优名单做 bleed 排除 + 番号前缀清理）
    if opt["enableTagMapping"]:
        _ex = list(out.get("actors") or [])
        if isinstance(out.get("actor"), list):
            _ex += [str(x) for x in out.get("actor")]
        _pfx = code_prefix(out.get("code") or out.get("id"))
        for key in ("genres", "tags"):
            vals = out.get(key) if isinstance(out.get(key), list) else None
            if not vals:
                continue
            out[key] = polish_tag_names(
                vals, lang=lang, enable_mapping=True, exclude=_ex, prefix=_pfx
            )

    out["metadataOptimize"] = {
        "useForumZhTitle": opt["useForumZhTitle"],
        "enableActorMapping": opt["enableActorMapping"],
        "enableTagMapping": opt["enableTagMapping"],
        "compactOutlineNewlines": opt["compactOutlineNewlines"],
        "mappingLanguage": lang,
    }
    return out
