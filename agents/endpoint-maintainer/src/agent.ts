import { Agent, type Connection } from "agents";
import {
  CHRISTOPHER_ENDPOINTS,
  getEndpointById,
  getRegistry as buildEndpointRegistry,
  listEndpoints as registryListEndpoints,
} from "./christopher-endpoints";
import { probeEndpoint, runAllProbes, type ProbeResult } from "./probes";

export interface MaintainerState {
  baseUrl: string;
  lastProbeAt: string | null;
  lastHealth: {
    ok: boolean;
    status?: string;
    llm?: boolean;
  } | null;
  recentProbes: ProbeResult[];
  alerts: Array<{
    id: string;
    at: string;
    endpointId: string;
    message: string;
  }>;
  dailySummaryAt: string | null;
}

export class ChristopherEndpointMaintainer extends Agent<Env, MaintainerState> {
  initialState: MaintainerState = {
    baseUrl: "http://127.0.0.1:8090",
    lastProbeAt: null,
    lastHealth: null,
    recentProbes: [],
    alerts: [],
    dailySummaryAt: null,
  };

  async onStart() {
    await this.initProbeHistoryTable();

    const baseUrl = this.env.CHRISTOPHER_BASE_URL ?? this.state.baseUrl;
    if (baseUrl !== this.state.baseUrl) {
      this.setState({ ...this.state, baseUrl });
    }

    // Health probes every 5 minutes (idempotent schedule)
    await this.schedule("*/5 * * * *", "runHealthProbes", {}, { idempotent: true });
    // Daily summary at 09:00 UTC
    await this.schedule("0 9 * * *", "runDailySummary", {}, { idempotent: true });

    // Run an initial probe on cold start
    await this.runHealthProbes();
  }

  private async initProbeHistoryTable() {
    await this.sql`
      CREATE TABLE IF NOT EXISTS probe_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        endpoint_id TEXT NOT NULL,
        ok INTEGER NOT NULL,
        status_code INTEGER NOT NULL,
        latency_ms INTEGER NOT NULL,
        error TEXT,
        detail TEXT,
        probed_at TEXT NOT NULL DEFAULT (datetime('now'))
      )
    `;
    await this.sql`
      CREATE INDEX IF NOT EXISTS idx_probe_history_probed_at
      ON probe_history (probed_at DESC)
    `;
  }

  private getBaseUrl(): string {
    return this.env.CHRISTOPHER_BASE_URL ?? this.state.baseUrl;
  }

  private async persistProbeResults(results: ProbeResult[]) {
    for (const r of results) {
      await this.sql`
        INSERT INTO probe_history (endpoint_id, ok, status_code, latency_ms, error, detail)
        VALUES (
          ${r.endpointId},
          ${r.ok ? 1 : 0},
          ${r.statusCode},
          ${r.latencyMs},
          ${r.error ?? null},
          ${r.detail ?? null}
        )
      `;
    }
  }

  private buildAlerts(results: ProbeResult[]): MaintainerState["alerts"] {
    const now = new Date().toISOString();
    const newAlerts = results
      .filter((r) => !r.ok)
      .map((r) => ({
        id: crypto.randomUUID(),
        at: now,
        endpointId: r.endpointId,
        message: r.detail ?? r.error ?? `Probe failed for ${r.path}`,
      }));

    const merged = [...newAlerts, ...this.state.alerts].slice(0, 50);
    return merged;
  }

  private extractHealthSnapshot(
    results: ProbeResult[],
  ): MaintainerState["lastHealth"] {
    const health = results.find((r) => r.endpointId === "health");
    if (!health?.ok) {
      return { ok: false };
    }
    return { ok: true };
  }

  async runHealthProbes() {
    const baseUrl = this.getBaseUrl();
    const results = await runAllProbes(baseUrl, CHRISTOPHER_ENDPOINTS);
    await this.persistProbeResults(results);

    // Enrich health snapshot from latest health probe response if possible
    let lastHealth = this.extractHealthSnapshot(results);
    const healthEndpoint = getEndpointById("health");
    if (healthEndpoint) {
      const healthProbe = await probeEndpoint(baseUrl, healthEndpoint);
      if (healthProbe.ok) {
        try {
          const res = await fetch(`${baseUrl.replace(/\/+$/, "")}/health`, {
            signal: AbortSignal.timeout(10_000),
          });
          const body = (await res.json()) as { status?: string; llm?: boolean };
          lastHealth = {
            ok: body.status === "ok",
            status: body.status,
            llm: body.llm,
          };
        } catch {
          // keep snapshot from probe result
        }
      }
    }

    const alerts = this.buildAlerts(results);
    this.setState({
      ...this.state,
      baseUrl,
      lastProbeAt: new Date().toISOString(),
      lastHealth,
      recentProbes: results,
      alerts,
    });

    if (alerts.length > 0 && this.env.AI) {
      await this.maybeSummarizeFailures(alerts.slice(0, 3));
    }

    return { baseUrl, results, lastHealth };
  }

