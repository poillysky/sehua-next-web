/**
 * Minimal maker-code parse for pack-bleed / firstMakerCodeIn.
 * Port of sehua-search makerCodeMatch (no av-makers registry).
 */

export type MakerCodeShape =
  | "std"
  | "fc2"
  | "fc2ppv"
  | "date6"
  | "alnum_id"
  | "western_date"
  | "western_ep";

export type ParsedMakerCode = {
  shape: MakerCodeShape;
  canonical: string;
  parts: string[];
  prefix: string;
};

const WESTERN_STUDIO_PREFIXES = new Set(
  [
    "BRAZZERS",
    "BLACKED",
    "BLACKEDRAW",
    "TUSHY",
    "TUSHYRAW",
    "VIXEN",
    "DEEPER",
    "REALITYKINGS",
    "RK",
    "RKPRIME",
    "NAUGHTYAMERICA",
    "BANGBROS",
    "BANGBUS",
    "MOFOS",
    "FAKETAXI",
    "FAKEHUB",
    "EVILANGEL",
    "JULESJORDAN",
    "PURETABOO",
    "ADULTTIME",
    "DORCEL",
    "DORCELCLUB",
    "PRIVATE",
    "ONLYFANS",
    "MANYVIDS",
    "DIGITALPLAYGROUND",
    "ELEGANTANGEL",
    "LETHALHARDCORE",
    "ANALVIDS",
    "KINK",
    "PUBLICAGENT",
    "FAMILYSTROKES",
    "TEAMSKEET",
    "BRATTYSIS",
    "NUBILES",
    "NUBILEFILMS",
    "LEGALPORNO",
    "SEXMEX",
    "PORNWORLD",
    "MILFY",
    "WICKED",
    "SEXART",
    "WATCH4BEAUTY",
    "PLAYBOYPLUS",
  ].map((s) => s.toUpperCase()),
);

const DATE6_PREFIX_LABEL: Record<string, string> = {
  CARIB: "CARIB",
  CARIBBEAN: "CARIB",
  CARIBBEANCOM: "CARIB",
  CARIBPR: "CARIBPR",
  "1PON": "1PON",
  "1PONDO": "1PON",
  PACO: "PACO",
  PACOPACOMAMA: "PACO",
  "10MU": "10MU",
  "10MUSUME": "10MU",
};

const PREFIX_SHAPE: Record<string, MakerCodeShape> = {
  FC2: "fc2",
  FC2PPV: "fc2ppv",
  H0930: "alnum_id",
  C0930: "alnum_id",
  H4610: "alnum_id",
  KIN8: "std",
  GACHI: "std",
  GACHINCO: "std",
};

for (const p of Object.keys(DATE6_PREFIX_LABEL)) {
  PREFIX_SHAPE[p] = "date6";
}
for (const p of WESTERN_STUDIO_PREFIXES) {
  PREFIX_SHAPE[p] = "western_date";
}

export function normalizeMakerCode(keyword: string): string {
  return String(keyword || "")
    .trim()
    .replace(/[－—–﹣]/g, "-")
    .replace(/[０-９]/g, (ch) =>
      String.fromCharCode(ch.charCodeAt(0) - 0xfee0),
    )
    .replace(/[Ａ-Ｚａ-ｚ]/g, (ch) =>
      String.fromCharCode(ch.charCodeAt(0) - 0xfee0),
    );
}

function prefixKey(prefix: string): string {
  return String(prefix || "")
    .trim()
    .toUpperCase()
    .replace(/[_\s]+/g, "-");
}

function westernKey(prefix: string): string {
  return String(prefix || "")
    .trim()
    .toUpperCase()
    .replace(/[_-\s]/g, "");
}

function isWesternStudioPrefix(prefix: string): boolean {
  return WESTERN_STUDIO_PREFIXES.has(westernKey(prefix));
}

function resolveMakerShape(prefix: string): MakerCodeShape {
  const key = prefixKey(prefix);
  const compact = westernKey(prefix);
  if (PREFIX_SHAPE[key]) return PREFIX_SHAPE[key];
  if (PREFIX_SHAPE[compact]) return PREFIX_SHAPE[compact];
  if (key === "FC2-PPV" || compact === "FC2PPV") return "fc2ppv";
  if (isWesternStudioPrefix(prefix)) return "western_date";
  return "std";
}

