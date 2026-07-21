import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ChartRenderer, { parseChartSpec } from "../ChartRenderer";

vi.mock("../ThemeProvider", () => ({
  useTheme: () => ({ resolvedTheme: "light" }),
}));

describe("parseChartSpec", () => {
  it("parses a valid bar spec", () => {
    const raw = JSON.stringify({
      type: "bar",
      xKey: "month",
      series: [{ key: "amt" }],
      data: [{ month: "1월", amt: 100 }],
    });
    const spec = parseChartSpec(raw);
    expect(spec).not.toBeNull();
    expect(spec?.type).toBe("bar");
  });

  it("parses a valid line spec", () => {
    const raw = JSON.stringify({
      type: "line",
      xKey: "month",
      series: [{ key: "amt" }],
      data: [],
    });
    const spec = parseChartSpec(raw);
    expect(spec?.type).toBe("line");
  });

  it("returns null when type is not bar/line", () => {
    const raw = JSON.stringify({ type: "pie", xKey: "x", series: [], data: [] });
    expect(parseChartSpec(raw)).toBeNull();
  });

  it("returns null when xKey is not a string", () => {
    const raw = JSON.stringify({ type: "bar", xKey: 1, series: [], data: [] });
    expect(parseChartSpec(raw)).toBeNull();
  });

  it("returns null when series is not an array", () => {
    const raw = JSON.stringify({ type: "bar", xKey: "x", series: "nope", data: [] });
    expect(parseChartSpec(raw)).toBeNull();
  });

  it("returns null when data is not an array", () => {
    const raw = JSON.stringify({ type: "bar", xKey: "x", series: [], data: "nope" });
    expect(parseChartSpec(raw)).toBeNull();
  });

  it("returns null (not throws) on invalid JSON", () => {
    expect(() => parseChartSpec("{not valid json")).not.toThrow();
    expect(parseChartSpec("{not valid json")).toBeNull();
  });

  it("parses successfully even with extra unknown fields", () => {
    const raw = JSON.stringify({
      type: "bar",
      xKey: "x",
      series: [{ key: "y" }],
      data: [],
      extra: "unused",
    });
    expect(parseChartSpec(raw)).not.toBeNull();
  });
});

describe("ChartRenderer", () => {
  const baseSpec = {
    type: "bar" as const,
    xKey: "month",
    series: [{ key: "amt", name: "금액" }],
    data: [{ month: "1월", amt: 100 }],
  };

  it("renders a title when provided", () => {
    const { getByText } = render(<ChartRenderer spec={{ ...baseSpec, title: "월별 매출" }} />);
    expect(getByText("월별 매출")).toBeInTheDocument();
  });

  it("does not render a title block when title is absent", () => {
    const { queryByText } = render(<ChartRenderer spec={baseSpec} />);
    expect(queryByText("월별 매출")).not.toBeInTheDocument();
  });

  it("renders bar chart svg elements for type bar", () => {
    const { container } = render(<ChartRenderer spec={baseSpec} />);
    expect(container.querySelectorAll(".recharts-bar").length).toBeGreaterThan(0);
  });

  it("renders line chart svg elements for type line", () => {
    const spec = { ...baseSpec, type: "line" as const };
    const { container } = render(<ChartRenderer spec={spec} />);
    expect(container.querySelectorAll(".recharts-line").length).toBeGreaterThan(0);
  });

  it("does not render legend when only one series is present", () => {
    const { container } = render(<ChartRenderer spec={baseSpec} />);
    expect(container.querySelectorAll(".recharts-legend-wrapper").length).toBe(0);
  });

  it("renders legend when multiple series are present", () => {
    const spec = {
      ...baseSpec,
      series: [
        { key: "amt", name: "금액" },
        { key: "qty", name: "수량" },
      ],
      data: [{ month: "1월", amt: 100, qty: 5 }],
    };
    const { container } = render(<ChartRenderer spec={spec} />);
    expect(container.querySelectorAll(".recharts-legend-wrapper").length).toBe(1);
  });

  it("cycles through the fixed 8-color palette when series exceed available colors", () => {
    const manySeries = Array.from({ length: 9 }, (_, i) => ({ key: `s${i}` }));
    const dataRow: Record<string, string | number> = { month: "1월" };
    manySeries.forEach((s, i) => {
      dataRow[s.key] = i + 1;
    });
    const spec = { ...baseSpec, series: manySeries, data: [dataRow] };
    const { container } = render(<ChartRenderer spec={spec} />);

    const legendIcons = container.querySelectorAll(".recharts-legend-icon");
    expect(legendIcons.length).toBe(9);
    // 9번째(index 8) 시리즈는 팔레트가 8색이라 첫번째 색으로 순환되어야 한다.
    expect(legendIcons[8].getAttribute("fill")).toBe(legendIcons[0].getAttribute("fill"));
    expect(legendIcons[7].getAttribute("fill")).not.toBe(legendIcons[0].getAttribute("fill"));
  });
});
