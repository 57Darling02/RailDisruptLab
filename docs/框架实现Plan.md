# 数学化 VAE 接口实现计划

## 接手摘要

本项目已经从“让 VAE 生成 MILP 约束矩阵”转为“让 VAE 在铁路上下文条件下生成扰动数学图”。RailGraph2Gurobi 负责把铁路语义编译为数学规则，也负责把 VAE 输出解码回铁路扰动；VAE 模块只负责读数学样本、训练、生成数学样本。

代码当前状态：

- `core/vae_learning_graph.py` 已能生成 `vae_math_learning_graph` 和 `vae_math_dataset_profile`。
- `scripts/bench_build.py` 现在统一 build MILP `case_library` 和 VAE `case_graph_library`，并发布 latest 固定目录。
- `scripts/decode_typed_generated_graph.py` 已能解码单个 `vae_math_generated_graph`。
- `scripts/decode_import_generated_graphs.py` 已能批量完成 generated graph -> disturbance graph -> config。
- `VAE/src` 已扁平化为数学 reader、VAE 模型、训练入口、生成入口和评估入口。
- 原 ACM-MILP 的 MILP 二分图转换、MIS/CA/SetCover 配置、Hydra 训练入口和旧 benchmark 流程已移除。
- VAE 模型已使用 typed message passing：节点先看自己的特征，再沿 `graph.edges.edge_index` 接收相邻节点和边特征的信息。
- `src.evaluate` 已保留结构/分布相似性与求解难度评估入口；求解难度读取 RailGraph2Gurobi `bench_solve.py --summary-csv`。
- 本机无 torch，只验证了不依赖 torch 的链路；服务器验收以 `docs/exp.md` 为准。

## Summary

当前工程边界调整为：

```text
RailGraph2Gurobi:
  负责铁路语义、锚点、规则、解码、回灌、MILP 验证

VAE:
  只读取数学规则和数值图
  只训练和生成数学 task output
```

RailGraph2Gurobi 导出两个文件：

- `graphs/*.json`: 每个文件都是一个 `vae_math_learning_graph`，是 VAE 主输入。
- `dataset_profile.json`: `vae_math_dataset_profile`，与 BaseContext 绑定的解释文件；一个 dataset 只生成一份。

## Math Learning Graph

VAE 主输入结构：

```json
{
  "schema_version": 1,
  "graph_type": "vae_math_learning_graph",
  "decode_handle": {},
  "rules": {},
  "graph": {},
  "supervision": {}
}
```

字段含义：

- `decode_handle`: 不透明句柄，只复制到生成结果，VAE 不学习。
- `rules.pools`: pool id、pool size、feature dim。
- `rules.edge_types`: edge type id、source pool、target pool、feature dim。
- `rules.tasks`: task id、target pool id、max slots、param dim、数值参数边界。
- `graph.pool_x`: 每个 pool 的数值特征矩阵。
- `graph.edges`: pool index 之间的数值边。
- `supervision.targets`: count、anchor index、params。
- `supervision.target_relations`: 训练侧可用的数值关系特征。

主文件不包含：

- anchor id
- feature name
- param name
- debug
- source config
- decode contract
- event/section/delay/speed/station/train 等铁路语义字符串

## VAE Implementation

VAE reader 只接受 `graph_type == "vae_math_learning_graph"`，构造内部 `MathGraphSample`：

- `pool_x: Dict[int, Tensor]`
- `edges: Dict[int, EdgeBatch]`
- `pool_rules / edge_type_rules / task_rules`
- `targets`
- `target_relation_x`

模型结构：

- context encoder 编码 pool feature，并通过 typed message passing 聚合 edge feature 和邻居节点信息。
- target encoder 训练时编码真实 count、anchor index、params 和 relation feature。
- prior 学习 `p(z | C)`。
- posterior 学习 `q(z | C, G_D, R)`。
- decoder 输出每个 task 的 count logits、pool-specific anchor logits、param vectors。

消息传递实现细节：

```text
raw event feature(6维)    -> event encoder  -> hidden_dim
raw section feature(4维)  -> section encoder -> hidden_dim
raw edge feature          -> edge encoder    -> hidden_dim
```

所有节点先被投影到同一个 `hidden_dim`，所以后续不是在原始 6 维/4 维空间里硬聚合，而是在统一隐空间里聚合。

每一轮 message passing 的逻辑是：

```text
for each edge_type:
  edge_h = edge_encoder(edge_attr)
  msg_forward = forward_message_layer([source_node_h, edge_h])
  aggregate msg_forward to target node by edge_index

  if edge.directed == false:
    msg_reverse = reverse_message_layer([target_node_h, edge_h])
    aggregate msg_reverse to source node

for each pool:
  agg = mean(incoming_messages)
  update = pool_update_layer([old_node_h, agg])
  new_node_h = LayerNorm(old_node_h + update)
```

几个关键点：

- event-event 和 section-section 是同池聚合。
- event-section 是跨池聚合；event 和 section 原始特征维度不同，但进入模型后都在 `hidden_dim` 中，所以可以通过类型专属 message layer 传递。
- edge type 不共享参数；event-event、section-section、event-section 各自有 edge encoder 和 message layer。
- 当前导出的上下文边是无向语义边，模型会做 forward 和 reverse 两个方向的消息。
- `--message-passing-steps 2` 表示重复两轮。第一轮看直接邻居，第二轮能间接看到邻居的邻居。

因此当前模型不是只做全局均值池化；`edge_index` 已经参与节点表示更新。最后才对更新后的 pool embeddings 做 mean pooling，形成 context 向量。

分池预测器规则：

- 每个 task 只对 `target_pool_id` 指向的 pool 打 anchor 分数。
- 不使用候选合法性语义 mask。
- `max_slots` 只是固定张量上限；loss 只对真实 `count` 范围内的 slot 计算 anchor/param 监督。

## Generated Graph

VAE 输出：

```json
{
  "schema_version": 1,
  "graph_type": "vae_math_generated_graph",
  "decode_handle": {},
  "task_outputs": {
    "0": {"count": 2, "anchor_index": [1, 2], "params": [[...], [...]]},
    "1": {"count": 4, "anchor_index": [0, 2, 1, 4], "params": [[...]]}
  }
}
```

RailGraph2Gurobi 读取 `decode_handle + task_outputs`，恢复标准 `disturbance_graph`，再回灌为 scenario config。

## Current Status

已完成：

- RailGraph2Gurobi 可导出 `vae_math_learning_graph` 和 `dataset_profile.json`。
- 解码脚本可接受 `vae_math_generated_graph`。
- VAE reader/model/train/generate/evaluate 已迁移到数学接口，并扁平化到 `VAE/src`。
- VAE 模型已加入 typed message passing，使用 `edge_index + edge_attr` 聚合邻居信息。
- 原 ACM-MILP 旧流程已清理，不再保留 MILP -> constraint-variable bipartite graph -> 修改 MILP 的入口。
- 本地已验证不依赖 torch 的链路：
  - math graph export
  - target-copy generated math graph
  - graph/task output evaluation
  - decode to `disturbance_graph`
  - import to config
  - `main.py build`

待服务器验证：

- VAE dataset load。
- 单样本 forward/backward，确认 message passing loss finite。
- 短训练，确认 checkpoint 可保存。
- model generate。
- 解码、回灌、build/solve/export/analyze 全链路。

服务器验证步骤见 `docs/exp.md`。
