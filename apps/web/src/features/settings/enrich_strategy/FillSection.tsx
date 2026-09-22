import { Check } from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';
import { SegTwo } from './ui';
import type { EnrichStrategyForm } from './useEnrichStrategyForm';

export function FillSection({
  actressAvatarMode,
  actressAvatarModeHint,
  busy,
  cfg,
  fillMode,
  fillModeHint,
  patch,
}: EnrichStrategyForm) {
    const fillOpts = cfg?.fillModes?.length
      ? cfg.fillModes
      : [
          { value: 'incremental', label: '增量' },
          { value: 'refresh_weak', label: '弱项重刮' },
          { value: 'overwrite', label: '覆盖' },
        ];
    const langOpts = cfg?.fieldLanguageOptions?.length
      ? cfg.fieldLanguageOptions
      : [
          { id: 'prefer_zh', label: '中文优先' },
          { id: 'prefer_ja', label: '日文优先' },
          { id: 'zh_or_translate', label: '中文或译中' },
        ];
    const outlineOpts = cfg?.outlineShowOptions?.length
      ? cfg.outlineShowOptions
      : [
          { id: 'zh', label: '仅中文' },
          { id: 'zh_jp', label: '中日' },
          { id: 'jp_zh', label: '日中' },
        ];
    const titleLang = cfg?.fieldLanguage?.title || 'prefer_zh';
    const overviewLang = cfg?.fieldLanguage?.overview || 'prefer_zh';
    const outline =
      cfg?.outlineShow === 'zh_jp' || cfg?.outlineShow === 'jp_zh'
        ? cfg.outlineShow
        : 'zh';
    return (
      <>
        <p className="settings-group-label">补齐策略</p>
        <ul className="settings-group enrich-strategy__fill-group">
          <li>
            <div className="settings-kv enrich-strategy__fill-row enrich-strategy__fill-row--stack">
              <span className="settings-nav__main">
                <span className="settings-kv__key">番号补齐</span>
                <span className="settings-nav__desc enrich-strategy__mode-desc">
                  {fillModeHint}
                </span>
              </span>
              <div
                className="enrich-strategy__chips"
                role="radiogroup"
                aria-label="刮削补齐模式"
              >
                {fillOpts.map((opt) => {
                  const id = opt.value;
                  const on = fillMode === id;
                  return (
                    <button
                      key={id}
                      type="button"
                      className={cn(
                        'enrich-strategy__chip',
                        on && 'enrich-strategy__chip--on',
                      )}
                      disabled={busy}
                      role="radio"
                      aria-checked={on}
                      onClick={() =>
                        patch({
                          fillMode:
                            id === 'overwrite'
                              ? 'overwrite'
                              : id === 'refresh_weak'
                                ? 'refresh_weak'
                                : 'incremental',
                        })
                      }
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </div>
          </li>
          <li>
            <div className="settings-kv enrich-strategy__fill-row">
              <span className="settings-nav__main">
                <span className="settings-kv__key">女优刮削</span>
                <span className="settings-nav__desc enrich-strategy__mode-desc">
                  {actressAvatarModeHint}
                </span>
              </span>
              <SegTwo
                ariaLabel="女优刮削头像模式"
                value={actressAvatarMode}
                left={{ id: 'incremental', label: '增量' }}
                right={{ id: 'overwrite', label: '覆盖' }}
                disabled={busy}
                onChange={(id) =>
                  patch({
                    actressAvatarMode:
                      id === 'overwrite' ? 'overwrite' : 'incremental',
                  })
                }
              />
            </div>
          </li>
        </ul>

        <p className="settings-group-label settings-group-label--spaced">
          字段语言与标题
        </p>
        <ul className="settings-group enrich-strategy__fill-group">
          <li>
            <div className="settings-kv enrich-strategy__fill-row enrich-strategy__fill-row--stack">
              <span className="settings-nav__main">
                <span className="settings-kv__key">标题语言</span>
                <span className="settings-nav__desc enrich-strategy__mode-desc">
                  合并时标题的语言偏好
                </span>
              </span>
              <div
                className="enrich-strategy__chips"
                role="radiogroup"
                aria-label="标题语言"
              >
                {langOpts.map((opt) => {
                  const on = titleLang === opt.id;
                  return (
                    <button
                      key={`title-${opt.id}`}
                      type="button"
                      className={cn(
                        'enrich-strategy__chip',
                        on && 'enrich-strategy__chip--on',
                      )}
                      disabled={busy}
                      role="radio"
                      aria-checked={on}
                      onClick={() =>
                        patch({
                          fieldLanguage: {
                            title: opt.id,
                            overview: overviewLang,
                          },
                        })
                      }
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </div>
          </li>
          <li>
            <div className="settings-kv enrich-strategy__fill-row enrich-strategy__fill-row--stack">
              <span className="settings-nav__main">
                <span className="settings-kv__key">剧情语言</span>
                <span className="settings-nav__desc enrich-strategy__mode-desc">
                  合并时剧情的语言偏好
                </span>
              </span>
              <div
                className="enrich-strategy__chips"
                role="radiogroup"
                aria-label="剧情语言"
              >
                {langOpts.map((opt) => {
                  const on = overviewLang === opt.id;
                  return (
                    <button
                      key={`ov-${opt.id}`}
                      type="button"
                      className={cn(
                        'enrich-strategy__chip',
                        on && 'enrich-strategy__chip--on',
                      )}
                      disabled={busy}
                      role="radio"
                      aria-checked={on}
                      onClick={() =>
                        patch({
                          fieldLanguage: {
                            title: titleLang,
                            overview: opt.id,
                          },
                        })
                      }
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </div>
          </li>
          <li>
            <div className="settings-kv enrich-strategy__fill-row enrich-strategy__fill-row--stack">
              <span className="settings-nav__main">
                <span className="settings-kv__key">详情剧情展示</span>
                <span className="settings-nav__desc enrich-strategy__mode-desc">
                  新刮削写入 NFO；双语需同时有中/日剧情
                </span>
              </span>
              <div
                className="enrich-strategy__chips"
                role="radiogroup"
                aria-label="详情剧情展示"
              >
                {outlineOpts.map((opt) => {
                  const on = outline === opt.id;
                  return (
                    <button
                      key={opt.id}
                      type="button"
                      className={cn(
                        'enrich-strategy__chip',
                        on && 'enrich-strategy__chip--on',
                      )}
                      disabled={busy}
                      role="radio"
                      aria-checked={on}
                      onClick={() =>
                        patch({
                          outlineShow:
                            opt.id === 'zh_jp' || opt.id === 'jp_zh'
                              ? opt.id
                              : 'zh',
                        })
                      }
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </div>
          </li>
          <li>
            <div className="settings-kv enrich-strategy__fill-row">
              <span className="settings-nav__main">
                <span className="settings-kv__key">剥标题尾女优名</span>
                <span className="settings-nav__desc enrich-strategy__mode-desc">
                  定稿后去掉标题末尾演员名（默认关）
                </span>
              </span>
              <Switch
                checked={Boolean(cfg?.stripTitleActorSuffix)}
                disabled={busy}
                onCheckedChange={(v) =>
                  patch({ stripTitleActorSuffix: Boolean(v) })
                }
              />
            </div>
          </li>
          <li>
            <div className="settings-kv enrich-strategy__fill-row">
              <span className="settings-nav__main">
                <span className="settings-kv__key">剥标题前番号</span>
                <span className="settings-nav__desc enrich-strategy__mode-desc">
                  定稿后去掉标题开头番号（默认关）
                </span>
              </span>
              <Switch
                checked={Boolean(cfg?.stripTitleCodePrefix)}
                disabled={busy}
                onCheckedChange={(v) =>
                  patch({ stripTitleCodePrefix: Boolean(v) })
                }
              />
            </div>
          </li>
          <li>
            <div className="settings-kv enrich-strategy__fill-row">
              <span className="settings-nav__main">
                <span className="settings-kv__key">FC2 卖家作女优</span>
                <span className="settings-nav__desc enrich-strategy__mode-desc">
                  女优空时用卖家名兜底（默认开）
                </span>
              </span>
              <Switch
                checked={cfg?.fc2SellerAsActor !== false}
                disabled={busy}
                onCheckedChange={(v) =>
                  patch({ fc2SellerAsActor: Boolean(v) })
                }
              />
            </div>
          </li>
        </ul>

        <p className="settings-group-label settings-group-label--spaced">
          增量强制写回
        </p>
        <ul className="settings-group enrich-strategy__fill-group">
          <li>
            <div className="enrich-strategy__force">
              <div className="enrich-strategy__force-head">
                <p className="enrich-strategy__force-desc">
                  仅增量生效；覆盖 / 弱项本就全量强制
                </p>
                {(cfg?.forceFields || []).length > 0 ? (
                  <button
                    type="button"
                    className="enrich-strategy__force-clear"
                    disabled={busy}
                    onClick={() => patch({ forceFields: [] })}
                  >
                    清除 · {(cfg?.forceFields || []).length}
                  </button>
                ) : (
                  <span className="enrich-strategy__force-count">未选</span>
                )}
              </div>
              <div
                className="enrich-strategy__force-grid"
                role="group"
                aria-label="增量强制字段"
              >
                {(
                  cfg?.forceFieldOptions?.length
                    ? cfg.forceFieldOptions
                    : [
                        { id: 'title', label: '标题' },
                        { id: 'overview', label: '剧情' },
                        { id: 'actors', label: '女优' },
                        { id: 'studio', label: '片商' },
                        { id: 'poster', label: '海报' },
                        { id: 'tags', label: '标签' },
                        { id: 'badges', label: '角标' },
                      ]
                ).map((opt) => {
                  const on = (cfg?.forceFields || []).includes(opt.id);
                  return (
                    <button
                      key={opt.id}
                      type="button"
                      className={cn(
                        'enrich-strategy__force-cell',
                        on && 'enrich-strategy__force-cell--on',
                      )}
                      disabled={busy}
                      aria-pressed={on}
                      onClick={() => {
                        const cur = new Set(cfg?.forceFields || []);
                        if (cur.has(opt.id)) cur.delete(opt.id);
                        else cur.add(opt.id);
                        patch({ forceFields: [...cur] });
                      }}
                    >
                      <span
                        className={cn(
                          'enrich-strategy__force-tick',
                          on && 'enrich-strategy__force-tick--on',
                        )}
                        aria-hidden
                      >
                        {on ? <Check strokeWidth={2.75} /> : null}
                      </span>
                      <span className="enrich-strategy__force-label">
                        {opt.label}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          </li>
        </ul>
      </>
    );
  }
