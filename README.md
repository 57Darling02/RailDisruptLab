# RailGraph2Gurobi

RailGraph2Gurobi 是一个按 project 沙箱组织的铁路扰动 MILP 实验平台。

当前主入口是 FastAPI + Vue 可视化界面；CLI 保留为 backend 调度 core 的机器接口和开发调试入口。

## 架构

- `core`：铁路原计划、场景消费、MILP、求解、模型训练和生成解码的原子算法能力。
- `backend`：FastAPI、Pueue 任务队列、任务快照、日志、项目数据读取和场景构造。
- `frontend`：交互、状态展示和图形化分析。

核心约定是参数显式传递。项目运行不依赖 `build.yml`、`solve.yml`、`train.yml` 等隐藏配置文件；前端提交的参数由 backend 写入任务快照：

```text
var/tasks/<projectid>/<timestamp>_<action>/input.json
```

Pueue 统一执行：

```text
python -m backend.runner <input.json>
```

## 项目数据流

仓库不提交任何 `projects/` 沙箱。启动 Web 后，通过右上角“新建”创建 project，
再在页面表单中上传数据、选择参数并提交任务。所有参数由 backend 写入
`var/tasks/<projectid>/<timestamp>_<action>/input.json`，不需要维护 demo 配置文件。

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
source files
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
conda activate r2g
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
2. 在仪表盘上传时刻表和里程表。
3. 点击“激活”原计划运行图，选择文件和 sheet 名称。
4. 在场景集合页新建或批量生成场景。
5. 在数据集页新建 MILP 数据集，选择场景或场景集合构建。
6. 按需求解、导出时刻表、训练模型和生成新场景。

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

实验平台流程见 [docs/exp.md](docs/exp.md)。
