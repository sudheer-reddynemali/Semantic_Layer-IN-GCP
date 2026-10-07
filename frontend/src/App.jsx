import { useState } from "react";
import ReactMarkdown from "react-markdown";
import Chart from "./Chart.jsx";
import { getSummary, getChart } from "./api.js";

export default function App() {
  const [mode, setMode] = useState("summary");
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      setResult(mode === "summary" ? await getSummary(question) : await getChart(question));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const tab = (m) =>
    `px-4 py-2 rounded-md text-sm font-medium ${
      mode === m ? "bg-blue-600 text-white" : "bg-white text-slate-700 border border-slate-200"
    }`;

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <div className="mx-auto max-w-4xl space-y-4 p-6">
        <h1 className="text-2xl font-bold">KPI Insights</h1>
        <div className="flex gap-2">
          <button className={tab("summary")} onClick={() => setMode("summary")}>Summary</button>
          <button className={tab("viz")} onClick={() => setMode("viz")}>Visualization</button>
        </div>
        <form onSubmit={submit} className="flex gap-2">
          <input
            className="flex-1 rounded-md border border-slate-300 px-3 py-2"
            placeholder={
              mode === "summary"
                ? "Summarise L1 KPIs for USA in 202508"
                : "Trend of tNPS actual vs plan by month"
            }
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
          <button
            disabled={loading}
            className="rounded-md bg-blue-600 px-4 py-2 text-white disabled:opacity-50"
          >
            {loading ? "Working..." : "Ask"}
          </button>
        </form>
        {error && <p className="rounded-md bg-red-50 p-3 text-red-700">{error}</p>}
        {result?.summary && (
          <div className="prose max-w-none rounded-lg border border-slate-200 bg-white p-4">
            <ReactMarkdown>{result.summary}</ReactMarkdown>
          </div>
        )}
        {result && "chart" in result && (
          <>
            {result.message && <p>{result.message}</p>}
            {result.chart ? <Chart spec={result.chart} /> : <p>No chart returned.</p>}
          </>
        )}
      </div>
    </div>
  );
}
