'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { ChevronRight } from 'lucide-react';
import {
  activateChatPreset,
  addChatPresetPrompt,
  chatPresetExportUrl,
  deleteChatPreset,
  enableChatPresetPrompt,
  getChatPreset,
  importChatPreset,
  listChatPresets,
  saveChatPresetParams,
  saveChatPresetPrompt,
  type AiSamplingConfig,
  type ChatPresetDetail,
  type ChatPresetListItem,
  type ChatPresetPrompt,
} from '@/lib/api';
import { Switch } from '@/components/ui/switch';
import { AppMsg } from '@/components/ui/AppMsg';
import { cn } from '@/lib/utils';

const PRESET_DEFAULTS = {
  temperature: '1',
  topP: '1',
  maxTokens: '2048',
  maxContext: '8192',
  frequencyPenalty: '0',
  presencePenalty: '0',
  topK: '',
  minP: '',
  repetitionPenalty: '',
  seed: '-1',
  n: '1',
};

type DetailTab = 'settings' | 'prompts';

function numStr(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '';
  return String(v);
}

function FormCard({ children }: { children: ReactNode }) {
  return <section className="ai-card">{children}</section>;
}

function SettingRow({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="ai-row">
      <span className="ai-row__label">{label}</span>
      <div className="ai-row__control">{children}</div>
    </div>
  );
}

