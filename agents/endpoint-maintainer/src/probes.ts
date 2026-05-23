import type { EndpointDefinition } from "./christopher-endpoints";

export interface ProbeResult {
  endpointId: string;
  method: string;
  path: string;
  ok: boolean;
  statusCode: number;
  latencyMs: number;
  error?: string;
  detail?: string;
  responseSnippet?: string;
}

const DEFAULT_TIMEOUT_MS = 30_000;

export function resolveBaseUrl(baseUrl: string): string {
  return baseUrl.replace(/\/+$/, "");
}

export async function probeEndpoint(
  baseUrl: string,
  endpoint: EndpointDefinition,
  options?: { timeoutMs?: number },
): Promise<ProbeResult> {
  const started = Date.now();
  const url = `${resolveBaseUrl(baseUrl)}${endpoint.path}`;
  const timeoutMs = options?.timeoutMs ?? DEFAULT_TIMEOUT_MS;

  const init: RequestInit = {
    method: endpoint.method,
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(timeoutMs),
  };

  if (endpoint.method === "POST") {
    init.headers = {
      ...init.headers,
      "Content-Type": "application/json",
    };
    init.body = JSON.stringify(
      endpoint.smokeTestBody ?? {
        messages: [{ role: "user", content: "ping" }],
      },
    );
  }

  try {
    const response = await fetch(url, init);
    const latencyMs = Date.now() - started;
    const text = await response.text();
    let body: unknown = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      return {
        endpointId: endpoint.id,
        method: endpoint.method,
        path: endpoint.path,
        ok: false,
        statusCode: response.status,
        latencyMs,
        error: "invalid_json",
        detail: "Response body is not valid JSON",
        responseSnippet: text.slice(0, 200),
      };
    }

    if (response.status !== endpoint.expectedStatus) {
      return {
        endpointId: endpoint.id,
        method: endpoint.method,
        path: endpoint.path,
        ok: false,
        statusCode: response.status,
        latencyMs,
        error: "unexpected_status",
        detail: `Expected HTTP ${endpoint.expectedStatus}, got ${response.status}`,
        responseSnippet: text.slice(0, 200),
      };
    }

    if (endpoint.validateResponse) {
      const validation = endpoint.validateResponse(body);
      if (!validation.ok) {
        return {
          endpointId: endpoint.id,
          method: endpoint.method,
          path: endpoint.path,
          ok: false,
          statusCode: response.status,
          latencyMs,
          error: "validation_failed",
          detail: validation.detail,
          responseSnippet: text.slice(0, 200),
        };
      }
    }

    return {
      endpointId: endpoint.id,
      method: endpoint.method,
      path: endpoint.path,
      ok: true,
      statusCode: response.status,
      latencyMs,
    };
  } catch (err) {
    return {
      endpointId: endpoint.id,
      method: endpoint.method,
      path: endpoint.path,
      ok: false,
      statusCode: 0,
      latencyMs: Date.now() - started,
      error: "fetch_failed",
      detail: err instanceof Error ? err.message : String(err),
    };
  }
}

export async function runAllProbes(
  baseUrl: string,
  endpoints: EndpointDefinition[],
): Promise<ProbeResult[]> {
  const results: ProbeResult[] = [];
  for (const endpoint of endpoints) {
    results.push(await probeEndpoint(baseUrl, endpoint));
  }
  return results;
}
