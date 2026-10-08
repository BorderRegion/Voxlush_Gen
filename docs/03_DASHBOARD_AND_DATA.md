# 03 · 前后端监控、归档与训练数据契约

## 1. 页面范围：四个页面与一个详情抽屉

不要做运营平台。首版交付以下完整页面：

| 页面 | 用户一眼要看见什么 | 主要交互 |
|---|---|---|
| 总览 | 已合格/目标、真实产量、在途/cap、瓶颈、运行原因 | 启动、排空、暂停、恢复；点击阶段看等待任务 |
| 样本 | 真实缩略图、合格/待审/失败、主题与规模 | 筛选、搜索、分页、看多视角、下载单样本或打开源码 |
| 覆盖与质量 | 目标配额和 actual accepted 的差额、近期质量/重复率 | 选场景/家族/规模、查看被暂缓主题和欠账原因 |
| 活动与设置 | 当前活动的模型/预算/并发/存储及历史发布 | 一次创建活动、配置验证、历史统计、导出、备份状态 |

详情抽屉：sample_id、brief、源码版本、当前阶段、简短进度时间线、实际错误、修复次数与成本、真实图片、几何/视觉证据、标签来源、归档文件与校验状态。日志默认折叠，按需打开。重试需剩余预算且创建命令，不直接改数据库。

## 2. 图形化总览的精确定义

上方仅保留 4–6 个短数字：accepted/target、accepted/hour、active/effective_cap、当前支出或 token、最长等待、关键状态。没有价格则显示“费用未知”，不是 0 元。

中间为 pipeline 图：待作者 → 本地构建/几何 → 渲染 → 审核 → 归档。每段显示队列数、活跃数与简短状态；返修路径用细回流线，点击可展开。动画由真实事件或真实聚合速率驱动，不在无进展时不断演示“新样本完成”。

底部为 accepted/hour 与 API 请求速率的时间曲线、并发与排队趋势、最新真实作品缩略图。近期失败只显示主要 3 个原因，详细日志放抽屉。覆盖页热力图显示**实际已接受**的场景/规模分布，同时标记未验证资格与欠账。

动效参数建议：数字/曲线过渡 150–300ms，消息更新约 1–2s，活跃象征动画最多几十个元素。动画元素不一对一承载十万任务；需要时注明是聚合表现。暂停时停止流动，断联时冻结上次快照并显示 stale，而不是随机补点。后台标签页停止动画；支持 `prefers-reduced-motion`，不能只靠颜色表达异常。

不做自动旋转 3D 地球、不为每次 API token 创建粒子、不首页加载所有样本、不自动播放大量 3D 建筑。首版真实缩略图+静态多视角即可；交互体素预览只在选中样本时延迟加载，性能未证明前不列为上线阻塞项。

## 3. 前后端边界与接口

后端 Pydantic 数据模型是运行接口真相，生成 OpenAPI/TypeScript 类型。不要前端手写一份与后端不同的状态枚举、cap 计算或费用逻辑。本包 JSON Schema 是资产/任务格式基线，实际实现时保持兼容或显式升版并迁移。

建议 API（这些接口是开发要求，目前不声称已实现）：

```text
GET  /api/v1/health/live
GET  /api/v1/health/ready
GET  /api/v1/overview?campaign_id=...
GET  /api/v1/events?campaign_id=...&after=...          # 单条 SSE
GET  /api/v1/metrics?campaign_id=...&window=1h
GET  /api/v1/samples?campaign_id=...&status=...&cursor=...&limit=50
GET  /api/v1/samples/{sample_id}
GET  /api/v1/artifacts/{artifact_id}                 # 注册过的安全文件
GET  /api/v1/coverage?campaign_id=...
GET  /api/v1/campaigns
GET  /api/v1/config                                 # 脱敏，不回传密钥
POST /api/v1/config/validate                        # 本地校验，不默认收费调用
POST /api/v1/campaigns                              # idempotency key
POST /api/v1/commands                               # 持久化控制命令
GET  /api/v1/commands/{command_id}
POST /api/v1/exports                                # 作为本地后台作业
GET  /api/v1/exports/{export_id}
```

