# RailDisruptLab 实验平台流程

本项目的主要入口是可视化界面。CLI 保留为 backend 调度 core 的机器接口和必要的调试入口，不作为主要用户操作方式。

核心原则：

- `core` 只做原子算法能力：准备原计划、消费场景构建 MILP、求解、训练和模型生成解码。
- `backend` 负责数据流、任务快照、队列、日志、场景表单构造和批量采样。
- `frontend` 负责交互、状态展示和图形化分析。
- 项目运行不依赖隐藏配置文件；前端参数会由 backend 写入任务快照，保证可追踪、可复现。

## 数据流

```text
source/
  -> context.json
  -> scenario_sets/<scenario_set_id>/*.yml
  -> datasets/<dataset_id>/cases/<case_id>/<case_id>.lp
  -> datasets/<dataset_id>/cases/<case_id>/<case_id>.sol
  -> datasets/<dataset_id>/cases/<case_id>/adjusted_timetable.json
  -> frontend visualization
```

模型训练和生成的数据流：

```text
context.json + scenario_sets/<scenario_set_id>/
  -> model/<model_id>/graph/
  -> model/<model_id>/*.pt
  -> scenario_sets/<target_scenario_set_id>/*.yml
```

## 项目结构

```text
projects/<projectid>/
  source/
  context.json
  scenario_sets/
    <scenario_set_id>/*.yml
  datasets/
    <dataset_id>/
      cases/
        <case_id>/
          build.json
          scenario.yml
          <case_id>.lp
          solve.json
          <case_id>.sol
          <case_id>.sol.csv
          adjusted_timetable.json
  model/
    <model_id>/
      graph/
      best_model.pt
      last_model.pt
      training_config.json
      training_summary.json
      schema_summary.json
      loss_history.jsonl
```

`projects/*` 是运行沙箱，不作为源码维护对象。仓库不提交 demo 项目；首次使用时在 Web
右上角新建 project，并通过页面表单完成 source 上传、原计划激活和后续任务参数配置。

## 后端任务

前端提交任务时，backend 会写入任务快照：

```text
var/tasks/<projectid>/<timestamp>_<action>/input.json
```

Pueue 执行统一入口：

```text
python -m backend.runner <input.json>
```

runner 读取快照后调用 backend 数据管理能力或 core 原子函数。任务日志由 Pueue 管理，前端通过任务面板查看命令、状态和日志。

这种方式避免了两类问题：

- 不需要在项目目录维护 `build.yml`、`solve.yml`、`train.yml` 等隐藏状态。
- 不需要让前端先写配置文件再触发任务，参数、产物和日志天然绑定到同一个 task。

## 主流程

1. 新建 Project

创建项目沙箱，初始化 `source/`、`scenario_sets/`、`datasets/` 和 `model/`。
项目 ID 由 Web 表单输入；项目目录由 backend 创建，不需要预置 demo。

2. 上传 Source

上传原始时刻表和里程表文件到 `source/`。

3. 激活原计划运行图

前端选择时刻表文件、里程表文件和 sheet 名称，backend 调用 core 生成：

```text
projects/<projectid>/context.json
```

`context.json` 是后续场景、MILP、训练和前端原计划运行图展示的共享基础。

4. 管理 Scenario Set

场景集合位于：

```text
projects/<projectid>/scenario_sets/<scenario_set_id>/
```

前端支持新建集合、手动新增/删除场景、批量生成 normal 场景。批量生成直接写入当前选择的 scenario set；同名场景按任务参数覆盖。

5. 创建 MILP 数据集

数据集目录位于：

```text
projects/<projectid>/datasets/<dataset_id>/
```

创建数据集只创建目录，不隐式构建内容。

6. 从场景构建 MILP

前端选择单个场景或整个场景集合，backend 调用 core 为每个 case 生成：

```text
cases/<case_id>/scenario.yml
cases/<case_id>/build.json
cases/<case_id>/<case_id>.lp
```

建模参数由前端任务表单传入，记录在任务快照和日志中。

7. 求解并导出时刻表数据

求解针对单个 `.lp` 或整个数据集执行。求解后生成：

```text
cases/<case_id>/<case_id>.sol
cases/<case_id>/solve.json
cases/<case_id>/<case_id>.sol.csv
cases/<case_id>/adjusted_timetable.json
```

`adjusted_timetable.json` 是前端运行图、调整对比和扰动可视化的主要数据源。
求解和导出时刻表支持批量执行，但批量执行本身只作为 task 行为记录；数据集完成度以每个 case 的实际产物为准。

8. 训练模型

前端选择模型 ID、scenario set 和训练参数。训练产物位于：

```text
projects/<projectid>/model/<model_id>/
```

训练参数写入 `training_config.json`，训练摘要写入 `training_summary.json`，loss 曲线由 `loss_history.jsonl` 提供。

9. 使用模型生成场景

前端选择具体 `.pt` checkpoint、目标 scenario set 和生成参数。生成过程不保留中间图 JSON 作为正式产物，最终只写入目标场景集合。

## 职责边界

`core` 不管理任务队列、不服务 HTTP、不设计 UI 状态、不构造实验场景，也不依赖项目配置文件。

`backend` 不实现 MILP/模型算法，只负责参数快照、任务调度、数据读取、场景构造、时刻表导出和 API。

`frontend` 不直接读写项目文件，只通过 `/api` 交互；图形化分析优先在前端基于结构化数据实现。
