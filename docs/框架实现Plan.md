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
- `core/project_layout.py` 已收敛为新 project 沙箱目录：source、context、scenario_sets、datasets、conf、model。
- `scripts/project.py` 已作为推荐入口，提供 `newproject`、`prepare`、`normal_generate`、`build`、`solve`、`analyze`、`model train` 和合并 decode 的 `generation`。
- `scripts/decode_typed_generated_graph.py` 已能解码单个 `vae_math_generated_graph`。
- `scripts/decode_import_generated_graphs.py` 已能批量完成 generated graph -> disturbance graph -> config。
- `VAE/src` 已扁平化为 reader、model、train、generate、evaluate。
- 原 ACM-MILP 的 MILP 二分图转换、MIS/CA/SetCover 配置、Hydra 训练入口和旧 benchmark 流程已移除。
- VAE 模型已加入 typed message passing，使用 `source_h + target_h + edge_h` 更新节点表示，edge feature 已精简到少数必要关系强度。
- 本地 `acmmilp` 环境已验证 compact graph library reader、单样本短训练、checkpoint 写出、model generate、target-copy 和 evaluate。
- 服务器端 `message_passing_steps = 2/3/4` 消融结果已同步到 `docs/消融实验/报告.md`，当前综合结果以 `steps=2` 最优为准。

完整批量验收仍以 `docs/exp.md` 为准。

## 2. 导出目录

主流程使用显式 project id 和场景/数据/模型 id，不再创建或读取 `latest`。推荐的项目目录是：

```text
projects/<project>/
projects/<project>/source/
projects/<project>/context.json
projects/<project>/scenario_sets/<scenario_set>/
projects/<project>/datasets/<dataset>/
projects/<project>/conf/
projects/<project>/model/<model>/
```

dataset 输出结构是：

```text
projects/<project>/datasets/<dataset>/dataset.json
projects/<project>/datasets/<dataset>/build.csv
projects/<project>/datasets/<dataset>/solve.csv
projects/<project>/datasets/<dataset>/analyze.csv
projects/<project>/datasets/<dataset>/cases/<case>/<case>.lp
projects/<project>/datasets/<dataset>/cases/<case>/<case>.sol
projects/<project>/datasets/<dataset>/cases/<case>/adjusted_timetable.xlsx
```

训练输出结构是：

```text
projects/<project>/model/<model>/graph/context.json
projects/<project>/model/<model>/graph/samples/*.json
projects/<project>/model/<model>/best_model.pt
projects/<project>/model/<model>/training_summary.json
```

git 只保留 `projects/demo/conf/`、`projects/demo/scenario_sets/default/` 和 `projects/demo/source/.gitkeep`。context、非 default 场景集、dataset 和 model 均为本地运行产物。

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

