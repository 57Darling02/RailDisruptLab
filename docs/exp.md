# RailGraph2Gurobi -> VAE -> RailGraph2Gurobi 验收流程

本文档是当前主流程的验收手册。核心约定：

- `config/batch_case_configs_demo` 只保存场景模拟输入，不是主流程产物目录。
- `bench_build.py` 每次只生成一个 timestamp run。
- `outputs/bench_build/latest` 是指向最新 build run 的软连接。
- `outputs/train/latest` 是指向最新训练 run 的软连接，生成默认使用 `outputs/train/latest/best_model.pt`。
- `outputs/generate/latest` 是指向最新生成 run 的软连接。
- VAE 训练只读 `config/train.yml`，训练参数不再散落在命令行里。

## 1. Prepare BaseContext

```bash
python scripts/prepare_base_context.py \
  --timetable-path inputs/下行计划时刻表.xlsx \
  --mileage-path inputs/区间里程.xlsx
```

验收产物：

```text
inputs/context_下行计划时刻表.json
```

## 2. Generate Scenario Inputs

```bash
python -u scripts/case_library_builder.py \
  --output-root config/batch_case_configs_demo \
  --clean > outputs/case_library_builder.log 2>&1
```

这些 YAML 只用于模拟扰动场景，后续真实 build 产物由 `bench_build.py` 统一接管。

验收产物：

```text
config/batch_case_configs_demo/*.yaml
outputs/case_library_builder.log
```

## 3. Build Reference Library

```bash
python -u scripts/bench_build.py \
  --config-root config/batch_case_configs_demo
```

每次 build 创建：

```text
outputs/bench_build/<time>/
outputs/bench_build/<time>/configs/*.yaml
outputs/bench_build/<time>/lp_simples/<case>/<case>.lp
outputs/bench_build/<time>/graph_samples/*.json
outputs/bench_build/<time>/context.json
outputs/bench_build/<time>/dataset_profile.json
outputs/bench_build/<time>/summary.csv
outputs/bench_build/<time>/summary.json
outputs/bench_build/<time>/bench_build.log
```

同时更新 latest 软连接：

```text
outputs/bench_build/latest -> outputs/bench_build/<time>
```

通过标准：

- `summary.csv` 中没有 failed。
- `outputs/bench_build/latest` 是软连接。
- `outputs/bench_build/latest/context.json` 的 `graph_type` 是 `vae_math_context_graph`。
- `outputs/bench_build/latest/context.json` 的 `rules.tasks` 已包含从样本推断出的 `max_slots`、`count_bounds` 和 `param_bounds`。
- `outputs/bench_build/latest/graph_samples/*.json` 的 `graph_type` 是 `vae_math_learning_sample`。

## 4. Validate Reference Cases

后续 batch 脚本都直接读取 latest build 的 `configs/`：

```bash
python -u scripts/bench_solve.py \
  --config-root outputs/bench_build/latest/configs \
  --summary-csv outputs/bench_build/reference_solve_summary.csv \
  --summary-json outputs/bench_build/reference_solve_summary.json \
  > outputs/bench_solve.log 2>&1

python -u scripts/bench_export_timetable.py \
  --config-root outputs/bench_build/latest/configs \
  --summary-csv outputs/bench_build/reference_export_timetable_summary.csv \
  --summary-json outputs/bench_build/reference_export_timetable_summary.json \
  > outputs/bench_export_timetable.log 2>&1

python -u scripts/bench_analyze.py \
  --config-root outputs/bench_build/latest/configs \
  --summary-csv outputs/bench_build/reference_analyze_summary.csv \
  --summary-json outputs/bench_build/reference_analyze_summary.json \
  > outputs/bench_analyze.log 2>&1
```

## 5. Train VAE

训练配置在 `config/train.yml`：

```bash
python scripts/train_vae.py
```

也可以显式指定配置：

```bash
python scripts/train_vae.py config/train.yml
```

当前推荐配置要点：

```text
data.graphs_root = outputs/bench_build/latest
optimization.epochs = 800
optimization.batch_size = 8
model.hidden_dim = 64
model.latent_dim = 16
model.message_passing_steps = 2
optimization.lr = 0.0003
loss_weights.param = 2.0
loss_weights.kl = 0.0015
```

这里的 `epochs` 可以通俗理解为“完整看完一遍训练样本的次数”。例如 `graph_samples` 里有 100 个样本，`epochs = 800` 就是这 100 个样本会被完整训练 800 轮。`batch_size = 8` 只表示每次梯度更新用 8 个样本，不改变一轮 epoch 要覆盖全部样本这个含义。

