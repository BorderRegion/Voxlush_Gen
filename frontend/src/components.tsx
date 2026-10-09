import { useEffect, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";
import { api, ApiError, artifactUrl, post, useApi } from "./api";
import type {
  Campaign,
  Command,
  CommandAction,
  CommandInput,
  Metric,
  Sample,
  SampleDetail,
} from "./types";

// Keep uncertain commands across page switches until the server confirms a terminal result.
const uncertainCommands = new Map<string, CommandInput>();

export function useDialogFocus(
  dialog: RefObject<HTMLElement | null>,
  close: () => void,
  active = true,
) {
  useEffect(() => {
    if (!active) return;
    const original = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialog.current?.focus();
    const listener = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        dialog.current?.querySelectorAll<HTMLElement>(
          "button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),summary",
        ) ?? [],
      ).filter((element) => element.getClientRects().length > 0);
      if (!focusable.length) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (
        event.shiftKey &&
        (document.activeElement === first ||
          document.activeElement === dialog.current)
      ) {
        event.preventDefault();
        last.focus();
      } else if (
        !event.shiftKey &&
        (document.activeElement === last ||
          document.activeElement === dialog.current)
      ) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", listener);
    return () => {
      document.body.style.overflow = overflow;
      document.removeEventListener("keydown", listener);
      original?.focus();
    };
  }, [dialog, close, active]);
}

const labels: Record<string, string> = {
  pure_target: "纯目标建筑",
  light_context: "轻上下文",
  contextual: "标准上下文",
  environment_rich: "环境丰富",
  calibration_target_reached: "候选校准目标已达到",
  composition_context_voxels: "环境体素过多",
  composition_context_extent: "环境占地过广",
  composition_subject_missing: "缺少建筑主体",
  idle: "未启动",
  running: "运行中",
  draining: "排空中",
  paused: "已暂停",
  degraded: "降级运行",
  blocked: "受阻",
  completed: "已完成",
  ready: "排队",
  deferred: "延后",
  awaiting_review: "待审核",
  accepted: "已合格",
  rejected: "未通过",
  cancelled: "已取消",
  provisional_pass: "暂定通过",
  awaiting_visual: "等待视觉审核",
  unqualified_model_profile: "模型配置未获资格",
  budget_exhausted: "预算已耗尽",
  live_disabled: "付费推理未启用",
  duplicate: "重复几何",
  fixture: "离线样例",
  brief: "任务",
  author: "作者",
  refine: "精细化",
  build: "构建",
  geometry: "几何",
  render: "渲染",
  review: "视觉审核",
  archive: "归档",
  architecture: "建筑",
  natural: "自然",
  hybrid: "复合",
  qualified: "已获资格",
  unqualified: "未获资格",
  start: "启动",
  resume: "恢复",
  drain: "排空",
  pause: "暂停",
  set_cap: "更新并发上限",
  emergency_stop: "紧急停止",
  queued: "等待执行",
  complete: "已完成",
  failed: "失败",
};
export const label = (value: string | null | undefined) =>
  value ? (labels[value] ?? value) : "—";
export const number = (value: number | null | undefined, digits = 0) =>
  value === null || value === undefined || !Number.isFinite(value)
    ? "—"
    : new Intl.NumberFormat("zh-CN", { maximumFractionDigits: digits }).format(
        value,
      );
export const duration = (seconds: number | null | undefined) =>
  seconds === null || seconds === undefined
    ? "—"
    : seconds < 60
      ? `${number(seconds)} 秒`
      : seconds < 3600
        ? `${number(seconds / 60, 1)} 分`
        : `${number(seconds / 3600, 1)} 小时`;
export const dateValue = (value: unknown): Date | null => {
  const date =
    typeof value === "number"
      ? new Date(value * 1000)
      : typeof value === "string"
        ? new Date(value)
        : null;
  return date && Number.isFinite(date.getTime()) ? date : null;
};
export const datetime = (value: unknown) =>
  dateValue(value)?.toLocaleString("zh-CN", { hour12: false }) ?? "—";
