# RailGraph2Gurobi 项目流程

## 0. 环境

```bash
conda activate acmmilp
```

主入口是 `scripts/project.py`。新流程以 project 为沙箱单位，所有运行产物写入 `projects/<project>/`，不再写入 `config/`、`inputs/` 或仓库根目录。

## 1. 初始化项目

```bash
python scripts/project.py newproject <projectid>
```

初始化后目录为：

```text
projects/<projectid>/
  source/
  scenario_sets/default/
  datasets/
  conf/
    prepare.yml
    solve.yml
    analyze.yml
    normal_generate/default.yml
    train/default.yml
  model/
```

`projects/*` 被 git 忽略。仓库只保留 `projects/demo/conf/`、`projects/demo/scenario_sets/default/` 和 `projects/demo/source/.gitkeep`。

## 2. Prepare

把时刻表和里程表放入：

```text
projects/<projectid>/source/
```

填写：

```yaml
timetable_filename:
mileage_filename:
timetable_sheet_name: Sheet1
mileage_sheet_name: Sheet1
```

只允许写文件名，文件必须来自本 project 的 `source/`。

执行：

```bash
python scripts/project.py <projectid> prepare
```

产物：

```text
projects/<projectid>/context.json
```

`context.json` 开头包含 project 元信息，不再单独写 manifest。

## 3. Scenario Sets

手写场景放在：

```text
projects/<projectid>/scenario_sets/default/*.yml
```

普通批量模拟使用：

```bash
python scripts/project.py <projectid> normal_generate
python scripts/project.py <projectid> normal_generate test
```

对应读取：

```text
projects/<projectid>/conf/normal_generate/default.yml
projects/<projectid>/conf/normal_generate/test.yml
```

配置里的 `scenario_set_id` 决定输出目录，例如 `reference` 会写入：

```text
projects/<projectid>/scenario_sets/reference/*.yml
```

## 4. Build

```bash
python scripts/project.py <projectid> build <scenario_set_id> <dataset_id>
```

产物：

```text
projects/<projectid>/datasets/<dataset_id>/dataset.json
projects/<projectid>/datasets/<dataset_id>/build.csv
projects/<projectid>/datasets/<dataset_id>/cases/<case_id>/<case_id>.lp
```

`build` 不再生成中间 configs 和 graph。训练直接读取 scenario set。

## 5. Solve

默认参数来自：

```text
projects/<projectid>/conf/solve.yml
```

执行：

```bash
python scripts/project.py <projectid> solve <dataset_id>
```

产物：

```text
projects/<projectid>/datasets/<dataset_id>/cases/<case_id>/<case_id>.sol
projects/<projectid>/datasets/<dataset_id>/solve.csv
```

`solve.csv` 包含 `num_nodes`，记录 Gurobi `NodeCount`。

## 6. Analyze

`export-timetable` 已并入 analyze。

```bash
python scripts/project.py <projectid> analyze <dataset_id>
```

产物：

```text
projects/<projectid>/datasets/<dataset_id>/cases/<case_id>/adjusted_timetable.xlsx
projects/<projectid>/datasets/<dataset_id>/cases/<case_id>/analysis_metrics.xlsx
projects/<projectid>/datasets/<dataset_id>/cases/<case_id>/timetable_plot.png
projects/<projectid>/datasets/<dataset_id>/analyze.csv
```

plot title 使用当前 `.sol` 文件名。

## 7. Train

默认读取：

```text
projects/<projectid>/conf/train/default.yml
```

执行：

```bash
python scripts/project.py <projectid> model train
python scripts/project.py <projectid> model train test
```

训练配置必须包含 `scenario_set_id` 和 `model_id`。训练阶段会把指定 scenario set 转成 math graph，并结合 project 共享 `context.json` 训练。

产物：

```text
projects/<projectid>/model/<model_id>/
  graph/context.json
  graph/samples/*.json
  best_model.pt
  last_model.pt
  training_summary.json
```

## 8. Generation

```bash
python scripts/project.py <projectid> generation <model_id> <scenario_set_id>
```

该命令合并 model generate 和 decode，直接写入：

```text
projects/<projectid>/scenario_sets/<scenario_set_id>/*.yml
```

对比功能暂不放入新入口。