export function ChatPresetsSection({
  onSamplingApplied,
}: {
  onSamplingApplied?: () => void;
}) {
  const [list, setList] = useState<ChatPresetListItem[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ChatPresetDetail | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>('settings');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  const [temp, setTemp] = useState(PRESET_DEFAULTS.temperature);
  const [topP, setTopP] = useState(PRESET_DEFAULTS.topP);
  const [maxTokens, setMaxTokens] = useState(PRESET_DEFAULTS.maxTokens);
  const [maxContext, setMaxContext] = useState(PRESET_DEFAULTS.maxContext);
  const [freq, setFreq] = useState(PRESET_DEFAULTS.frequencyPenalty);
  const [pres, setPres] = useState(PRESET_DEFAULTS.presencePenalty);
  const [topK, setTopK] = useState(PRESET_DEFAULTS.topK);
  const [minP, setMinP] = useState(PRESET_DEFAULTS.minP);
  const [rep, setRep] = useState(PRESET_DEFAULTS.repetitionPenalty);
  const [seed, setSeed] = useState(PRESET_DEFAULTS.seed);
  const [n, setN] = useState(PRESET_DEFAULTS.n);
  const [stream, setStream] = useState(true);
  const [ctxUnlocked, setCtxUnlocked] = useState(false);
  const [continuePrefill, setContinuePrefill] = useState(false);
  const [squash, setSquash] = useState(false);
  const [thoughts, setThoughts] = useState(false);

  const [editPrompt, setEditPrompt] = useState<ChatPresetPrompt | null>(null);

  async function reloadList() {
    const r = await listChatPresets();
    setList(r.presets || []);
    setActiveId(r.activeId);
  }

  useEffect(() => {
    void (async () => {
      try {
        await reloadList();
      } catch (e) {
        setMsg(e instanceof Error ? e.message : '读取预设失败');
      }
    })();
  }, []);

  function applySamplingDraft(s: AiSamplingConfig) {
    setTemp(numStr(s.temperature) || PRESET_DEFAULTS.temperature);
    setTopP(numStr(s.topP) || PRESET_DEFAULTS.topP);
    setMaxTokens(numStr(s.maxTokens) || PRESET_DEFAULTS.maxTokens);
    setMaxContext(numStr(s.maxContext) || PRESET_DEFAULTS.maxContext);
    setFreq(numStr(s.frequencyPenalty) || PRESET_DEFAULTS.frequencyPenalty);
    setPres(numStr(s.presencePenalty) || PRESET_DEFAULTS.presencePenalty);
    setTopK(numStr(s.topK));
    setMinP(numStr(s.minP));
    setRep(numStr(s.repetitionPenalty));
    setSeed(numStr(s.seed) || PRESET_DEFAULTS.seed);
    setN(numStr(s.n) || PRESET_DEFAULTS.n);
    setStream(s.streamOpenai !== false);
    setCtxUnlocked(Boolean(s.maxContextUnlocked));
    setContinuePrefill(Boolean(s.continuePrefill));
    setSquash(Boolean(s.squashSystemMessages));
    setThoughts(Boolean(s.showThoughts));
  }

  async function openDetail(id: string) {
    setBusy(true);
    setMsg('');
    try {
      const d = await getChatPreset(id);
      setDetail(d);
      setDetailId(id);
      setDetailTab('settings');
      applySamplingDraft(d.sampling || {});
      setEditPrompt(null);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '打开失败');
    } finally {
      setBusy(false);
    }
  }

  async function onImport(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true);
    setMsg('');
    try {
      let lastId = '';
      for (const f of Array.from(files)) {
        const item = await importChatPreset(f);
        lastId = item.id;
      }
      await reloadList();
      setMsg('预设已导入');
      if (lastId) await openDetail(lastId);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '导入失败');
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  }

  async function onToggleActive(id: string) {
    setBusy(true);
    setMsg('');
    try {
      const r = await activateChatPreset(id);
      setList(r.presets || []);
      setActiveId(r.activeId);
      setMsg(r.activeId === id ? '已启用并同步采样到聊天' : '已取消启用');
      onSamplingApplied?.();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '启用失败');
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(id: string) {
    if (!window.confirm('删除此预设？不可恢复')) return;
    setBusy(true);
    setMsg('');
    try {
      const r = await deleteChatPreset(id);
      setList(r.presets || []);
      setActiveId(r.activeId);
      setDetail(null);
      setDetailId(null);
      setMsg('已删除');
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '删除失败');
    } finally {
      setBusy(false);
    }
  }

  function samplingBody(): AiSamplingConfig {
    const parse = (s: string) => {
      const t = s.trim();
      if (!t) return undefined;
      const n = Number(t);
      return Number.isFinite(n) ? n : undefined;
    };
    const parseIntSafe = (s: string) => {
      const n = parse(s);
      return n != null ? Math.round(n) : undefined;
    };
    return {
      temperature: parse(temp),
      topP: parse(topP),
      maxTokens: parseIntSafe(maxTokens),
      maxContext: parseIntSafe(maxContext),
      frequencyPenalty: parse(freq),
      presencePenalty: parse(pres),
      topK: parseIntSafe(topK),
      minP: parse(minP),
      repetitionPenalty: parse(rep),
      seed: parseIntSafe(seed),
      n: parseIntSafe(n),
      streamOpenai: stream,
      maxContextUnlocked: ctxUnlocked,
      continuePrefill: continuePrefill,
      squashSystemMessages: squash,
      showThoughts: thoughts,
    };
  }

  function resetDefaults() {
    setTemp(PRESET_DEFAULTS.temperature);
    setTopP(PRESET_DEFAULTS.topP);
    setMaxTokens(PRESET_DEFAULTS.maxTokens);
    setMaxContext(PRESET_DEFAULTS.maxContext);
    setFreq(PRESET_DEFAULTS.frequencyPenalty);
    setPres(PRESET_DEFAULTS.presencePenalty);
    setTopK(PRESET_DEFAULTS.topK);
    setMinP(PRESET_DEFAULTS.minP);
    setRep(PRESET_DEFAULTS.repetitionPenalty);
    setSeed(PRESET_DEFAULTS.seed);
    setN(PRESET_DEFAULTS.n);
    setStream(true);
    setCtxUnlocked(false);
    setContinuePrefill(false);
    setSquash(false);
    setThoughts(false);
  }

  async function onSaveParams() {
    if (!detailId) return;
    setBusy(true);
    setMsg('');
    try {
      const d = await saveChatPresetParams(detailId, samplingBody());
      setDetail(d);
      applySamplingDraft(d.sampling || {});
      setMsg('预设参数已保存');
      if (activeId === detailId) onSamplingApplied?.();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '保存失败');
    } finally {
      setBusy(false);
    }
  }

  async function onTogglePrompt(p: ChatPresetPrompt) {
    if (!detailId) return;
    setBusy(true);
    try {
      const prompts = await enableChatPresetPrompt(
        detailId,
        p.identifier,
        !p.enabled,
      );
      setDetail((prev) => (prev ? { ...prev, prompts } : prev));
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '更新失败');
    } finally {
      setBusy(false);
    }
  }

  async function onAddPrompt() {
    if (!detailId) return;
    setBusy(true);
    try {
      const prompts = await addChatPresetPrompt(detailId, { name: '自定义提示' });
      setDetail((prev) => (prev ? { ...prev, prompts } : prev));
      const created = prompts[prompts.length - 1];
      if (created) setEditPrompt(created);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '新建失败');
    } finally {
      setBusy(false);
    }
  }

  async function onSavePrompt() {
    if (!detailId || !editPrompt) return;
    setBusy(true);
    try {
      const prompts = await saveChatPresetPrompt(detailId, {
        identifier: editPrompt.identifier,
        name: editPrompt.name,
        role: editPrompt.role,
        content: editPrompt.content,
        enabled: editPrompt.enabled,
      });
      setDetail((prev) => (prev ? { ...prev, prompts } : prev));
      setEditPrompt(null);
      setMsg('提示词已保存');
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '保存失败');
    } finally {
      setBusy(false);
    }
  }

  if (detailId && detail) {
    return (
      <>
        <ul className="settings-group">
          <li>
            <button
              type="button"
              className="settings-nav"
              onClick={() => {
                setDetailId(null);
                setDetail(null);
                setEditPrompt(null);
              }}
            >
              <span className="settings-nav__main">
                <span className="settings-nav__title">返回预设列表</span>
                <span className="settings-nav__desc">{detail.name}</span>
              </span>
              <ChevronRight className="settings-nav__chev" size={16} strokeWidth={2.25} />
            </button>
          </li>
        </ul>

        <div className="app-seg" role="tablist" aria-label="预设详情">
          {(
            [
              { key: 'settings', label: '设置' },
              { key: 'prompts', label: '提示词' },
            ] as const
          ).map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={detailTab === t.key}
              className={cn('app-seg__btn', detailTab === t.key && 'app-seg__btn--active')}
              onClick={() => setDetailTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>

        {detailTab === 'settings' ? (
          <>
            <p className="settings-group-label">长度</p>
            <FormCard>
              <SettingRow label="上下文">
                <input
                  className="allow-select ai-input"
                  inputMode="numeric"
                  value={maxContext}
                  onChange={(e) => setMaxContext(e.target.value)}
                  disabled={busy}
                />
              </SettingRow>
              <SettingRow label="最大回复">
                <input
                  className="allow-select ai-input"
                  inputMode="numeric"
                  value={maxTokens}
                  onChange={(e) => setMaxTokens(e.target.value)}
                  disabled={busy}
                />
              </SettingRow>
            </FormCard>

            <p className="settings-group-label">采样</p>
            <FormCard>
              <SettingRow label="温度">
                <input
                  className="allow-select ai-input"
                  inputMode="decimal"
                  value={temp}
                  onChange={(e) => setTemp(e.target.value)}
                  disabled={busy}
                />
              </SettingRow>
              <SettingRow label="Top P">
                <input
                  className="allow-select ai-input"
                  inputMode="decimal"
                  value={topP}
                  onChange={(e) => setTopP(e.target.value)}
                  disabled={busy}
                />
              </SettingRow>
              <SettingRow label="频率惩罚">
                <input
                  className="allow-select ai-input"
                  inputMode="decimal"
                  value={freq}
                  onChange={(e) => setFreq(e.target.value)}
                  disabled={busy}
                />
              </SettingRow>
              <SettingRow label="存在惩罚">
                <input
                  className="allow-select ai-input"
                  inputMode="decimal"
                  value={pres}
                  onChange={(e) => setPres(e.target.value)}
                  disabled={busy}
                />
              </SettingRow>
              <SettingRow label="Top K">
                <input
                  className="allow-select ai-input"
                  inputMode="numeric"
                  value={topK}
                  onChange={(e) => setTopK(e.target.value)}
                  disabled={busy}
                />
              </SettingRow>
              <SettingRow label="Min P">
                <input
                  className="allow-select ai-input"
                  inputMode="decimal"
                  value={minP}
                  onChange={(e) => setMinP(e.target.value)}
                  disabled={busy}
                />
              </SettingRow>
              <SettingRow label="重复惩罚">
                <input
                  className="allow-select ai-input"
                  inputMode="decimal"
                  value={rep}
                  onChange={(e) => setRep(e.target.value)}
                  disabled={busy}
                />
              </SettingRow>
              <SettingRow label="种子">
                <input
                  className="allow-select ai-input"
                  inputMode="numeric"
                  placeholder="-1 随机"
                  value={seed}
                  onChange={(e) => setSeed(e.target.value)}
                  disabled={busy}
                />
              </SettingRow>
              <SettingRow label="备选数">
                <input
                  className="allow-select ai-input"
                  inputMode="numeric"
                  value={n}
                  onChange={(e) => setN(e.target.value)}
                  disabled={busy}
                />
              </SettingRow>
            </FormCard>

            <p className="settings-group-label">行为</p>
            <ul className="settings-group">
              <li>
                <div className="settings-kv">
                  <span className="settings-kv__key">解锁上下文</span>
                  <Switch checked={ctxUnlocked} onCheckedChange={setCtxUnlocked} disabled={busy} />
                </div>
              </li>
              <li>
                <div className="settings-kv">
                  <span className="settings-kv__key">流式传输</span>
                  <Switch checked={stream} onCheckedChange={setStream} disabled={busy} />
                </div>
              </li>
              <li>
                <div className="settings-kv">
                  <span className="settings-kv__key">续写预填充</span>
                  <Switch
                    checked={continuePrefill}
                    onCheckedChange={setContinuePrefill}
                    disabled={busy}
                  />
                </div>
              </li>
              <li>
                <div className="settings-kv">
                  <span className="settings-kv__key">压缩系统消息</span>
                  <Switch checked={squash} onCheckedChange={setSquash} disabled={busy} />
                </div>
              </li>
              <li>
                <div className="settings-kv">
                  <span className="settings-kv__key">请求思维链</span>
                  <Switch checked={thoughts} onCheckedChange={setThoughts} disabled={busy} />
                </div>
              </li>
            </ul>

            <div className="app-actions">
              <button
                type="button"
                className="app-btn-secondary"
                disabled={busy}
                onClick={() => resetDefaults()}
              >
                还原
              </button>
              <button
                type="button"
                className="app-btn-primary"
                style={{ flex: 1 }}
                disabled={busy}
                onClick={() => void onSaveParams()}
              >
                保存
              </button>
            </div>
            <div className="app-actions" style={{ marginTop: 8 }}>
              <a
                className="app-btn-secondary"
                style={{ flex: 1, textAlign: 'center', textDecoration: 'none' }}
                href={chatPresetExportUrl(detailId)}
              >
                导出 JSON
              </a>
              <button
                type="button"
                className="app-btn-secondary"
                disabled={busy}
                onClick={() => void onDelete(detailId)}
              >
                删除此预设
              </button>
            </div>
          </>
        ) : null}

        {detailTab === 'prompts' ? (
          <>
            <div className="app-actions" style={{ marginBottom: 8 }}>
              <button
                type="button"
                className="app-btn-primary"
                style={{ flex: 1 }}
                disabled={busy}
                onClick={() => void onAddPrompt()}
              >
                新建提示词
              </button>
            </div>
            {editPrompt ? (
              <FormCard>
                <SettingRow label="名称">
                  <input
                    className="allow-select ai-input"
                    value={editPrompt.name}
                    onChange={(e) =>
                      setEditPrompt({ ...editPrompt, name: e.target.value })
                    }
                    disabled={busy}
                  />
                </SettingRow>
                <SettingRow label="角色">
                  <select
                    className="allow-select ai-input"
                    value={editPrompt.role}
                    onChange={(e) =>
                      setEditPrompt({ ...editPrompt, role: e.target.value })
                    }
                    disabled={busy}
                  >
                    <option value="system">system</option>
                    <option value="user">user</option>
                    <option value="assistant">assistant</option>
                  </select>
                </SettingRow>
                <div className="ai-row ai-row--stack">
                  <span className="ai-row__label">内容</span>
                  <textarea
                    className="allow-select ai-textarea"
                    rows={8}
                    value={editPrompt.content || ''}
                    onChange={(e) =>
                      setEditPrompt({ ...editPrompt, content: e.target.value })
                    }
                    disabled={busy}
                  />
                </div>
                <div className="app-actions" style={{ marginTop: 8 }}>
                  <button
                    type="button"
                    className="app-btn-secondary"
                    disabled={busy}
                    onClick={() => setEditPrompt(null)}
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    className="app-btn-primary"
                    style={{ flex: 1 }}
                    disabled={busy}
                    onClick={() => void onSavePrompt()}
                  >
                    保存提示词
                  </button>
                </div>
              </FormCard>
            ) : (
              <ul className="settings-group">
                {(detail.prompts || []).length === 0 ? (
                  <li>
                    <div className="settings-kv">
                      <span className="settings-kv__key">提示词</span>
                      <span className="settings-kv__val">暂无</span>
                    </div>
                  </li>
                ) : (
                  detail.prompts.map((p) => (
                    <li key={p.identifier}>
                      <div className="settings-kv" style={{ gap: 8 }}>
                        <button
                          type="button"
                          className="settings-nav"
                          style={{ flex: 1, minWidth: 0 }}
                          onClick={() => setEditPrompt(p)}
                        >
                          <span className="settings-nav__main">
                            <span className="settings-nav__title">{p.name || p.identifier}</span>
                            <span className="settings-nav__desc">
                              {p.role}
                              {p.marker ? ' · 标记' : ''}
                            </span>
                          </span>
                          <ChevronRight
                            className="settings-nav__chev"
                            size={16}
                            strokeWidth={2.25}
                          />
                        </button>
                        <Switch
                          checked={p.enabled}
                          onCheckedChange={() => void onTogglePrompt(p)}
                          disabled={busy}
                        />
                      </div>
                    </li>
                  ))
                )}
              </ul>
            )}
          </>
        ) : null}

        <AppMsg allowSelect onDismiss={() => setMsg('')}>
          {msg}
        </AppMsg>
      </>
    );
  }

  return (
    <>
      <ul className="settings-group">
        <li>
          <div className="settings-kv">
            <span className="settings-kv__key">当前启用</span>
            <span className="settings-kv__val">
              {activeId
                ? list.find((p) => p.id === activeId)?.name || activeId
                : '未启用'}
            </span>
          </div>
        </li>
      </ul>

      <input
        ref={fileRef}
        type="file"
        accept="application/json,.json"
        multiple
        hidden
        onChange={(e) => void onImport(e.target.files)}
      />

      <div className="app-actions" style={{ marginBottom: 8 }}>
        <button
          type="button"
          className="app-btn-primary"
          style={{ flex: 1 }}
          disabled={busy}
          onClick={() => fileRef.current?.click()}
        >
          导入预设 JSON
        </button>
      </div>

      <p className="settings-group-label">对话预设</p>
      <ul className="settings-group">
        {list.length === 0 ? (
          <li>
            <div className="settings-kv">
              <span className="settings-kv__key">列表</span>
              <span className="settings-kv__val">暂无预设</span>
            </div>
          </li>
        ) : (
          list.map((p) => (
            <li key={p.id}>
              <div className="settings-kv" style={{ gap: 8 }}>
                <button
                  type="button"
                  className="settings-nav"
                  style={{ flex: 1, minWidth: 0 }}
                  onClick={() => void openDetail(p.id)}
                >
                  <span className="settings-nav__main">
                    <span className="settings-nav__title">{p.name}</span>
                    <span className="settings-nav__desc">
                      {p.promptCount ?? 0} 条提示词
                    </span>
                  </span>
                  <ChevronRight
                    className="settings-nav__chev"
                    size={16}
                    strokeWidth={2.25}
                  />
                </button>
                <Switch
                  checked={activeId === p.id}
                  onCheckedChange={() => void onToggleActive(p.id)}
                  disabled={busy}
                />
              </div>
            </li>
          ))
        )}
      </ul>

      <AppMsg allowSelect onDismiss={() => setMsg('')}>
        {msg}
      </AppMsg>
    </>
  );
}