/** 与后端 search_av.resolve_maker_shape / prefix_format_meta 对齐的规范样例 */
export function makerCodeFormatMeta(prefix: string): {
  shape: MakerCodeShape;
  codeFormat: string;
  codeSample: string;
  padEditable: boolean;
} {
  const key = prefixKey(prefix);
  const compact = westernKey(prefix);
  const shape = resolveMakerShape(prefix);
  if (shape === "western_date") {
    return {
      shape,
      codeFormat: "western_date",
      codeSample: `${compact || key}.2026.01.15`,
      padEditable: false,
    };
  }
  if (shape === "fc2ppv") {
    return {
      shape,
      codeFormat: "fc2ppv",
      codeSample: "FC2-PPV-1234567",
      padEditable: false,
    };
  }
  if (shape === "fc2") {
    return {
      shape,
      codeFormat: "fc2",
      codeSample: "FC2-1234567",
      padEditable: false,
    };
  }
  if (shape === "date6") {
    const label = DATE6_PREFIX_LABEL[key] || DATE6_PREFIX_LABEL[compact] || key;
    return {
      shape,
      codeFormat: "date6",
      codeSample: `${label}-260115-001`,
      padEditable: false,
    };
  }
  if (shape === "alnum_id") {
    const sample =
      key === "H0930"
        ? "H0930-ORI123"
        : key === "C0930"
          ? "C0930-ABC123"
          : key === "H4610"
            ? "H4610-ABC123"
            : `${key}-ABC123`;
    return { shape, codeFormat: "alnum_id", codeSample: sample, padEditable: false };
  }
  return {
    shape: "std",
    codeFormat: "digit_pad",
    codeSample: `${key}-001`,
    padEditable: true,
  };
}

export { resolveMakerShape };

function parseFc2(raw: string): ParsedMakerCode | null {
  const u = normalizeMakerCode(raw).toUpperCase();
  let m = u.match(/^FC2[-_\s.]?PPV[-_\s.]?(\d{5,10})$/i);
  if (m) {
    return {
      shape: "fc2ppv",
      canonical: `FC2-PPV-${m[1]}`,
      parts: ["FC2", "PPV", m[1]],
      prefix: "FC2PPV",
    };
  }
  m = u.match(/^FC2(?![-_\s.]?PPV)[-_\s.]?(\d{5,10})$/i);
  if (m) {
    return {
      shape: "fc2",
      canonical: `FC2-${m[1]}`,
      parts: ["FC2", m[1]],
      prefix: "FC2",
    };
  }
  return null;
}

function parseDate6Keyword(raw: string): ParsedMakerCode | null {
  const u = normalizeMakerCode(raw).toUpperCase();
  const m = u.match(
    /^([A-Z0-9]{2,20})[-_\s.]?(\d{6})[-_\s.](\d{2,3})(?:[-_\s.]?[A-Z]{0,2})?$/i,
  );
  if (m) {
    const label =
      DATE6_PREFIX_LABEL[prefixKey(m[1])] ||
      DATE6_PREFIX_LABEL[westernKey(m[1])] ||
      prefixKey(m[1]);
    if (PREFIX_SHAPE[prefixKey(m[1])] === "date6" || DATE6_PREFIX_LABEL[label]) {
      return {
        shape: "date6",
        canonical: `${label}-${m[2]}-${m[3]}`,
        parts: [label, m[2], m[3]],
        prefix: label,
      };
    }
  }
  return null;
}

function parseAlnumId(raw: string): ParsedMakerCode | null {
  const u = normalizeMakerCode(raw).toUpperCase();
  const m = u.match(/^([HC]0930|H4610)[-_\s.]?([A-Z0-9]{3,24})$/i);
  if (!m) return null;
  const prefix = m[1].toUpperCase();
  const id = m[2].toUpperCase();
  return {
    shape: "alnum_id",
    canonical: `${prefix}-${id}`,
    parts: [prefix, id],
    prefix,
  };
}

function westernYyyy(yyOrYyyy: string): string {
  const s = String(yyOrYyyy || "").trim();
  if (/^(19|20)\d{2}$/.test(s)) return s;
  if (/^\d{2}$/.test(s)) return `20${s}`;
  return s;
}

