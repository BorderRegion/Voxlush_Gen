# 01 · 执行、调度、恢复与资源效率

本文件规定运行行为。数值是先导初值，不代表已经测出本工程容量；硬质量与计费安全不允许因调参绕过。

## 1. 最小运行模型

一个后端进程内：API 服务、一个 scheduler、一个 Store 写入任务、异步模型调用、有限的本地工作队列。生成源码在可真正终止的隔离子进程/容器执行；渲染使用单独受限 worker。UI 完全独立于运行循环。

API、源码执行、几何/渲染、归档分别限制资源。**不能用同一个信号量包住完整样本生命周期**；模型返回并持久化响应后立即释放网络槽，不能等待构建、评审或保存。退避期间任务只有 `next_ready_at`，不占网络槽和 worker。

调度器从 SQLite 按条件领取小批任务；不要把十万样本的源码/体素/聊天历史放内存，不要启动十万个 asyncio Task，不要每次 tick 遍历十万目录。常驻队列只保存 ID 和小型上下文引用。

推荐初值：`ready_buffer = clamp(4 × 当前有效 API cap, 64, 1024)`；内存队列有界，SQLite 可以保存更大的待处理任务表。CPU 执行和渲染初始各 1–2 个，根据实测峰值内存和耗时调节。不要机械设置等于 CPU 核数。

## 2. 状态不能指数膨胀

用几个正交字段代替几十个带组合含义的状态名：

- `stage`：brief / author / refine / build / geometry / render / review / archive。
- `status`：ready / running / deferred / awaiting_review / accepted / rejected / blocked / cancelled。
- `reason_code`：明确原因，如 rate_limited、awaiting_visual、budget_exhausted、same_error_no_progress。

“repair”是一次带 `repair_target` 的作者调用，不额外设计第三套状态机。骨架/精细化由 `generation_mode` 和 `source_revision` 表示。根本未需要的阶段直接跳过，不生成空 API 调用。

每个样本关键字段：sample_id、campaign_id、theme_seed_id、quality_contract、generation_mode、stage/status、revision、source_hash、last_progress_at、lease_owner/lease_until、attempt_id、next_ready_at、累计预算计数、artifact refs、终止原因。心跳单独记录，不得用心跳刷新“实际进展时间”。

活动状态：idle / running / draining / paused / degraded / blocked / completed。活动状态不是某个样本状态的复制。暂时失败一个主题应只影响相应 theme × route 队列，不连带停所有主题。

## 3. 单一状态所有者与 SQLite

所有变更经 Store 的事务函数，scheduler/API handler 不分别直接改 state.json。建议最小表：campaigns、samples、attempts、commands、events、assets、metrics_minute；主题配置以版本化 JSON 保存，不必再拆成十几张表。预算 reservation/settlement 放 attempts，活动聚合余额事务更新。大请求/响应、源码和图像留文件，DB 保存路径与 hash。

必要约束/索引：

```text
samples(sample_id PRIMARY KEY)
samples(status, next_ready_at, stage)
samples(campaign_id, status, theme_seed_id)
attempts(attempt_id PRIMARY KEY)
assets(sample_id, revision) UNIQUE
assets(canonical_voxel_hash) UNIQUE WHERE accepted_unique = 1 AND is_current = 1
commands(command_id PRIMARY KEY)
events(campaign_id, event_id)
```

如不同任务确实生成同一几何，第二个保留 duplicate 记录，但不再计独立资产。校验、标签或几何版本更新形成新 revision/release，不能偷偷覆盖旧 accepted。已有样本更新标注/修订时，事务切换 current revision 而不增加 accepted_unique；旧 release 仍引用旧不可变工件。

领取任务在短事务内检查旧 revision/lease，写 running 与 attempt；提交同样比较 lease/revision。过期 worker 的输出可隔离落盘，但不得覆盖更新版本。对同一个 source_hash 的幂等本地检查可以复用结果。

只允许一个 scheduler owner：使用本地主进程锁并检测失效，不依赖在内存设一个布尔值。不能 `uvicorn --workers 4` 后把 scheduler 在每个 lifespan 中启动。启动失败要能解释；不能让第二个进程“悄悄帮忙”。

WAL 数据库必须在本机文件系统；其单写入限制和共享内存要求见 SQLite 官方文档。启动记录 Python 实际链接的 `sqlite3.sqlite_version`，采用包含 WAL-reset 修复的版本（官方列出的 3.51.3 及以后，或具有对应 backport 的 3.50.7/3.44.6；不要把这几个号码误当唯一可用版本）。用发行版补丁时保留其证据。默认单写入连接和 checkpoint 同一所有者，不额外堆防护线程。[R1]

