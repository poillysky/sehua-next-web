"""小花助手：统一卡片 / 消息协议。"""

from __future__ import annotations

import re
from typing import Any, Literal

AssistantSource = Literal["sehua", "magnet", "scrap", "media", "web"]

DEFAULT_SUGGEST_CHIPS: list[str] = [
    "三上悠亚 有码",
    "SSIS-001",
    "片商里找无码",
    "最近热门电影",
    "蓝光 磁力",
]

SYSTEM_PROMPT = """你是「小花」，用户的智能搜片助手。可查本地仓库(色花)、片商库、磁力(Bitmagnet)、影视元数据(TMDB等)、影人作品，以及（若已配置）网络搜索。

## 意图 → 工具（你必须自己判断，不要瞎调）
- 先读懂用户要什么：事实问答 / 作品清单 / 找片资源 / 多跳推导（由 A 推到 B）。
- 事实与片单（谁演的、演过哪些）：优先 media_search、media_person_works、web_search；交叉验证 2～3 次即可，够用就停，不要刷仓库/磁力。
- 要下载、种子、仓库资源：再开 sehua_* / scrap_* / magnet_*。
- AV/番号/女优 → scrap + sehua；正规电影剧 → media（+ 需要种子时再 magnet）；网上资料 → web_search。
- 同一轮可并行多个工具；依赖上一步结果时再分步。
- 多跳示例「给我镜中人女主演电影」：
  1) web_search / media_search 确认女主姓名（可中英双语检索，如「镜中人 女主」再查英文名）；
  2) media_person_works（或英文名再搜）列其作品；
  禁止只搜一次片名就把搜索命中当答案。
- 多轮约束（有码/无码/女优/年份/只要磁力）必须写进后续工具参数。

## 回答（整合，对标优质助手）
- 工具结果只是素材。先给结论，再按需列要点；用换行和「· 」条目，不要写成一段糊在一起。
- 作品清单示例格式：
  《镜中人》(Look Away, 2018) 女主是 India Eisley（英迪娅·埃斯利），一人分饰两角。
  其他主要作品：
  · 《xxx》(English, 年份) — 角色
  · …
- 条目写清中文名/英文名、年份、角色（若有）；必要时点名来源（豆瓣/TMDB/维基），不要提工具名、向量、分数。
- 篇幅随问题：短问答几十到百余字；片单可到约 300 字。禁止把工具返回的原始标题列表整段复读。
- 没搜到或工具失败：如实说，并提示换问法或去设置里配，不要编造。

## 资源卡片
- 卡片由系统按用户意图决定。信息问答与作品清单以文字整合为主；只有用户明确要库内资源/磁力时才依赖卡片。"""

# 即使聊天预设覆盖了 systemPrompt，也会追加这段，保证行为底线
BEHAVIOR_APPENDIX = """
【行为底线】
1. 按问题主动选择工具（可多工具并行或分步多跳；关键信息中英交叉验证），不要无关乱调。
2. 拿到工具结果后必须整合成自然语言答复（结论 + 条目），禁止整段复读搜索列表。
3. 纯问答 / 作品清单以文字为主；用户要找库内资源或磁力时再强调可点条目。"""

# 小花可配置工具（设置页开关）
DEFAULT_ASSISTANT_TOOLS: dict[str, bool] = {
    "sehua_keyword": True,
    "sehua_semantic": True,
    "scrap_search": True,
    "scrap_list": True,
    "magnet_search": True,
    "magnet_semantic": True,
    "media_search": True,
    "media_person_works": True,
    "web_search": True,
}

ASSISTANT_TOOL_META: list[dict[str, str]] = [
    {
        "id": "sehua_keyword",
        "group": "warehouse",
        "label": "仓库关键词",
        "desc": "色花标题/文件名搜索",
    },
    {
        "id": "sehua_semantic",
        "group": "warehouse",
        "label": "仓库语义",
        "desc": "向量相近推荐",
    },
    {
        "id": "scrap_search",
        "group": "makers",
        "label": "片商语义",
        "desc": "刮削库向量搜",
    },
    {
        "id": "scrap_list",
        "group": "makers",
        "label": "片商筛选",
        "desc": "女优/厂牌/标签列表",
    },
    {
        "id": "magnet_search",
        "group": "magnet",
        "label": "磁力搜索",
        "desc": "Bitmagnet 关键词",
    },
    {
        "id": "magnet_semantic",
        "group": "magnet",
        "label": "磁力语义",
        "desc": "Bitmagnet 向量相近",
    },
    {
        "id": "media_search",
        "group": "media",
        "label": "影视搜索",
        "desc": "TMDB / 豆瓣等",
    },
    {
        "id": "media_person_works",
        "group": "media",
        "label": "影人作品",
        "desc": "按演员/导演列作品",
    },
    {
        "id": "web_search",
        "group": "web",
        "label": "网络搜索",
        "desc": "SearXNG / Serper / Brave",
    },
]