每个 `graph/samples/*.json` 是一个训练样本，也就是 `G_D / R`：

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
  -> 扫描 samples/*.json
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

初始化项目：

```bash
python scripts/project.py newproject demo
```

准备共享 context：

```bash
python scripts/project.py demo prepare
```

生成场景模拟输入：

```bash
python scripts/project.py demo normal_generate
python scripts/project.py demo normal_generate test
```

构建 reference dataset：

```bash
python scripts/project.py demo build reference reference

python scripts/project.py demo solve reference
python scripts/project.py demo analyze reference
```

训练：

```bash
python scripts/project.py demo model train
python scripts/project.py demo model train test
```

模型生成：

```bash
python scripts/project.py demo generation vae_reference generated_reference
```

## 7. 生成实例相似性评估计划

生成实例是否“学到位”不能只看图指标和求解时间。图指标能说明生成的 task output 是否在数量、锚点和关系上接近参考集；求解时间能说明生成实例是否在求解难度上接近参考集。但论文评估还需要同时覆盖扰动场景本身、MILP 规模和求解行为，避免模型只学到表面图统计，却没有复现真实扰动分布和优化问题难度。

评估应分成四类：

- 图结构相似性：节点数、边数、任务数量、锚点分布、任务关系。
- 扰动场景相似性：晚点时长、限速开始时间、限速持续时间、限速值、中断发生时间。
- MILP 规模相似性：变量数、约束数、非零系数数、构建耗时。
- 求解行为相似性：求解状态、求解时间、目标值、MIP gap、可行解发现情况、分支节点数。

关键口径：

- 晚点时长不是 context graph 的拓扑结构。它是 task output 的扰动参数，训练样本中对应 delay task 的参数，解码后对应 `DelayScenario.seconds`。因此晚点时长应作为扰动场景参数分布评估，而不是归入节点/边拓扑指标。
- 限速中断可从 speed limit 任务中单独拆出：当解码后的 `limit_speed == 0` 时，将其视为中断；当 `limit_speed > 0` 时，将其视为普通限速。
- “发生时间点 JS 散度”是合理指标，适合比较晚点、限速和中断在一天内不同时间段的概率分布。但时间、站点顺序和区间顺序都是有序变量，单独使用 JS 散度会丢失相邻 bin 的距离信息，所以应同时报告 Wasserstein/EMD 或 KS statistic。
- 新入口 `scripts/project.py <project> solve <dataset>` 已在 `solve.csv` 中记录 Gurobi `NodeCount`，字段名为 `num_nodes`；time limit 且无可行解的记录也会尽量保留节点数。历史报告里没有该字段的 run 仍会跳过分支节点数。

建议指标口径如下：

| 维度 | 指标 | 推荐比较方法 |
|---|---|---|
| 扰动数量 | 总扰动数、晚点数、限速数、中断数 | JS 散度、均值/方差相对误差 |
| 晚点参数 | 晚点时长、晚点发生时间、晚点站点分布 | JS 散度、Wasserstein、KS |
| 限速参数 | 开始时间、持续时长、限速值、区间分布 | JS 散度、Wasserstein、KS |
| 中断参数 | 中断次数、开始时间、持续时长、区间分布 | JS 散度、Wasserstein |
| 联合结构 | 扰动类型 × 时间段、站点顺序 × 时间段、区间顺序 × 时间段 | 联合直方图 JS 散度 |
| MILP 规模 | 变量数、约束数、非零系数数 | 相对误差、分布距离 |
| 求解行为 | 状态、时间、目标值、gap、可行解时间、分支节点数 | 状态余弦距离、相对误差、JS/KS |

这些指标的使用方式：

- JS 散度用于类别分布和分箱后的连续变量，例如扰动类型、发生时间段、晚点时长区间、限速持续时间区间。
- Wasserstein/EMD 用于有自然顺序的连续或离散变量，例如发生时间、晚点时长、限速持续时长、站点顺序和区间顺序。
- KS statistic 用于辅助判断一维连续分布形状是否接近，尤其适合晚点时长、持续时长和求解时间。
- 状态余弦距离用于比较求解状态分布，例如 optimal、feasible、timeout、infeasible 的比例是否接近。
- 相对误差用于比较均值类指标，例如平均变量数、平均约束数、平均求解时间和平均目标值。

`message_passing_steps = 2/3/4` 的生成、build、solve 和相似性评估结果已经回填到 `docs/消融实验/报告.md`。当前报告显示 `steps=2` 的综合误差最低、相似度最高；原始 run 产物不随当前仓库保留，复现实验仍按 `docs/exp.md` 重新生成 `projects/<project>/` 产物。

## 8. 当前状态

已完成：

- project layout 已切换到 `source/`、共享 `context.json`、`scenario_sets/`、`datasets/`、`conf/`、`model/`。
- `model train` 会在模型目录内生成 `graph/context.json`、`graph/samples/*.json` 和 `graph/dataset_profile.json`。
- `context.json` 的 `rules.tasks` 会由训练 scenario set 的 learning samples 推断 `max_slots`、`count_bounds` 和 `param_bounds`。
- 显式共享 context：`projects/<project>/context.json`。
- 显式 scenario set 工程目录：`projects/<project>/scenario_sets/<scenario_set>`。
- 显式 dataset 工程目录：`projects/<project>/datasets/<dataset>`。
- 显式训练工程目录：`projects/<project>/model/<model>`。
- `generation` 已合并 model generate 和 decode，直接输出 scenario set。
- VAE 训练同时写出 `best_model.pt` 和 `last_model.pt`，生成默认使用 best checkpoint。
- `projects/demo/conf/` 管理 prepare、solve、analyze、normal_generate 和 train 参数。
- `projects/demo/scenario_sets/default/` 管理手写 demo 场景输入。
- `project.py demo prepare` 生成共享 context，`project.py demo normal_generate` 生成命名 scenario set，流程产物不再写入 `inputs/` 或 `config/`。
- speed 维度按 `speed_limit / 350` 归一化后进入训练样本。
- VAE reader 支持共享 context + 多 learning sample。
- VAE generation reader 支持只读 context graph。
- VAE typed message passing 已接入 `edge_index + edge_attr`。
- model generate 的中间 math graph 保留在 `projects/<project>/model/<model>/generated/`，最终输出为 `scenario_sets/<scenario_set>/*.yml`。
- target-copy 作为管道连通性检查保留。
- generated graph 可解码为 disturbance graph，并批量回灌为 config。
- evaluate 支持 graph/task output 相似性和 solver CSV 难度对比入口。
- 消融实验报告已回填到 `docs/消融实验/报告.md`，当前结论是 `message_passing_steps = 2` 综合相似度最高。
- 本地 `acmmilp` 环境已跑通过：
  - compact graph library reader
  - VAE dataset load
  - 单样本短训练
  - checkpoint 写出
  - model generate
  - target-copy
  - graph/task output evaluation
  - `project.py demo build default smoke_dataset`
- 2026-05-26 本地非破坏性检查已通过：
  - 54 个 Python 文件语法检查通过。
  - `main.py --help` 和 `scripts/project.py --help` 可正常启动。
  - `projects/demo/context.json` 的 BaseContext 可加载，当前下行 BaseContext 含 1560 个 event anchor 和 5 个 section anchor。
  - `projects/demo/scenario_sets/default/` 可展开为 5 个 demo 场景：base、delay、interruptions、mixed、speed_limits。
  - `project.py demo solve smoke_dataset --limit 1 --time-limit 1` 输出字段包含 `num_nodes`，用于记录 Gurobi 分支节点数。

待完整批量验收：

- 当前本地仓库没有保留历史运行产物，完整复现需要重新生成 `projects/<project>/` 下的命名产物。
- 全量 `scripts/project.py demo build reference reference`。
- 全量 `scripts/project.py demo solve reference`。
- 全量 `scripts/project.py demo analyze reference`。
- 全量 VAE 训练。
- 全量 `scripts/project.py demo generation <model_id> <scenario_set_id>`。
- reference 和 generated solver CSV 对比。

验收步骤以 `docs/exp.md` 为准。
