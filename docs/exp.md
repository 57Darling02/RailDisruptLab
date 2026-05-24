# RailGraph2Gurobi -> VAE -> RailGraph2Gurobi 实验流程

本文档是当前唯一主流程操作手册。背景和设计先读：

```text
docs/框架优化.md
docs/框架实现Plan.md
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
  --clean > outputs/case_library_builder.log 2>&1
```

输出：

```text
config/batch_case_configs_demo/*.yaml
```

## 3. Check generated case library

```bash
python -u scripts/bench_build.py            --config-root config/batch_case_configs_demo
python -u scripts/bench_solve.py            --config-root outputs/bench_build/case_library > outputs/bench_solve.log 2>&1
python -u scripts/bench_export_timetable.py --config-root outputs/bench_build/case_library > outputs/bench_export_timetable.log 2>&1
python -u scripts/bench_analyze.py          --config-root outputs/bench_build/case_library > outputs/bench_analyze.log 2>&1
```

`bench_build.py` 会自动创建类似 `outputs/bench_build/2026-05-24_19-05-21/` 的目录，并在其中写入 `summary.csv`、`summary.json`、`bench_build.log`；终端输出会同步写入该 log。`case_library` 和 `case_graph_library` 会同时发布到 `outputs/bench_build/` 下的 latest 固定目录。

这些步骤只验证规则样例库能通过原有 `build -> solve -> export-timetable -> analyze` 流程。

## 4. Build math graph library

输出：

```text
outputs/bench_build/<time>/case_library/<case>/config.yaml
outputs/bench_build/<time>/case_library/<case>/<case>.lp
outputs/bench_build/<time>/case_graph_library/graphs/*.json
outputs/bench_build/<time>/case_graph_library/dataset_profile.json
outputs/bench_build/case_library/<case>/config.yaml
outputs/bench_build/case_library/<case>/<case>.lp
outputs/bench_build/case_graph_library/graphs/*.json
outputs/bench_build/case_graph_library/dataset_profile.json
```

`bench_build.py` 同时完成 MILP build 和 VAE math graph build。`outputs/bench_build/case_graph_library/graphs/*.json` 是 VAE 默认训练输入，格式为：

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
python scripts/train_vae.py \
  --graphs-root outputs/bench_build/case_graph_library \
  --epochs 3 \
  --batch-size 12 \
  --message-passing-steps 2
```

训练输出统一写到：

```text
outputs/train/<time>/model.pt
outputs/train/<time>/training_config.json
outputs/train/<time>/schema_summary.json
outputs/train/<time>/history.json
outputs/train/<time>/training.log
outputs/train/model/model.pt
outputs/train/model/training_config.json
outputs/train/model/schema_summary.json
outputs/train/model/history.json
outputs/train/model/training.log
outputs/train/latest_run.txt
```

`training_config.json` 记录本次训练参数，包括 `epochs`、`batch_size`、`hidden_dim`、`latent_dim`、`message_passing_steps`、`lr`、`kl_weight`、`seed` 和输出目录。训练过程中终端会显示进度条，`training.log` 会同步记录每个 step/epoch 的 loss 指标。

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
python scripts/generate_vae.py \
  --checkpoint outputs/train/model/model.pt \
  --context-graphs outputs/bench_build/case_graph_library \
  --num-samples 100 \
  --mode model
```

每次生成都会自动创建一个独立 run 目录：

```text
outputs/generate/YYYY-MM-DD_HH-MM-SS/
outputs/generate/YYYY-MM-DD_HH-MM-SS/math_sample/*.json
outputs/generate/YYYY-MM-DD_HH-MM-SS/generation_config.json
outputs/generate/YYYY-MM-DD_HH-MM-SS/generation_summary.json
outputs/generate/latest_run.txt
```

调试时可以使用 target-copy，不需要训练模型。target-copy 和 model 生成都写入 `outputs/generate`；同一次实验中二者择一执行，或先清理该目录。

```bash
python scripts/generate_vae.py \
  --context-graphs outputs/bench_build/case_graph_library \
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
python scripts/evaluate_vae.py \
  --reference-graphs outputs/bench_build/case_graph_library \
  --generated-graphs outputs/generate/<run> \
  --output outputs/generate/<run>/evaluation.json
```

该步骤保留原 ACM-MILP 中“结构相似性/分布相似性”的评估思想，但只比较当前边界允许的数值图和 task output。注意 `vae_math_generated_graph` 只包含 task output，不包含完整上下文边，因此直接评估时重点看生成 count、anchor 分布和参数分布；求解难度评估仍在 RailGraph2Gurobi 完成 build/solve 后执行：把参考配置和生成配置的 `bench_solve.py --summary-csv` 结果传给 `python scripts/evaluate_vae.py --reference-solve-csv ... --generated-solve-csv ...`。

## 7. Decode and import generated graphs

```bash
python scripts/decode_import_generated_graphs.py \
  --generated-graphs outputs/generate/<run> \
  --base-config config/base_demo.yaml
```

该脚本跨 Linux / Windows 使用同一套命令，内部完成两步：

- 将 `vae_math_generated_graph` 解码为标准 `disturbance_graph`。
- 将 `disturbance_graph` 回灌为 RailGraph2Gurobi YAML config。

输出：

```text
outputs/generate/<run>/math_sample/*.json
outputs/generate/<run>/disturbance_graphs/*.json
outputs/generate/<run>/configs/*.yaml
outputs/generate/<run>/decode_import_summary.csv
outputs/generate/<run>/decode_import_summary.json
```

生成的 YAML 中 `project.output_dir` 指向 `outputs/generate/<run>/case_outputs/<case>/`；该目录由后续 build/solve/export/analyze 创建和填充。

具体铁路语义恢复、速度阈值解释、中断解释和 24h 时间窗校验都由 RailGraph2Gurobi 完成。若生成图缺少 `decode_handle.base_context_path`，可显式传入 `--base-context-path inputs/context_下行计划时刻表.json`。

## 8. Validate generated configs

```bash
python -u scripts/bench_build.py            --config-root outputs/generate/<run>/configs
python -u scripts/bench_solve.py            --config-root outputs/bench_build/case_library --summary-csv outputs/generate/<run>/bench_solve_summary.csv --summary-json outputs/generate/<run>/bench_solve_summary.json > outputs/generate/<run>/bench_solve.log 2>&1
python -u scripts/bench_export_timetable.py --config-root outputs/bench_build/case_library > outputs/generate/<run>/bench_export_timetable.log 2>&1
python -u scripts/bench_analyze.py          --config-root outputs/bench_build/case_library > outputs/generate/<run>/bench_analyze.log 2>&1
```

第 8 步的 `bench_build.py` 会把生成配置再次发布到 `outputs/bench_build/case_library`，所以 solve/export/analyze 统一衔接这个 latest case library。

本文档即当前验收主流程。