收敛主要看 `history.json` 和 `training.log`：

- `loss`、`count_loss`、`anchor_loss`、`param_loss` 应该总体下降，允许小幅波动。
- 如果 loss 明显震荡，优先使用 `best_model.pt`，再考虑继续降低 `optimization.lr`。
- 如果 param loss 长期压不下去，先确认 `speed` 已经按 `speed_limit / 350` 归一化，再适当提高 `loss_weights.param`。
- 如果 KL 很快压过其它 loss，先保持 `loss_weights.kl = 0.0015`，不要过早继续调大。

验收产物：

```text
outputs/train/<time>/best_model.pt
outputs/train/<time>/last_model.pt
outputs/train/<time>/training_config.json
outputs/train/<time>/training_summary.json
outputs/train/<time>/schema_summary.json
outputs/train/<time>/history.json
outputs/train/<time>/training.log
outputs/train/latest -> outputs/train/<time>
```

通过标准：

- 训练过程没有 non-finite loss。
- `outputs/train/latest` 是软连接。
- `outputs/train/latest/best_model.pt` 和 `outputs/train/latest/last_model.pt` 写出。
- `schema_summary.json` 中 `message_passing.uses_edge_index = true`，`message_passing.uses_edge_attr = true`。

## 6. Generate Math Graphs

模型生成：

```bash
python scripts/generate_vae.py \
  --checkpoint outputs/train/latest/best_model.pt \
  --context-graph outputs/bench_build/latest/context.json \
  --num-samples 100 \
  --mode model
```

target-copy 只用于管道检查：

```bash
python scripts/generate_vae.py \
  --context-graphs outputs/bench_build/latest \
  --num-samples 10 \
  --mode target-copy
```

生成结果：

```text
outputs/generate/<run>/math_sample/*.json
outputs/generate/<run>/generation_config.json
outputs/generate/<run>/generation_summary.json
outputs/generate/latest -> outputs/generate/<run>
```

## 7. Evaluate Generated Graphs

```bash
python scripts/evaluate_vae.py \
  --reference-graphs outputs/bench_build/latest \
  --generated-graphs outputs/generate/latest \
  --output outputs/generate/latest/evaluation.json
```

这里主要比较 count、anchor 分布和参数分布。求解难度等生成配置 solve 后再比较。

## 8. Decode And Import

```bash
python scripts/decode_import_generated_graphs.py \
  --generated-graphs outputs/generate/latest \
  --base-config config/base_demo.yaml
```

验收产物：

```text
outputs/generate/latest/disturbance_graphs/*.json
outputs/generate/latest/configs/*.yaml
outputs/generate/latest/decode_import_summary.csv
outputs/generate/latest/decode_import_summary.json
```

通过标准：

- `decode_import_summary.csv` 中没有 failed。
- 生成 YAML 的 `project.output_dir` 指向 `outputs/generate/latest/case_outputs/<case>/`。

## 9. Build Generated Configs

```bash
python -u scripts/bench_build.py \
  --config-root outputs/generate/latest/configs
```

这会创建新的 `outputs/bench_build/<time>/`，并把 `outputs/bench_build/latest` 软连接切到这次生成配置的 build run。

## 10. Validate Generated Cases

```bash
python -u scripts/bench_solve.py \
  --config-root outputs/bench_build/latest/configs \
  --summary-csv outputs/generate/latest/bench_solve_summary.csv \
  --summary-json outputs/generate/latest/bench_solve_summary.json \
  > outputs/generate/latest/bench_solve.log 2>&1

python -u scripts/bench_export_timetable.py \
  --config-root outputs/bench_build/latest/configs \
  --summary-csv outputs/generate/latest/bench_export_timetable_summary.csv \
  --summary-json outputs/generate/latest/bench_export_timetable_summary.json \
  > outputs/generate/latest/bench_export_timetable.log 2>&1

python -u scripts/bench_analyze.py \
  --config-root outputs/bench_build/latest/configs \
  --summary-csv outputs/generate/latest/bench_analyze_summary.csv \
  --summary-json outputs/generate/latest/bench_analyze_summary.json \
  > outputs/generate/latest/bench_analyze.log 2>&1
```

## 11. Compare Solver Difficulty

```bash
python scripts/evaluate_vae.py \
  --reference-solve-csv outputs/bench_build/reference_solve_summary.csv \
  --generated-solve-csv outputs/generate/latest/bench_solve_summary.csv \
  --output outputs/generate/latest/solver_difficulty.json
```

到这里，当前主链路验收完成。