  async runDailySummary() {
    const rows = await this.sql<{ endpoint_id: string; ok: number; cnt: number }>`
      SELECT endpoint_id, ok, COUNT(*) as cnt
      FROM probe_history
      WHERE probed_at >= datetime('now', '-1 day')
      GROUP BY endpoint_id, ok
    `;

    this.setState({
      ...this.state,
      dailySummaryAt: new Date().toISOString(),
    });

    this.broadcast(
      JSON.stringify({
        type: "daily_summary",
        at: this.state.dailySummaryAt,
        stats: rows,
        baseUrl: this.getBaseUrl(),
      }),
    );

    return { stats: rows };
  }

  private async maybeSummarizeFailures(
    alerts: MaintainerState["alerts"],
  ) {
    try {
      const prompt = `Summarize these Christopher-AI endpoint failures for an on-call engineer (2-3 sentences):\n${JSON.stringify(alerts)}`;
      const response = await this.env.AI!.run("@cf/meta/llama-3.1-8b-instruct", {
        messages: [{ role: "user", content: prompt }],
        max_tokens: 200,
      });
      const text =
        typeof response === "object" && response && "response" in response
          ? String((response as { response: string }).response)
          : JSON.stringify(response);

      this.broadcast(
        JSON.stringify({
          type: "failure_summary",
          summary: text,
          alerts,
        }),
      );
    } catch (err) {
      console.error("AI failure summary skipped:", err);
    }
  }

  async checkHealth(): Promise<ProbeResult> {
    const endpoint = getEndpointById("health");
    if (!endpoint) {
      throw new Error("health endpoint not in registry");
    }
    const result = await probeEndpoint(this.getBaseUrl(), endpoint);
    await this.persistProbeResults([result]);
    return result;
  }

  async smokeTestChat(): Promise<ProbeResult> {
    const endpoint = getEndpointById("chat_completions");
    if (!endpoint) {
      throw new Error("chat_completions endpoint not in registry");
    }
    const result = await probeEndpoint(this.getBaseUrl(), endpoint, {
      timeoutMs: 120_000,
    });
    await this.persistProbeResults([result]);
    return result;
  }

  async getProbeHistory(limit = 20) {
    const capped = Math.min(Math.max(limit, 1), 100);
    return this.sql`
      SELECT endpoint_id, ok, status_code, latency_ms, error, detail, probed_at
      FROM probe_history
      ORDER BY probed_at DESC
      LIMIT ${capped}
    `;
  }

  async onMessage(connection: Connection, message: string) {
    let data: { type?: string; limit?: number };
    try {
      data = JSON.parse(message) as { type?: string; limit?: number };
    } catch {
      connection.send(JSON.stringify({ type: "error", message: "invalid JSON" }));
      return;
    }

    try {
      switch (data.type) {
        case "getRegistry":
          connection.send(
            JSON.stringify({
              type: "registry",
              payload: buildEndpointRegistry(),
            }),
          );
          break;
        case "listEndpoints":
          connection.send(
            JSON.stringify({
              type: "endpoints",
              payload: registryListEndpoints(),
            }),
          );
          break;
        case "checkHealth":
          connection.send(
            JSON.stringify({
              type: "probe",
              payload: await this.checkHealth(),
            }),
          );
          break;
        case "smokeTestChat":
          connection.send(
            JSON.stringify({
              type: "probe",
              payload: await this.smokeTestChat(),
            }),
          );
          break;
        case "runProbes":
          connection.send(
            JSON.stringify({
              type: "probes",
              payload: await this.runHealthProbes(),
            }),
          );
          break;
        case "getState":
          connection.send(
            JSON.stringify({ type: "state", payload: this.state }),
          );
          break;
        case "getProbeHistory":
          connection.send(
            JSON.stringify({
              type: "history",
              payload: await this.getProbeHistory(data.limit ?? 20),
            }),
          );
          break;
        default:
          connection.send(
            JSON.stringify({
              type: "error",
              message: `Unknown message type: ${data.type}`,
            }),
          );
      }
    } catch (err) {
      connection.send(
        JSON.stringify({
          type: "error",
          message: err instanceof Error ? err.message : String(err),
        }),
      );
    }
  }

  async onConnect(connection: Connection) {
    connection.send(
      JSON.stringify({
        type: "welcome",
        role: "Christopher-AI endpoint maintainer",
        baseUrl: this.getBaseUrl(),
        state: this.state,
        registry: buildEndpointRegistry(),
      }),
    );
  }
}
