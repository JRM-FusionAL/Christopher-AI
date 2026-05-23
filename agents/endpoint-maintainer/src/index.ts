import { routeAgentRequest } from "agents";
import { ChristopherEndpointMaintainer } from "./agent";

export { ChristopherEndpointMaintainer };

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/" && request.method === "GET") {
      return Response.json({
        service: "christopher-endpoint-maintainer",
        agent: "ChristopherEndpointMaintainer",
        agentPath: "/agents/ChristopherEndpointMaintainer/default",
        christopherBaseUrl: env.CHRISTOPHER_BASE_URL,
        endpoints: ["/health", "/v1/chat/completions"],
      });
    }

    return (
      (await routeAgentRequest(request, env, { cors: true })) ??
      new Response("Not found", { status: 404 })
    );
  },
} satisfies ExportedHandler<Env>;
