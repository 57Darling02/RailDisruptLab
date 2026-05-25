# 数学化 VAE 接口实现计划

这篇文档只记录工程实现和项目进度。框架思想见 `docs/框架优化.md`，完整验收命令见 `docs/exp.md`。

## 1. 当前结论

项目已经从“让 VAE 生成 MILP 约束矩阵”调整为“让 VAE 在铁路上下文条件下生成扰动数学图”。

当前工程边界是：

```text
RailGraph2Gurobi:
  负责铁路语义、锚点、规则、解码、回灌和 MILP 验证

VAE:
  只读取数学规则和数值图
  只训练和生成数学 task output
```

当前已完成的主线：

- `core/vae_learning_graph.py` 已能从 scenario config 导出共享 `vae_math_context_graph`、逐样本 `vae_math_learning_sample` 和 `vae_math_dataset_profile`。
- `scripts/bench_build.py` 已统一完成 build run 构建，并把 `outputs/bench_build/latest` 作为 latest 软连接。
- `scripts/decode_typed_generated_graph.py` 已能解码单个 `vae_math_generated_graph`。
- `scripts/decode_import_generated_graphs.py` 已能批量完成 generated graph -> disturbance graph -> config。
- `VAE/src` 已扁平化为 reader、model、train、generate、evaluate。
- 原 ACM-MILP 的 MILP 二分图转换、MIS/CA/SetCover 配置、Hydra 训练入口和旧 benchmark 流程已移除。
- VAE 模型已加入 typed message passing，使用 `source_h + target_h + edge_h` 更新节点表示，edge feature 已精简到少数必要关系强度。
- 本地 `acmmilp` 环境已验证 compact graph library reader、单样本短训练、checkpoint 写出、model generate、target-copy 和 evaluate。

完整批量验收仍以 `docs/exp.md` 为准。

## 2. 导出目录

`bench_build.py` 每次只生成一个 timestamp run。这个 run 里同时放构建用配置、LP 样本和 VAE 训练样本。

输出结构是：

```text
outputs/bench_build/<time>/configs/*.yaml
outputs/bench_build/<time>/lp_simples/<case>/<case>.lp
outputs/bench_build/<time>/graph_samples/*.json
outputs/bench_build/<time>/context.json
outputs/bench_build/<time>/dataset_profile.json
outputs/bench_build/<time>/summary.csv
outputs/bench_build/<time>/summary.json
outputs/bench_build/<time>/bench_build.log

outputs/bench_build/latest -> outputs/bench_build/<time>
```

`latest` 只是指向最新 run 的软连接，不再复制目录。后续 `bench_solve`、`bench_export_timetable`、`bench_analyze` 都读：

```text
outputs/bench_build/latest/configs
```

latest 软连接只有在本次 build 全部成功时才更新。

## 3. JSON 接口

### 3.1 Context Graph

`context.json` 是共享上下文，也就是 `C`：

```json
{
  "schema_version": 1,
  "graph_type": "vae_math_context_graph",
  "decode_handle": {},
  "rules": {},
  "graph": {}
}
```

字段说明：

- `decode_handle`: 不透明句柄，VAE 不学习，只复制到生成结果。
- `rules.pools`: pool id、pool size、feature dim。
- `rules.edge_types`: edge type id、source pool、target pool、feature dim。
- `rules.tasks`: task id、target pool id、max slots、param dim、参数边界和约束。
- `rules.target_relation_feature_dim`: 训练辅助关系的特征维度。
- `graph.pool_x`: 每个 pool 的数值特征矩阵。
- `graph.edges`: pool index 之间的数值边。

`context.json` 不包含：

- anchor id
- feature name
- param name
- debug
- source config
- decode contract
- 车次、站名、区间名、delay、speed 等铁路语义字符串

### 3.2 Learning Sample

每个 `graph_samples/*.json` 是一个训练样本，也就是 `G_D / R`：

```json
{
  "schema_version": 1,
  "graph_type": "vae_math_learning_sample",
  "context_ref": "context.json",
  "supervision": {
    "targets": {},
    "target_relations": []
  }
}
```

字段说明：

- `context_ref`: 指向共享 `context.json`。
- `supervision.targets`: 每个 task 的 `count`、`anchor_index`、`params`。
- `supervision.target_relations`: 训练辅助关系，包含 `left_task_id`、`left_slot`、`right_task_id`、`right_slot` 和数值特征 `x`。

