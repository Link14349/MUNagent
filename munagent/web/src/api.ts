export interface ScenarioSummary {
  id: string;
  title: string;
  author: string;
  version: string;
  source: "builtin" | "user";
  readonly: boolean;
}

export interface ScenarioDetail extends ScenarioSummary {
  manifest: Record<string, unknown>;
  files: Record<string, string>;
}

export interface ConfigPublic {
  providers: Record<
    string,
    { base_url: string; api_key_masked: string; has_key: boolean }
  >;
  roles: Record<string, { provider: string; model: string }>;
  tools: {
    mineru: { base_url: string };
    search: { provider: string; api_key_masked: string; has_key: boolean };
  };
  engine: Record<string, unknown>;
  server: { host: string; port: number; debug_dump_prompts: boolean };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listScenarios: () => request<ScenarioSummary[]>("/api/scenarios"),
  getScenario: (id: string) => request<ScenarioDetail>(`/api/scenarios/${id}`),
  createScenario: (body: { id: string; title: string }) =>
    request<ScenarioDetail>("/api/scenarios", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteScenario: (id: string) =>
    request<{ status: string }>(`/api/scenarios/${id}`, { method: "DELETE" }),
  getConfig: () => request<ConfigPublic>("/api/config"),
  putConfig: (body: unknown) =>
    request<ConfigPublic>("/api/config", { method: "PUT", body: JSON.stringify(body) }),
  testConfig: (target: string) =>
    request<{ ok: boolean; message: string }>("/api/config/test", {
      method: "POST",
      body: JSON.stringify({ target }),
    }),
};