控制命令 request：`command_id, campaign_id, action, expected_config_revision, payload`；response：queued/applied/rejected 与实际 reason。不要把 HTTP 200 当已应用，前端应等待 command result。

统一错误：`code, message, retryable, request_id, details`。不同角色/主题故障区分 scope。列表游标稳定，所有限制分页；上限不能由前端传入极大数字绕过。

SSE 一个连接复用 overview/metrics/command/status 事件，带 `schema_version, event_id, server_time, campaign_id, payload`。先获取一致的 snapshot 和 event cursor，再续接事件；游标过旧或服务重启不能回放时发送 reset，前端重新拉 snapshot。不要为了 UI 重放保存每个 token 或所有瞬时数值。

后端每 1–2 秒做一次共享聚合，不为每个浏览器重算十万行。慢客户端允许丢掉过期 metrics snapshot，但控制结果/最终状态可通过 API 补查；缓冲有上限。SSE 心跳约 15s，断开自动重连并退避。原生 SSE 在 HTTP/1.x 有浏览器连接数约束，不能每个图表另开一个连接。[U1]

同源 HttpOnly 会话 cookie 或既有受保护代理适合单用户部署；不要把 API 密钥写进前端 bundle、SSE URL 或 localStorage。Cookie 鉴权的写操作需 CSRF/Origin 保护。页面模型文本转义，源码只读文本显示，不运行任意脚本。

UI 断开不影响生成；API 只读查询压力不能抢占 scheduler。扩展按钮可放“高级”，但不能把基本启动隐藏在脚本里。

## 4. 监控指标的统一口径

| 指标 | 定义/注意 |
|---|---|
| accepted_unique | 工件已持久化、适用质量证据通过、非重复且正式提交的资产数 |
| qualified_pending_archive | 质量通过但尚未原子归档，不混入 accepted |
| author_response_complete | 模型端点的完整响应；不是构建成功 |
| acceptance_yield | 已结清候选中的 accepted_unique / 已结清候选总数，报告分子分母 |
| first_pass_yield | 无语义修复的候选最终 accepted 比例；不要用 HTTP 200 计算 |
| accepted_per_hour | 明确 15m/1h 窗口内计数折算；启动期标注窗口不足 |
| requests_per_accepted | 活动相关所有收费请求（含失败、修复、视觉、brief 摊销）/ accepted |
| cost_per_accepted | 费用已知部分与未知预留分别显示；没有 accepted 时 null |
| API utilization | active / effective_cap，同时显示 configured_cap、observed_pool_cap（可能 unknown） |
| waiting_age | 当前时间减最近进入该队列时间，不因心跳归零 |
| stalled | 有待办但长时间无实际阶段推进，并明确阻塞原因；与正常等模型区分 |
| ETA | 仅在有足量稳定产出时给出范围/估计；不凭队列数量编造 |

零分母、未知值、部分计费、队列等待、稀有主题样本不足都应有明确表示。图表可平滑视觉过渡，但导出和累计数字来自真实计数。自适应 cap 降低后利用率的变化不能被当成吞吐改善。

## 5. 数据目录：代码与资产分离

```text
$VOXLUSH_DATA/
  runtime.db
  work/<id_prefix>/<sample_id>/                 # 活跃候选、局部修订
  assets/<id_prefix>/<sample_id>/v0001/          # 不可变合格资产
  rejected/<id_prefix>/<sample_id>/             # 失败与原因，按策略保留
  runs/<campaign_id>/                           # 配置、指标、请求/响应索引
  runtimes/<runtime_hash>/                      # 冻结的绘图/材料运行时
  releases/<release_id>/                        # manifest、切分、分片及报告
  backups/
```

每个 finalized asset 至少包括：

```text
manifest.json
brief.json
authored_source.py                 # 模型为本资产写的最终源码，训练 target
build.py                           # 可独立运行的组合入口，包含/定位冻结运行时
voxels.npz                         # canonical occupied arrays，allow_pickle=False
palette.json                       # 方块状态与组件映射
components.json                    # 组件、父对象、语义与实际 bbox
geometry.json
review.json
previews/view_a.webp
previews/view_b.webp
```

