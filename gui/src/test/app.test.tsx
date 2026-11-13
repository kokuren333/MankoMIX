import { beforeEach, describe, expect, it } from "vitest";
import { act, renderHook, screen, waitFor, within } from "@testing-library/react";
import { App } from "../App";
import { ReportView, REPORT_SECTIONS } from "../screens/ReportScreen";
import { STRINGS } from "../i18n/strings";
import { classifyWidth, useBreakpoint } from "../hooks/useBreakpoint";
import type { Report } from "../types";
import { FakeEngine, FullCapsBackend, demoBackend, renderWithApp, setWidth } from "./helpers";

function go(route: string) {
  window.location.hash = `#/${route}`;
}

beforeEach(() => {
  setWidth(1280);
  go("listen");
});

describe("capabilities in mock mode", () => {
  it("shows the demo banner explaining what is unavailable", async () => {
    renderWithApp(<App />, { engineFactory: () => new FakeEngine() });
    const banner = await screen.findByTestId("mock-banner");
    const en = STRINGS.en;
    expect(banner.textContent).toContain(en["mock.cannot.upload"]);
    expect(banner.textContent).toContain(en["mock.cannot.dsp"]);
    expect(banner.textContent).toContain(en["mock.cannot.agent"]);
    expect(banner.textContent).toContain(en["mock.cannot.models"]);
    expect(banner.textContent).toContain("never sends data");
  });

  it("disables import, plan approval and undo with an explanation", async () => {
    go("project");
    const { unmount } = renderWithApp(<App />);
    const imp = (await screen.findByTestId("import-button")) as HTMLButtonElement;
    expect(imp.disabled).toBe(true);
    expect(imp.title).toBe(STRINGS.en["app.disabledInDemo"]);
    unmount();

    go("plan");
    const r2 = renderWithApp(<App />);
    const approve = (await screen.findAllByTestId("plan-approve")) as HTMLButtonElement[];
    expect(approve.length).toBeGreaterThan(0);
    expect(approve.every((b) => b.disabled)).toBe(true);
    expect((screen.getAllByTestId("plan-reject") as HTMLButtonElement[]).every((b) => b.disabled)).toBe(true);
    // Agent proposals explain that the agent link is needed.
    expect(screen.getByText(STRINGS.en["plan.agentNeedsLink"])).toBeTruthy();
    r2.unmount();

    go("history");
    renderWithApp(<App />);
    const undo = (await screen.findByTestId("undo")) as HTMLButtonElement;
    expect(undo.disabled).toBe(true);
  });

  it("enables the same actions with full local capabilities and hides the banner", async () => {
    go("project");
    renderWithApp(<App />, { backend: new FullCapsBackend() });
    const imp = (await screen.findByTestId("import-button")) as HTMLButtonElement;
    expect(imp.disabled).toBe(false);
    expect(screen.queryByTestId("mock-banner")).toBeNull();
  });
});

describe("Mix Report renderer", () => {
  it("shows all ten section headings (en and ja), even for a minimal report", async () => {
    const report = await demoBackend().getReport("v01", "en");
    const minimal: Report = { summary: { result: "incomplete" } };
    for (const [lang, r] of [
      ["en", report],
      ["ja", minimal],
    ] as const) {
      const { unmount } = renderWithApp(<ReportView report={r} reportLang={lang} onLang={() => {}} variantId="v01" />, { lang });
      await screen.findByText(STRINGS[lang]["report.s1"]);
      for (const s of REPORT_SECTIONS) expect(screen.getByRole("heading", { name: STRINGS[lang][s.heading] })).toBeTruthy();
      // Decisions are grouped by the six elements (when the report has decisions).
      if (r.decisions) for (const el of ["balance", "panning", "frequency", "depth", "dynamics", "interest"] as const) {
        expect(screen.getByRole("heading", { name: STRINGS[lang][`report.el.${el}`] })).toBeTruthy();
      }
      unmount();
    }
  });

  it("renders listening checks with time stamps", async () => {
    const report = await demoBackend().getReport("v01", "en");
    renderWithApp(<ReportView report={report} reportLang="en" onLang={() => {}} variantId="v01" />);
    const section = (await screen.findByText(STRINGS.en["report.s9"])).closest("section")!;
    expect(within(section).getByText("0:42")).toBeTruthy();
  });
});

describe("responsive layout", () => {
  it("classifies widths", () => {
    expect(classifyWidth(360)).toBe("narrow");
    expect(classifyWidth(719)).toBe("narrow");
    expect(classifyWidth(720)).toBe("medium");
    expect(classifyWidth(1100)).toBe("wide");
  });

  it("updates on resize", () => {
    setWidth(360);
    const { result } = renderHook(() => useBreakpoint());
    expect(result.current).toBe("narrow");
    act(() => setWidth(1400));
    expect(result.current).toBe("wide");
  });

  it("switches the app shell and the stem list to cards at 360 px", async () => {
    setWidth(360);
    go("stems");
    renderWithApp(<App />);
    const root = await screen.findByTestId("app-root");
    expect(root.className).toContain("layout-narrow");
    expect(await screen.findByTestId("stem-cards")).toBeTruthy();
    act(() => setWidth(1280));
    await waitFor(() => expect(root.className).toContain("layout-wide"));
    expect(await screen.findByTestId("stem-table")).toBeTruthy();
  });
});
