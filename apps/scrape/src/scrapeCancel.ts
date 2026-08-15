/**
 * 单次 /api/scrape 的取消令牌（AsyncLocalStorage）。
 * deadline 触发后 trip；过盾排队侧见 aborted 立即放弃，勿再占全局锁。
 */
import { AsyncLocalStorage } from "node:async_hooks";

export type ScrapeCancelFlag = {
  aborted: boolean;
  reason: string;
};

export const scrapeCancelAls = new AsyncLocalStorage<ScrapeCancelFlag>();

export function createScrapeCancelFlag(): ScrapeCancelFlag {
  return { aborted: false, reason: "" };
}

export function tripScrapeCancel(
  flag: ScrapeCancelFlag,
  reason = "scrape-deadline",
): void {
  flag.aborted = true;
  flag.reason = reason;
}

export function isScrapeCancelled(): boolean {
  return Boolean(scrapeCancelAls.getStore()?.aborted);
}

export function assertScrapeNotCancelled(): void {
  const flag = scrapeCancelAls.getStore();
  if (flag?.aborted) {
    throw new Error(flag.reason || "scrape aborted");
  }
}
