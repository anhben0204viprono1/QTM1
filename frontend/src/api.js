const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

async function getJson(path) {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {}
    throw new Error(message);
  }
  return response.json();
}

export const api = {
  health: () => getJson("/api/health"),
  devices: () => getJson("/api/devices"),
  metrics: (limit = 100) => getJson(`/api/metrics?limit=${limit}`),
  interfaces: () => getJson("/api/interfaces"),
  alerts: (resolved = 0) => getJson(`/api/alerts?resolved=${resolved}&limit=100`)
};