export function Badge({ value }: { value: string | null | undefined }) {
  return (
    <span className={`badge badge-${value ?? "unknown"}`}>{label(value)}</span>
  );
}
export function ErrorBox({
  error,
  retry,
}: {
  error: Error | null;
  retry?: () => void;
}) {
  if (!error) return null;
  return (
    <div className="error-box" role="alert">
      <span>
        {error.message}
        {error instanceof ApiError && error.requestId
          ? ` · ${error.requestId}`
          : ""}
      </span>
      {retry && (
        <button className="text-button" onClick={retry}>
          重试读取
        </button>
      )}
    </div>
  );
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <span className="empty-mark">◇</span>
      <strong>{title}</strong>
      {children && <p>{children}</p>}
    </div>
  );
}
export function Panel({
  title,
  note,
  children,
  className = "",
}: {
  title: string;
  note?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-heading">
        <h2>{title}</h2>
        {note && <span>{note}</span>}
      </div>
      {children}
    </section>
  );
}

export function SampleCard({
  sample,
  open,
}: {
  sample: Sample;
  open: (id: string) => void;
}) {
  return (
    <button
      className="sample-card"
      onClick={() => open(sample.sample_id)}
      aria-label={`查看样本 ${sample.sample_id}`}
    >
      <div className="sample-image">
        {sample.preview_artifact_id ? (
          <img
            loading="lazy"
            src={artifactUrl(sample.preview_artifact_id)}
            alt={`${sample.sample_id} 的真实体素预览`}
          />
        ) : (
          <span>预览尚未生成</span>
        )}
        <Badge value={sample.status} />
      </div>
      <div className="sample-card-body">
        <strong title={sample.sample_id}>{sample.sample_id}</strong>
        <span>{sample.theme_seed_id}</span>
        <div>
          <span>
            {label(sample.scene_type)} ·{" "}
            {sample.composition_mode
              ? label(sample.composition_mode)
              : "未指定 / 不适用"}{" "}
            · v{sample.revision}
          </span>
          <span>{label(sample.stage)}</span>
        </div>
        {sample.reason_code && <small>{label(sample.reason_code)}</small>}
      </div>
    </button>
  );
}

