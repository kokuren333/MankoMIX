import { defineConfig } from "vitest/config";

// Backend selection at build time:
//   VITE_BACKEND=mock|local (environment variable) wins,
//   otherwise `--mode demo` selects the in-browser mock (GitHub Pages build),
//   otherwise the local server backend is used.
// At run time `?backend=mock|local` in the page URL overrides both.
export default defineConfig(({ mode }) => {
  const backend = process.env.VITE_BACKEND ?? (mode === "demo" ? "mock" : "local");
  // Dev-server proxy target for `mankomix serve` (only used by `npm run dev`).
  const apiTarget = process.env.MANKOMIX_API ?? "http://127.0.0.1:8765";
  return {
    // Relative base so the static build works on GitHub Pages under any sub-path.
    base: "./",
    define: {
      "import.meta.env.VITE_BACKEND": JSON.stringify(backend),
    },
    esbuild: { jsx: "automatic" },
    server: {
      proxy: {
        "/api": { target: apiTarget, changeOrigin: false },
      },
    },
    build: {
      outDir: "dist",
      emptyOutDir: true,
      sourcemap: false,
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      include: ["src/**/*.test.{ts,tsx}"],
    },
  };
});
