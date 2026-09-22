import { useCallback, useState } from 'react';

/** 设置面板上报给父级（设置首页）的状态色调 */
export type StatusTone = 'ok' | 'warn' | 'mute';

/** 设置面板的 `onStatus` 契约：文案 + 色调 */
export type StatusReporter = (text: string, tone: StatusTone) => void;

/** 统一的「异常 → 提示文案」转换（原先各面板各写一遍 `instanceof` 判断） */
export function errorText(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

/**
 * 连接性测试结果的文案：优先用后端 message，其次按结果取兜底文案。
 * 例：`testResultText(r, '连接成功', '连接失败')`
 */
export function testResultText(
  r: { ok?: boolean; message?: string },
  okText: string,
  failText: string,
): string {
  return r.message || (r.ok ? okText : failText);
}

export type PanelAction = {
  /** 面板底部提示文案（`AppMsg` 显示） */
  msg: string;
  setMsg: (text: string) => void;
  /** 提交中（用于禁用输入与按钮） */
  busy: boolean;
  setBusy: (busy: boolean) => void;
  /** 只做 busy/msg 生命周期，异常向上抛，供调用方自理 */
  withBusy: <T>(fn: () => Promise<T>) => Promise<T>;
  /** withBusy + 统一错误转文案；`onError` 供少数面板追加错误态上报 */
  run: (
    fallback: string,
    fn: () => Promise<void>,
    onError?: (e: unknown) => void,
  ) => Promise<void>;
};

/**
 * 集中管理设置面板「保存 / 测试」动作的公共样板：
 *
 * ```ts
 * const { msg, setMsg, busy, run } = usePanelAction();
 *
 * await run('保存失败', async () => {
 *   await putXxx(payload);
 *   setMsg('已保存');
 * });
 * ```
 *
 * 由此消掉原先 8 个面板里逐字重复的
 * `setBusy(true) → setMsg('') → try/catch(setMsg) → finally setBusy(false)`。
 */
export function usePanelAction(): PanelAction {
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);

  const withBusy = useCallback(async <T>(fn: () => Promise<T>): Promise<T> => {
    setBusy(true);
    setMsg('');
    try {
      return await fn();
    } finally {
      setBusy(false);
    }
  }, []);

  const run = useCallback(
    async (fallback: string, fn: () => Promise<void>): Promise<void> => {
      try {
        await withBusy(fn);
      } catch (e) {
        setMsg(errorText(e, fallback));
      }
    },
    [withBusy],
  );

  return { msg, setMsg, busy, setBusy, withBusy, run };
}