关键状态/预算事务需要可靠持久化；日志、心跳和瞬时指标可以缓冲。不要为每个 token/粒子事件做 fsync。DB 故障阻断新付费派发，同时尽量保存已返回响应；不把持久化失败当普通可重试生成失败。

## 4. 最小调度算法

一次调度迭代（事件到达或 0.5–1 秒 tick）只做：

1. 应用持久化控制命令，处理到期 deferred，收割已完成工作，更新聚合指标。
2. 检查预算、已有在途/未知占用、本地下游高水位，算当前允许派发的容量。
3. 在可用主题队列中选缺口较大且有资格的任务；每栋内部同一时刻只有一个阶段运行。
4. 领取并预留预算，提交网络或本地工作；返回事件循环。

不要把调度器写成“反复检查所有任务是否能运行”的脚本集合。`asyncio.Queue(maxsize=...)` 等有界队列已经可以表达背压，无需引入外部消息系统。[R2]

### 4.1 全局 API 容量

真正的 cap 是以下限制的最小值，而不是池页面上的总容量：

```text
effective_cap = min(
  用户已授权的本应用全局 cap,
  已确认的供应方/路由限制,
  当前自适应并发上限,
  本地下游可承受的准入上限
)
available = max(0, effective_cap - active_requests - unresolved_provider_occupancy)
```

同一池的作者、修复、视觉、批量 brief 和可选强模型全部计入全局 cap；共享账户/上游限额的多个模型不能各自把额度用一遍。遵守已授权路由与提供方限制，不通过换账户/代理绕过限额。

并发不是 RPM/TPM。端点给出 RPM/TPM 时，同时约束请求启动速率和 token 预算；长输出可以先耗尽 TPM。连接池大小、网关实际在途、首内容时间、下载带宽同样要检查，不能只扩大 semaphore。

### 4.2 自适应规则，不做复杂优化器

初始并发取 `min(8, hard_cap)`；稳定后可增至 16/32/64 等，最终允许达到**已经确认的合法上限**，不永久写死 32，也不默认冲 512。

一个窗口至少 120 秒且结束 30 个模型请求再评估一次；数据不足不扩容。窗口内有效完整响应率、429/5xx、p95 延迟、下游排队时间和 accepted/hour 一起看。出现明显拥塞（例如 429/5xx 超 5%，或下游积压持续跨两个窗口增长）降至原 cap 的约 0.7，最小 1、最大不超过用户 cap；cap=0 就不派发。参数可在先导中调整。

无拥塞、质量配置合格、API 队列确有待办、下游有余量时小步增加（低并发可加倍至 32，更高时约 +10% 或 +8）。后端下降后槽位自然排空，不杀正常在途；上升不能突破任何硬 cap。

调用窗口扩容和长窗口产量调优分开：短窗口保证网络稳定；至少积累足够完成样本后，若并发提升只增加成本/延迟、accepted/hour 没增长，则回到上一稳定档。数据不足应显示 insufficient_data，而不是假优化。

### 4.3 公平性与背压

网络待办可用简单加权轮询：新作者/必要细化约 60%、有明确修复价值的任务约 25%、视觉/brief 等收尾约 15%。这是可借用份额，不是预留闲槽：某队列空闲时其他队列立即使用；增加等待时间权重，防止长任务/稀有主题永远挨饿。历史坏样本另设较小上限，不掩盖新生产产量。

本地归档优先；几何失败直接修，不先排最终渲染。使用双水位避免频繁开关：例如待渲染高水位取渲染 workers × 8、低水位 workers × 3；持续超过高水位时压低相应上游，不继续积压大量已付费样本。CPU、内存、磁盘预算也纳入相同机制，不额外建立多层 controller。

针对内存按**字节**约束，不仅按任务个数。用先导测得的每类峰值内存限制本地并行度，预留操作系统余量；构建 worker 之间不反复复制大型 Python 体素字典。

## 5. 一个 API 适配层，一个重试所有者

`inference/` 对其余系统提供统一结果：

```text
ModelResult:
  request_id, attempt_id, role, endpoint_alias, requested_model,
  reported_model, response_complete, finish_reason, content,
  usage (nullable fields), billing_status,
  first_content_at, elapsed_ms, raw_response_ref, error_category
```

不能依据型号字符串断言真实后端能力或身份。记录 requested/reported model，未知路由保持 unknown。模型参数通过角色配置传入；未知 `reasoning_effort`、JSON mode、tools 等不要一律强加。启动/模型配置变化时做少量能力测试，结果缓存，普通请求不重复探测。

