/**
 * Canonical registry of Christopher-AI HTTP endpoints (server mode).
 * Keep in sync with `build_server_app()` in ../../christopher.py
 */

export type HttpMethod = "GET" | "POST";

export interface EndpointDefinition {
  id: string;
  method: HttpMethod;
  path: string;
  description: string;
  expectedStatus: number;
  /** Optional JSON body for smoke tests (POST). */
  smokeTestBody?: Record<string, unknown>;
  validateResponse?: (body: unknown) => ValidationResult;
}

export interface ValidationResult {
  ok: boolean;
  detail?: string;
}

export interface EndpointRegistry {
  version: string;
  source: string;
  defaultPort: number;
  endpoints: EndpointDefinition[];
}

function validateHealthBody(body: unknown): ValidationResult {
  if (!body || typeof body !== "object") {
    return { ok: false, detail: "response must be a JSON object" };
  }
  const record = body as Record<string, unknown>;
  const status = record.status;
  if (status !== "ok" && status !== "degraded") {
    return { ok: false, detail: 'status must be "ok" or "degraded"' };
  }
  if (typeof record.llm !== "boolean") {
    return { ok: false, detail: "llm must be a boolean" };
  }
  return { ok: true };
}

function validateChatCompletionBody(body: unknown): ValidationResult {
  if (!body || typeof body !== "object") {
    return { ok: false, detail: "response must be a JSON object" };
  }
  const record = body as Record<string, unknown>;
  if (record.object !== "chat.completion") {
    return { ok: false, detail: 'object must be "chat.completion"' };
  }
  const choices = record.choices;
  if (!Array.isArray(choices) || choices.length === 0) {
    return { ok: false, detail: "choices must be a non-empty array" };
  }
  const first = choices[0] as Record<string, unknown>;
  const message = first?.message as Record<string, unknown> | undefined;
  if (!message || message.role !== "assistant" || typeof message.content !== "string") {
    return { ok: false, detail: "choices[0].message must be assistant with string content" };
  }
  return { ok: true };
}

/** Single source of truth for Christopher server-mode routes. */
export const CHRISTOPHER_ENDPOINTS: EndpointDefinition[] = [
  {
    id: "health",
    method: "GET",
    path: "/health",
    description:
      "Liveness probe; reports ok/degraded based on llama-server reachability.",
    expectedStatus: 200,
    validateResponse: validateHealthBody,
  },
  {
    id: "chat_completions",
    method: "POST",
    path: "/v1/chat/completions",
    description: "OpenAI-compatible chat completions (Christopher server mode).",
    expectedStatus: 200,
    smokeTestBody: {
      messages: [{ role: "user", content: "Reply with exactly: pong" }],
      max_tokens: 32,
    },
    validateResponse: validateChatCompletionBody,
  },
];

export function getRegistry(): EndpointRegistry {
  return {
    version: "1.0.0",
    source: "christopher.py :: build_server_app",
    defaultPort: 8090,
    endpoints: CHRISTOPHER_ENDPOINTS,
  };
}

export function listEndpoints(): Array<
  Pick<
    EndpointDefinition,
    "id" | "method" | "path" | "description" | "expectedStatus"
  >
> {
  return CHRISTOPHER_ENDPOINTS.map(
    ({ id, method, path, description, expectedStatus }) => ({
      id,
      method,
      path,
      description,
      expectedStatus,
    }),
  );
}

export function getEndpointById(id: string): EndpointDefinition | undefined {
  return CHRISTOPHER_ENDPOINTS.find((e) => e.id === id);
}
