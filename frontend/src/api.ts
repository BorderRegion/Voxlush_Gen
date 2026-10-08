import { useCallback, useEffect, useRef, useState } from "react";
import type { Overview } from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code: string,
    public requestId?: string,
  ) {
    super(message);
  }
}
export const artifactUrl = (id: string) =>
  `/api/v1/artifacts/${encodeURIComponent(id)}`;
export const query = (values: Record<string, string | number | undefined>) => {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== "") params.set(key, String(value));
  });
  return params.toString();
};
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    credentials: "same-origin",
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const error = data.error ?? data.detail ?? data;
    throw new ApiError(
      typeof error === "string"
        ? error
        : typeof error.message === "string"
          ? error.message
          : Array.isArray(error)
            ? error
                .map(
                  (item) =>
                    `${item.loc?.join(".") ?? "参数"}：${item.msg ?? "格式无效"}`,
                )
                .join("；")
            : `请求失败（HTTP ${response.status}）`,
      response.status,
      error.code ?? "http_error",
      error.request_id,
    );
  }
  return response.json() as Promise<T>;
}
export const post = <T>(path: string, body: unknown) =>
  api<T>(path, { method: "POST", body: JSON.stringify(body) });

export function useApi<T>(path: string | null, refreshKey = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(false);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    setData(null);
    setError(null);
  }, [path]);
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    setLoading(true);
    api<T>(path, { signal: controller.signal })
      .then((result) => {
        if (controller.signal.aborted) return;
        setData(result);
        setError(null);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, refreshKey, reload]);
  return {
    data,
    error,
    loading,
    refresh: useCallback(() => setReload((n) => n + 1), []),
  };
}

type Connection = "connecting" | "live" | "reconnecting" | "stale";
export function useOverview(campaignId: string | null, refreshKey: number) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [receivedAt, setReceivedAt] = useState<number | null>(null);
  const [now, setNow] = useState(Date.now());
  const cursor = useRef(0);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    setOverview(null);
    setError(null);
    setReceivedAt(null);
    cursor.current = 0;
    if (!campaignId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const accept = (value: Overview) => {
      if (
        controller.signal.aborted ||
        !value ||
        value.campaign_id !== campaignId ||
        !Array.isArray(value.queues)
      )
        return;
      setOverview(value);
      cursor.current = value.event_cursor ?? cursor.current;
      setReceivedAt(Date.now());
      setError(null);
      setConnection("live");
    };
    const delay = (ms: number) =>
      new Promise<void>((resolve) => {
        timer = setTimeout(resolve, ms);
        controller.signal.addEventListener(
          "abort",
          () => {
            clearTimeout(timer);
            resolve();
          },
          { once: true },
        );
      });
    async function connect() {
      let backoff = 500;
      while (!controller.signal.aborted) {
        try {
          setConnection(cursor.current ? "reconnecting" : "connecting");
          const snapshot = await api<Overview>(
            `/overview?${query({ campaign_id: campaignId! })}`,
            { signal: controller.signal },
          );
          accept(snapshot);
          const response = await fetch(
            `/api/v1/events?${query({ campaign_id: campaignId!, after: cursor.current })}`,
            {
              credentials: "same-origin",
              signal: controller.signal,
              headers: { Accept: "text/event-stream" },
            },
          );
          if (!response.ok || !response.body)
            throw new ApiError(
              `实时连接失败（HTTP ${response.status}）`,
              response.status,
              "sse_error",
            );
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";
          try {
            while (!controller.signal.aborted) {
              const part = await reader.read();
              if (part.done) throw new Error("实时连接已断开");
              buffer += decoder
                .decode(part.value, { stream: true })
                .replace(/\r\n/g, "\n");
              if (buffer.length > 1024 * 1024)
                throw new Error("实时事件超过大小限制");
              let boundary: number;
              while ((boundary = buffer.indexOf("\n\n")) >= 0) {
                const block = buffer.slice(0, boundary);
                buffer = buffer.slice(boundary + 2);
                const lines = block.split("\n");
                const kind =
                  lines
                    .find((line) => line.startsWith("event:"))
                    ?.slice(6)
                    .trim() ?? "message";
                const raw = lines
                  .filter((line) => line.startsWith("data:"))
                  .map((line) => line.slice(5).trimStart())
                  .join("\n");
                if (!raw || !["snapshot", "reset", "message"].includes(kind))
                  continue;
                const value = JSON.parse(raw);
                const next = value.payload ?? value;
                accept(next);
                if (Number.isFinite(Number(value.event_id)))
                  cursor.current = Number(value.event_id);
                backoff = 500;
              }
            }
          } finally {
            await reader.cancel().catch(() => undefined);
          }
        } catch (e) {
          if (controller.signal.aborted) return;
          setError(e instanceof Error ? e : new Error(String(e)));
          setConnection("reconnecting");
          await delay(backoff);
          backoff = Math.min(15000, backoff * 2);
        }
      }
    }
    void connect();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [campaignId, refreshKey]);
  const age =
    receivedAt === null ? null : Math.max(0, (now - receivedAt) / 1000);
  return {
    overview,
    error,
    age,
    connection:
      connection === "live" && (age ?? 0) > 15
        ? ("stale" as Connection)
        : connection,
  };
}
