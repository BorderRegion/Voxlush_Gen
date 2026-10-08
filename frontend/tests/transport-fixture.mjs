// CI transport only. These counters are not model-quality or production-acceptance evidence.
import { createServer } from "node:http";
let state;
const streams = new Set();
function reset() {
  for (const stream of streams) stream.end();
  streams.clear();
  state = {
    event: 1,
    accepted: 2,
    offline: false,
    errors: false,
    emptyMetrics: false,
    command: null,
    commands: {},
    commandFailOnce: false,
    configRevision: 1,
    configuredCap: 8,
    commandPosts: [],
    requests: [],
    source: "<script>window.unsafeExecuted = true</script>",
    exports: null,
    campaign: "running",
    activeStreams: 0,
    maxStreams: 0,
  };
}
reset();
const campaign = () => ({
  campaign_id: "transport_fixture",
  name: "OFFLINE TRANSPORT FIXTURE",
  state: state.campaign,
  target: 100,
  accepted_unique: state.accepted,
  config_revision: state.configRevision,
  requests_used: 8,
  requests_limit: 800,
});
const overview = () => ({
  campaign_id: "transport_fixture",
  state: state.campaign,
  reason_code: "unqualified_model_profile",
  target: 100,
  accepted_unique: state.accepted,
  provisional_pass: 3,
  active_requests: 1,
  unknown_occupancy: 0,
  effective_cap: 2,
  configured_cap: state.configuredCap,
  requests_used: 8,
  requests_limit: 800,
  cost_known: null,
  cost_unknown: 2,
  reserved_cost: 0.2,
  accepted_per_hour: null,
  window_seconds: 120,
  queues: ["author", "build", "geometry", "render", "review", "archive"].map(
    (stage) => ({
      stage,
      ready: stage === "review" ? 3 : 0,
      running: stage === "author" ? 1 : 0,
      oldest_wait_seconds: stage === "review" ? 90 : 0,
    }),
  ),
  event_cursor: state.event,
  server_time: Date.now() / 1000,
  schema_version: "voxlush.overview.v1",
});
const sample = (i) => ({
  sample_id: `transport_fixture_${String(i).padStart(3, "0")}`,
  campaign_id: "transport_fixture",
  stage: i === 2 ? "review" : "archive",
  status: i === 2 ? "awaiting_review" : "accepted",
  reason_code: i === 2 ? "awaiting_visual" : "fixture",
  theme_seed_id: "island_s01",
  scene_type: "natural",
  revision: 1,
  updated_at: Date.parse("2026-10-06T12:00:00Z") / 1000,
  preview_artifact_id: null,
});
const send = (response, body, status = 200) => {
  response.writeHead(status, { "Content-Type": "application/json" });
  response.end(JSON.stringify(body));
};
const read = async (request) => {
  let text = "";
  for await (const part of request) text += part;
  return text ? JSON.parse(text) : {};
};
createServer(async (request, response) => {
  const url = new URL(request.url, "http://127.0.0.1");
  const path = url.pathname;
  if (path === "/__test/reset") {
    reset();
    return send(response, { ok: true });
  }
  if (path === "/__test/state")
    return send(response, { ...state, command: state.command });
  if (path === "/__test/change") {
    const changes = await read(request);
    Object.assign(state, changes);
    state.event++;
    if (state.offline) for (const stream of streams) stream.end();
    return send(response, { ok: true });
  }
  state.requests.push({ path, query: Object.fromEntries(url.searchParams) });
  if (path.endsWith("/health/live") || path.endsWith("/health/ready"))
    return send(response, { ready: true, fixture: true });
  if (state.offline && (path.endsWith("/overview") || path.endsWith("/events")))
    return send(
      response,
      { code: "fixture_offline", message: "测试连接暂时不可用" },
      503,
    );
  if (path.endsWith("/campaigns") && request.method === "GET")
    return send(response, { items: [campaign()] });
  if (path.endsWith("/campaigns"))
    return send(response, { campaign_id: (await read(request)).campaign_id });
  if (path.endsWith("/overview")) return send(response, overview());
  if (path.endsWith("/events")) {
    response.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    });
    streams.add(response);
    state.activeStreams++;
    state.maxStreams = Math.max(state.maxStreams, state.activeStreams);
    const snapshot = () =>
      response.write(
        `event: snapshot\nid: ${state.event}\ndata: ${JSON.stringify({ ...overview(), event_id: state.event })}\n\n`,
      );
    snapshot();
    const timer = setInterval(snapshot, 1000);
    response.on("close", () => {
      clearInterval(timer);
      if (streams.delete(response)) state.activeStreams--;
    });
    return;
  }
  if (path.endsWith("/samples")) {
    if (state.errors)
      return send(
        response,
        {
          code: "fixture_query_failure",
          message: "数据库读取测试错误",
          retryable: true,
          request_id: "fixture-error",
        },
        500,
      );
    const items = url.searchParams.get("cursor")
      ? [sample(25)]
      : Array.from(
          { length: Math.min(Number(url.searchParams.get("limit") ?? 24), 24) },
          (_, i) => sample(i + 1),
        );
    return send(response, {
      items,
      next_cursor: url.searchParams.get("cursor") ? null : "fixture_cursor",
    });
  }
  if (path.includes("/samples/"))
    return send(response, {
      ...sample(1),
      sample_id: path.split("/").pop(),
      task: {
        instruction: state.source,
        quality_contract: "landscape",
        requested_tags: { "spatial_relation": "水陆关系" },
        sampling_tags: { "landform": "群岛" },
        seed: 7,
        generation_mode: "direct",
      },
      artifacts: [
        { artifact_id: "source_fixture", name: "authored_source.py" },
        { artifact_id: "geometry_fixture", name: "geometry.json" },
      ],
      events: [
        {
          event_id: 1,
          kind: "archive",
          created_at: Date.parse("2026-10-06T12:00:00Z") / 1000,
          detail: "offline fixture",
        },
      ],
      attempts: [{ role: "review", known_cost: null, usage: null }],
    });
  if (path.endsWith("/metrics"))
    return send(response, {
      items: state.emptyMetrics
        ? []
        : [
            {
              minute: Date.parse("2026-10-06T12:01:00Z") / 1000,
              accepted: 0,
              requests: 4,
              active_requests: 1,
              effective_cap: 2,
            },
            {
              minute: Date.parse("2026-10-06T12:00:00Z") / 1000,
              accepted: 2,
              requests: 2,
              active_requests: 1,
              effective_cap: 2,
            },
          ],
    });
  if (path.endsWith("/coverage"))
    return send(response, {
      items: [
        {
          family_id: "islands",
          name: "群岛与水岸",
          scene_type: "natural",
          target: 25,
          accepted: 2,
          active: 3,
          rejected: 4,
          duplicate: 1,
          debt: 23,
          qualification: "unqualified",
          reason_code: "unqualified_model_profile",
        },
      ],
      totals: {
        target: 25,
        accepted: 2,
        active: 3,
        rejected: 4,
        duplicate: 1,
        debt: 23,
      },
    });
  if (path.endsWith("/config"))
    return send(response, {
      allow_live: false,
      campaign_defaults: { target: 100, request_limit: 800, api_cap: 8 },
    });
  if (path.endsWith("/config/validate"))
    return send(response, { valid: true, errors: [] });
  if (path.endsWith("/commands")) {
    const command = await read(request);
    state.commandPosts.push(command);
    if (!state.commands[command.command_id]) {
      const result = {
        command_id: command.command_id,
        campaign_id: command.campaign_id,
        action: command.action,
        status: "queued",
        reason: null,
      };
      state.commands[command.command_id] = result;
      state.command = result;
      setTimeout(() => {
        result.status = "applied";
        if (command.action === "set_cap") {
          state.configuredCap = command.payload.api_cap;
          state.configRevision++;
        } else
          state.campaign = command.action === "pause" ? "paused" : "running";
      }, 800);
    }
    if (state.commandFailOnce) {
      state.commandFailOnce = false;
      return response.destroy();
    }
    return send(response, state.commands[command.command_id]);
  }
  if (path.includes("/commands/"))
    return send(response, state.commands[path.split("/").pop()]);
  if (path.endsWith("/exports")) {
    state.exports = {
      export_id: (await read(request)).export_id,
      status: "queued",
    };
    setTimeout(() => {
      state.exports = {
        ...state.exports,
        status: "complete",
        result: {
          artifacts: [{ artifact_id: "release_fixture", name: "发布工件" }],
        },
      };
    }, 800);
    return send(response, state.exports);
  }
  if (path.includes("/exports/")) return send(response, state.exports);
  if (path.endsWith("/session")) {
    await read(request);
    response.setHeader(
      "Set-Cookie",
      "voxlush_session=offline_fixture; HttpOnly; SameSite=Strict; Path=/",
    );
    return send(response, { authenticated: true });
  }
  if (path.includes("/artifacts/")) {
    response.writeHead(200, {
      "Content-Type": "text/plain",
      "Content-Disposition": "attachment",
    });
    return response.end(state.source);
  }
  send(response, { code: "fixture_missing", message: path }, 404);
}).listen(8067, "127.0.0.1");
