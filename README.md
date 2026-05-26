# RailGraph2Gurobi

RailGraph2Gurobi 是一个按 project 沙箱组织的铁路扰动 MILP 工具。它当前覆盖四类功能：

- 基于计划时刻表和里程表，结合突发场景，生成扰动调整 MILP 实例。
- 按比例批量模拟突发场景。
- 用 GNN+VAE 学习扰动规律，并生成新的扰动场景。
- 对 dataset 做求解、时刻表导出和指标分析。

主入口是：

```bash
python scripts/project.py ...
```

底层脚本仍保留给开发调试，但日常使用只推荐走 `scripts/project.py`。

## 1. 核心约定

所有运行产物都放在：

```text
projects/<projectid>/
```

git 规则是：

- `projects/*` 默认忽略。
- 仓库只保留 demo 的配置模板和默认手写场景：
  - `projects/demo/conf/**`
  - `projects/demo/scenario_sets/default/**`
  - `projects/demo/source/.gitkeep`
- `source/` 里的真实 Excel、`context.json`、dataset、model、生成场景集都不进入 git。

几个概念：

| 名称 | 含义 |
|---|---|
| `project` | 一个完整实验沙箱，包含 source、context、scenario sets、datasets、model 和 conf |
| `source` | 用户自行放入的计划时刻表和里程表 |
| `context.json` | 由 source 生成的共享 BaseContext，一个 project 共用一份 |
| `scenario_set` | 一组场景 YAML，可以手写、普通模拟生成，也可以由模型生成 |
| `dataset` | 从某个 scenario set build 出来的 MILP 实例集合 |
| `model` | 从某个 scenario set 训练出来的 VAE 模型 |

## 2. 目录结构

初始化后结构如下：

```text
projects/<projectid>/
  source/
    .gitkeep
    <your timetable>.xlsx
    <your mileage>.xlsx

  context.json

  scenario_sets/
    default/
      *.yml
    <scenario_set_id>/
      *.yml

  datasets/
    <dataset_id>/
      dataset.json
      build.csv
      solve.csv
      analyze.csv
      cases/
        <case_id>/
          <case_id>.lp
          <case_id>.sol
          adjusted_timetable.xlsx
          analysis_metrics.xlsx
          timetable_plot.png

  conf/
    prepare.yml
    solve.yml
    analyze.yml
    normal_generate/
      default.yml
      <config_id>.yml
    train/
      default.yml
      <config_id>.yml

  model/
    <model_id>/
      graph/
        context.json
        samples/*.json
        dataset_profile.json
      best_model.pt
      last_model.pt
      training_summary.json
```

## 3. 环境

```bash
conda activate acmmilp
```

所有命令都从项目根目录执行。

## 4. 初始化 Project

```bash
python scripts/project.py newproject <projectid>
```

例如：

```bash
python scripts/project.py newproject exp01
```

这会创建：

```text
projects/exp01/source/
projects/exp01/scenario_sets/default/
projects/exp01/datasets/
projects/exp01/conf/
projects/exp01/model/
```

并生成默认配置文件。

## 5. Prepare：生成共享 Context

先把计划时刻表和里程表放到：

```text
projects/<projectid>/source/
```

然后填写：

```text
projects/<projectid>/conf/prepare.yml
```

格式：

```yaml
timetable_filename: 下行计划时刻表.xlsx
mileage_filename: 区间里程.xlsx
timetable_sheet_name: Sheet1
mileage_sheet_name: Sheet1
```

注意：这里只允许写文件名，不能写路径。文件必须位于当前 project 的 `source/` 目录。

执行：

```bash
python scripts/project.py <projectid> prepare
```

输出：

```text
projects/<projectid>/context.json
```

`context.json` 是后续 build、normal_generate、train、generation 共用的上下文。

## 6. Scenario Set：场景输入

手写场景放在：

```text
projects/<projectid>/scenario_sets/default/*.yml
```

场景文件只描述扰动：

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

`limit_speed: 0` 表示区间中断。

## 7. 普通批量模拟场景

默认配置：

```text
projects/<projectid>/conf/normal_generate/default.yml
```

示例：

```yaml
scenario_set_id: reference
overwrite: true
seed: 20260320
delay_count: 10
speed_count: 10
interruption_count: 10
combo_per_type: 10
```

必须填写 `scenario_set_id`。若写 `reference`，输出到：

```text
projects/<projectid>/scenario_sets/reference/*.yml
```

执行默认配置：

```bash
python scripts/project.py <projectid> normal_generate
```

执行指定配置：

```bash
python scripts/project.py <projectid> normal_generate test
```

对应读取：

```text
projects/<projectid>/conf/normal_generate/test.yml
```

## 8. Build：生成 MILP 实例

```bash
python scripts/project.py <projectid> build <scenario_set_id> <dataset_id>
```

例如：

```bash
python scripts/project.py demo build default demo_dataset
python scripts/project.py demo build reference reference_dataset
```

输出：

