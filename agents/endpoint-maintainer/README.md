# Christopher Endpoint Maintainer

Cloudflare **Agents SDK** worker that monitors and smoke-tests the HTTP API exposed by Christopher-AI in server mode (`python christopher.py --server`).

## Christopher endpoints (registry)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Liveness; `status` is `ok` or `degraded`, `llm` reflects llama-server reachability |
| `POST` | `/v1/chat/completions` | OpenAI-compatible chat (default server port **8090**) |

The canonical registry lives in [`src/christopher-endpoints.ts`](src/christopher-endpoints.ts) and should stay aligned with `build_server_app()` in [`../../christopher.py`](../../christopher.py).

## What this agent does

- **Scheduled probes** every 5 minutes (`runHealthProbes`)
- **Daily summary** broadcast at 09:00 UTC (`runDailySummary`)
- **SQL audit log** of probe results (`probe_history` table)
- **Stateful dashboard** via `setState` (last health, recent probes, alerts)
- **WebSocket tools** (message `type`): `getRegistry`, `listEndpoints`, `checkHealth`, `smokeTestChat`, `runProbes`, `getState`, `getProbeHistory`
- Optional **Workers AI** summaries when probes fail (requires `AI` binding)

## Prerequisites

1. Christopher running in server mode:

   ```bash
   cd ../..
   python christopher.py --server --server-port 8090
   ```

2. Node.js 18+ and npm

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `CHRISTOPHER_BASE_URL` | `http://127.0.0.1:8090` | Base URL for Christopher HTTP API (wrangler `vars`) |

### Local development

`wrangler dev` can reach `http://127.0.0.1:8090` on your machine when Christopher is listening locally.

### Deployed worker + remote Christopher

Cloudflare Workers **cannot** call `127.0.0.1` on your PC. Use an SSH tunnel or Cloudflare Tunnel and set `CHRISTOPHER_BASE_URL` to the public/tunneled URL (same pattern as [`check-stack-status.ps1`](../../check-stack-status.ps1) tunnel ports).

Example after tunneling Christopher to local port 18089:

```jsonc
"vars": {
  "CHRISTOPHER_BASE_URL": "https://your-tunnel.example.com"
}
```

Or override per deploy:

```bash
npx wrangler deploy --var CHRISTOPHER_BASE_URL:https://christopher.example.com
```

## Commands

```bash
cd agents/endpoint-maintainer
npm install
npm run dev          # http://localhost:8787
npm run cf-typegen   # refresh worker-configuration.d.ts
npm run check        # wrangler check + tsc
npm test
npm run deploy
```

## Connect to the agent

- **HTTP meta**: `GET http://localhost:8787/`
- **WebSocket**: `ws://localhost:8787/agents/ChristopherEndpointMaintainer/default`

Example message:

```json
{ "type": "runProbes" }
```

## Related stack

- Christopher server: port **8090** (`--server-port`)
- llama-server: port **8080** (`LLAMA_SERVER_URL`)
- FusionAL MCP health checks: see `check-stack-status.ps1`
