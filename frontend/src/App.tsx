import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { api, artifactUrl, post, query, useApi, useOverview } from "./api";
import {
  Badge,
  Drawer,
  Empty,
  ErrorBox,
  LineChart,
  Panel,
  SampleCard,
  duration,
  label,
  number,
  useCommands,
  useDialogFocus,
} from "./components";
import type {
  Campaign,
  Coverage,
  ExportJob,
  Metric,
  Overview,
  Page,
  Sample,
  CommandAction,
} from "./types";

const pages = [
  { id: "overview", name: "运行总览", path: "M3 11 12 3l9 8v10h-6v-7H9v7H3Z" },
  {
    id: "samples",
    name: "样本作品",
    path: "M3 3h7v7H3ZM14 3h7v7h-7ZM3 14h7v7H3ZM14 14h7v7h-7Z",
  },
  {
    id: "coverage",
    name: "覆盖与质量",
    path: "M4 20V10M12 20V4M20 20v-7M2 21h20",
  },
  { id: "settings", name: "活动与设置", path: "M4 7h16M4 17h16M8 4v6M16 14v6" },
];
function Icon({ path }: { path: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={path} />
    </svg>
  );
}
function Stat({
  name,
  value,
  note,
  accent = false,
}: {
  name: string;
  value: ReactNode;
  note: ReactNode;
  accent?: boolean;
}) {
  return (
    <div className={`stat ${accent ? "stat-accent" : ""}`}>
      <span>{name}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </div>
  );
}