```text
projects/<projectid>/datasets/<dataset_id>/dataset.json
projects/<projectid>/datasets/<dataset_id>/build.csv
projects/<projectid>/datasets/<dataset_id>/cases/<case_id>/<case_id>.lp
```

设计约定：

- `build` 只负责生成 MILP 实例。
- `build` 不再生成临时 configs。
- `build` 不再生成训练 graph。
- 训练直接读取 `scenario_set_id`，不依赖 dataset。

## 9. Solve：求解 Dataset

默认参数来自：

```text
projects/<projectid>/conf/solve.yml
```

执行：

```bash
python scripts/project.py <projectid> solve <dataset_id>
```

常用调试：

```bash
python scripts/project.py <projectid> solve <dataset_id> --limit 1 --time-limit 1
```

输出：

```text
projects/<projectid>/datasets/<dataset_id>/cases/<case_id>/<case_id>.sol
projects/<projectid>/datasets/<dataset_id>/solve.csv
```

`solve.csv` 会记录求解行为，包括：

- `status`
- `objective`
- `mip_gap`
- `num_nodes`
- `duration_sec`

其中 `num_nodes` 是 Gurobi `NodeCount`。

## 10. Analyze：导出时刻表和指标

`export-timetable` 已并入 analyze。

配置文件：

```text
projects/<projectid>/conf/analyze.yml
```

执行：

```bash
python scripts/project.py <projectid> analyze <dataset_id>
```

输出：

```text
projects/<projectid>/datasets/<dataset_id>/cases/<case_id>/adjusted_timetable.xlsx
projects/<projectid>/datasets/<dataset_id>/cases/<case_id>/analysis_metrics.xlsx
projects/<projectid>/datasets/<dataset_id>/cases/<case_id>/timetable_plot.png
projects/<projectid>/datasets/<dataset_id>/analyze.csv
```

plot title 默认使用当前 `.sol` 文件名。

## 11. Train：训练扰动生成模型

默认配置：

```text
projects/<projectid>/conf/train/default.yml
```

示例：

```yaml
scenario_set_id: reference
model_id: vae_reference
data:
  limit: 0
  max_slots: 8
  event_time_window: 3600
  event_top_k: 8
  section_order_window: 2
  speed_interruption_threshold: 20.0
model:
  hidden_dim: 64
  latent_dim: 16
  message_passing_steps: 2
optimization:
  epochs: 800
  batch_size: 8
  lr: 0.0003
  seed: 1
  device: auto
  log_every: 1
loss_weights:
  count: 1.0
  anchor: 1.0
  param: 2.0
  kl: 0.0015
```

必须填写：

- `scenario_set_id`
- `model_id`

执行默认配置：

```bash
python scripts/project.py <projectid> model train
```

执行指定配置：

```bash
python scripts/project.py <projectid> model train test
```

输出：

```text
projects/<projectid>/model/<model_id>/graph/context.json
projects/<projectid>/model/<model_id>/graph/samples/*.json
projects/<projectid>/model/<model_id>/best_model.pt
projects/<projectid>/model/<model_id>/last_model.pt
projects/<projectid>/model/<model_id>/training_summary.json
```

## 12. Generation：生成并解码场景

```bash
python scripts/project.py <projectid> generation <model_id> <scenario_set_id>
```

例如：

```bash
python scripts/project.py demo generation vae_reference generated_by_vae
```

这个命令会：

1. 读取 `projects/<projectid>/model/<model_id>/best_model.pt`。
2. 生成 math graph。
3. 立即 decode 成 RailGraph2Gurobi 场景 YAML。
4. 写入 `projects/<projectid>/scenario_sets/<scenario_set_id>/`。

覆盖已有场景集时需要显式加：

```bash
python scripts/project.py <projectid> generation <model_id> <scenario_set_id> --overwrite
```

## 13. Demo 最小流程

demo 的配置和手写场景已经在仓库中。真实 Excel 不进 git，如本地还没有 demo source 文件，可以先复制：

```bash
cp inputs/下行计划时刻表.xlsx projects/demo/source/
cp inputs/区间里程.xlsx projects/demo/source/
```

然后运行：

```bash
python scripts/project.py demo prepare
python scripts/project.py demo build default smoke_dataset
python scripts/project.py demo solve smoke_dataset --limit 1 --time-limit 1
```

训练 smoke 可以新建一个轻量训练配置，例如 `projects/demo/conf/train/smoke.yml`，然后：

```bash
python scripts/project.py demo model train smoke
python scripts/project.py demo generation <model_id> <new_scenario_set_id> --num-samples 1 --overwrite
```

## 14. 常见错误

| 错误 | 处理 |
|---|---|
| `Missing project context` | 先运行 `python scripts/project.py <projectid> prepare` |
| `timetable_filename must be a filename` | `prepare.yml` 只能写文件名，不能写路径 |
| `Scenario set not found` | 检查 `scenario_sets/<scenario_set_id>/` 是否存在 |
| `Output already exists` | 在生成场景配置中设置 `overwrite: true`，或 generation 时加 `--overwrite` |
| `Solution not found` | `analyze` 前先运行 `solve` |
