import { scrapeJavbus } from "./javbus.js";
import {
  scrapeAvsoxFamily,
  scrapeFc2Hub,
  scrapeJavdb,
  scrapeMadou,
  scrapeMadouqu,
  scrapeMgstage,
  scrapeXchina,
} from "./htmlMeta.js";
import {
  scrape7mmtv,
  scrapeAiravIo,
  scrapeAiravWiki,
  scrapeAvbase,
  scrapeCarib,
  scrapeDmm,
  scrapeFd2ppv,
  scrapeFc2Official,
  scrapeFreejavbt,
  scrapeIqqtv,
  scrapeJav321,
  scrapeJavlibrary,
  scrapeLibreDmm,
  scrapeMissav,
  scrapeTheporndb,
} from "./more.js";
import type { PartialFromSource, SourceId } from "../sources.js";

export type ScrapeFn = (code: string) => Promise<PartialFromSource | null>;

export const SOURCE_RUNNERS: Partial<Record<SourceId, ScrapeFn>> = {
  dmm: (code) => scrapeDmm(code),
  mgstage: (code) => scrapeMgstage(code),
  libredmm: (code) => scrapeLibreDmm(code),
  javlibrary: (code) => scrapeJavlibrary(code),
  avbase: (code) => scrapeAvbase(code),
  javdb: (code) => scrapeJavdb(code),
  javbus: async (code) => {
    const p = await scrapeJavbus(code);
    return p?.title || p?.poster ? { ...p, source: "javbus", code } : null;
  },
  jav321: (code) => scrapeJav321(code),
  avmoo: (code) =>
    scrapeAvsoxFamily(code, {
      baseUrl: "https://avmoo.shop",
      source: "avmoo",
    }),
  sevenmmtv: (code) => scrape7mmtv(code),
  iqqtv: (code) => scrapeIqqtv(code),
  airav: (code) => scrapeAiravWiki(code),
  airav_io: (code) => scrapeAiravIo(code),
  freejavbt: (code) => scrapeFreejavbt(code),
  miss_av: (code) => scrapeMissav(code),
  carib: (code) => scrapeCarib(code),
  avsox: (code) =>
    scrapeAvsoxFamily(code, {
      baseUrl: "https://avsox.click",
      source: "avsox",
    }),
  fc2: (code) => scrapeFc2Official(code),
  fc2_hub: (code) => scrapeFc2Hub(code),
  fd2ppv: (code) => scrapeFd2ppv(code),
  madou: (code) => scrapeMadou(code),
  madouqu: (code) => scrapeMadouqu(code),
  xiao_huang_shu: (code) => scrapeXchina(code),
  theporndb: (code) => scrapeTheporndb(code),
};
