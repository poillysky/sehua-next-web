/**
 * Sync shared map JSON from apps/maps → apps/web/maps (real files).
 * Turbopack cannot import outside its filesystem root / via outbound junctions.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const webDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const srcRoot = path.resolve(webDir, "../maps");
const dstRoot = path.join(webDir, "maps");

const FILES = [
  "prefixes/code-shapes.json",
  "sites/sehuatang-forum.json",
];

function copyOne(rel) {
  const from = path.join(srcRoot, rel);
  const to = path.join(dstRoot, rel);
  if (!fs.existsSync(from)) {
    throw new Error(`missing source map: ${from}`);
  }
  fs.mkdirSync(path.dirname(to), { recursive: true });
  fs.copyFileSync(from, to);
  console.log(`[sync-maps] ${rel}`);
}

for (const rel of FILES) copyOne(rel);
console.log(`[sync-maps] done → ${dstRoot}`);
