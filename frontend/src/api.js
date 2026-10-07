const API = import.meta.env.VITE_API_URL ?? "";

async function post(path, question) {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
}

export const getSummary = (q) => post("/api/summary", q);
export const getChart = (q) => post("/api/visualize", q);