function OverviewPage({
  overview,
  campaignId,
  tick,
  open,
  stage,
}: {
  overview: Overview | null;
  campaignId: string;
  tick: number;
  open: (id: string) => void;
  stage: (stage: string) => void;
}) {
  const latest = useApi<Page<Sample>>(
    `/samples?${query({ campaign_id: campaignId, limit: 4 })}`,
    tick,
  );
  const metrics = useApi<Page<Metric>>(
    `/metrics?${query({ campaign_id: campaignId })}`,
    tick,
  );
  if (!overview)
    return (
      <Empty title="等待后端快照">连接恢复后，会显示本活动的真实计数。</Empty>
    );
  const oldest = overview.queues.length
    ? Math.max(...overview.queues.map((q) => q.oldest_wait_seconds ?? 0))
    : null;
  const progress = overview.target
    ? Math.min(100, (overview.accepted_unique / overview.target) * 100)
    : 0;
  const cost =
    overview.cost_known === null || overview.cost_known === undefined
      ? "费用未知"
      : `$${number(overview.cost_known, 4)}`;
  const windowNote =
    overview.window_seconds < 3600
      ? `启动窗口 ${duration(overview.window_seconds)}`
      : `窗口 ${duration(overview.window_seconds)}`;
  const pipeline = [
    {
      id: "author",
      name: "模型作者",
      detail: "独立源码创作",
      stages: ["brief", "author", "refine"],
    },
    {
      id: "build",
      name: "构建与几何",
      detail: "隔离执行 · 合同检查",
      stages: ["build", "geometry"],
    },
    {
      id: "render",
      name: "真实渲染",
      detail: "互补视角 · 体素证据",
      stages: ["render"],
    },
    {
      id: "review",
      name: "视觉审核",
      detail: "绑定图片与几何 hash",
      stages: ["review"],
    },
    {
      id: "archive",
      name: "不可变归档",
      detail: "校验 · 去重 · 提交",
      stages: ["archive"],
    },
  ];
  return (
    <>
      <div className="stats-grid">
        <Stat
          name="合格独立资产"
          value={
            <>
              {number(overview.accepted_unique)}
              <em> / {number(overview.target)}</em>
            </>
          }
          note={`${number(overview.provisional_pass)} 个暂定通过，未计入合格`}
          accent
        />
        <Stat
          name="真实产出 / 小时"
          value={number(overview.accepted_per_hour, 1)}
          note={windowNote}
        />
        <Stat
          name="API 在途 / 有效上限"
          value={
            <>
              {number(overview.active_requests)}
              <em> / {number(overview.effective_cap)}</em>
            </>
          }
          note={`配置硬上限 ${number(overview.configured_cap)} · 未知占位 ${number(overview.unknown_occupancy)}`}
        />
        <Stat
          name="已知费用"
          value={cost}
          note={
            overview.cost_unknown === null ||
            overview.cost_unknown === undefined
              ? "价格或计费证据尚未确定"
              : `未知计费 ${number(overview.cost_unknown)} 次 · 已预留 $${number(overview.reserved_cost, 4)}`
          }
        />
        <Stat
          name="请求预算"
          value={
            <>
              {number(overview.requests_used)}
              <em> / {number(overview.requests_limit)}</em>
            </>
          }
          note="包含作者、修复与视觉请求"
        />
        <Stat
          name="最长队列等待"
          value={duration(oldest)}
          note={
            overview.reason_code
              ? label(overview.reason_code)
              : label(overview.state)
          }
        />
      </div>
      <Panel title="生成流水线" note="点击阶段查看任务">
        <div className="target-progress">
          <span>
            目标完成度 <b>{number(progress, 2)}%</b>
          </span>
          <div>
            <i style={{ width: `${progress}%` }} />
          </div>
        </div>
        <div className="pipeline">
          {pipeline.map((part, index) => {
            const queues = overview.queues.filter((q) =>
              part.stages.includes(q.stage),
            );
            const ready = queues.reduce((n, q) => n + q.ready, 0);
            const active = queues.reduce((n, q) => n + q.running, 0);
            return (
              <button
                className={`pipeline-step ${active && ["running", "draining", "degraded"].includes(overview.state) ? "pipeline-active" : ""}`}
                key={part.id}
                onClick={() => stage(part.id)}
              >
                <span className="step-number">0{index + 1}</span>
                <strong>{part.name}</strong>
                <p>{part.detail}</p>
                <div>
                  <span>
                    排队 <b>{number(ready)}</b>
                  </span>
                  <span>
                    活跃 <b>{number(active)}</b>
                  </span>
                </div>
                <small>
                  最长{" "}
                  {duration(
                    queues.length
                      ? Math.max(
                          ...queues.map((q) => q.oldest_wait_seconds ?? 0),
                        )
                      : null,
                  )}
                </small>
              </button>
            );
          })}
        </div>
        <p className="pipeline-note">
          返修沿既有版本继续，费用与失败均保留。合格数在工件校验及归档提交后更新。
        </p>
      </Panel>
      <div className="charts-grid">
        <Panel title="产出与请求" note="每分钟 · 真实计数">
          <ErrorBox error={metrics.error} retry={metrics.refresh} />
          <LineChart
            metrics={metrics.data?.items ?? []}
            title="每分钟合格数与请求数"
            series={[
              { key: "accepted", label: "合格资产 / 分钟", color: "#168477" },
              { key: "requests", label: "请求 / 分钟", color: "#d89941" },
            ]}
          />
        </Panel>
        <Panel title="并发趋势" note="在途与有效上限">
          <LineChart
            metrics={metrics.data?.items ?? []}
            title="实际 API 并发趋势"
            series={[
              { key: "active_requests", label: "在途请求", color: "#168477" },
              { key: "effective_cap", label: "有效上限", color: "#9aa9ad" },
            ]}
          />
        </Panel>
      </div>
      <Panel title="最新真实作品" note="最多读取 4 条样本">
        <ErrorBox error={latest.error} retry={latest.refresh} />
        {latest.data?.items.length ? (
          <div className="sample-grid sample-grid-small">
            {latest.data.items.map((sample) => (
              <SampleCard key={sample.sample_id} sample={sample} open={open} />
            ))}
          </div>
        ) : (
          !latest.error && (
            <Empty title="尚无作品记录">
              后端创建候选后，阶段、图片与失败原因会在这里出现。
            </Empty>
          )
        )}
      </Panel>
    </>
  );
}

