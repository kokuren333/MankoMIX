// Theme "Circuit White / Solder Mask" and the shared icon set (D-067).
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { ICONS } from "../components/Icon";
import { GUI_ROOT, REPO_ROOT } from "./helpers";

const SRC = join(GUI_ROOT, "src");
const TOKENS = readFileSync(join(SRC, "theme", "tokens.css"), "utf8");
const STYLES = readFileSync(join(SRC, "styles.css"), "utf8");
const ICON_DIR = join(GUI_ROOT, "public", "icons");
const RAW_COLOUR = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/;

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? (e.name === "test" ? [] : sourceFiles(join(dir, e.name))) : /\.(tsx?|css)$/.test(e.name) ? [join(dir, e.name)] : [],
  );
}

describe("theme tokens", () => {
  it("defines the family base tokens with the canonical values", () => {
    const base: Record<string, string> = {
      "--cs-board": "#EEF6F8",
      "--cs-panel": "#FFFFFF",
      "--cs-pad": "#EAF6F9",
      "--cs-trace": "#19C3E6",
      "--cs-trace-deep": "#0A86A8",
      "--cs-ink": "#0B2A3A",
      "--cs-warn": "#E8A317",
      "--cs-error": "#E5484D",
      "--cs-agent": "#7C5CFF",
    };
    for (const [k, v] of Object.entries(base)) expect(TOKENS).toContain(`${k}: ${v};`);
  });

  it("keeps the verbatim block identical to CyberSprite when the sibling checkout is present", () => {
    const sibling = join(REPO_ROOT, "..", "CyberSprite", "gui", "src", "theme", "tokens.css");
    if (!existsSync(sibling)) return;
    const begin = "/* ===== BEGIN verbatim: CyberSprite gui/src/theme/tokens.css ===== */\n";
    const block = TOKENS.slice(TOKENS.indexOf(begin) + begin.length, TOKENS.indexOf("/* ===== END verbatim"));
    expect(block).toBe(readFileSync(sibling, "utf8").replace(/\r\n/g, "\n"));
  });

  it("maps every MankoMIX role token to a base or family role token and documents it", () => {
    const decls = [...TOKENS.matchAll(/^\s*(--mm-[a-z0-9-]+):\s*([^;]+);/gm)];
    expect(decls.length).toBeGreaterThan(10);
    for (const [, name, value] of decls) {
      expect(value, name).toMatch(/^var\(--(cs|ui)-[a-z0-9-]+\)$/);
      expect(TOKENS.split(name).length, `${name} is not listed in the comment block`).toBeGreaterThanOrEqual(3);
    }
  });

  it("uses no raw colours outside tokens.css, and only defined tokens", () => {
    for (const f of sourceFiles(SRC).filter((p) => !p.endsWith("tokens.css"))) {
      const text = readFileSync(f, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
      expect(RAW_COLOUR.test(text), `${f} contains a raw colour`).toBe(false);
    }
    const used = new Set([...STYLES.matchAll(/var\((--[a-z0-9-]+)\)/g)].map((m) => m[1]));
    for (const v of used) expect(TOKENS, `${v} is not defined in tokens.css`).toContain(`${v}:`);
  });
});

describe("icon set", () => {
  const manifest = JSON.parse(readFileSync(join(ICON_DIR, "manifest.json"), "utf8")) as {
    icons: { name: string; file: string; origin: string; source_project?: string; license: string }[];
  };

  it("has a file and a provenance entry for every icon the GUI uses", () => {
    const byName = new Map(manifest.icons.map((e) => [e.name, e]));
    for (const name of ICONS) {
      expect(existsSync(join(ICON_DIR, `${name}.png`)), name).toBe(true);
      const e = byName.get(name);
      expect(e, name).toBeTruthy();
      expect(e!.license).toBe("Apache-2.0");
      if (e!.origin === "reused") expect(e!.source_project).toBe("CyberSprite");
    }
    expect(manifest.icons.map((e) => e.name).sort()).toEqual([...ICONS].sort());
  });

  it("records no absolute path in the manifest", () => {
    const text = readFileSync(join(ICON_DIR, "manifest.json"), "utf8");
    expect(/[A-Za-z]:[\\/]|\/Users\/|\/home\//.test(text)).toBe(false);
  });
});