原格式 `sample.json.gz`、原始 tools JSON 等按兼容合同保留/导出。不要让 sample.json.gz 与 voxels.npz 变成两份独立真相：都必须由同一最终数组生成，经过一致性回读。最终 manifest 文件列表以实际存在和校验通过为准。

`build.py` 必须在文档说明的离线 Python 环境中、没有生产服务/密钥/隐藏绝对路径的情况下独立重建。可组合冻结的 trusted runtime 与 authored source，也可引用随 release 提供的准确 runtime bundle，但不能依赖未知的服务器目录。`authored_source.py` 单独保存，训练时不必每条重复喂全部框架包装。

## 6. Canonical 体素数据与坐标约定

v1 保持 256×256×256 的整数域，所有占用坐标 0..255，Y up、north=-Z。完整样本表示为**全部占用体素+隐含 air**，不是全局每次分配一份 256³ 多通道稠密数组。

建议 `voxels.npz`：

```text
coords:       [N,3] uint16, 列顺序 x,y,z，字典序排序，唯一
block_index:  [N] uint16/uint32，引用 palette.block_states
component_index: [N] uint32，引用 palette.component_ids
```

每个 block state 保留完整命名空间与属性；与实例方位有关的 facing/axis 等不能丢失。材料允许表、Minecraft/资源包版本从已有项目取得并固定；目前不假定某个 Minecraft 版本。导出时遇到未知方块必须显式失败/保留 unresolved，不静默换 stone。

逐体素 component ownership 保留；组件是语义/调试标注，不是限定生成形状的模板。样本可包含多个 object/building/landform，组件 parent 不再硬编码所有都属于 building_01。旧单体用 adapter 映射，迁移时保留 original identifiers。

canonical hash 对坐标、block states、必要的表示版本明确规范；用于几何 exact 去重的 hash 不依赖随机 component 名称。另一份 annotation hash 覆盖组件/标签，从而能区分“几何相同、标注修订”。不要把注释或坐标存储顺序改变误判为新几何。

canonical voxel hash 不直接取 NPZ/ZIP 文件字节（其容器元信息可能不同）。v1 建议固定：格式前缀 `voxlush.voxels.v1\0`；little-endian uint16 的三个 grid 值；只含实际使用状态、按规范化 block-state 字符串排序的 UTF-8 JSON palette（前置 uint64 字节长度）；uint64 的 N；字典序 coords 的 little-endian uint16 C-order 字节；按该 palette 重映射的 uint32 block_index 字节。block-state 属性键排序、名字规范化规则锁版本；组件名字不进入几何 hash。文件本身另有 SHA256 校验和。相同数组的不同压缩封装必须得到相同 canonical hash。

规范化只去掉存储层的不确定性，不擅自平移/旋转最终产物；用于近重复检索的归一化视图单独派生。所有随机数种子显式来自 task，不从当前时间获取；相同代码/runtime/seed 应得到同一 canonical hash。

## 7. Manifest 必需内容

`schemas/asset_manifest.schema.json` 是机器可读基线，至少包含：

- schema/asset/sample/campaign/revision、task_id、theme_seed_id、scene_type、quality_contract。
- 256 域与坐标约定、material catalog/runtime/validator/renderer/rubric 的版本/hash。
- authored source、canonical voxel、annotation、preview hashes 和相对 artifact paths。
- sampling_tags / requested_tags / generator_declared / observed_tags；每个 observed 有 source、evidence_ref、confidence 或确定性证据类型。
- geometry 与 visual 分离结果、accepted_at、archive commit、duplicate/lineage 信息。
- endpoint alias、请求/报告模型名、generation_mode、原始请求响应引用、revision lineage、seed。
- attempts/usage、已知费用、未知费用、生成/执行/渲染时间；缺失数值用 null。
- 数据/贴图/参考来源、许可状态（可 unknown/internal_only）；不得把仓库 MIT 自动写成所有资产的许可。