function parseWestern(raw: string): ParsedMakerCode | null {
  const u = normalizeMakerCode(raw).toUpperCase();
  // KEY.YYYY.MM.DD
  let m = u.match(
    /^([A-Z]{2,24})[._\-\s]?(19\d{2}|20\d{2})[._\-](\d{2})[._\-](\d{2})$/i,
  );
  if (m && isWesternStudioPrefix(m[1])) {
    const key = westernKey(m[1]);
    const yyyy = m[2];
    const can = `${key}.${yyyy}.${m[3]}.${m[4]}`;
    return {
      shape: "western_date",
      canonical: can,
      parts: [key, yyyy, m[3], m[4]],
      prefix: key,
    };
  }
  // KEY.YY.MM.DD → KEY.20YY.MM.DD
  m = u.match(
    /^([A-Z]{2,24})[._\-\s]?(\d{2})[._\-](\d{2})[._\-](\d{2})$/i,
  );
  if (m && isWesternStudioPrefix(m[1])) {
    if (m[2] === "19" || m[2] === "20") return null;
    const key = westernKey(m[1]);
    const yyyy = westernYyyy(m[2]);
    const can = `${key}.${yyyy}.${m[3]}.${m[4]}`;
    return {
      shape: "western_date",
      canonical: can,
      parts: [key, yyyy, m[3], m[4]],
      prefix: key,
    };
  }
  // KEY.260513 → KEY.2026.05.13
  m = u.match(/^([A-Z]{2,24})[-_\s.](\d{6})$/i);
  if (m && isWesternStudioPrefix(m[1])) {
    const key = westernKey(m[1]);
    const ymd = m[2];
    const yyyy = westernYyyy(ymd.slice(0, 2));
    const mo = ymd.slice(2, 4);
    const d = ymd.slice(4, 6);
    const can = `${key}.${yyyy}.${mo}.${d}`;
    return {
      shape: "western_date",
      canonical: can,
      parts: [key, yyyy, mo, d],
      prefix: key,
    };
  }
  // KEY.YYYY.MM
  m = u.match(
    /^([A-Z]{2,24})[._\-\s]?(19\d{2}|20\d{2})[._\-](\d{2})$/i,
  );
  if (m && isWesternStudioPrefix(m[1])) {
    const key = westernKey(m[1]);
    return {
      shape: "western_date",
      canonical: `${key}.${m[2]}.${m[3]}`,
      parts: [key, m[2], m[3]],
      prefix: key,
    };
  }
  // KEY.YYYY
  m = u.match(/^([A-Z]{2,24})[._\-\s]?(19\d{2}|20\d{2})$/i);
  if (m && isWesternStudioPrefix(m[1])) {
    const key = westernKey(m[1]);
    return {
      shape: "western_date",
      canonical: `${key}.${m[2]}`,
      parts: [key, m[2]],
      prefix: key,
    };
  }
  return null;
}

function parseStd(raw: string): ParsedMakerCode | null {
  const u = normalizeMakerCode(raw).toUpperCase();
  const m = u.match(
    /^(?:(\d{2,3}))?([A-Z]{2,20})[-_\s.]?(\d{2,10})(?:[-_\s.]?([A-Z0-9]{1,6}))?$/i,
  );
  if (!m) return null;
  const prefix = m[2].toUpperCase();
  const shape = resolveMakerShape(prefix);
  if (shape !== "std" && shape !== "western_ep") {
    if (shape === "fc2" || shape === "fc2ppv" || shape === "date6") {
      return null;
    }
    if (shape === "alnum_id") return null;
  }
  const num = m[3];
  return {
    shape: "std",
    canonical: `${prefix}-${num}`,
    parts: [prefix, num],
    prefix,
  };
}

export function parseMakerCode(keyword: string): ParsedMakerCode | null {
  const raw = normalizeMakerCode(keyword);
  if (!raw || raw.length > 48) return null;
  return (
    parseFc2(raw) ||
    parseAlnumId(raw) ||
    parseDate6Keyword(raw) ||
    parseWestern(raw) ||
    parseStd(raw)
  );
}