优先复用现有正确异步客户端，否则只选择一个成熟 HTTP 客户端。确认 SDK、池、gateway 是否已经重试；只留一个可审计的语义重试层，避免 2×3×3 的请求放大。

### 5.1 请求超时

连接、首个有效内容、内容空闲、总时长分别定义。先导可从 connect 10s、首内容 90s、内容空闲 60s、total 240s 开始；推理模型或既有 SLA 较长时按实际合约调整，**这些不是所有端点的强制值**。配置必须贯穿真实链路；不能客户端设 900s 而网关 300s 先断。

心跳不算有效输出进展；reasoning 内容单独记录，不能当源码。流式和非流式都支持，以端点实际正确性和吞吐选择，不为动效强制流式。

只在满足该端点完成合约时认定响应完整。`finish_reason=length`、空内容、正文后 error、未满足终止合约的 EOF 不能执行和计为完成；也不要对明确不使用 `[DONE]` 的正常端点强加该标记。完整响应、可执行源码、几何合格、最终 accepted 是四个独立指标。

### 5.2 故障分类

| 故障 | 行为 |
|---|---|
| 明确未发送（连接建立前失败） | 最多一次退避重试，仍受总请求预算约束 |
| 429/明确服务忙 | 遵守 Retry-After；释放本地网络槽，延迟重新排队 |
| 已完整返回但格式/源码错误 | 进入一次有依据的语义修复，不当网络重试 |
| 长度截断 | 保存原响应，改为合适的分阶段/输出预算再尝试；不执行残片 |
| POST 已发送后不明断连 | outcome_unknown；不默认立即重发同一逻辑请求 |
| 401/403/明确额度不足 | 隔离相关端点，显示配置/配额原因，不逐样本反复尝试 |
| 单主题几何/质量长期零产出 | 降低该主题×模型配置资格，其他主题继续 |
| DB/归档目录不可写或预算耗尽 | 停止新的付费派发，本地尽可能排空，保留明确状态 |

HTTP 非幂等请求无法凭重连就保证安全重试，见 RFC 9110。[R3] 提供方确有 request_id 查询/幂等 key 能力时复用；不能假装 OpenAI-compatible 就必然支持。

未知请求先保留费用预留与上游占用估计，在有合同依据的超时/查询确认后再释放占用。关闭本地 socket 不代表服务方立即停止计算。没有可查询能力且无法判定终止时，该任务隔离，其他预算允许的任务继续；同路由未知占用累计触及其 cap 时应暂停该路由，而非冒险越界。未知费用不能当零，可按已授权保守上界结算为 estimated_unknown，保留对账状态；没有可信上界则冻结相应预留。

默认不重放未知请求。有限自动补尝试必须是操作者提前启用的风险策略，明确最多一次并计入总预算；不要求用户逐个处理失败请求，也不无限补偿。重试 POST 的具体能力不能靠猜。

## 6. 预算与长期自动补量

每次可能收费调用之前事务性 reserve，之后 settle。记录 provider actual usage、未知项、估算依据和预算余额，区分 input/output/reasoning/cache tokens；提供方没给的不编造。作者、修复、视觉、主题规划、失败和未知调用都进入账本；批量 brief 成本可按生成的任务均摊，但活动总账只计一次。

初始单样本上限建议：总模型请求 8 次；几何/代码修复最多 2 次；视觉修复最多 1 次；灰区复审最多 1 次；同根因两次没有实质改善就停止相同策略。总上限优先，不能把每个子上限加起来无限执行。一次可选强模型调用**替代**剩余修复槽，不凭空增加预算；未配置强模型也必须可运行。

普通正常路径 1 次作者 + 1 次视觉，复杂路径 2 次作者 + 1 次视觉；不含可选的批量 brief 均摊。模式和上限都能追踪，不在单样本日志中写“无限直到通过”。

活动预算至少有明确的请求/费用等授权硬上限；依赖每请求输出/计费上界时必须能真实约束。价格未知可以按用户批准的请求/令牌限制试运行，并显示费用未知；不能宣称美元预算得到保障。缺少所有全局预算上限时，不得启动无人值守大批量运行。

目标缺口按 accepted_unique 计算，规划器自动补充新任务。rejected/duplicate 不算已满足目标；但补任务也消耗活动预算，预算耗尽时状态是 blocked_budget，不是 completed。达到目标时停止新作者派发，默认将已经付费的少量在途资产收尾并记 surplus，不删除已付费结果；发布精确目标个数，余量独立列示。

