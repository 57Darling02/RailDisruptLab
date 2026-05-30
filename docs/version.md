# 版本与升级说明

本文记录断兼容改版和旧数据处理方式。当前项目不保留旧流程兼容入口；旧版本产物需要按规则迁移到新项目目录。

## 当前架构版本

当前版本采用 Web/API-first 架构：

- `frontend` 负责交互和可视化。
- `backend` 负责项目目录、数据流、任务快照、Pueue 队列、流程编排和分析聚合。
- `core` 只保留原子算法能力，不再包含 workflow 包。

任务统一由 backend 写入：

```text
var/tasks/<project>/<timestamp>_<action>/input.json
```

并由 Pueue 执行：

```text
python -m backend.runner <input.json>
```

## 2026-05-30 架构收缩

本次改动目标是做减法，让 core 更纯净，让 backend 成为唯一流程层。

移除内容：

- 删除 `core/workflow/`。
- 删除 `scripts/project.py` 旧 workflow CLI。
- 删除依赖 `core.loader.load_config()` 的旧配置导入/导出脚本。
- 删除 `.runs` 旧任务记录读取逻辑。
- 移除 `core.loader.load_config(path)` 文件配置入口。
- `core.__init__` 不再导出配置加载接口。

保留内容：

- `core.loader.load_config_payload(...)` 暂作为内部 adapter，用于把 backend workflow 的显式参数组装成 `AppConfig` 供 MILP builder 使用。
- `scripts/train_vae.py`、`scripts/generate_vae.py`、`scripts/evaluate_vae.py` 作为模型算法脚本保留。
- `projects/<project>/...` 下的正式产物格式继续作为 Web 平台读取对象。

## ID 与产物命名规范

当前版本对 project、scenario set、dataset、model、case 等 ID 统一做规范化后再作为目录名、文件名前缀和产物字段写入。

规范化规则：

- 保留字母、数字、中文等 `isalnum()` 字符，以及 `-`、`_`。
- 其他字符替换为 `_`。
- 去掉首尾 `_`。
- 空 ID 或规范化后为空的 ID 会直接报错，不再兜底为 `default`。

受影响的正式产物包括：

```text
projects/<project>/
scenario_sets/<scenario_set>/
datasets/<dataset>/cases/<case>/
datasets/<dataset>/cases/<case>/<case>.lp
datasets/<dataset>/cases/<case>/<case>.sol
datasets/<dataset>/cases/<case>/<case>.sol.csv
model/<model>/
model/<model>/graph/samples/<case>.json
```

对应 JSON/YAML 字段也使用规范化后的 ID：

```text
scenario.yml: name
build.json: case_id / scenario_set_id / source_scenario_id
solve.json: case_id
adjusted_timetable.json: case_id
```

`.sol.csv` 的列名固定为：

```text
variable,value
```

其中 `variable` 列保存 MILP 求解变量名本身，不做额外迁移改名；变量名必须能被当前 `core.postprocess` 正确解析。

## 旧数据升级规则

### Project

旧 project 目录如果已经接近当前结构，可以迁移为：

```text
projects/<project>/
  source/
  context.json
  scenario_sets/
  datasets/
  model/
```

如果旧项目依赖 `build.yml`、`solve.yml`、`train.yml` 等隐藏配置，不再直接执行这些配置。需要在 Web 表单中重新提交参数，生成新的 task snapshot 和产物记录。

### Scenario Set

当前场景文件必须位于：

```text
projects/<project>/scenario_sets/<scenario_set>/*.yml
```

推荐格式：

```yaml
name: case001
delays:
  - event_anchor_id: event_0001
    seconds: 600
speed_limits:
  - section_anchor_id: section_0001
    start_time: 08:00:00
    duration: 1800
    limit_speed: 160
```

中断不再使用单独 `interruptions` 字段；统一使用 `speed_limits`，并令 `limit_speed: 0`。

### Dataset

当前 MILP 实例集必须位于：

```text
projects/<project>/datasets/<dataset>/cases/<case>/
```

每个 case 的正式产物为：