sample 不重复保存 `rules`、`graph.pool_x` 和 `graph.edges`。

### 3.3 Dataset Profile

`dataset_profile.json` 是解释文件，不是 VAE 输入。

它保存：

- pool 行号到 anchor id 的映射。
- feature names。
- task、param、edge 的可读说明。
- source config 列表。
- export 参数。
- decode contract。
- debug 信息。

VAE reader 不读取 profile。

### 3.4 Generated Graph

VAE 输出 `vae_math_generated_graph`：

```json
{
  "schema_version": 1,
  "graph_type": "vae_math_generated_graph",
  "decode_handle": {},
  "task_outputs": {
    "0": {
      "count": 1,
      "anchor_index": [15],
      "params": [[0.0069]]
    },
    "1": {
      "count": 1,
      "anchor_index": [3],
      "params": [[0.35, 0.04, 0.22857143]]
    }
  }
}
```

RailGraph2Gurobi 读取 `decode_handle + task_outputs`，恢复标准 `disturbance_graph`，再回灌为 scenario config。

## 4. VAE Reader

训练 reader：

```text
RailDisturbanceDataset(graphs_root)
  -> 读取 context.json
  -> 扫描 graph_samples/*.json
  -> 每个样本组合成 MathGraphSample
```

生成 reader：

```text
RailDisturbanceContextDataset(context_graph 或 compact graph library)
  -> 只读取 vae_math_context_graph
  -> 构造空 targets，复用 decoder 输出格式
```

内部统一使用 `MathGraphSample`：

```text
pool_x: Dict[int, Tensor]
edges: Dict[int, EdgeBatch]
pool_rules / edge_type_rules / task_rules
targets: Dict[int, TargetData]
target_relation_index: Tensor
target_relation_x: Tensor
```

`EdgeBatch` 中的关键字段：

```text
edge_index: [2, num_edges]
edge_attr:  [num_edges, feature_dim]
directed:   [num_edges]
```

这里 `edge_index[0]` 是 source index，`edge_index[1]` 是 target index。

## 5. VAE Model

模型入口在 `VAE/src/model.py`。

### 5.1 Context Encoder

先把不同来源的原始特征投影到同一维度：

```text
event raw feature    6维 -> pool encoder -> hidden_dim
section raw feature  4维 -> pool encoder -> hidden_dim
edge raw feature      N维 -> edge encoder -> hidden_dim
```

当前 encoder 是两层 MLP：

```text
Linear -> ReLU -> Linear -> ReLU
```

默认参数：

```text
hidden_dim = 64
latent_dim = 16
message_passing_steps = 2
```

### 5.2 Typed Message Passing

每一轮消息传递按 edge type 单独做：

```text
edge_attr -> edge_encoder -> edge_h
source_node_h + target_node_h + edge_h -> message layer -> message
message 按 target index 聚合

如果 directed = false:
  target_node_h + source_node_h + edge_h -> reverse message layer -> reverse message
  reverse message 按 source index 聚合
```

节点更新：

```text
agg = incoming messages 的平均值
new_node = LayerNorm(old_node + update_layer([old_node, agg]))
```

关键点：

- event-event、section-section、event-section 三类边不共享 message layer。
- event-section 可以跨 pool 传递，因为节点和边都先投影到了 `hidden_dim`。
- `message_passing_steps = 2` 表示重复两轮，节点能看到直接邻居和部分间接邻居信息。
- 最后才对更新后的 pool embeddings 做 mean pooling。

### 5.3 Context 向量

context encoder 的输出是：

```text
每个 pool 一个 mean-pooled 向量
每类 edge 一个 mean-pooled 向量
拼接成 context
```

当前默认有 2 个 pool 和 3 类 edge，所以：

```text
context_dim = hidden_dim * (2 + 3) = 64 * 5 = 320
```

### 5.4 Target Encoder

训练时，target encoder 读取：

```text
count
anchor_index
params
target_relations
```

这些内容只来自 `vae_math_learning_sample`。生成时没有 target，模型只使用 prior。

### 5.5 Prior / Posterior / Decoder

训练：