## 7. 控制语义与恢复

- `start/resume`：在配置与预算允许的情况下派发；重复命令幂等。
- `drain`：停止所有新的付费请求（包括修复/视觉），允许已经返回的结果完成构建、检查、渲染与可完成的归档；需要新视觉调用的留待 resume。不要把它混同“直到全部 accepted”。
- `pause`：停止新阶段领取；已发模型请求尽量完成并安全保存；保留明确在途数。不是强杀。
- `emergency_stop`：尽力取消本地请求和子进程，剩余外部结果可能 unknown；记录并核对。不能承诺远端零费用。
- `shutdown`：先 drain，持久化并关闭；有上限，不永远等一个坏 worker。

启动恢复依赖 DB、attempt 记录与工件 hash，而不是重新扫每个任务全部历史。已完整落盘模型响应但 stage 未更新时使用已有响应继续；已产生 voxels 不重新调用作者；已安装工件但 DB 未提交时校验后补提交。真正 unknown 的请求不重发。

lease 过期不代表本地旧进程已退出。重领需要确认旧 worker 已终止或隔离其提交；本地进程 PID 不能跨重启盲认，结合 owner_instance_id/启动 epoch。

## 8. 归档提交的崩溃窗口

采用简单两阶段文件提交，不声称文件系统与 SQLite 有跨系统事务：

1. 工件写入同一数据卷的 staging/sample_id/revision，完成校验和 commit_manifest，必要时 fsync。
2. 原子 rename 到最终不可变路径（同文件系统）；DB 事务注册 assets、sample accepted 与计数。
3. 启动恢复只对未结清 staging/commit 记录核对。工件存在且合法但 DB 未注册则补注册；DB 指向丢失文件则标记完整性事故，不计 accepted。

最终唯一性约束避免重复计数。临时目录不放在另一个磁盘再把 `rename` 当跨卷原子操作。接受记录写入后不得再静默修改工件。

## 9. 必要隔离，不另造安全平台

模型生成 Python 是不可信代码。禁网、非 root、只读输入/运行时、仅本样本可写目录、CPU/内存/pids/输出字节限制、真实可杀的超时是必要条件。不能把 AST 检查当作安全边界；不要给执行环境提供密钥、宿主大目录或 Docker socket。简单白名单语法检查可用于早期报错，但不必为了每种 Python 语法做自制安全解释器。

Docker 默认不自动给容器设置资源限额，必须显式配置并测试。[R4] 可以复用预装依赖的镜像，但各样本运行状态要隔离；不能为了省启动开销跨样本保留可污染的 Python 全局变量。先测启动开销，再决定是否需要 worker 复用。

前端默认本机访问或既有受保护反向代理；远程部署需 TLS 与单用户鉴权。读写文件只接收已注册 artifact ID，不接任意路径。前端显示模型文本必须转义，不使用任意 HTML。首次实现这些边界，之后不对每次调用重复进行昂贵全环境检查。

## 10. 运行可观测性与效率报告

后端聚合：请求完整率、accepted/hour（15m/1h，附窗口长度与数量）、尝试到 accepted 转化率、每 accepted 请求/令牌/费用、p50/p95 请求时延、API 活跃/合法 cap/自适应 cap、各阶段队列数与最久等待、本地 CPU/内存/磁盘、unknown 请求与费用预留。

预算指标区分本次活动与历史修复；分母为 0 显示 null/暂无，不显示 0 成本。只统计完整窗口或明确标记启动窗口；ETA 用实际足量 accepted 速率计算，不足则显示暂无估计。

比较不同并发必须记录同一主题/规模组合，避免把简单任务更多当调度进步。估算上界可用 `API_requests/hour ≤ 3600 × concurrency / 平均占槽秒数`，再除以**含失败在内的 requests/accepted**；实际还受 RPM/TPM、本地阶段和质量率约束。这只是容量推导，不能当实测吞吐。

如果没有机房/设备电量遥测，不报告“能效提升 X%”。用 token、请求数、CPU-seconds、渲染秒数、内存峰值、磁盘字节及每 accepted 的对应值作为可测替代指标。

## 技术依据（官方，2026-10-06 核实）

[R1] https://www.sqlite.org/wal.html （同机、单写入、WAL 文件与 WAL-reset 修复）\
[R2] https://docs.python.org/3/library/asyncio-queue.html （有界队列）\
[R3] https://www.rfc-editor.org/rfc/rfc9110.html#section-9.2.2 （非幂等请求重试边界）\
[R4] https://docs.docker.com/engine/containers/resource_constraints/ （容器资源限制）
