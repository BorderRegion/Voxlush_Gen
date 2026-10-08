# 数据格式基线

本目录是 `task.v1` / `asset.v1` 的机器可读规范。示例在 ../examples/，全部明确标注 example/fixture；没有宣称存在新的真实合格建筑。

JSON Schema 处理字段、类型、枚举和部分 accepted 条件。以下跨字段/文件约束必须由实际生成器的 `verify_asset` 处理，不能宣称 schema 已覆盖：

- 任务 theme_seed_id 存在且 scene_type/quality_contract 合理；legacy 合同只用于明确保留的集合。
- 当前 voxel hash 等于图像审核的 input_voxel_sha256，预览 hash 对应实际审核文件。
- 文件必须位于受管理目录，防止路径穿越、symlink 跳出；内容 hash/大小正确。
- coords 数组、palette、component 引用与 canonical hash 一致，源码可复现。
- accepted 具有所需类型的 source、voxel、metadata、geometry、review、preview 工件，而非仅够文件数量。
- 任务质量合同、runtime/renderer/rubric 版本匹配；模型配置已获得资格。
- accepted_unique、lineage/duplicate 与发布切分通过事务和去重一致性检查。

这些约束应合并在正常归档验收中一次执行，不额外给每个条件开一轮 agent 评审。代码里避免重复维护前后端字段：运行模型生成接口/schema；如果需要改变本基线，显式升级 schema 并提供迁移与回归用例。
