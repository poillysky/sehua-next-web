"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AppPush } from "@/components/ui/AppPush";
import {
  fetchMakerFsRegion,
  type MakerFsRegionCatalog,
  type MakerFsRegionSummary,
  type ScrapeTask,
  type ScrapeTaskField,
} from "@/lib/api";
import { makerFsGroupLabel } from "@/lib/makerFsUi";

/** 任务可刮削字段 */
const ALL_FIELDS: ScrapeTaskField[] = [
  "cover",
  "titleZh",
  "outline",
  "studio",
  "actors",
  "tags",
  "series",
];

const FIELD_OPTIONS: Array<{ id: ScrapeTaskField; label: string }> = [
  { id: "cover", label: "封面图" },
  { id: "titleZh", label: "中文标题" },
  { id: "outline", label: "简介" },
  { id: "studio", label: "制片方" },
  { id: "actors", label: "女优" },
  { id: "tags", label: "标签" },
  { id: "series", label: "系列" },
];

/** 可从索引物化复用（封面永远网络） */
const LOCAL_FIELD_OPTIONS: Array<{ id: ScrapeTaskField; label: string }> = [
  { id: "titleZh", label: "中文标题" },
  { id: "outline", label: "简介" },
  { id: "studio", label: "制片方" },
  { id: "actors", label: "女优" },
  { id: "tags", label: "标签" },
  { id: "series", label: "系列" },
];

function normalizeTaskFields(raw: ScrapeTaskField[] | undefined): ScrapeTaskField[] {
  const seen = new Set<ScrapeTaskField>();
  const out: ScrapeTaskField[] = [];
  for (const item of raw || []) {
    if (!ALL_FIELDS.includes(item) || seen.has(item)) continue;
    seen.add(item);
    out.push(item);
  }
  return out.length ? out : [...ALL_FIELDS];
}

/** 允许空：未勾选则不从索引读任何内容字段 */
function normalizeLocalFields(
  raw: ScrapeTaskField[] | undefined,
  scrapeFields: ScrapeTaskField[],
): ScrapeTaskField[] {
  const allow = new Set(LOCAL_FIELD_OPTIONS.map((f) => f.id));
  const scrape = new Set(scrapeFields);
  const seen = new Set<ScrapeTaskField>();
  const out: ScrapeTaskField[] = [];
  for (const item of raw || []) {
    if (!allow.has(item) || !scrape.has(item) || seen.has(item)) continue;
    seen.add(item);
    out.push(item);
  }
  return out;
}

export type ScrapeTaskDraft = {
  id: string;
  name: string;
  regions: string[];
  maker: string;
  prefix: string;
  code: string;
  mode: "incremental" | "force";
  fields: ScrapeTaskField[];
  localFields: ScrapeTaskField[];
  watchEnabled: boolean;
};

function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `task_${Date.now().toString(36)}`;
}

function toDraft(task: ScrapeTask | null, regions: MakerFsRegionSummary[]): ScrapeTaskDraft {
  if (task) {
    const fields = normalizeTaskFields(task.fields);
    return {
      id: task.id,
      name: task.name || "",
      regions: [...(task.regions || [])],
      maker: task.maker || "",
      prefix: task.prefix || "",
      code: task.code || "",
      mode: task.mode === "force" ? "force" : "incremental",
      fields,
      localFields: normalizeLocalFields(task.localFields, fields),
      watchEnabled: Boolean(task.watchEnabled),
    };
  }
  const first = regions[0]?.id || "";
  const fields = [...ALL_FIELDS];
  return {
    id: newId(),
    name: "",
    regions: first ? [first] : [],
    maker: "",
    prefix: "",
    code: "",
    mode: "incremental",
    fields,
    localFields: [],
    watchEnabled: false,
  };
}