```text
scenario.yml
build.json
<case>.lp
solve.json
<case>.sol
<case>.sol.csv
adjusted_timetable.json
```

旧版跨数据集 summary、import summary、benchmark summary 不再作为正式产物。Web 分析会按 case 目录中的实际产物即时计算。

如果旧数据的 case 目录名、`.lp/.sol/.sol.csv` 文件名前缀和 JSON 内部 `case_id` 不一致，推荐重新从场景集构建数据集。手动迁移时必须保证三者使用同一个规范化后的 `<case>`：

```text
cases/<case>/
  build.json              # case_id = <case>
  solve.json              # case_id = <case>
  <case>.lp
  <case>.sol
  <case>.sol.csv
```

旧 `.sol.csv` 若使用 `var`、`name` 等列名，需要转换为当前固定列名 `variable,value`；否则 Web 分析和时刻表导出不会把它视为当前格式。

### Model

当前模型目录必须位于：

```text
projects/<project>/model/<model>/
```

可被 Web 读取的主要产物为：

```text
graph/
best_model.pt
last_model.pt
training_config.json
training_summary.json
schema_summary.json
loss_history.jsonl
```

旧版训练 YAML 不再读取。重新训练时通过 Web 表单提交参数，backend 会写入新的任务快照和训练产物。

### Task

旧版批量清理和等待接口已移除：

```text
DELETE /api/tasks
POST /api/tasks/<task_id>/wait
```

当前任务管理只保留：

```text
GET    /api/tasks
GET    /api/tasks/<task_id>
GET    /api/tasks/<task_id>/log
POST   /api/tasks/<task_id>/cancel
DELETE /api/tasks/<task_id>
```

`DELETE /api/tasks/<task_id>` 只允许清理已结束任务，并会同时删除对应的 `var/tasks/<project>/<timestamp>_<action>/input.json` 快照目录和本地任务日志。运行中、排队中、暂停中任务必须先取消或等待结束。

任务返回结构新增 `action` 和 `params` 字段，前端任务详情以这两个字段展示关键参数；命令本身只保留为底层执行记录。

任务资源锁也收缩为更精确的规则：

- `build` 仍锁整个 dataset，因为构建会重置并重写数据集目录。
- 批量 `solve` / 批量 `export_timetable` 锁整个 dataset。
- 指定 `case_id` 的 `solve` / `export_timetable` 只锁 `dataset:<dataset>:case:<case>`，不同 case 可并发。

### Frontend

前端不再等待短任务执行完再把结果当作同步操作返回。所有创建、构建、求解、训练、生成等行为统一表现为“提交任务”，随后由任务面板和项目状态轮询反映实际完成情况。

这意味着旧项目升级时不要依赖“按钮点击后立刻出现完整产物”的交互假设；应以任务状态和 case/model/scenario_set 实际产物为准。

## 旧版本功能如何复现

旧 CLI 行为不再作为代码入口保留。等价操作通过 Web/API 完成：

- `newproject`：Web 右上角新建项目。
- `prepare`：仪表盘激活原计划运行图。
- `normal_generate`：构建扰动场景页批量生成。
- `build`：构建 MILP 实例页从场景或场景集构建。
- `solve`：构建 MILP 实例页单个或全部求解。
- `export_timetable`：构建 MILP 实例页单个或全部导出时刻表。
- `model train`：扰动生成模型页训练或重新训练。
- `generation`：扰动生成模型页选择 checkpoint 生成场景。

中间 typed/generated graph 和 disturbance graph JSON 不再作为正式升级目标；如果旧实验只保留了这些中间文件，应重新通过模型页生成目标场景集。

## 升级检查清单

1. 确认没有业务流程再引用 `core.workflow`。
2. 确认没有任务入口再调用 `scripts/project.py`。
3. 确认正式分析只读取 `projects/<project>` 下的结构化产物。
4. 确认旧 summary 文件不会作为 Web 状态来源。
5. 确认所有耗时任务都能在任务面板看到 task、参数、状态和日志。
6. 确认旧自动化脚本没有调用已删除的 `/api/tasks` 批量清理或 `/api/tasks/<task_id>/wait`。
