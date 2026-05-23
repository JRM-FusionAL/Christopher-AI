// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  CHRISTOPHER_ENDPOINTS,
  getEndpointById,
  getRegistry,
  listEndpoints,
} from "../src/christopher-endpoints";

describe("christopher-endpoints registry", () => {
  it("includes health and chat completions", () => {
    const ids = CHRISTOPHER_ENDPOINTS.map((e) => e.id);
    expect(ids).toContain("health");
    expect(ids).toContain("chat_completions");
  });

  it("getRegistry matches endpoint count", () => {
    const registry = getRegistry();
    expect(registry.endpoints).toHaveLength(2);
    expect(registry.defaultPort).toBe(8090);
  });

  it("listEndpoints returns summary fields only", () => {
    const listed = listEndpoints();
    expect(listed[0]).toHaveProperty("path");
    expect(listed[0]).not.toHaveProperty("validateResponse");
  });

  it("validates health response shape", () => {
    const health = getEndpointById("health");
    expect(health?.validateResponse?.({ status: "ok", llm: true }).ok).toBe(
      true,
    );
    expect(
      health?.validateResponse?.({ status: "broken", llm: true }).ok,
    ).toBe(false);
  });
});
