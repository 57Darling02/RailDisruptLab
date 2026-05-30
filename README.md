# RailDisruptLab

RailDisruptLab 是一个面向铁路运行扰动场景的实验平台，用于构造扰动场景、生成 MILP 实例、调度求解任务、训练扰动生成模型，并在 Web 界面中完成可视化分析。

项目以 FastAPI + Vue 作为唯一用户入口。耗时实验由 backend 写入任务快照后交给 Pueue 执行。

## 架构

- `core`：铁路原计划解析、MILP 建模、求解、扰动图转换和 VAE 数学图转换等原子算法能力。
- `backend`：FastAPI、Pueue 任务队列、任务快照、日志、项目数据流、场景构造、模型训练/生成流程编排。
- `frontend`：项目交互、任务监控、状态展示和图形化分析。

每次实验操作都由 Web 表单或 API 请求显式提交参数。backend 会为任务保存一份输入快照，便于追踪、复现和查看日志：

```text
var/tasks/<projectid>/<timestamp>_<action>/input.json
```

Pueue 统一执行：

```text
python -m backend.runner <input.json>
```

## 项目数据流

仓库不提交任何 `projects/` 沙箱。启动 Web 后，通过右上角“新建”创建 project，
再在页面表单中上传数据、选择参数并提交任务。每个 project 的输入、场景、实例、模型和分析产物都保存在独立目录中。

```text
projects/<projectid>/
  source/
  context.json
  scenario_sets/
  datasets/
  model/
```

主实验流程：

```text
timetable / mileage files
  -> context.json
  -> scenario_sets/<scenario_set_id>/*.yml
  -> datasets/<dataset_id>/cases/<case_id>/<case_id>.lp
  -> datasets/<dataset_id>/cases/<case_id>/<case_id>.sol
  -> datasets/<dataset_id>/cases/<case_id>/adjusted_timetable.json
  -> frontend visualization
```

模型流程：

```text
context.json + scenario_sets/<scenario_set_id>/
  -> model/<model_id>/*.pt
  -> scenario_sets/<target_scenario_set_id>/*.yml
```

## 环境

```bash
conda env create -f environment.yml
conda activate rdl
```

启动后端：

```bash
python -m backend --host 127.0.0.1 --port 8000
```

访问：

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/api/docs
```

首次使用：

1. 在 Web 右上角新建 project。
2. 在仪表盘点击“原计划运行图”状态卡，上传时刻表和里程表并激活。
3. 在“构建扰动场景”页新建或批量生成扰动场景集。
4. 在“构建MILP实例”页新建实例集，并选择场景或场景集构建。
5. 按需求解、导出时刻表、训练扰动生成模型和生成新场景。

前端开发：

```bash
cd frontend
pnpm install
pnpm dev
```

部署前端：

```bash
cd frontend
pnpm build
```

后端会优先分发 `frontend/dist/`。

## 产物约定

数据集产物：

```text
projects/<projectid>/datasets/<dataset_id>/
  cases/
    <case_id>/
      build.json
      scenario.yml
      <case_id>.lp
      solve.json
      <case_id>.sol
      <case_id>.sol.csv
      adjusted_timetable.json
```

模型产物：

```text
projects/<projectid>/model/<model_id>/
  graph/
  best_model.pt
  last_model.pt
  training_config.json
  training_summary.json
  schema_summary.json
  loss_history.jsonl
```

## 文档

实验平台流程见 [docs/exp.md](docs/exp.md)，断兼容变更和数据升级说明见 [docs/version.md](docs/version.md)。
