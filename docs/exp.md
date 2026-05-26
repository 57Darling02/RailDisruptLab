# RailGraph2Gurobi 项目流程

当前推荐配置模型：

- `config/demo.yml` 是 project config，包含 BaseContext、solver/export/analyze 和 train 配置。
- `config/scenario/...` 是 scenario config，只包含单个 case 的扰动。
- `build.scenarios` 可以引用单个 scenario YAML，也可以引用 scenario 目录。
- 不使用 `latest`。
- 同名 project/dataset/model/generation 重跑时覆盖原目录。

输出统一放在：

```text
outputs/<project>/
  datasets/<dataset>/
  models/<model>/
  generations/<generation>/
  comparisons/<comparison>/
```

## 1. Prepare BaseContext

```bash
python scripts/prepare_base_context.py \
  --timetable-path inputs/下行计划时刻表.xlsx \
  --mileage-path inputs/区间里程.xlsx
```

产物：

```text
inputs/context_下行计划时刻表.json
```

## 2. Scenario Inputs

手写场景放在：

```text
config/scenario/demo/*.yml
```

批量生成场景：

```bash
python -u scripts/case_library_builder.py \
  --output-root config/scenario/generated_reference \
  --clean
```

场景文件只保存扰动：

```yaml
name: mixed
delays:
  - train_id: G1
    station: jinanxi
    event_type: dep
    seconds: 600
speed_limits:
  - start_station: taian
    end_station: qufudong
    start_time: "09:00:00"
    duration: 2400
    limit_speed: 0
```

## 3. Build Dataset

使用 `config/demo.yml` 默认引用的场景目录：

```bash
python scripts/project.py dataset build \
  --config config/demo.yml \
  --dataset demo
```

用同一个 project config 临时切换 scenario 目录：

```bash
python scripts/project.py dataset build \
  --config config/demo.yml \
  --dataset reference \
  --scenarios config/scenario/generated_reference
```

dataset 结构：

```text
outputs/main/datasets/reference/
  manifest.json
  configs/*.yaml
  cases/<case_id>/<case_id>.lp
  graph/context.json
  graph/samples/*.json
  graph/dataset_profile.json
  benchmark/build_summary.csv
  benchmark/build_summary.json
  logs/build.log
```

通过标准：

- `benchmark/build_summary.csv` 中没有 failed。
- `graph/context.json` 的 `graph_type` 是 `vae_math_context_graph`。
- `graph/samples/*.json` 的 `graph_type` 是 `vae_math_learning_sample`。

## 4. Benchmark Dataset

```bash
python scripts/project.py dataset benchmark \
  --config config/demo.yml \
  --dataset reference \
  --time-limit 120
```

并行求解：

```bash
python scripts/project.py dataset benchmark \
  --config config/demo.yml \
  --dataset reference \
  --time-limit 120 \
  --workers 4 \
  --threads-per-solve 8
```

产物：

```text
outputs/main/datasets/reference/benchmark/solve_summary.csv
outputs/main/datasets/reference/benchmark/export_timetable_summary.csv
outputs/main/datasets/reference/benchmark/analyze_summary.csv
outputs/main/datasets/reference/benchmark/scenario_report/
outputs/main/datasets/reference/logs/solve.log
outputs/main/datasets/reference/logs/export_timetable.log
outputs/main/datasets/reference/logs/analyze.log
```

`--time-limit 120` 是当前对比口径。reference 和 generated datasets 必须使用同一限制。

## 5. Train VAE

训练是可选分支。训练参数保存在 `config/demo.yml` 的 `train` 段，dataset graph 路径和 model 输出路径由 `project.py` 注入。

```bash
python scripts/project.py model train \
  --config config/demo.yml \
  --model vae_reference \
  --dataset reference
```

产物：

```text
outputs/main/models/vae_reference/
  manifest.json
  best_model.pt
  last_model.pt
  training_config.json
  training_summary.json
  schema_summary.json
  history.json
  training.log
```

## 6. Generate Graphs

模型生成：

```bash
python scripts/project.py generation create \
  --config config/demo.yml \
  --generation gen_reference \
  --dataset reference \
  --model vae_reference \
  --num-samples 100
```

target-copy 只用于管道检查：

```bash
python scripts/project.py generation create \
  --config config/demo.yml \
  --generation target_copy_reference \
  --dataset reference \
  --num-samples 10 \
  --mode target-copy
```

产物：

```text
outputs/main/generations/gen_reference/
  manifest.json
  math_graphs/*.json
  generation_config.json
  generation_summary.json
```

## 7. Decode Generated Graphs

```bash
python scripts/project.py generation decode \
  --config config/demo.yml \
  --generation gen_reference
```

产物：

```text
outputs/main/generations/gen_reference/disturbance_graphs/*.json
outputs/main/generations/gen_reference/configs/*.yaml
outputs/main/generations/gen_reference/case_outputs/<case_id>/
outputs/main/generations/gen_reference/decode_summary.csv
outputs/main/generations/gen_reference/decode_summary.json
```

## 8. Build And Benchmark Generated Dataset

生成配置进入新的 dataset，不把指标写回 generation 目录。

```bash
python scripts/project.py dataset build \
  --project-config config/demo.yml \
  --dataset generated_reference \
  --config-root outputs/main/generations/gen_reference/configs

python scripts/project.py dataset benchmark \
  --config config/demo.yml \
  --dataset generated_reference \
  --time-limit 120
```

## 9. Compare Solver Difficulty

```bash
python scripts/project.py compare solver \
  --config config/demo.yml \
  --reference reference \
  --candidate generated_reference \
  --generation gen_reference
```

产物：

```text
outputs/main/generations/gen_reference/solver_difficulty.json
```
