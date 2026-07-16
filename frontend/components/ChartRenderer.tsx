"use client";

import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type Series = { key: string; name?: string };

type ChartSpec = {
  type: "bar" | "line";
  title?: string;
  xKey: string;
  series: Series[];
  data: Record<string, string | number>[];
};

// Fixed-order categorical slots (light/dark) — see dataviz skill palette.
const SERIES_COLORS_LIGHT = [
  "#2a78d6",
  "#1baf7a",
  "#eda100",
  "#008300",
  "#4a3aa7",
  "#e34948",
  "#e87ba4",
  "#eb6834",
];
const SERIES_COLORS_DARK = [
  "#3987e5",
  "#199e70",
  "#c98500",
  "#008300",
  "#9085e9",
  "#e66767",
  "#d55181",
  "#d95926",
];

function useIsDark(): boolean {
  const [isDark, setIsDark] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setIsDark(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return isDark;
}

export function parseChartSpec(raw: string): ChartSpec | null {
  try {
    const spec = JSON.parse(raw);
    if (
      spec &&
      (spec.type === "bar" || spec.type === "line") &&
      typeof spec.xKey === "string" &&
      Array.isArray(spec.series) &&
      Array.isArray(spec.data)
    ) {
      return spec as ChartSpec;
    }
  } catch {
    // not a valid chart spec — caller falls back to rendering as code
  }
  return null;
}

export default function ChartRenderer({ spec }: { spec: ChartSpec }) {
  const isDark = useIsDark();
  const colors = isDark ? SERIES_COLORS_DARK : SERIES_COLORS_LIGHT;
  const ink = isDark ? "#c3c2b7" : "#52514e";
  const grid = isDark ? "#2c2c2a" : "#e1e0d9";
  const surface = isDark ? "#1a1a19" : "#fcfcfb";
  const axis = isDark ? "#383835" : "#c3c2b7";

  const Chart = spec.type === "bar" ? BarChart : LineChart;

  return (
    <div
      style={{
        background: surface,
        border: `1px solid ${grid}`,
        borderRadius: 8,
        padding: "12px 8px 4px",
        margin: "8px 0",
      }}
    >
      {spec.title && (
        <div style={{ fontSize: 13, fontWeight: 600, color: isDark ? "#fff" : "#0b0b0b", padding: "0 8px 8px" }}>
          {spec.title}
        </div>
      )}
      <ResponsiveContainer width="100%" height={280}>
        <Chart data={spec.data} margin={{ top: 4, right: 12, left: 0, bottom: 4 }}>
          <CartesianGrid stroke={grid} strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey={spec.xKey}
            stroke={axis}
            tick={{ fill: ink, fontSize: 11 }}
            tickLine={false}
          />
          <YAxis stroke={axis} tick={{ fill: ink, fontSize: 11 }} tickLine={false} width={56} />
          <Tooltip
            contentStyle={{
              background: surface,
              border: `1px solid ${grid}`,
              borderRadius: 6,
              fontSize: 12,
              color: isDark ? "#fff" : "#0b0b0b",
            }}
          />
          {spec.series.length > 1 && (
            <Legend wrapperStyle={{ fontSize: 12, color: ink }} />
          )}
          {spec.series.map((s, i) =>
            spec.type === "bar" ? (
              <Bar
                key={s.key}
                dataKey={s.key}
                name={s.name || s.key}
                fill={colors[i % colors.length]}
                radius={[4, 4, 0, 0]}
              />
            ) : (
              <Line
                key={s.key}
                type="monotone"
                dataKey={s.key}
                name={s.name || s.key}
                stroke={colors[i % colors.length]}
                strokeWidth={2}
                dot={{ r: 3 }}
              />
            )
          )}
        </Chart>
      </ResponsiveContainer>
    </div>
  );
}