生产 accepted 需要真实有效 hash 和存在的文件；示例 manifest 使用 `record_kind=example`，不能导入主集。本包没有提供新生成的真实建筑，示例仅展示格式。

## 8. 标签与训练导出

分别支持三种有明确 schema 的导出：

1. `source_sft.jsonl`：任务/必要约束→本资产 authored source；可引用固定 runtime contract。保留原始语言任务和经核实的最终描述，不随意构造被原任务要求却未实现的目标。
2. `asset_index.jsonl` / 可选 Parquet：样本 ID、instruction、标签、真实图像/体素路径、尺寸/材料、split、质量与 provenance。
3. `repair_pairs.jsonl`：有同一任务/source lineage 与真实前后检查的错误→修正版。单独数据集，不混入普通正例；视觉偏好对需要实际一致任务与人工/可靠证据，不凭两个随机样本自动标胜负。

先导期间可直接 JSONL，不为十万行引入数据仓库。每个 release 有 schema、统计、来源/限制、质量方法和 counts 的 dataset card；导出版本固定，只读可重建。

split 默认约 train/val/test=90/5/5，但按源码衍生 lineage/near-duplicate cluster 分组后分配，不能随机逐行。相同 brief 的 A/B、相同源码派生、旋转材质变体不能跨组泄漏。主题 family 不是 lineage，不要把所有同主题样本塞进同一个 split。

后发现一个 duplicate group 横跨 split：新 release 重新分组或隔离冲突，记录变更；不静默篡改旧 release。用于提示/rubric 调参的校准集标 calibration，不混进最终 blind holdout。评审分数、修复建议和生成器内部答案不应泄漏进训练输入。

## 9. 十万级归档与保留成本

运行期按 hash 前缀分目录，列表/检索走索引，避免每次 UI 请求 glob 全盘。归档与导出流式写入，不能一次加载十万体素/图像。

发布时按**字节**与数量双上限分 shard（建议 256–1024 个资产且约 0.5–1 GiB 一片，先导后调整）；使用可流式读取的标准 tar/JSONL 等既有格式，不自造二进制容器。图像已压缩不再反复高成本压缩。保存清晰 shard index 和校验和；export job 可断点继续且相同配置不会产生不同顺序的清单。需要字节级可重复导出时固定 tar/压缩 header 时间、文件排序与元数据，不能把系统当前时间写入规范化内容。

原始请求/响应按 attempt 留存，可批量 gzip/zstd 和按 run 分片，不为每个 token 建文件。成功资产完整保留；失败保留 brief、源码、响应、错误、预算与 lineage，庞大临时体素/重复预览可按一次授权的保留策略清理。默认不得自动删除旧交接数据或已发布资产；GC 先 dry-run 并只操作受管理临时区域，永不跟随 symlink 到数据根之外。

容量预测必须来自先导：每 accepted 的 canonical/source/preview/trace 平均与 p95 字节，乘目标数量并加失败保留、work-in-progress 和备份余量。不要把“压缩后应该很小”当十万级容量规划。磁盘低水位先停新收费派发并收尾，不等写盘失败才处理。

备份数据库采用一致的在线备份/受控停机流程，不只复制活动中的 .db 而漏掉 WAL。备份 manifest/配置和不可变资产目录，至少有一次恢复到新目录并重建计数的测试。热更新以固定 tag 和 schema 兼容判断进行，不在生产自动 git pull 最新 main。

## 10. 界面验收必须是真实贯通

必须验证浏览器关闭后仍生成、重新打开能恢复；断线显示 stale 且重连补 snapshot；真实一个样本通过后，后端 accepted 数、DB、目录和 UI 恰好一致；失败不计成功；暂停没有假流动；配额/费用未知不显示零；十万条样本仅分页加载、没有全量 JSON 响应。

demo/mock 页面可以用于开发和 CI，但必须显著标明演示，生产构建禁用隐式 mock fallback。真实 API 出错不能静默切换演示数据。前端纯动画不是伪装工作的授权。

[U1] https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events
