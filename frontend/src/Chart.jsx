import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";

const COLORS = ["#2563eb", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6"];

export default function Chart({ spec }) {
  const { type, title, xKey, series = [], data = [] } = spec;
  const Plot = type === "line" ? LineChart : BarChart;
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <h3 className="mb-2 font-semibold">{title}</h3>
      <ResponsiveContainer width="100%" height={340}>
        <Plot data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey={xKey} />
          <YAxis />
          <Tooltip />
          <Legend />
          {series.map((s, i) =>
            type === "line" ? (
              <Line key={s.key} dataKey={s.key} name={s.label} stroke={COLORS[i % 5]} />
            ) : (
              <Bar key={s.key} dataKey={s.key} name={s.label} fill={COLORS[i % 5]} />
            )
          )}
        </Plot>
      </ResponsiveContainer>
    </div>
  );
}
