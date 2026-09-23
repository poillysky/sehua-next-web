'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  enrichScrapLibraryItem,
  fetchScrapLibrarySubtitles,
  fetchTranslate,
  getScrapEnrichStrategy,
  getScrapLibraryQualityGate,
  listScrapLibraryEmbedItems,
  listScrapLibrarySubtitles,
  lookupScrapActressAvatarUrls,
  peekActressAvatarPosterApi,
  rememberActressAvatarPosterApis,
  saveScrapLibraryPlot,
  searchScrapLibraryEmbed,
  scrapLibraryCoverUrl,
  type ScrapLibraryEmbedItem,
} from '@/lib/api';
import { useTabNavigation } from '@/shell';
import { useOverlay } from '@/components/overlay/OverlayContext';
import { writeP115AttachSubs } from '@/lib/p115AttachSubs';
import { openMakerHomeSearch, isCensoredRightCropRegion, stripTitleCodePrefix } from './makersUi';
import { isScrapFavorite, toggleScrapFavorite, ensureScrapFavoritesLoaded } from './scrapFavorites';
import { parseScrapSourceText } from './scrapSourceMeta';
import { useScrapLocalCover, SCRAP_DETAIL_COVER_OPTS } from './useScrapLocalCover';
import { stripTrailingActressName } from './scrapDetailHelpers';