export function LineChart({
  metrics,
  series,
  title,
}: {
  metrics: Metric[];
  series: { key: keyof Metric; label: string; color: string }[];
  title: string;
}) {
  if (!metrics.length)
    return <Empty title="尚无指标窗口">图表会在后端产生真实记录后显示。</Empty>;
  metrics = [...metrics].sort((a, b) => a.minute - b.minute);
  const values = metrics.flatMap((point) =>
    series.map((s) => Number(point[s.key]) || 0),
  );
  const max = Math.max(1, ...values);
  const width = 720;
  const height = 190;
  const left = 34;
  const right = width - 12;
  const top = 12;
  const bottom = height - 28;
  const x = (i: number) =>
    left + (i * (right - left)) / Math.max(1, metrics.length - 1);
  const y = (v: number) => bottom - (v / max) * (bottom - top);
  const tickTime = (date: number) =>
    dateValue(date)
      ? dateValue(date)!.toLocaleTimeString("zh-CN", {
          hour: "2-digit",
          minute: "2-digit",
        })
      : "—";
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
        <title>
          {title}，{metrics.length} 个真实记录
        </title>
        {[0, 0.5, 1].map((frac) => (
          <g key={frac}>
            <line
              x1={left}
              x2={right}
              y1={y(max * frac)}
              y2={y(max * frac)}
              className="chart-grid"
            />
            <text x={left - 8} y={y(max * frac) + 4} textAnchor="end">
              {number(max * frac, 1)}
            </text>
          </g>
        ))}
        {series.map((s) => (
          <g key={s.key}>
            <polyline
              fill="none"
              stroke={s.color}
              strokeWidth="2.5"
              strokeLinejoin="round"
              points={metrics
                .map((point, i) => `${x(i)},${y(Number(point[s.key]) || 0)}`)
                .join(" ")}
            />
            {metrics.length === 1 && (
              <circle
                cx={x(0)}
                cy={y(Number(metrics[0][s.key]) || 0)}
                r="3"
                fill={s.color}
              />
            )}
          </g>
        ))}
        <text x={left} y={height - 6}>
          {tickTime(metrics[0].minute)}
        </text>
        <text x={right} y={height - 6} textAnchor="end">
          {tickTime(metrics[metrics.length - 1].minute)}
        </text>
      </svg>
      <div className="chart-legend">
        {series.map((s) => (
          <span key={s.key}>
            <i style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}

export function useCommands(
  campaign: Campaign | undefined,
  applied: () => void,
) {
  const [pending, setPending] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const mounted = useRef(true);
  const busy = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  async function run(
    action: CommandAction,
    payload: Record<string, unknown> = {},
  ) {
    if (!campaign || busy.current) return;
    busy.current = true;
    setPending(action);
    setError(null);
    setMessage(null);
    const key = `${campaign.campaign_id}:${action}:${JSON.stringify(payload)}`;
    const command = uncertainCommands.get(key) ?? {
      command_id: crypto.randomUUID(),
      campaign_id: campaign.campaign_id,
      action,
      expected_config_revision: campaign.config_revision,
      payload,
    };
    const id = command.command_id;
    uncertainCommands.set(key, command);
    let rejected = false;
    try {
      let result = await post<Command>("/commands", command);
      for (
        let count = 0;
        result.status === "queued" && count < 120 && mounted.current;
        count++
      ) {
        await new Promise((resolve) => setTimeout(resolve, 500));
        if (!mounted.current) return;
        result = await api<Command>(`/commands/${encodeURIComponent(id)}`);
      }
      if (!mounted.current) return;
      if (result.status === "applied") {
        setMessage(`已应用：${label(action)} · ${id.slice(0, 8)}`);
        uncertainCommands.delete(key);
        applied();
      } else if (result.status === "rejected") {
        uncertainCommands.delete(key);
        rejected = true;
        throw new Error(`命令未应用：${result.reason ?? "后端拒绝"}`);
      } else setMessage(`命令已持久化，等待应用：${id}`);
    } catch (e) {
      if (mounted.current)
        setError(
          new Error(
            `${e instanceof Error ? e.message : String(e)}${rejected ? "" : "。再次提交相同内容会复用同一命令 ID。"}`,
          ),
        );
    } finally {
      busy.current = false;
      if (mounted.current) setPending(null);
    }
  }
  return { pending, message, error, run };
}

export function Drawer({
  sampleId,
  campaign,
  close,
  refresh,
}: {
  sampleId: string;
  campaign?: Campaign;
  close: () => void;
  refresh: () => void;
}) {
  const { data, error, loading } = useApi<SampleDetail>(
    `/samples/${encodeURIComponent(sampleId)}`,
  );
  const [file, setFile] = useState<{ name: string; text: string } | null>(null);
  const [fileError, setFileError] = useState<Error | null>(null);
  const [fileLoading, setFileLoading] = useState(false);
  const dialog = useRef<HTMLElement>(null);
  const commands = useCommands(campaign, refresh);
  useDialogFocus(dialog, close);
  async function openFile(id: string, name: string) {
    setFileLoading(true);
    setFileError(null);
    try {
      const response = await fetch(artifactUrl(id), {
        credentials: "same-origin",
      });
      if (!response.ok)
        throw new Error(`文件读取失败（HTTP ${response.status}）`);
      const text = await response.text();
      if (text.length > 1024 * 1024)
        throw new Error("文件超过 1 MiB，请使用下载");
      setFile({ name, text });
    } catch (e) {
      setFileError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setFileLoading(false);
    }
  }
  const imageArtifacts =
    data?.artifacts.filter((a) => /\.(webp|png|jpe?g)$/i.test(a.name)) ?? [];
  const uniqueImages = new Map<string, (typeof imageArtifacts)[number]>();
  for (const artifact of imageArtifacts) {
    const name = artifact.name.split("/").pop()?.toLowerCase();
    if (!name) continue;
    const current = uniqueImages.get(name);
    if (!current || artifact.name.startsWith("previews/")) {
      uniqueImages.set(name, artifact);
    }
  }
  const images = [...uniqueImages.values()];
  const brief = data?.task.instruction;
  return (
    <div className="drawer-backdrop" onClick={close}>
      <aside
        className="drawer"
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="detail-title"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="drawer-header">
          <div>
            <p className="eyebrow">SAMPLE EVIDENCE</p>
            <h2 id="detail-title">{sampleId}</h2>
          </div>
          <button
            aria-label="关闭样本详情"
            className="icon-button"
            onClick={close}
          >
            ×
          </button>
        </header>
        <ErrorBox error={error} />
        {loading && !data && <Empty title="正在读取样本证据" />}
        {data && (
          <>
            <div className="detail-meta">
              <Badge value={data.status} />
              <span>
                {label(data.stage)} · 源码版本 {data.revision}
              </span>
              <span>{datetime(data.updated_at)}</span>
            </div>
            {data.reason_code && (
              <div className="notice">{label(data.reason_code)}</div>
            )}
            <div className="detail-previews">
              {images.length ? (
                images.map((image) => (
                  <a
                    key={image.artifact_id}
                    href={artifactUrl(image.artifact_id)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <img
                      src={artifactUrl(image.artifact_id)}
                      alt={`${data.sample_id} · ${image.name}`}
                    />
                    <span>{image.name}</span>
                  </a>
                ))
              ) : (
                <Empty title="尚无真实渲染预览" />
              )}
            </div>
            <Panel title="创作任务">
              <p className="brief">
                {typeof brief === "string" ? brief : "未记录任务说明"}
              </p>
              <dl className="facts">
                <dt>主题种子</dt>
                <dd>{data.theme_seed_id}</dd>
                <dt>场景 / 合同</dt>
                <dd>
                  {label(data.scene_type)} /{" "}
                  {String(data.task.quality_contract ?? "—")}
                </dd>
                <dt>生成模式</dt>
                <dd>{String(data.task.generation_mode ?? "—")}</dd>
                <dt>请求场景构成</dt>
                <dd>
                  {data.composition_mode
                    ? label(data.composition_mode)
                    : "未指定 / 不适用"}
                </dd>
                <dt>观察到的构成</dt>
                <dd>
                  {data.composition?.observed?.visual.observed_mode
                    ? label(data.composition.observed.visual.observed_mode)
                    : "暂无独立图像证据"}
                </dd>
                <dt>构成目标符合</dt>
                <dd>
                  {data.composition?.meets_requested === true
                    ? "通过"
                    : data.composition?.meets_requested === false
                      ? "未通过"
                      : "未确认 / 不适用"}
                </dd>
                <dt>任务种子</dt>
                <dd>{String(data.task.seed ?? "—")}</dd>
              </dl>
              {data.composition?.observed && (
                <p className="muted">
                  测得非主体体素{" "}
                  {(
                    data.composition.observed.geometry.context_fraction * 100
                  ).toFixed(1)}
                  %（基于声明语义）；图像证据：
                  {data.composition.observed.visual.evidence}
                </p>
              )}
              <details>
                <summary>任务与标签来源</summary>
                <pre>{JSON.stringify(data.task, null, 2)}</pre>
              </details>
            </Panel>
            <Panel title="阶段时间线" note={`${data.events.length} 条记录`}>
              <ol className="timeline">
                {data.events.slice(-20).map((event, i) => (
                  <li key={String(event.event_id ?? i)}>
                    <span className="timeline-dot" />
                    <strong>
                      {label(
                        String(
                          event.kind ?? event.stage ?? event.type ?? "事件",
                        ),
                      )}
                    </strong>
                    <time>
                      {datetime(
                        event.created_at ?? event.server_time ?? event.time,
                      )}
                    </time>
                    <pre>{JSON.stringify(event, null, 2)}</pre>
                  </li>
                ))}
              </ol>
              {!data.events.length && <p className="muted">尚无阶段事件。</p>}
            </Panel>
            <Panel title="工件与质量证据" note="仅访问后端登记的文件">
              <div className="artifact-list">
                {data.artifacts.map((artifact) => (
                  <div key={artifact.artifact_id}>
                    <span>{artifact.name}</span>
                    <div>
                      {/\.(py|json|txt|md)$/i.test(artifact.name) && (
                        <button
                          className="text-button"
                          disabled={fileLoading}
                          onClick={() =>
                            void openFile(artifact.artifact_id, artifact.name)
                          }
                        >
                          查看文本
                        </button>
                      )}
                      <a href={artifactUrl(artifact.artifact_id)} download>
                        下载
                      </a>
                    </div>
                  </div>
                ))}
              </div>
              <ErrorBox error={fileError} />
              {file && (
                <details open>
                  <summary>{file.name}</summary>
                  <pre className="source-code">{file.text}</pre>
                </details>
              )}
            </Panel>
            <details className="panel">
              <summary>
                请求、修复与完整证据（{data.attempts.length} 次）
              </summary>
              <pre>{JSON.stringify(data.attempts, null, 2)}</pre>
            </details>
            <details className="panel">
              <summary>完整样本记录</summary>
              <pre>{JSON.stringify(data, null, 2)}</pre>
            </details>
            {["rejected", "blocked", "deferred"].includes(data.status) && (
              <div className="detail-retry">
                <p className="muted">
                  重试由后端检查剩余预算与资格，保留既有版本及证据。
                </p>
                <button
                  disabled={!!commands.pending}
                  onClick={() =>
                    void commands.run("retry", { sample_id: sampleId })
                  }
                >
                  提交重试命令
                </button>
                <ErrorBox error={commands.error} />
                {commands.message && <p role="status">{commands.message}</p>}
              </div>
            )}
          </>
        )}
      </aside>
    </div>
  );
}