/** 新建/编辑刮削任务：全屏 push，非弹窗 */
export function ScrapeTaskModal({
  open,
  task,
  regions,
  busy,
  onClose,
  onSave,
}: {
  open: boolean;
  task: ScrapeTask | null;
  regions: MakerFsRegionSummary[];
  busy?: boolean;
  onClose: () => void;
  /** 仅保存任务（含监控开/关），不启动刮削 */
  onSave: (draft: ScrapeTaskDraft, opts?: { toastOk?: boolean }) => void;
}) {
  const [draft, setDraft] = useState<ScrapeTaskDraft>(() =>
    toDraft(task, regions),
  );
  const [catalog, setCatalog] = useState<MakerFsRegionCatalog | null>(null);
  const skipAutoSaveRef = useRef(true);
  const onSaveRef = useRef(onSave);
  onSaveRef.current = onSave;
  const hydratedKeyRef = useRef("");

  // 仅在「打开 / 换任务」时回填已存参数；勿因 regions 引用变化反复重置
  useEffect(() => {
    if (!open) {
      skipAutoSaveRef.current = true;
      hydratedKeyRef.current = "";
      return;
    }
    const key = `${task?.id || "new"}`;
    if (hydratedKeyRef.current === key) return;
    hydratedKeyRef.current = key;
    setDraft(toDraft(task, regions));
    skipAutoSaveRef.current = true;
  }, [open, task, regions]);

  const singleRegion = draft.regions.length === 1 ? draft.regions[0] : "";

  useEffect(() => {
    if (!open || !singleRegion) {
      setCatalog(null);
      return;
    }
    let cancelled = false;
    void fetchMakerFsRegion(singleRegion)
      .then((c) => {
        if (!cancelled) setCatalog(c);
      })
      .catch(() => {
        if (!cancelled) setCatalog(null);
      });
    return () => {
      cancelled = true;
    };
  }, [open, singleRegion]);

  const makers = useMemo(() => {
    const map = new Map<string, number>();
    for (const p of catalog?.prefixes || []) {
      const m = makerFsGroupLabel(singleRegion, p);
      map.set(m, (map.get(m) || 0) + 1);
    }
    // 已配置厂牌不在索引时仍插入，保证 select 能显示回填值
    if (draft.maker && !map.has(draft.maker)) {
      map.set(draft.maker, 0);
    }
    return [...map.entries()].map(([name, n]) => ({ name, n }));
  }, [catalog, singleRegion, draft.maker]);

  const prefixes = useMemo(() => {
    const rows = (catalog?.prefixes || []).filter((p) => {
      if (!draft.maker) return true;
      return makerFsGroupLabel(singleRegion, p) === draft.maker;
    });
    // 已配置前缀不在当前列表时仍保留选项，避免被浏览器重置成「全部」
    if (
      draft.prefix &&
      !rows.some((p) => p.prefix === draft.prefix)
    ) {
      return [
        {
          prefix: draft.prefix,
          codeCount: undefined as number | undefined,
        },
        ...rows,
      ];
    }
    return rows;
  }, [catalog, draft.maker, draft.prefix, singleRegion]);

  // catalog 到达后：用前缀反查厂牌，修正历史命名不一致
  useEffect(() => {
    if (!open || !catalog || !singleRegion) return;
    const prefix = draft.prefix.trim();
    if (!prefix) return;
    const row = (catalog.prefixes || []).find(
      (p) => String(p.prefix || "").trim() === prefix,
    );
    if (!row) return;
    const label = makerFsGroupLabel(singleRegion, row);
    if (!label || label === draft.maker) return;
    setDraft((d) => (d.prefix === prefix ? { ...d, maker: label } : d));
    skipAutoSaveRef.current = true;
  }, [open, catalog, singleRegion, draft.prefix, draft.maker]);

  function toggleRegion(id: string) {
    setDraft((d) => {
      const has = d.regions.includes(id);
      const next = has
        ? d.regions.filter((x) => x !== id)
        : [...d.regions, id];
      const clearScope = next.length !== 1;
      return {
        ...d,
        regions: next,
        maker: clearScope ? "" : d.maker,
        prefix: clearScope ? "" : d.prefix,
      };
    });
  }

  const defaultName = useMemo(() => {
    if (draft.regions.length === 1) {
      return regions.find((r) => r.id === draft.regions[0])?.label || "刮削任务";
    }
    if (draft.regions.length > 1) return `多区 · ${draft.regions.length}`;
    return "刮削任务";
  }, [draft.regions, regions]);

  const resolvedDraft = useMemo((): ScrapeTaskDraft => {
    const fields = normalizeTaskFields(draft.fields);
    return {
      ...draft,
      name: draft.name.trim() || defaultName,
      code: "",
      fields,
      localFields: normalizeLocalFields(draft.localFields, fields),
    };
  }, [draft, defaultName]);

  const canSave = draft.regions.length > 0 && resolvedDraft.fields.length > 0;

  function toggleField(field: ScrapeTaskField) {
    setDraft((d) => {
      const has = d.fields.includes(field);
      const next = has
        ? d.fields.filter((x) => x !== field)
        : [...d.fields, field];
      if (!next.length) return d;
      const fields = normalizeTaskFields(next);
      return {
        ...d,
        fields,
        localFields: normalizeLocalFields(d.localFields, fields),
      };
    });
  }

  function toggleLocalField(field: ScrapeTaskField) {
    setDraft((d) => {
      // 开启本地复用时，同步勾上刮削字段
      let fields = d.fields.includes(field)
        ? d.fields
        : normalizeTaskFields([...d.fields, field]);
      const has = d.localFields.includes(field);
      const nextLocal = has
        ? d.localFields.filter((x) => x !== field)
        : [...d.localFields, field];
      return {
        ...d,
        fields,
        localFields: normalizeLocalFields(nextLocal, fields),
      };
    });
  }

  // 仅「编辑已有任务」自动保存；新建等关闭/开始时再落库，避免冲掉其它任务卡
  useEffect(() => {
    if (!open || busy || !task) return;
    if (skipAutoSaveRef.current) {
      skipAutoSaveRef.current = false;
      return;
    }
    const timer = window.setTimeout(() => {
      onSaveRef.current(resolvedDraft);
    }, 320);
    return () => window.clearTimeout(timer);
  }, [open, busy, task, resolvedDraft]);

  function handleBack() {
    if (busy) return;
    // 新建：至少填了厂牌/前缀才落库；仅默认选区就关掉不建空卡
    if (task || draft.maker.trim() || draft.prefix.trim()) {
      onSaveRef.current(resolvedDraft);
    }
    onClose();
  }

  if (!open) return null;

  return (
    <AppPush
      title={task ? "编辑刮削任务" : "新建刮削任务"}
      onBack={handleBack}
    >
      <div className="scrape-task-page">
        <div className="scrape-task-page__scroll">
          <div className="scrape-task-modal">
            <label className="scrape-task-field scrape-task-field--name">
              <span className="scrape-task-field__label">任务名</span>
              <input
                data-autofocus="true"
                className="scrape-task-field__control allow-select"
                value={draft.name}
                placeholder={defaultName}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, name: e.target.value }))
                }
                autoComplete="off"
                spellCheck={false}
              />
            </label>

            <section className="scrape-task-section">
              <header className="scrape-task-section__head">
                <span className="scrape-task-section__title">五大路径</span>
                <span className="scrape-task-section__meta mute">
                  {draft.regions.length
                    ? `已选 ${draft.regions.length}`
                    : "可多选"}
                </span>
              </header>
              <div className="scrape-task-regions">
                {regions.map((r) => {
                  const on = draft.regions.includes(r.id);
                  return (
                    <button
                      key={r.id}
                      type="button"
                      className={`scrape-task-region${on ? " is-on" : ""}`}
                      aria-pressed={on}
                      onClick={() => toggleRegion(r.id)}
                    >
                      <span className="scrape-task-region__dot" aria-hidden />
                      <span className="scrape-task-region__name">{r.label}</span>
                      {r.codeCount ? (
                        <span className="scrape-task-region__count">
                          {r.codeCount}
                        </span>
                      ) : null}
                    </button>
                  );
                })}
              </div>
            </section>

            <section className="scrape-task-section">
              <header className="scrape-task-section__head">
                <span className="scrape-task-section__title">范围</span>
                <span className="scrape-task-section__meta mute">
                  {singleRegion ? "可选" : "需单区"}
                </span>
              </header>
              {singleRegion ? (
                <div className="scrape-task-scope">
                  <label
                    className={`scrape-task-scope__cell${draft.maker ? " is-filled" : ""}`}
                  >
                    <span className="scrape-task-scope__label">厂牌</span>
                    <span className="scrape-task-scope__select-wrap">
                      <select
                        className="scrape-task-scope__select"
                        value={draft.maker}
                        onChange={(e) => {
                          const next = e.target.value;
                          setDraft((d) => {
                            if (next === d.maker) return d;
                            return {
                              ...d,
                              maker: next,
                              prefix: "",
                            };
                          });
                        }}
                      >
                        <option value="">全部厂牌</option>
                        {makers.map((m) => (
                          <option key={m.name} value={m.name}>
                            {m.name}
                          </option>
                        ))}
                      </select>
                      <span className="scrape-task-scope__chev" aria-hidden />
                    </span>
                  </label>
                  <label
                    className={`scrape-task-scope__cell${draft.prefix ? " is-filled" : ""}`}
                  >
                    <span className="scrape-task-scope__label">前缀</span>
                    <span className="scrape-task-scope__select-wrap">
                      <select
                        className="scrape-task-scope__select"
                        value={draft.prefix}
                        onChange={(e) =>
                          setDraft((d) => ({ ...d, prefix: e.target.value }))
                        }
                      >
                        <option value="">全部前缀</option>
                        {prefixes.map((p) => (
                          <option key={p.prefix} value={p.prefix}>
                            {p.prefix}
                            {p.codeCount != null ? ` · ${p.codeCount}` : ""}
                          </option>
                        ))}
                      </select>
                      <span className="scrape-task-scope__chev" aria-hidden />
                    </span>
                  </label>
                </div>
              ) : (
                <p className="scrape-task-note mute">
                  多区按全区索引刮削；厂牌 / 前缀需只选一个区。
                </p>
              )}
            </section>

            <section className="scrape-task-section">
              <header className="scrape-task-section__head">
                <span className="scrape-task-section__title">模式</span>
              </header>
              <div className="scrape-task-seg" role="group" aria-label="刮削模式">
                <button
                  type="button"
                  className={`scrape-task-seg__btn${draft.mode === "incremental" ? " is-on" : ""}`}
                  aria-pressed={draft.mode === "incremental"}
                  onClick={() =>
                    setDraft((d) => ({ ...d, mode: "incremental" }))
                  }
                >
                  <span className="scrape-task-seg__label">增量</span>
                  <span className="scrape-task-seg__sub">跳过已有</span>
                </button>
                <button
                  type="button"
                  className={`scrape-task-seg__btn${draft.mode === "force" ? " is-on" : ""}`}
                  aria-pressed={draft.mode === "force"}
                  onClick={() =>
                    setDraft((d) => ({ ...d, mode: "force" }))
                  }
                >
                  <span className="scrape-task-seg__label">强制重刮</span>
                  <span className="scrape-task-seg__sub">覆盖写入</span>
                </button>
              </div>
            </section>

            <section className="scrape-task-section">
              <header className="scrape-task-section__head">
                <span className="scrape-task-section__title">字段配置</span>
                <span className="scrape-task-section__meta mute">刮削/落盘</span>
              </header>
              <div
                className="scrape-task-fields"
                role="group"
                aria-label="刮削字段"
              >
                {FIELD_OPTIONS.map((f) => {
                  const on = draft.fields.includes(f.id);
                  return (
                    <button
                      key={f.id}
                      type="button"
                      className={`scrape-task-fieldchip${on ? " is-on" : ""}`}
                      aria-pressed={on}
                      onClick={() => toggleField(f.id)}
                    >
                      {f.label}
                    </button>
                  );
                })}
              </div>
            </section>

            <section className="scrape-task-section">
              <header className="scrape-task-section__head">
                <span className="scrape-task-section__title">本地可复用</span>
                <span className="scrape-task-section__meta mute">
                  {draft.localFields.length
                    ? `已选 ${draft.localFields.length}`
                    : "不读索引"}
                </span>
              </header>
              <div
                className="scrape-task-fields"
                role="group"
                aria-label="本地可复用字段"
              >
                {LOCAL_FIELD_OPTIONS.map((f) => {
                  const on = draft.localFields.includes(f.id);
                  return (
                    <button
                      key={f.id}
                      type="button"
                      className={`scrape-task-fieldchip${on ? " is-on" : ""}`}
                      aria-pressed={on}
                      onClick={() => toggleLocalField(f.id)}
                    >
                      {f.label}
                    </button>
                  );
                })}
              </div>
              <p className="scrape-task-note mute">
                先读索引物化里勾选的字段，再对比缺口发起网络补全；来源分别标
                index / 站点。
              </p>
            </section>

            <div className="scrape-task-page__footer">
              <label
                className={`scrape-task-modal__watch${draft.watchEnabled ? " is-on" : ""}`}
              >
                <span className="scrape-task-modal__watch-text">
                  <span className="scrape-task-modal__watch-title">监控</span>
                  <span className="scrape-task-modal__watch-sub mute">
                    {draft.watchEnabled
                      ? "开启后须手动开始并跑完一轮才自动增量"
                      : "已关闭"}
                  </span>
                </span>
                <span className="scrape-src-card__switch scrape-task-modal__watch-switch">
                  <input
                    type="checkbox"
                    checked={draft.watchEnabled}
                    disabled={busy}
                    aria-label={draft.watchEnabled ? "关闭监控" : "开启监控"}
                    onChange={(e) =>
                      setDraft((d) => ({
                        ...d,
                        watchEnabled: e.target.checked,
                      }))
                    }
                  />
                </span>
              </label>
              <div className="scrape-task-modal__actions">
                <button
                  type="button"
                  className="btn scrape-task-modal__start"
                  disabled={busy || !canSave}
                  onClick={() => {
                    if (busy || !canSave) return;
                    onSave(resolvedDraft, { toastOk: true });
                    onClose();
                  }}
                >
                  {busy ? "保存中…" : "保存"}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppPush>
  );
}
