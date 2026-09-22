'use client';

import { useEffect, useState } from 'react';
import {
  getPrefixCatalogPrefixDetail,
  getPrefixCatalogPrefixes,
  getPrefixCatalogSummary,
  type PrefixCatalogPrefixDetail,
  type PrefixCatalogPrefixRow,
  type PrefixCatalogSummary,
} from '@/lib/api';
import { MAKER_KIND_TABS } from '@/features/makers/makersUi';
import { CODES_PAGE_SIZE, type CatalogNav } from './types';

export function useMakersCatalog({
  setMsg,
}: {
  setMsg: (text: string) => void;
}) {
  const [catalogNav, setCatalogNav] = useState<CatalogNav | null>(null);
  const [catalogSummary, setCatalogSummary] = useState<PrefixCatalogSummary | null>(
    null,
  );
  const [catalogPrefixes, setCatalogPrefixes] = useState<PrefixCatalogPrefixRow[]>(
    [],
  );
  const [catalogDetail, setCatalogDetail] =
    useState<PrefixCatalogPrefixDetail | null>(null);
  const [catalogCodePage, setCatalogCodePage] = useState(1);
  const [catalogBusy, setCatalogBusy] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        setCatalogSummary(await getPrefixCatalogSummary());
      } catch {
        setCatalogSummary(null);
      }
    })();
  }, []);

  async function refreshCatalogSummary() {
    try {
      setCatalogSummary(await getPrefixCatalogSummary());
    } catch {
      /* keep previous */
    }
  }

  async function openCatalogRegion(regionId: string, label: string) {
    setMsg('');
    setCatalogDetail(null);
    setCatalogCodePage(1);
    setCatalogPrefixes([]);
    setCatalogNav({ level: 'region', regionId, label });
    setCatalogBusy(true);
    try {
      setCatalogPrefixes(await getPrefixCatalogPrefixes(regionId));
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '读取前缀失败');
    } finally {
      setCatalogBusy(false);
    }
  }

  async function loadCatalogCodes(
    regionId: string,
    prefix: string,
    page: number,
  ) {
    setCatalogBusy(true);
    try {
      const offset = Math.max(0, (page - 1) * CODES_PAGE_SIZE);
      setCatalogDetail(
        await getPrefixCatalogPrefixDetail(regionId, prefix, {
          offset,
          limit: CODES_PAGE_SIZE,
        }),
      );
      setCatalogCodePage(page);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '读取番号失败');
    } finally {
      setCatalogBusy(false);
    }
  }

  async function openCatalogPrefix(
    regionId: string,
    regionLabel: string,
    prefix: string,
  ) {
    setMsg('');
    setCatalogDetail(null);
    setCatalogCodePage(1);
    setCatalogNav({ level: 'prefix', regionId, regionLabel, prefix });
    await loadCatalogCodes(regionId, prefix, 1);
  }

  function openCatalogRegions() {
    setMsg('');
    setCatalogNav({ level: 'regions' });
  }

  function catalogRegionsBack() {
    setCatalogNav(null);
    setMsg('');
  }

  function catalogRegionBack() {
    setCatalogNav({ level: 'regions' });
    setCatalogPrefixes([]);
    setCatalogDetail(null);
    setCatalogCodePage(1);
    setMsg('');
  }

  function catalogPrefixBack() {
    if (!catalogNav || catalogNav.level !== 'prefix') return;
    // 不要重新拉取前缀列表，否则会清空 DOM、冲掉已记住的滚动位置
    setCatalogDetail(null);
    setCatalogCodePage(1);
    setMsg('');
    setCatalogNav({
      level: 'region',
      regionId: catalogNav.regionId,
      label: catalogNav.regionLabel,
    });
  }

  const codeTotal = catalogDetail?.code_count ?? 0;
  const codePages = Math.max(1, Math.ceil(codeTotal / CODES_PAGE_SIZE));

  const catalogRegionRows =
    catalogSummary?.regions ||
    MAKER_KIND_TABS.map((t) => ({
      id: t.id,
      label: t.label,
      prefix_count: 0,
      scrap_prefix_count: 0,
      code_count: 0,
    }));

  return {
    catalogNav,
    catalogSummary,
    catalogPrefixes,
    catalogDetail,
    catalogCodePage,
    catalogBusy,
    refreshCatalogSummary,
    openCatalogRegion,
    loadCatalogCodes,
    openCatalogPrefix,
    openCatalogRegions,
    catalogRegionsBack,
    catalogRegionBack,
    catalogPrefixBack,
    codeTotal,
    codePages,
    catalogRegionRows,
  };
}