function SamplesPage({
  campaignId,
  tick,
  open,
  initialStage,
}: {
  campaignId: string;
  tick: number;
  open: (id: string) => void;
  initialStage: string;
}) {
  const [status, setStatus] = useState("");
  const [stage, setStage] = useState(initialStage);
  const [search, setSearch] = useState("");
  const [term, setTerm] = useState("");
  const [cursors, setCursors] = useState<string[]>([""]);
  const cursor = cursors[cursors.length - 1];
  useEffect(() => {
    setStage(initialStage);
    setCursors([""]);
  }, [initialStage]);
  const list = useApi<Page<Sample>>(
    `/samples?${query({ campaign_id: campaignId, limit: 24, cursor, status, stage, q: term })}`,
    tick,
  );
  const filter = (fn: () => void) => {
    fn();
    setCursors([""]);
  };
  return (
    <>
      <div className="filter-bar">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            filter(() => setTerm(search.trim()));
          }}
          className="search-form"
        >
          <label className="sr-only" htmlFor="sample-search">
            搜索样本 ID 或主题
          </label>
          <input
            id="sample-search"
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索样本 ID / 主题种子"
          />
          <button type="submit">搜索</button>
        </form>
        <label>
          状态{" "}
          <select
            value={status}
            onChange={(e) => filter(() => setStatus(e.target.value))}
          >
            <option value="">全部状态</option>
            {[
              "accepted",
              "awaiting_review",
              "rejected",
              "blocked",
              "running",
              "ready",
              "deferred",
            ].map((value) => (
              <option key={value} value={value}>
                {label(value)}
              </option>
            ))}
          </select>
        </label>
        <label>
          阶段{" "}
          <select
            value={stage}
            onChange={(e) => filter(() => setStage(e.target.value))}
          >
            <option value="">全部阶段</option>
            {[
              "brief",
              "author",
              "refine",
              "build",
              "geometry",
              "render",
              "review",
              "archive",
            ].map((value) => (
              <option key={value} value={value}>
                {label(value)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <ErrorBox error={list.error} retry={list.refresh} />
      {list.loading && !list.data && <Empty title="正在读取本页样本" />}
      {list.data && (
        <>
          <p className="list-caption">
            第 {cursors.length} 页 · 本页 {list.data.items.length} 条 ·
            每次最多读取 24 条
          </p>
          {list.data.items.length ? (
            <div className="sample-grid">
              {list.data.items.map((sample) => (
                <SampleCard
                  key={sample.sample_id}
                  sample={sample}
                  open={open}
                />
              ))}
            </div>
          ) : (
            <Empty title="没有匹配的样本">
              调整筛选，或等待活动创建新候选。
            </Empty>
          )}
          <div className="pagination">
            <button
              className="secondary"
              disabled={cursors.length === 1 || list.loading}
              onClick={() => setCursors((values) => values.slice(0, -1))}
            >
              上一页
            </button>
            <span>第 {cursors.length} 页</span>
            <button
              className="secondary"
              disabled={!list.data.next_cursor || list.loading}
              onClick={() =>
                setCursors((values) => [...values, list.data!.next_cursor!])
              }
            >
              下一页
            </button>
          </div>
        </>
      )}
    </>
  );
}

function CoveragePage({
  campaignId,
  tick,
}: {
  campaignId: string;
  tick: number;
}) {
  const coverage = useApi<{
    items: Coverage[];
    totals: Record<string, number>;
  }>(`/coverage?${query({ campaign_id: campaignId })}`, tick);
  const [scene, setScene] = useState("");
  const [debtOnly, setDebtOnly] = useState(false);
  const items =
    coverage.data?.items.filter(
      (item) =>
        (!scene || item.scene_type === scene) && (!debtOnly || item.debt > 0),
    ) ?? [];
  return (
    <>
      <div className="notice">
        覆盖只由实际合格资产抵扣。暂定通过、在途候选和重复几何单独列出；未获得资格的主题保持可见。
      </div>
      <div className="coverage-summary">
        {["target", "accepted", "active", "rejected", "duplicate", "debt"].map(
          (key) => (
            <Stat
              key={key}
              name={
                {
                  target: "计划目标",
                  accepted: "实际合格",
                  active: "在途候选",
                  rejected: "未通过",
                  duplicate: "重复候选",
                  debt: "覆盖欠账",
                }[key]!
              }
              value={number(coverage.data?.totals[key])}
              note="活动口径"
              accent={key === "debt"}
            />
          ),
        )}
      </div>
      <div className="filter-bar">
        <label>
          场景{" "}
          <select value={scene} onChange={(e) => setScene(e.target.value)}>
            <option value="">全部场景</option>
            {["architecture", "natural", "hybrid"].map((value) => (
              <option key={value} value={value}>
                {label(value)}
              </option>
            ))}
          </select>
        </label>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={debtOnly}
            onChange={(e) => setDebtOnly(e.target.checked)}
          />
          只看欠账主题
        </label>
        <span className="muted">{items.length} 个主题家族</span>
      </div>
      <ErrorBox error={coverage.error} retry={coverage.refresh} />
      {!coverage.data && !coverage.error && <Empty title="正在读取覆盖计划" />}
      {coverage.data && (
        <>
          <div className="coverage-grid">
            {items.map((item) => (
              <article
                key={item.family_id}
                className={`coverage-card ${item.reason_code ? "coverage-blocked" : ""}`}
              >
                <div className="coverage-title">
                  <span>{label(item.scene_type)}</span>
                  <Badge value={item.qualification} />
                </div>
                <h3>{item.name}</h3>
                <small className="muted">{item.family_id}</small>
                <div className="coverage-count">
                  <strong>{number(item.accepted)}</strong>
                  <span>/ {number(item.target)} 合格</span>
                  <b>欠 {number(item.debt)}</b>
                </div>
                <div className="coverage-track">
                  <i
                    style={{
                      width: `${item.target ? Math.min(100, (item.accepted / item.target) * 100) : 0}%`,
                    }}
                  />
                </div>
                <p>
                  在途 {number(item.active)} · 未通过 {number(item.rejected)} ·
                  重复 {number(item.duplicate)}
                </p>
                {item.reason_code && (
                  <div className="coverage-reason">
                    {label(item.reason_code)}
                  </div>
                )}
              </article>
            ))}
          </div>
          {!items.length && <Empty title="当前筛选无主题" />}
          <Panel title="质量口径">
            <p className="muted">
              所有正式合格资产需要适用的几何合同、绑定真实预览的视觉审核、去重及归档提交。模型资格与软件离线验证分别记录；没有真实模型校准结果时不显示“已获资格”。
            </p>
          </Panel>
        </>
      )}
    </>
  );
}

function SettingsPage({
  campaigns,
  select,
  campaignId,
  refresh,
}: {
  campaigns: Campaign[];
  select: (id: string) => void;
  campaignId: string | null;
  refresh: () => void;
}) {
  const config = useApi<Record<string, unknown>>("/config");
  const [editor, setEditor] = useState("");
  const [validation, setValidation] = useState<{
    valid: boolean;
    errors: unknown[];
  } | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<string | null>(null);
  const [exportJob, setExportJob] = useState<ExportJob | null>(null);
  const exportId = useRef<string | null>(null);
  const creationId = useRef<string>(crypto.randomUUID());
  const currentCampaign = campaigns.find(
    (item) => item.campaign_id === campaignId,
  );
  const capCommands = useCommands(currentCampaign, refresh);
  const [cap, setCap] = useState("");
  useEffect(() => {
    setCap("");
    setExportJob(null);
    exportId.current = null;
  }, [campaignId]);
  useEffect(() => {
    if (config.data) {
      const {
        model_qualified: _qualified,
        profile_hash: _hash,
        auth_required: _auth,
        campaign_defaults: _defaults,
        ...validatable
      } = config.data;
      setEditor(JSON.stringify(validatable, null, 2));
    }
  }, [config.data]);
  useEffect(() => {
    if (!exportJob || !["queued", "running"].includes(exportJob.status)) return;
    let stopped = false;
    const timer = setTimeout(() => {
      api<ExportJob>(`/exports/${encodeURIComponent(exportJob.export_id)}`)
        .then((result) => {
          if (!stopped) setExportJob(result);
        })
        .catch((e) => {
          if (!stopped) setError(e);
        });
    }, 1000);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [exportJob]);
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setCreated(null);
    const fields = new FormData(event.currentTarget);
    const values: Record<string, unknown> = {
      campaign_id: creationId.current,
      name: String(fields.get("name")),
      target: Number(fields.get("target")),
      request_limit: Number(fields.get("request_limit")),
      api_cap: Number(fields.get("api_cap")),
    };
    const weights = ["architecture", "natural", "hybrid"].map((key) =>
      String(fields.get(key) ?? "").trim(),
    );
    if (weights.some(Boolean)) {
      if (!weights.every(Boolean)) {
        setError(new Error("填写场景配方时，请填写三个场景的份额。"));
        setBusy(false);
        return;
      }
      values.scene_weights = Object.fromEntries(
        ["architecture", "natural", "hybrid"].map((key, i) => [
          key,
          Number(weights[i]),
        ]),
      );
    }
    try {
      await post("/campaigns", values);
      setCreated(creationId.current);
      select(creationId.current);
      creationId.current = crypto.randomUUID();
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setBusy(false);
    }
  }
  async function validate() {
    setBusy(true);
    setError(null);
    setValidation(null);
    try {
      setValidation(await post("/config/validate", JSON.parse(editor)));
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setBusy(false);
    }
  }
  async function exportData() {
    if (!campaignId || busy) return;
    setBusy(true);
    setError(null);
    exportId.current ??= crypto.randomUUID();
    try {
      const job = await post<ExportJob>("/exports", {
        export_id: exportId.current,
        campaign_id: campaignId,
        include_provisional: false,
      });
      setExportJob(job);
      if (!["queued", "running"].includes(job.status)) exportId.current = null;
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setBusy(false);
    }
  }
  const defaults = config.data?.campaign_defaults as
    | Record<string, unknown>
    | undefined;
  return (
    <>
      <ErrorBox error={error} />
      <div className="settings-grid">
        <Panel title="创建活动" note="提交后不会自动发出收费请求">
          <form className="campaign-form" onSubmit={(e) => void create(e)}>
            <label>
              活动名称
              <input
                name="name"
                required
                maxLength={100}
                placeholder="例如：跨场景先导数据集"
              />
            </label>
            <div className="form-row">
              <label>
                目标合格数量
                <input
                  name="target"
                  type="number"
                  required
                  min={1}
                  defaultValue={defaults?.target as number | undefined}
                  placeholder="目标独立资产数"
                />
              </label>
              <label>
                请求预算上限
                <input
                  name="request_limit"
                  type="number"
                  required
                  min={1}
                  defaultValue={defaults?.request_limit as number | undefined}
                  placeholder="全部推理请求总数"
                />
              </label>
            </div>
            <label>
              合法 API 并发硬上限
              <input
                name="api_cap"
                type="number"
                required
                min={0}
                max={defaults?.api_cap as number | undefined}
                defaultValue={defaults?.api_cap as number | undefined}
                placeholder="由模型池权限确定，0 表示禁派发"
              />
            </label>
            <details>
              <summary>场景配方</summary>
              <p className="muted">
                留空使用后端配置。填写时三个份额会在后端统一校验。
              </p>
              <div className="form-row three">
                {["architecture", "natural", "hybrid"].map((key) => (
                  <label key={key}>
                    {label(key)}
                    <input
                      name={key}
                      type="number"
                      min={0}
                      max={1}
                      step="0.01"
                      placeholder="0–1"
                    />
                  </label>
                ))}
              </div>
            </details>
            <button type="submit" disabled={busy}>
              {busy ? "正在提交…" : "创建活动"}
            </button>
            {created && (
              <p className="success-text" role="status">
                已创建：{created}
              </p>
            )}
          </form>
        </Panel>
        <Panel title="训练数据导出" note="本地后台作业">
          <p className="muted">
            导出当前活动的正式合格资产，按衍生组分配训练、验证、测试集。暂定通过与未验证旧数据不混入正例。
          </p>
          <button
            disabled={
              !campaignId ||
              busy ||
              ["queued", "running"].includes(exportJob?.status ?? "")
            }
            onClick={() => void exportData()}
          >
            创建可重建发布
          </button>
          {exportJob && (
            <div className="export-status">
              <Badge value={exportJob.status} />
              <p>{exportJob.export_id}</p>
              {exportJob.reason && <p>{exportJob.reason}</p>}
              {(
                exportJob.result?.artifacts ??
                (exportJob.artifact_id
                  ? [{ artifact_id: exportJob.artifact_id, name: "发布工件" }]
                  : [])
              ).map((artifact) => (
                <a
                  key={artifact.artifact_id}
                  href={artifactUrl(artifact.artifact_id)}
                  download
                >
                  下载
                  {artifact.name === "发布工件"
                    ? artifact.name
                    : `：${artifact.name}`}
                </a>
              ))}
              <details>
                <summary>发布作业记录</summary>
                <pre>{JSON.stringify(exportJob, null, 2)}</pre>
              </details>
            </div>
          )}
          <div className="settings-note">
            <h3>备份与恢复</h3>
            <p>
              一致备份与恢复通过服务器上的 <code>voxlush backup</code>{" "}
              完成。实际位置、容量和恢复结果以运行记录为准。
            </p>
          </div>
        </Panel>
      </div>
      <Panel title="活动并发上限" note="持久化命令 · 等待后端确认">
        <p className="muted">
          调整当前活动的 API 并发硬上限。设为 0
          后停止新派发，已在途请求继续结算。最终上限由服务器检查授权。
        </p>
        <form
          className="cap-form"
          onSubmit={(e) => {
            e.preventDefault();
            void capCommands.run("set_cap", { api_cap: Number(cap) });
          }}
        >
          <label>
            新的 API 并发硬上限
            <input
              value={cap}
              onChange={(e) => setCap(e.target.value)}
              type="number"
              min={0}
              max={defaults?.api_cap as number | undefined}
              required
              placeholder="0 表示停止新派发"
            />
          </label>
          <button disabled={!currentCampaign || !!capCommands.pending}>
            {capCommands.pending ? "等待应用…" : "应用并发上限"}
          </button>
        </form>
        <ErrorBox error={capCommands.error} />
        {capCommands.message && (
          <p className="command-result" role="status">
            {capCommands.message}
          </p>
        )}
      </Panel>
      <Panel title="活动记录" note={`${campaigns.length} 个活动`}>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>活动</th>
                <th>状态</th>
                <th>合格 / 目标</th>
                <th>请求 / 预算</th>
                <th>配置版本</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {campaigns.map((campaign) => (
                <tr key={campaign.campaign_id}>
                  <td>
                    <strong>{campaign.name}</strong>
                    <small>{campaign.campaign_id}</small>
                  </td>
                  <td>
                    <Badge value={campaign.state} />
                  </td>
                  <td>
                    {number(campaign.accepted_unique)} /{" "}
                    {number(campaign.target)}
                  </td>
                  <td>
                    {number(campaign.requests_used)} /{" "}
                    {number(campaign.requests_limit)}
                  </td>
                  <td>v{campaign.config_revision}</td>
                  <td>
                    <button
                      className="text-button"
                      onClick={() => select(campaign.campaign_id)}
                    >
                      切换活动
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!campaigns.length && <Empty title="尚未创建活动" />}
        </div>
      </Panel>
      <Panel title="连接与配置校验" note="只做本地校验，不产生模型费用">
        <ErrorBox error={config.error} retry={config.refresh} />
        <p className="muted">
          服务器只返回脱敏配置。密钥与数据目录在服务器配置文件中管理；此处校验不会保存配置或测试收费端点。
        </p>
        <details>
          <summary>查看脱敏配置与校验</summary>
          <label className="sr-only" htmlFor="config-editor">
            脱敏配置 JSON
          </label>
          <textarea
            id="config-editor"
            className="config-editor"
            value={editor}
            onChange={(e) => setEditor(e.target.value)}
            spellCheck={false}
          />
          <button disabled={busy || !editor} onClick={() => void validate()}>
            校验配置
          </button>
          {validation && (
            <div
              role="status"
              className={validation.valid ? "success-text" : "error-box"}
            >
              {validation.valid ? "本地配置格式通过" : "配置格式未通过"}
              {!!validation.errors.length && (
                <pre>{JSON.stringify(validation.errors, null, 2)}</pre>
              )}
            </div>
          )}
        </details>
      </Panel>
    </>
  );
}

export default function App() {
  const [page, setPage] = useState("overview");
  const [campaignId, setCampaignId] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [tick, setTick] = useState(0);
  const [sampleId, setSampleId] = useState<string | null>(null);
  const [sampleStage, setSampleStage] = useState("");
  const [sessionOpen, setSessionOpen] = useState(false);
  const [token, setToken] = useState("");
  const [sessionError, setSessionError] = useState<Error | null>(null);
  const [sessionBusy, setSessionBusy] = useState(false);
  const sessionDialog = useRef<HTMLElement>(null);
  const closeSession = useCallback(() => {
    setSessionOpen(false);
    setToken("");
    setSessionError(null);
  }, []);
  useDialogFocus(sessionDialog, closeSession, sessionOpen);
  const campaigns = useApi<Page<Campaign>>("/campaigns", refreshKey);
  const readiness = useApi<Record<string, unknown>>(
    "/health/ready",
    refreshKey,
  );
  const { overview, error, connection, age } = useOverview(
    campaignId,
    refreshKey,
  );
  const campaign = campaigns.data?.items.find(
    (value) => value.campaign_id === campaignId,
  );
  const refresh = useCallback(() => {
    setRefreshKey((value) => value + 1);
    setTick((value) => value + 1);
  }, []);
  const controls = useCommands(campaign, refresh);
  const closeDrawer = useCallback(() => setSampleId(null), []);
  useEffect(() => {
    if (!campaignId && campaigns.data?.items.length)
      setCampaignId(campaigns.data.items[0].campaign_id);
  }, [campaignId, campaigns.data]);
  useEffect(() => {
    const timer = setInterval(() => {
      if (!document.hidden) setTick((value) => value + 1);
    }, 10000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    const update = () =>
      document.documentElement.classList.toggle("tab-hidden", document.hidden);
    update();
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);
  async function signIn(event: FormEvent) {
    event.preventDefault();
    setSessionBusy(true);
    setSessionError(null);
    try {
      await post("/session", { token });
      setToken("");
      setSessionOpen(false);
      refresh();
    } catch (e) {
      setSessionError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setSessionBusy(false);
    }
  }
  const title = pages.find((p) => p.id === page)!.name;
  const connectionLabel = {
    live: "实时连接",
    connecting: "正在连接",
    reconnecting: "连接断开 · 重连中",
    stale: "快照已过期",
  }[connection];
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="Voxlush Gen 首页">
          <svg viewBox="0 0 40 44" aria-hidden="true">
            <path d="M20 2 38 12v20L20 42 2 32V12Z" fill="#71b7a7" />
            <path d="m20 2 18 10-18 10L2 12Z" fill="#a6d7bd" />
            <path d="M20 22v20L2 32V12Z" fill="#469783" />
            <path
              d="m9 16 11 6 11-6M20 22v12"
              fill="none"
              stroke="#102520"
              strokeWidth="2"
            />
          </svg>
          <span>
            VOXLUSH<strong>GEN / WORKSPACE</strong>
          </span>
        </a>
        <p className="sidebar-caption">体素数据集工作台</p>
        <nav aria-label="主导航">
          {pages.map((item) => (
            <button
              key={item.id}
              className={page === item.id ? "nav-active" : ""}
              aria-current={page === item.id ? "page" : undefined}
              onClick={() => setPage(item.id)}
            >
              <Icon path={item.path} />
              <span>{item.name}</span>
              {page === item.id && <i />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-rule" />
          <p>
            独立创作 · 真实证据
            <br />
            从候选到可复现资产
          </p>
          <span className="server-status">
            <i className={readiness.data && !readiness.error ? "ready" : ""} />
            {readiness.error
              ? "服务未就绪"
              : readiness.data
                ? "后端已连接"
                : "检查后端…"}
          </span>
          <button
            className="session-button"
            onClick={() => setSessionOpen(true)}
          >
            会话认证
          </button>
          <small>v1.0 · LOCAL FIRST</small>
        </div>
      </aside>
      <main className="main-content">
        <header className="topbar">
          <span>VOXEL DATASET / {title}</span>
          <div className={`connection connection-${connection}`} role="status">
            <i />
            {campaignId ? connectionLabel : "未选择活动"}
            {campaignId && age !== null && connection !== "live" && (
              <span> · {number(age)} 秒前快照</span>
            )}
          </div>
        </header>
        <div className="workspace">
          <div className="page-heading">
            <div>
              <p className="eyebrow">
                {page === "overview"
                  ? "GENERATION MONITOR"
                  : page === "samples"
                    ? "ASSET LIBRARY"
                    : page === "coverage"
                      ? "COVERAGE & QUALITY"
                      : "CAMPAIGNS & SETTINGS"}
              </p>
              <h1>{title}</h1>
              <p>
                {page === "overview"
                  ? "查看真实产出、瓶颈与剩余预算。"
                  : page === "samples"
                    ? "每一份工件都有独立源码与版本证据。"
                    : page === "coverage"
                      ? "从合格结果看多样性，不用在途数量填平缺口。"
                      : "管理生成目标，核对配置与可重建发布。"}
              </p>
            </div>
            <label className="campaign-picker">
              <span>当前活动</span>
              <select
                aria-label="当前活动"
                value={campaignId ?? ""}
                onChange={(e) => {
                  setCampaignId(e.target.value || null);
                  setSampleStage("");
                }}
              >
                <option value="" disabled>
                  选择活动
                </option>
                {campaigns.data?.items.map((value) => (
                  <option key={value.campaign_id} value={value.campaign_id}>
                    {value.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <ErrorBox error={campaigns.error} retry={campaigns.refresh} />
          <ErrorBox error={readiness.error} retry={readiness.refresh} />
          {campaignId && page === "overview" && <ErrorBox error={error} />}
          {campaignId && overview && page === "overview" && (
            <div className="campaign-control">
              <div>
                <Badge value={overview.state} />
                {overview.reason_code && (
                  <span>{label(overview.reason_code)}</span>
                )}
              </div>
              <div className="control-buttons">
                {[
                  { action: "start", name: "启动" },
                  { action: "drain", name: "排空" },
                  { action: "pause", name: "暂停" },
                  { action: "resume", name: "恢复" },
                ].map((item) => (
                  <button
                    key={item.action}
                    className={item.action === "start" ? "" : "secondary"}
                    disabled={!!controls.pending || !campaign}
                    onClick={() =>
                      void controls.run(item.action as CommandAction)
                    }
                  >
                    {controls.pending === item.action ? "等待应用…" : item.name}
                  </button>
                ))}
              </div>
            </div>
          )}
          <ErrorBox error={controls.error} />
          {controls.message && (
            <p className="command-result" role="status">
              {controls.message}
            </p>
          )}
          {page === "settings" ? (
            <SettingsPage
              campaigns={campaigns.data?.items ?? []}
              campaignId={campaignId}
              select={setCampaignId}
              refresh={refresh}
            />
          ) : !campaignId ? (
            <Empty title="创建第一个生成活动">
              <span>后端独立运行；关闭面板不会影响生成。</span>
              <button onClick={() => setPage("settings")}>
                前往活动与设置
              </button>
            </Empty>
          ) : page === "overview" ? (
            <OverviewPage
              overview={overview}
              campaignId={campaignId}
              tick={tick}
              open={setSampleId}
              stage={(value) => {
                setSampleStage(value);
                setPage("samples");
              }}
            />
          ) : page === "samples" ? (
            <SamplesPage
              key={campaignId}
              campaignId={campaignId}
              tick={tick}
              open={setSampleId}
              initialStage={sampleStage}
            />
          ) : (
            <CoveragePage campaignId={campaignId} tick={tick} />
          )}
          <footer className="workspace-footer">
            <span>Voxlush Gen · 计数来自权威 Store</span>
            <span>模型资格与生产发布单独验收</span>
          </footer>
        </div>
      </main>
      {sampleId && (
        <Drawer
          key={sampleId}
          sampleId={sampleId}
          campaign={campaign}
          close={closeDrawer}
          refresh={refresh}
        />
      )}
      {sessionOpen && (
        <div className="modal-backdrop" onClick={closeSession}>
          <section
            className="session-modal"
            ref={sessionDialog}
            tabIndex={-1}
            role="dialog"
            aria-modal="true"
            aria-labelledby="session-title"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="icon-button modal-close"
              aria-label="关闭会话认证"
              onClick={closeSession}
            >
              ×
            </button>
            <p className="eyebrow">SECURE SESSION</p>
            <h2 id="session-title">会话认证</h2>
            <p className="muted">
              输入服务器访问令牌。认证后使用 HttpOnly 会话；浏览器不保存令牌。
            </p>
            <form onSubmit={(e) => void signIn(e)}>
              <label>
                访问令牌
                <input
                  type="password"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  autoComplete="off"
                  required
                  autoFocus
                />
              </label>
              <ErrorBox error={sessionError} />
              <button disabled={sessionBusy}>
                {sessionBusy ? "认证中…" : "建立会话"}
              </button>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}
