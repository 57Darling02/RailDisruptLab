# RailGraph2Gurobi -> VAE -> RailGraph2Gurobi 实验流程

本文档是操作手册。背景和设计先读：

```text
docs/框架优化.md
docs/框架实现Plan.md
```

如果只想验收当前代码，直接读：

```text
docs/test.md
```

本文档记录当前主链路。核心边界是：

```text
RailGraph2Gurobi:
  railway semantics -> mathematical rules + numeric graph

VAE:
  read math graph -> train -> generate math graph

RailGraph2Gurobi:
  generated math graph -> disturbance_graph -> config -> MILP validation
```

VAE 子模块不读取铁路语义字符串，不解析 anchor id，不生成 YAML/LP/MPS。铁路语义只在 RailGraph2Gurobi 中编译和恢复。

## 1. Prepare BaseContext

```bash
python scripts/prepare_base_context.py \
  --timetable-path inputs/下行计划时刻表.xlsx \
  --mileage-path inputs/区间里程.xlsx
```

输出：

```text
inputs/context_下行计划时刻表.json
```

## 2. Generate case configs

```bash
python -u scripts/case_library_builder.py \
  --output-root config/batch_case_configs_demo \
  --project-output-root outputs/case_library \
  --clean > outputs/case_library_builder.log 2>&1
```

输出：

```text
config/batch_case_configs_demo/*.yaml
```

## 3. Check generated case library

```bash
python -u scripts/bench_build.py            --config-root config/batch_case_configs_demo > outputs/bench_build.log 2>&1
python -u scripts/bench_solve.py            --config-root config/batch_case_configs_demo > outputs/bench_solve.log 2>&1
python -u scripts/bench_export_timetable.py --config-root config/batch_case_configs_demo > outputs/bench_export_timetable.log 2>&1
python -u scripts/bench_analyze.py          --config-root config/batch_case_configs_demo > outputs/bench_analyze.log 2>&1
```

这些步骤只验证规则样例库能通过原有 `build -> solve -> export-timetable -> analyze` 流程。

## 4. Export math VAE dataset

```bash
python scripts/export_typed_vae_learning_graph.py \
  --config-glob "config/batch_case_configs_demo/**/*.yaml" \
  --output-dir outputs/vae_math_dataset
```

输出：

```text
outputs/vae_math_dataset/graphs/*.json
outputs/vae_math_dataset/dataset_profile.json
```

`outputs/vae_math_dataset/graphs/*.json` 是 VAE 唯一训练输入，格式为：

```text
vae_math_learning_graph
```

主文件只包含：

- `decode_handle`
- `rules`
- `graph.pool_x`
- `graph.edges`
- `supervision.targets`
- `supervision.target_relations`

`dataset_profile.json` 与同一个 `base_context_path` 绑定，只生成一份。它用于排查和解释，包含 anchor id、feature name、task/edge 说明、source config 列表、导出参数和 decode contract。VAE reader 不读取 profile。

## 5. Train VAE

```bash
cd VAE

python -m src.train \
  --graphs-root ../outputs/vae_math_dataset \
  --output-dir outputs/math_graph_vae \
  --epochs 3 \
  --batch-size 1 \
  --message-passing-steps 2
```

VAE 训练职责：

- 读取 numeric pool feature matrix。
- 读取 numeric edge list 和 edge feature。
- 读取 numeric task rules。
- 使用 `--message-passing-steps` 控制沿图边聚合邻居信息的轮数；默认 2 轮。
- 使用 `supervision.targets` 监督 count、anchor index、params。
- 可选使用 `supervision.target_relations` 编码真实扰动之间的数学关系。

通俗地说，message passing 会让每个候选锚点先看自己的数值特征，再沿着 `graph.edges` 接收邻居锚点的信息。边特征会告诉模型这条关系是什么，例如同车、同站、时间接近、区间相邻或车次路径经过区间。

VAE 不读取：

- `feature_names`
- `ids`
- `debug`
- `source_config_path`
- `decode_contract`
- 任何铁路业务字符串

## 6. Generate math graphs

```bash
python -m src.generate \
  --checkpoint outputs/math_graph_vae/model.pt \
  --context-graphs ../outputs/vae_math_dataset \
  --output-dir ../outputs/generated_math_graphs \
  --num-samples 100 \
  --mode model
```

调试时可以使用 target-copy，不需要训练模型：

```bash
python -m src.generate \
  --context-graphs ../outputs/vae_math_dataset \
  --output-dir ../outputs/generated_math_graphs_target_copy \
  --num-samples 10 \
  --mode target-copy
```

生成格式为：

```text
vae_math_generated_graph
```

每个样本只包含 `decode_handle` 和 numeric `task_outputs`。

## 6.5 Evaluate generated graphs

```bash
cd VAE

python -m src.evaluate \
  --reference-graphs ../outputs/vae_math_dataset \
  --generated-graphs ../outputs/generated_math_graphs \
  --output ../outputs/generated_math_graphs/evaluation.json

cd ..
```

该步骤保留原 ACM-MILP 中“结构相似性/分布相似性”的评估思想，但只比较当前边界允许的数值图和 task output。注意 `vae_math_generated_graph` 只包含 task output，不包含完整上下文边，因此直接评估时重点看生成 count、anchor 分布和参数分布；求解难度评估仍在 RailGraph2Gurobi 完成 build/solve 后执行：把参考配置和生成配置的 `bench_solve.py --summary-csv` 结果传给 `python -m src.evaluate --reference-solve-csv ... --generated-solve-csv ...`。

## 7. Decode and import generated graphs

```powershell
cd ..

New-Item -ItemType Directory -Force `
  outputs/generated_disturbance_graphs, `
  config/generated_vae_configs | Out-Null

Get-ChildItem outputs/generated_math_graphs -Filter *.json | ForEach-Object {
  $stem = $_.BaseName
  $disturbanceGraph = "outputs/generated_disturbance_graphs/$stem.json"
  $configPath = "config/generated_vae_configs/$stem.yaml"

  python scripts/decode_typed_generated_graph.py `
    --typed-graph $_.FullName `
    --output-disturbance-graph $disturbanceGraph

  python scripts/import_disturbance_graph.py `
    --graph $disturbanceGraph `
    --base-config config/base_demo.yaml `
    --output-config $configPath
}
```

`decode_typed_generated_graph.py` 文件名保持兼容，但现在可解码 `vae_math_generated_graph`。具体铁路语义恢复、速度阈值解释、中断解释和 24h 时间窗校验都由 RailGraph2Gurobi 完成。

## 8. Validate generated configs

```bash
python -u scripts/bench_build.py            --config-root config/generated_vae_configs > outputs/generated_bench_build.log 2>&1
python -u scripts/bench_solve.py            --config-root config/generated_vae_configs > outputs/generated_bench_solve.log 2>&1
python -u scripts/bench_export_timetable.py --config-root config/generated_vae_configs > outputs/generated_bench_export_timetable.log 2>&1
python -u scripts/bench_analyze.py          --config-root config/generated_vae_configs > outputs/generated_bench_analyze.log 2>&1
```

完整服务器验证流程见 `docs/test.md`。
