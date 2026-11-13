// Copy the canonical definition files (objectives, media profiles, delivery
// formats, model registry) into the demo dataset verbatim. These are data
// definitions, not results; results are produced by the core (SPEC 11.4).
// Usage: npm run demo:sync-defs [-- <demo-dir>]
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "..", "..");
const demo = resolve(process.argv[2] ?? join(here, "..", "public", "demo"));

export const DEFINITIONS = [
  ["objectives/catalog.json", "definitions/objectives.json"],
  ["profiles/media_profiles.json", "definitions/media_profiles.json"],
  ["profiles/delivery_formats.json", "definitions/delivery_formats.json"],
  ["registry/models.json", "definitions/models.json"],
];

mkdirSync(join(demo, "definitions"), { recursive: true });
for (const [src, dst] of DEFINITIONS) {
  copyFileSync(join(repo, src), join(demo, dst));
  console.log(`${src} -> demo/${dst}`);
}