export function useScrapDetail({
  item,
  region: regionProp,
  onFavoriteChange,
  onOpenActress,
  onOpenGenre,
  onOpenStudio,
  onOpenRelated,
  onItemPatch,
}: {
  item: ScrapLibraryEmbedItem;
  /** 当前片商分区，优先于 item.region */
  region?: string;
  onFavoriteChange?: (favorited: boolean) => void;
  onOpenActress?: (name: string, posterApi?: string) => void;
  onOpenGenre?: (name: string) => void;
  onOpenStudio?: (name: string) => void;
  onOpenRelated?: (next: ScrapLibraryEmbedItem) => void;
  /** 剧情译中落库后回写条目 */
  onItemPatch?: (patch: Partial<ScrapLibraryEmbedItem>) => void;
}) {
  const tabCtx = useTabNavigation();
  const { toast } = useOverlay();
  const meta = useMemo(
    () => parseScrapSourceText(item.sourceText),
    [item.sourceText],
  );
  const actressKey = meta.actresses.join('\0');
  const actressAvatarsSeed = useMemo(() => {
    const m: Record<string, string> = {};
    if (!actressKey) return m;
    for (const name of actressKey.split('\0')) {
      const api = peekActressAvatarPosterApi(name);
      if (api) m[name] = api;
    }
    return m;
  }, [actressKey]);
  const [actressAvatarsResolved, setActressAvatarsResolved] = useState<
    Record<string, string>
  >({});
  useEffect(() => {
    const names = actressKey ? actressKey.split('\0') : [];
    setActressAvatarsResolved({});
    if (!names.length) return;
    let cancelled = false;
    void lookupScrapActressAvatarUrls(names)
      .then((m) => {
        if (cancelled) return;
        rememberActressAvatarPosterApis(m || {});
        setActressAvatarsResolved(m || {});
      })
      .catch(() => {
        /* 保持乐观路径 */
      });
    return () => {
      cancelled = true;
    };
  }, [actressKey]);
  const actressAvatars = useMemo(() => {
    const next = { ...actressAvatarsSeed };
    for (const [name, api] of Object.entries(actressAvatarsResolved)) {
      if (api) next[name] = api;
    }
    return next;
  }, [actressAvatarsSeed, actressAvatarsResolved]);
  const code = String(item.code || meta.code || '').trim();
  const title = String(item.title || meta.title || '').trim();
  const originalTitle = String(meta.originalTitle || '').trim();
  const stripCodePrefix = (raw: string) => stripTitleCodePrefix(raw, code);
  const titleZhOrJa = (() => {
    const a = stripCodePrefix(title);
    const b = stripCodePrefix(originalTitle);
    const hasCjk = (s: string) => /[\u4e00-\u9fff]/.test(s);
    if (a && hasCjk(a)) return a;
    if (b && hasCjk(b)) return b;
    return a || b;
  })();
  const displayTitle = useMemo(
    () => stripTrailingActressName(titleZhOrJa, meta.actresses),
    [titleZhOrJa, actressKey],
  );
  const secondaryTitle = (() => {
    const a = stripCodePrefix(title);
    const b = stripCodePrefix(originalTitle);
    if (!b || !displayTitle) return '';
    if (b.toLowerCase() === displayTitle.toLowerCase()) return '';
    if (b === displayTitle) return '';
    const mainIsCjk = /[\u4e00-\u9fff]/.test(displayTitle);
    const bIsCjk = /[\u4e00-\u9fff]/.test(b);
    if (mainIsCjk && !bIsCjk) return b;
    if (!mainIsCjk && bIsCjk) return b;
    if (a && a !== displayTitle && a !== b) return a;
    return b !== displayTitle ? b : '';
  })();
  const [outlineShow, setOutlineShow] = useState(
    meta.outlineShow === 'zh_jp' || meta.outlineShow === 'jp_zh'
      ? meta.outlineShow
      : 'zh',
  );
  useEffect(() => {
    let cancelled = false;
    void getScrapEnrichStrategy()
      .then((s) => {
        if (cancelled) return;
        const v = s.outlineShow;
        if (v === 'zh_jp' || v === 'jp_zh' || v === 'zh') setOutlineShow(v);
      })
      .catch(() => {
        /* 用 meta 默认 */
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const [coverRev, setCoverRev] = useState(0);
  const {
    src: posterRaw,
    onError: onPosterError,
  } = useScrapLocalCover({
    posterApi: item.posterApi,
    thumbApi: item.thumbApi,
    coverUrl: item.coverUrl,
    itemId: item.itemId,
    ...SCRAP_DETAIL_COVER_OPTS,
    rp: isCensoredRightCropRegion(
      item.region || item.relPath || item.posterApi,
    ),
  });
  const poster = posterRaw
    ? `${posterRaw}${posterRaw.includes('?') ? '&' : '?'}v=${coverRev || 0}`
    : '';
  const fanart = item.fanartApi
    ? scrapLibraryCoverUrl(
        { posterApi: item.fanartApi, coverUrl: '' },
        { prefer: 'poster', w: 720, rp: false },
      )
    : '';
  // 背景洗图可用横 thumb；主海报已是高清 poster
  const thumbWide = item.thumbApi
    ? scrapLibraryCoverUrl(
        { posterApi: item.thumbApi, coverUrl: '' },
        { prefer: 'poster', w: 720, rp: false },
      )
    : '';
  const washSrcBase = fanart || thumbWide || posterRaw;
  const washSrc = washSrcBase
    ? `${washSrcBase}${washSrcBase.includes('?') ? '&' : '?'}v=${coverRev || 0}`
    : '';

  const [imgGone, setImgGone] = useState(false);
  const [favorited, setFavorited] = useState(false);
  const [favBusy, setFavBusy] = useState(false);
  const [subBusy, setSubBusy] = useState(false);
  const [subReady, setSubReady] = useState(false);
  const [enrichBusy, setEnrichBusy] = useState(false);
  const [plotZh, setPlotZh] = useState('');
  const [plotSaved, setPlotSaved] = useState(false);
  const [plotBusy, setPlotBusy] = useState(false);
  const [related, setRelated] = useState<ScrapLibraryEmbedItem[]>([]);
  const [relatedLoading, setRelatedLoading] = useState(false);

  const plotLooksChinese = useMemo(() => {
    const p = String(meta.plot || '');
    // 有假名就是日文（夹汉字也不能当中文），否则会跳过翻译、界面仍显示日文
    if (/[\u3040-\u309f\u30a0-\u30ff]/.test(p)) return false;
    const cjk = (p.match(/[\u4e00-\u9fff]/g) || []).length;
    return cjk >= 8;
  }, [meta.plot]);

  const displayPlot = useMemo(() => {
    const raw = String(plotZh || meta.plot || '');
    return raw
      .replace(/<br\s*\/?>/gi, '\n')
      .replace(/&nbsp;/gi, ' ')
      .replace(/\r\n/g, '\n')
      .trim();
  }, [plotZh, meta.plot]);

  const originalPlotText = useMemo(() => {
    const raw = String(meta.originalPlot || '');
    return raw
      .replace(/<br\s*\/?>/gi, '\n')
      .replace(/&nbsp;/gi, ' ')
      .replace(/\r\n/g, '\n')
      .trim();
  }, [meta.originalPlot]);

  const bilingualPlots = useMemo(() => {
    const zh = displayPlot;
    const ja = originalPlotText;
    if (!ja || !zh || ja.toLowerCase() === zh.toLowerCase()) {
      return { primary: zh || ja, secondary: '' };
    }
    if (outlineShow === 'jp_zh') return { primary: ja, secondary: zh };
    if (outlineShow === 'zh_jp') return { primary: zh, secondary: ja };
    return { primary: zh || ja, secondary: '' };
  }, [displayPlot, originalPlotText, outlineShow]);

  useEffect(() => {
    setImgGone(false);
    setSubReady(false);
    setPlotZh('');
    setPlotSaved(false);
    setPlotBusy(false);
    setEnrichBusy(false);
    setCoverRev(0);
    let cancelled = false;
    const id = String(item.itemId || '');
    // 收藏真相在服务端：先确保缓存就绪再据其点亮状态
    void (async () => {
      await ensureScrapFavoritesLoaded();
      if (cancelled) return;
      setFavorited(isScrapFavorite(id));
    })();
    void (async () => {
      try {
        const st = await listScrapLibrarySubtitles({
          itemId: id,
          code,
        });
        if (!cancelled) setSubReady((st.files || []).length > 0);
      } catch {
        if (!cancelled) setSubReady(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [item.itemId, code]);

  useEffect(() => {
    let cancelled = false;
    const selfId = String(item.itemId || '');
    const selfCode = code.toUpperCase();
    const region = String(regionProp || item.region || '').trim();
    const prefix = String(item.prefix || meta.prefix || '').trim();
    const actress = meta.actresses[0] || '';
    const studio = meta.studio || '';

    const take = (
      rows: ScrapLibraryEmbedItem[],
      seen: Set<string>,
      out: ScrapLibraryEmbedItem[],
    ) => {
      for (const row of rows) {
        const id = String(row.itemId || '');
        const c = String(row.code || '').toUpperCase();
        const key = id || c;
        if (!key || key === selfId || c === selfCode || seen.has(key)) continue;
        seen.add(key);
        out.push(row);
        if (out.length >= 12) break;
      }
    };

    void (async () => {
      setRelatedLoading(true);
      setRelated([]);
      const seen = new Set<string>();
      const out: ScrapLibraryEmbedItem[] = [];

      const tryList = async (
        opts: Parameters<typeof listScrapLibraryEmbedItems>[0],
      ) => {
        if (cancelled || out.length >= 12) return;
        try {
          const page = await listScrapLibraryEmbedItems({
            ...opts,
            region: opts?.region || region || undefined,
            sort: 'recent',
            limit: 18,
          });
          if (!cancelled) take(page.items || [], seen, out);
        } catch {
          /* 单路失败继续 */
        }
      };

      // 同女优 → 同片商 → 同前缀；语义搜索最后且可失败
      if (actress) await tryList({ tag: actress });
      if (studio && out.length < 8) await tryList({ studio });
      if (prefix && out.length < 8) await tryList({ prefix });

      if (!cancelled && out.length < 6) {
        const q = [actress, studio, ...meta.genres.slice(0, 2)]
          .filter(Boolean)
          .join(' ');
        if (q) {
          try {
            const hits = await searchScrapLibraryEmbed({
              query: q,
              limit: 16,
              region,
            });
            if (!cancelled) take(hits, seen, out);
          } catch {
            /* 语义可选 */
          }
        }
      }

      if (!cancelled) {
        setRelated(out.slice(0, 12));
        setRelatedLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
    // 仅随条目变化拉取；勿依赖父组件 inline 回调
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.itemId, item.region, item.prefix, regionProp, code, meta.actresses[0], meta.studio, meta.prefix]);

  async function onToggleFavorite() {
    if (!item.itemId) {
      toast('无法收藏：缺少条目 ID', 'error');
      return;
    }
    if (favBusy) return;
    setFavBusy(true);
    try {
      await ensureScrapFavoritesLoaded();
      const prev = isScrapFavorite(item.itemId);
      const next = await toggleScrapFavorite(item, regionProp);
      setFavorited(next);
      onFavoriteChange?.(next);
      toast(next ? '已加入收藏' : '已取消收藏', 'success');
    } catch (e) {
      // 落库失败：按已加载缓存回滚提示
      const prev = isScrapFavorite(item.itemId);
      setFavorited(prev);
      onFavoriteChange?.(prev);
      toast(e instanceof Error ? `操作失败：${e.message}` : '操作失败', 'error');
    } finally {
      setFavBusy(false);
    }
  }

  function onSearch() {
    const region = String(regionProp || item.region || '').trim();
    const prefix = String(item.prefix || meta.prefix || '').trim();
    const ok = openMakerHomeSearch(
      { code, title, id: item.itemId, region, prefix },
      tabCtx?.scrollToTab,
    );
    if (!ok) toast('没有可用的番号用于搜索', 'error');
    else toast('已跳转资源库搜索', 'success');
  }

  async function onRefreshMeta() {
    if (enrichBusy) return;
    const iid = String(item.itemId || '').trim();
    if (!iid) {
      toast('无法刷新：缺少条目 ID', 'error');
      return;
    }
    setEnrichBusy(true);
    toast('正在清空向量并全量重刮覆盖…', 'info');
    try {
      const data = await enrichScrapLibraryItem({
        itemId: iid,
        overwrite: true,
      });
      const one = data.result;
      if (!data.ok || !one?.ok) {
        toast(
          one?.error === 'detail_not_found' ||
            one?.error === '各数据源均未找到该番号'
          ? '各数据源均未找到该番号'
          : one?.error || '刷新失败',
          'error',
        );
        return;
      }
      const fresh = data.item;
      if (fresh) {
        onItemPatch?.(fresh);
        setPlotZh('');
        setPlotSaved(false);
      }
      setCoverRev((n) => n + 1);
      setImgGone(false);
      const bits: string[] = [];
      if (one.nfoChanged) bits.push('元数据');
      if (one.posterDownloaded) bits.push('封面');
      if ((one.actors || 0) > 0) bits.push(`女优×${one.actors}`);
      const slow = (one.sourceTimings || [])
        .slice(0, 3)
        .map(
          (t) =>
            `${t.id || '?'}${typeof t.ms === 'number' ? ` ${Math.round(t.ms / 100) / 10}s` : ''}${t.ok ? '' : '×'}`,
        )
        .filter(Boolean);
      const timingHint = slow.length
        ? ` · 最慢 ${slow.join(' / ')}`
        : typeof one.fetchMs === 'number'
          ? ` · ${Math.round(one.fetchMs / 100) / 10}s`
          : '';
      toast(
        (bits.length ? `已覆盖重写${bits.join('与')}` : '已全量刷新') +
          timingHint,
        'success',
      );
    } catch (e) {
      toast(e instanceof Error ? e.message : '刷新失败', 'error');
    } finally {
      setEnrichBusy(false);
    }
  }

  async function onCheckQualityGate() {
    try {
      const data = await getScrapLibraryQualityGate({
        itemId: String(item.itemId || ''),
        code,
        relPath: String(item.relPath || ''),
      });
      const hard = data.hardFail || [];
      const soft = data.soft || [];
      if (data.ok && !hard.length) {
        toast(
          soft.length
            ? `门禁通过 · soft ${soft.slice(0, 3).join(' / ')}`
            : '门禁通过',
          'success',
        );
        return;
      }
      toast(
        `门禁未过：${(hard.length ? hard : soft).slice(0, 4).join(' / ')}`,
        'error',
      );
    } catch (e) {
      toast(e instanceof Error ? e.message : '门禁检查失败', 'error');
    }
  }

  async function onTranslatePlot() {
    const raw = String(meta.plot || '')
      .replace(/<br\s*\/?>/gi, '\n')
      .replace(/&nbsp;/gi, ' ')
      .trim();
    if (!raw || plotBusy) return;
    const hasKana = /[\u3040-\u309f\u30a0-\u30ff]/.test(raw);
    if ((plotLooksChinese || plotSaved) && !hasKana) {
      toast('剧情已是中文', 'info');
      return;
    }
    const iid = String(item.itemId || '').trim();
    if (!iid) {
      toast('无法保存：缺少条目 ID', 'error');
      return;
    }
    setPlotBusy(true);
    try {
      const data = await fetchTranslate(raw, { target: 'zh' });
      const out = String(data.text || '').trim();
      if (!out) {
        toast('翻译结果为空', 'error');
        return;
      }
      const outHasKana = /[\u3040-\u309f\u30a0-\u30ff]/.test(out);
      if (data.alreadyChinese && !hasKana && !outHasKana) {
        setPlotZh(out);
        setPlotSaved(true);
        toast('剧情已是中文', 'info');
        return;
      }
      if (outHasKana && hasKana) {
        toast('翻译仍是日文，请稍后重试或检查大模型', 'error');
        return;
      }
      // 先上屏中文，避免保存/重嵌入失败时界面仍停在日文
      setPlotZh(out);
      try {
        const saved = await saveScrapLibraryPlot({ itemId: iid, plot: out });
        const fullPlot = String(saved.plot || out).trim() || out;
        let sourceText = String(saved.sourceText || '').trim();
        if (sourceText && fullPlot) {
          if (/^剧情：/m.test(sourceText)) {
            sourceText = sourceText.replace(
              /^剧情：[\s\S]+?(?=\n[^\s][^：\n]*：|$)/m,
              `剧情：${fullPlot}`,
            );
          } else {
            sourceText = `${sourceText}\n剧情：${fullPlot}`;
          }
        }
        setPlotZh(fullPlot);
        setPlotSaved(true);
        if (sourceText) {
          onItemPatch?.({ sourceText });
        } else {
          const prev = String(item.sourceText || '');
          const next = prev.replace(
            /^剧情：[\s\S]+?(?=\n[^\s][^：\n]*：|$)/m,
            `剧情：${fullPlot}`,
          );
          onItemPatch?.({
            sourceText: next.includes('剧情：')
              ? next
              : `${prev}\n剧情：${fullPlot}`,
          });
        }
        toast('已翻译并保存', 'success');
      } catch (saveErr) {
        setPlotSaved(false);
        toast(
          saveErr instanceof Error
            ? `已译出中文，但保存失败：${saveErr.message}`
            : '已译出中文，但保存失败',
          'error',
        );
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : '翻译失败', 'error');
    } finally {
      setPlotBusy(false);
    }
  }

  async function onFetchSubtitle() {
    if (subBusy) return;
    if (!code && !item.itemId) {
      toast('没有可用的番号', 'error');
      return;
    }
    setSubBusy(true);
    const region = String(regionProp || item.region || '').trim();
    try {
      const data = await fetchScrapLibrarySubtitles({
        itemId: String(item.itemId || ''),
        code,
        force: subReady,
        upload115: true,
        region,
      });
      writeP115AttachSubs({
        code,
        itemId: String(item.itemId || ''),
        region,
      });
      const n = (data.files || []).length;
      const up = data.upload115;
      if (!(data.ok && n > 0)) {
        setSubReady(false);
        toast(
          data.reason === 'not_found'
            ? data.message || '未找到对应中文字幕'
            : data.reason === 'network'
              ? data.message || '无法连接字幕站，请检查代理'
              : data.message || data.reason || '搜字幕失败',
          'error',
        );
        return;
      }
      setSubReady(true);
      if (up?.ok && (up.count || 0) > 0) {
        toast(data.message || up.message || '字幕已上传到 115', 'success');
      } else if (up && !up.ok) {
        toast(
          up.message
            ? `字幕已保存本地；115：${up.message}`
            : '字幕已保存本地，但上传 115 失败',
          'error',
        );
      } else {
        toast(
          data.message || `字幕已保存（${n}），但未返回上传结果`,
          'error',
        );
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : '搜字幕失败', 'error');
    } finally {
      setSubBusy(false);
    }
  }

  const facts: Array<{ k: string; v: string; onClick?: () => void }> = [];
  if (meta.year) facts.push({ k: '年份', v: meta.year });
  if (meta.studio) {
    facts.push({
      k: '片商',
      v: meta.studio,
      onClick: onOpenStudio ? () => onOpenStudio(meta.studio) : undefined,
    });
  }
  if (meta.label && meta.label !== meta.studio) {
    facts.push({ k: '发行', v: meta.label });
  }
  if (meta.definition) facts.push({ k: '清晰度', v: meta.definition });
  if (meta.mosaic) facts.push({ k: '马赛克', v: meta.mosaic });

  const badgeChips = (() => {
    const out: string[] = [];
    if (meta.cnsub) out.push('中字');
    for (const b of meta.badges || []) {
      const t = String(b || '').trim();
      if (!t) continue;
      if (t === '中字' || t === '字幕' || /^cnsub$/i.test(t)) continue;
      if (!out.includes(t)) out.push(t);
    }
    return out.slice(0, 8);
  })();

  return {
    item,
    meta,
    code,
    title,
    washSrc,
    imgGone,
    setImgGone,
    poster,
    onPosterError,
    enrichBusy,
    onCheckQualityGate,
    onRefreshMeta,
    displayTitle,
    outlineShow,
    secondaryTitle,
    facts,
    favorited,
    favBusy,
    onToggleFavorite,
    badgeChips,
    actressAvatars,
    onOpenActress,
    onOpenGenre,
    onOpenRelated,
    plotZh,
    plotLooksChinese,
    plotSaved,
    onTranslatePlot,
    plotBusy,
    bilingualPlots,
    subReady,
    onFetchSubtitle,
    subBusy,
    onSearch,
    relatedLoading,
    related,
  };
}