ASSISTANT_SKILL_GROUPS: list[dict[str, str]] = [
    {"id": "warehouse", "label": "仓库", "desc": "色花资源库"},
    {"id": "makers", "label": "片商", "desc": "刮削番号库"},
    {"id": "magnet", "label": "磁力", "desc": "Bitmagnet"},
    {"id": "media", "label": "影视", "desc": "TMDB 等元数据"},
    {"id": "web", "label": "网络", "desc": "公开网页搜索"},
]

_RESOURCE_INTENT_RE = re.compile(
    r"(找|搜|有没有|有么|推荐|给我|来几|整几|下[载載]|磁力|种子|番号|资源|"
    r"片单|作品|电影|电视剧|剧集|片子|想看|看看|列[出举]|清单|蓝光|4k|有码|无码)",
    re.IGNORECASE,
)
_FACT_ONLY_RE = re.compile(
    r"(是谁|谁演|女主是|男主是|主演是|哪一年|哪年|什么时候|"
    r"剧情|简介|讲什么|多少分|评分怎么样|真的吗|对吗|什么意思)",
    re.IGNORECASE,
)
# 作品信息清单（对标 Grok：文字整合，不出资源卡）
_INFO_LIST_RE = re.compile(
    r"(女主|男主|主演).{0,12}(演|电影|作品)|(演[的过]?[了的]?电影|演[的过]?[了的]?作品|"
    r"其他作品|还有哪些片|作品列表|影视作品)",
    re.IGNORECASE,
)
_DOWNLOAD_RE = re.compile(r"(磁力|种子|下载|仓库|色花|bitmagnet|有码|无码|番号)", re.IGNORECASE)
_CODE_RE = re.compile(r"^[A-Za-z]{2,8}-?\d{2,5}[A-Za-z]?$")


def user_wants_resource_cards(message: str) -> bool:
    """用户是否在要「可点开的资源/片单」；纯事实问答与作品信息清单则 False。"""
    text = (message or "").strip()
    if not text:
        return False
    if _CODE_RE.match(text):
        return True
    # 「给我镜中人女主演电影」这类：要信息整合，不是仓库卡片
    if _INFO_LIST_RE.search(text) and not _DOWNLOAD_RE.search(text):
        return False
    fact = bool(_FACT_ONLY_RE.search(text))
    resource = bool(_RESOURCE_INTENT_RE.search(text))
    if fact and not resource:
        return False
    if resource:
        return True
    # 短片名/女优名单独丢来 → 倾向当找片
    if len(text) <= 24 and not re.search(r"[？?]", text):
        return True
    return False


def card_id(source: str, key: str) -> str:
    return f"{source}:{key}"


def make_card(
    *,
    source: AssistantSource,
    title: str,
    open_payload: dict[str, Any],
    subtitle: str = "",
    meta: str = "",
    cover: str = "",
    score: float | None = None,
    key: str = "",
) -> dict[str, Any]:
    kid = key or str(open_payload.get("hash") or open_payload.get("id") or title)[:80]
    row: dict[str, Any] = {
        "id": card_id(source, kid),
        "source": source,
        "title": (title or "").strip() or kid,
        "subtitle": (subtitle or "").strip(),
        "meta": (meta or "").strip(),
        "cover": (cover or "").strip(),
        "open": open_payload,
    }
    if isinstance(score, (int, float)):
        row["score"] = round(float(score), 3)
    return row


def compact_cards_for_llm(cards: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, c in enumerate(cards[:limit], 1):
        row: dict[str, Any] = {
            "n": i,
            "source": c.get("source"),
            "title": str(c.get("title") or "")[:80],
        }
        if c.get("subtitle"):
            row["code"] = str(c["subtitle"])[:40]
        if c.get("meta"):
            row["meta"] = str(c["meta"])[:48]
        if isinstance(c.get("score"), (int, float)):
            row["score"] = c["score"]
        out.append(row)
    return out


def merge_cards(*groups: list[dict[str, Any]], limit: int = 24) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for group in groups:
        for c in group:
            cid = str(c.get("id") or "")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            out.append(c)
            if len(out) >= limit:
                return out
    return out


def select_ui_cards(
    results: list[dict[str, Any]],
    *,
    wants_cards: bool,
    limit: int = 24,
) -> list[dict[str, Any]]:
    """决定给前端的卡片：无资源意图则空；多跳时优先最后一轮工具结果。"""
    if not wants_cards:
        return []
    buckets: dict[int, list[dict[str, Any]]] = {}
    for r in results:
        if not isinstance(r, dict):
            continue
        cards = list(r.get("cards") or [])
        if not cards:
            continue
        step = int(r.get("_step") or 0)
        buckets.setdefault(step, []).extend(cards)
    if not buckets:
        return []
    last_step = max(buckets)
    # 多跳：只展示最后一轮（例如女主作品），避免中间「片名搜索」刷屏
    if len(buckets) >= 2:
        return merge_cards(buckets[last_step], limit=limit)
    return merge_cards(buckets[last_step], limit=limit)
