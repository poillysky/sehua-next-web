'use client';

import { Switch } from '@/components/ui/switch';
import { AppFootnote } from '@/components/ui/AppMsg';
import { FormCard, SettingRow } from './ui';
import type { AiModelsPanelState } from './useAiModelsPanel';

export function AiXiaohuaTab({ p }: { p: AiModelsPanelState }) {
  const {
    enabledSkillLabels,
    skillGroups,
    toolMeta,
    skillOn,
    setSkillEnabled,
    busy,
    assistantTools,
    setToolEnabled,
    webEnabled,
    setWebEnabled,
    webProvider,
    setWebProvider,
    webProviders,
    webBaseUrl,
    setWebBaseUrl,
    webHint,
    webShowKey,
    setWebShowKey,
    webApiKey,
    setWebApiKey,
    isSearxng,
    onSaveXiaohua,
  } = p;

  return (
    <>
      <ul className="settings-group">
        <li>
          <div className="settings-kv">
            <span className="settings-kv__key">角色</span>
            <span className="settings-kv__val">智能搜片助手</span>
          </div>
        </li>
        <li>
          <div className="settings-kv">
            <span className="settings-kv__key">可搜</span>
            <span className="settings-kv__val">
              {enabledSkillLabels.length ? enabledSkillLabels.join(' · ') : '未启用'}
            </span>
          </div>
        </li>
      </ul>

      <p className="settings-group-label">技能与工具</p>
      {skillGroups.map((group) => {
        const toolsInGroup = toolMeta.filter((t) => t.group === group.id);
        const groupOn = skillOn(group.id);
        return (
          <div key={group.id} style={{ marginBottom: 12 }}>
            <ul className="settings-group">
              <li>
                <div className="settings-kv">
                  <span className="settings-kv__key">
                    {group.label}
                    <span
                      className="settings-kv__hint"
                      style={{ display: 'block', fontSize: 12, opacity: 0.65, fontWeight: 400 }}
                    >
                      {group.desc}
                    </span>
                  </span>
                  <Switch
                    checked={groupOn}
                    onCheckedChange={(on) => setSkillEnabled(group.id, on)}
                    disabled={busy}
                  />
                </div>
              </li>
              {toolsInGroup.map((tool) => (
                <li key={tool.id}>
                  <div className="settings-kv">
                    <span className="settings-kv__key">
                      {tool.label}
                      <span
                        style={{ display: 'block', fontSize: 12, opacity: 0.65, fontWeight: 400 }}
                      >
                        {tool.desc}
                      </span>
                    </span>
                    <Switch
                      checked={assistantTools[tool.id] !== false}
                      onCheckedChange={(on) => setToolEnabled(tool.id, on)}
                      disabled={busy}
                    />
                  </div>
                </li>
              ))}
            </ul>
          </div>
        );
      })}

      {skillOn('web') ? (
        <>
          <p className="settings-group-label">网络搜索</p>
          <FormCard>
            <SettingRow label="启用服务">
              <Switch
                checked={webEnabled}
                onCheckedChange={(on) => {
                  setWebEnabled(on);
                  if (on) setToolEnabled('web_search', true);
                }}
                disabled={busy}
              />
            </SettingRow>
            <SettingRow label="服务商">
              <select
                className="allow-select ai-input"
                value={webProvider}
                onChange={(e) => {
                  const v = e.target.value;
                  setWebProvider(v);
                  if (v === 'searxng') {
                    setWebShowKey(false);
                    if (!webBaseUrl.trim()) setWebBaseUrl('http://192.168.2.38:8085');
                  } else {
                    setWebShowKey(true);
                  }
                }}
                disabled={busy || !webEnabled}
              >
                {webProviders.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </SettingRow>
            {isSearxng ? (
              <SettingRow label="服务地址">
                <input
                  className="allow-select ai-input"
                  type="url"
                  placeholder="http://192.168.2.38:8085"
                  value={webBaseUrl}
                  onChange={(e) => setWebBaseUrl(e.target.value)}
                  disabled={busy || !webEnabled}
                  autoCapitalize="off"
                  autoCorrect="off"
                  spellCheck={false}
                />
              </SettingRow>
            ) : webHint && !webShowKey ? (
              <SettingRow label="API Key">
                <div className="ai-key-saved">
                  <span className="allow-select">{webHint}</span>
                  <button
                    type="button"
                    className="settings-inline-action"
                    disabled={busy}
                    onClick={() => setWebShowKey(true)}
                  >
                    更换
                  </button>
                </div>
              </SettingRow>
            ) : (
              <SettingRow label="API Key">
                <input
                  className="allow-select ai-input"
                  type="password"
                  placeholder={webProvider === 'brave' ? 'Brave API Key' : 'Serper API Key'}
                  value={webApiKey}
                  onChange={(e) => setWebApiKey(e.target.value)}
                  disabled={busy || !webEnabled}
                  autoCapitalize="off"
                  autoCorrect="off"
                  spellCheck={false}
                />
              </SettingRow>
            )}
          </FormCard>
        </>
      ) : null}

      <AppFootnote>
        关掉某技能后，小花对话里不会再调用对应工具。网络可选 SearXNG（自建免 Key）或 Serper/Brave；本地库不依赖外网。
      </AppFootnote>

      <div className="app-actions">
        <button
          type="button"
          className="app-btn-primary"
          style={{ flex: 1 }}
          disabled={busy}
          onClick={() => void onSaveXiaohua()}
        >
          保存
        </button>
      </div>
    </>
  );
}