```text
context -> prior_mu / prior_logvar
context + target -> posterior_mu / posterior_logvar
posterior sample z -> decoder
```

生成：

```text
context -> prior_mu / prior_logvar
prior sample z -> decoder
```

decoder 对每个 task 输出：

```text
count_logits
anchor_logits
params
```

anchor 预测是分池的：

```text
task_id -> target_pool_id
slot query @ target_pool_embeddings.T -> anchor logits
```

所以 task 0 只在 event pool 里选，task 1 只在 section pool 里选。

### 5.6 Loss

训练 loss 包含：

```text
count_loss   = cross entropy
anchor_loss  = cross entropy，只计算真实 count 范围内的 slot
param_loss   = smooth L1，只计算真实 count 范围内的 slot
kl           = posterior 和 prior 的 KL
```

总损失：

```text
loss =
  count_weight * count_loss
  + anchor_weight * anchor_loss
  + param_weight * param_loss
  + kl_weight * kl
```

`max_slots` 只是张量上限。超过真实 `count` 的 slot 是 padding，不参与 anchor 和 param loss。

## 6. 脚本入口

生成场景模拟输入：

```bash
python -u scripts/case_library_builder.py \
  --output-root config/batch_case_configs_demo \
  --clean
```

构建 reference build run：

```bash
python -u scripts/bench_build.py --config-root config/batch_case_configs_demo
```

训练：

```bash
python scripts/train_vae.py
```

也可以显式指定配置：

```bash
python scripts/train_vae.py config/train.yml
```

`config/train.yml` 保存训练输入目录、模型维度、优化参数和 loss 权重。训练脚本不再接受零散训练参数，避免同一套实验参数散落在命令行里。

模型生成：

```bash
python scripts/generate_vae.py \
  --checkpoint outputs/train/latest/best_model.pt \
  --context-graph outputs/bench_build/latest/context.json \
  --num-samples 100 \
  --mode model
```

target-copy 调试生成：

```bash
python scripts/generate_vae.py \
  --context-graphs outputs/bench_build/latest \
  --num-samples 10 \
  --mode target-copy
```

评估：

```bash
python scripts/evaluate_vae.py \
  --reference-graphs outputs/bench_build/latest \
  --generated-graphs outputs/generate/latest \
  --output outputs/generate/latest/evaluation.json
```

解码并回灌配置：

```bash
python scripts/decode_import_generated_graphs.py \
  --generated-graphs outputs/generate/latest \
  --base-config config/base_demo.yaml
```

## 7. 当前状态

已完成：

- timestamp build run 的 `context.json`、`graph_samples/*.json` 和 `dataset_profile.json` 导出。
- `context.json` 的 `rules.tasks` 会由本次 build 的 learning samples 推断 `max_slots`、`count_bounds` 和 `param_bounds`。
- `outputs/bench_build/latest` latest build run 软连接发布。
- `outputs/train/latest` latest training run 软连接发布。
- VAE 训练同时写出 `best_model.pt` 和 `last_model.pt`，生成默认使用 best checkpoint。
- `config/train.yml` 统一管理训练输入、模型维度、优化参数和 loss 权重。
- speed 维度按 `speed_limit / 350` 归一化后进入训练样本。
- VAE reader 支持共享 context + 多 learning sample。
- VAE generation reader 支持只读 context graph。
- VAE typed message passing 已接入 `edge_index + edge_attr`。
- model generate 输出 `outputs/generate/<run>/math_sample/*.json`，并发布 `outputs/generate/latest` 软连接。
- target-copy 作为管道连通性检查保留。
- generated graph 可解码为 disturbance graph，并批量回灌为 config。
- evaluate 支持 graph/task output 相似性和 solver CSV 难度对比入口。
- 本地 `acmmilp` 环境已跑通过：
  - compact graph library reader
  - VAE dataset load
  - 单样本短训练
  - checkpoint 写出
  - model generate
  - target-copy
  - graph/task output evaluation
  - `bench_build.py --limit 1`

待完整批量验收：

- 全量 `bench_build.py`。
- 全量 VAE 训练。
- 全量 model generate。
- generated graph 批量 decode/import。
- 生成配置的 build/solve/export/analyze。
- reference 和 generated solver CSV 对比。

验收步骤以 `docs/exp.md` 为准。
