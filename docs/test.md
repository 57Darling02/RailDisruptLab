# Typed VAE End-to-End Test Plan

本文件用于有完整 torch / Gurobi 环境的服务器执行。当前 VAE 代码不依赖 PyG；当前本地环境没有 torch，因此本地只验证不依赖 torch 的导出、target-copy、解码、评估和 build。

当前本地已验证：

- `py_compile` 通过。
- `export_typed_vae_learning_graph.py` 可导出 `dataset_profile.json + graphs/*.json`。
- VAE `target-copy` 生成能从 dataset 根目录自动读取 `graphs/`。
- `src.evaluate` 可生成 graph/task output 评估 JSON。
- `decode_typed_generated_graph.py` 可解码 `vae_math_generated_graph`。
- target-copy 结果可回灌并 `main.py build`。

服务器必须补验：

- VAE dataset load。
- 单样本 forward/backward，确认 typed message passing 可运行。
- 1 epoch 短训练。
- checkpoint model generate。
- model generated graph 的 decode/build。

## 0. Environment

在 RailGraph2Gurobi 根目录确认基础依赖：

```bash
python --version
python -c "import yaml, pandas, openpyxl; print('base deps ok')"
```

在 `VAE/` 目录确认 VAE 依赖：

```bash
cd VAE
python -c "import torch; print(torch.__version__)"
cd ..
```

如需完整 MILP 验证，确认 Gurobi：

```bash
python -c "import gurobipy; print(gurobipy.gurobi.version())"
```

成功标准：上述命令均无异常。没有 Gurobi 时跳过 solve/export/analyze，只执行 build。

## 1. Export math learning graph

```bash
python scripts/prepare_base_context.py \
  --timetable-path inputs/下行计划时刻表.xlsx \
  --mileage-path inputs/区间里程.xlsx

python scripts/export_typed_vae_learning_graph.py \
  --config config/mixed_scenarios_demo.yaml \
  --output outputs/test_math_vae/single.json

python scripts/export_typed_vae_learning_graph.py \
  --config-glob "config/batch_case_configs_demo/**/*.yaml" \
  --output-dir outputs/test_math_vae/dataset
```

成功标准：

- `outputs/test_math_vae/single.json` 的 `graph_type` 是 `vae_math_learning_graph`。
- 主文件不包含 `feature_names`、`ids`、`debug`、`type_system`。
- 单样本 profile 存在：`outputs/test_math_vae/dataset_profile.json`。
- batch 样本存在于：`outputs/test_math_vae/dataset/graphs/`。
- batch profile 存在：`outputs/test_math_vae/dataset/dataset_profile.json`。

可用以下命令快速检查：

```bash
python - <<'PY'
import json
from pathlib import Path
p = Path("outputs/test_math_vae/single.json")
g = json.loads(p.read_text(encoding="utf-8"))
assert g["graph_type"] == "vae_math_learning_graph"
raw = p.read_text(encoding="utf-8")
for token in ["feature_names", "debug", "type_system"]:
    assert token not in raw
assert len(g["rules"]["pools"]) == 2
assert len(g["rules"]["tasks"]) == 2
assert len(g["rules"]["edge_types"]) == 3
print("math graph export ok")
PY

python - <<'PY'
import json
from pathlib import Path
graph_dir = Path("outputs/test_math_vae/dataset/graphs")
assert graph_dir.is_dir()
assert any(graph_dir.glob("*.json"))
p = Path("outputs/test_math_vae/dataset/dataset_profile.json")
profile = json.loads(p.read_text(encoding="utf-8"))
assert profile["graph_type"] == "vae_math_dataset_profile"
assert profile["math_graph_type"] == "vae_math_learning_graph"
assert profile["base_context_path"]
assert len(profile["samples"]) > 0
print("dataset profile ok")
PY
```

## 2. VAE data/model smoke tests

```bash
cd VAE

python - <<'PY'
from src.data import RailDisturbanceDataset
from src.model import RailDisturbanceVAE, vae_loss

dataset = RailDisturbanceDataset("../outputs/test_math_vae/single.json")
sample = dataset[0]
model = RailDisturbanceVAE.from_sample(sample, hidden_dim=32, latent_dim=16, message_passing_steps=2)
outputs = model(sample)
loss, metrics = vae_loss(sample, outputs, kl_weight=1e-3)
loss.backward()
assert metrics["loss"] == metrics["loss"]
print("forward/backward ok", metrics)
PY

cd ..
```

成功标准：无异常，loss finite，输出 metrics 包含 `count_loss`、`anchor_loss`、`param_loss`、`kl`。这一步会实际使用 `edge_index + edge_attr` 做消息传递。

## 3. Short training

```bash
cd VAE

python -m src.train \
  --graphs-root ../outputs/test_math_vae/dataset \
  --output-dir outputs/test_math_graph_vae \
  --epochs 1 \
  --batch-size 1 \
  --hidden-dim 32 \
  --latent-dim 16 \
  --message-passing-steps 2 \
  --limit 4

cd ..
```

成功标准：

- `VAE/outputs/test_math_graph_vae/model.pt` 存在。
- `training_config.json`、`schema_summary.json`、`history.json` 存在。
- 日志中的 loss 非 NaN/Inf。

## 4. Generate math graphs

先执行 target-copy：

```bash
cd VAE

python -m src.generate \
  --context-graphs ../outputs/test_math_vae/dataset \
  --output-dir ../outputs/test_math_vae/generated_target_copy \
  --num-samples 2 \
  --mode target-copy

cd ..
```

再执行模型生成：

```bash
cd VAE

python -m src.generate \
  --checkpoint outputs/test_math_graph_vae/model.pt \
  --context-graphs ../outputs/test_math_vae/dataset \
  --output-dir ../outputs/test_math_vae/generated_model \
  --num-samples 2 \
  --mode model

cd ..
```

成功标准：

- 输出 JSON 的 `graph_type` 是 `vae_math_generated_graph`。
- 每个样本包含 `decode_handle` 和 `task_outputs`。
- `task_outputs` 只包含 `count`、`anchor_index`、`params`。

## 4.5 Evaluate graph similarity

```bash
cd VAE

python -m src.evaluate \
  --reference-graphs ../outputs/test_math_vae/dataset \
  --generated-graphs ../outputs/test_math_vae/generated_target_copy \
  --output ../outputs/test_math_vae/evaluation_target_copy.json

cd ..
```

成功标准：
- `evaluation_target_copy.json` 存在。
- JSON 中包含 `graph_similarity.generation_similarity`。
- 若生成文件是 `vae_math_generated_graph`，`graph_similarity.structure_similarity.status` 可以是 `not_applicable`；因为生成图只包含 task output，不包含完整上下文边。
- 对 model generate 样本可重复执行同一命令。

## 5. Decode and import

target-copy 解码应稳定通过：

```bash
python scripts/decode_typed_generated_graph.py \
  --typed-graph outputs/test_math_vae/generated_target_copy/sample_000001.json \
  --output-disturbance-graph outputs/test_math_vae/decoded_target_copy.json

python scripts/import_disturbance_graph.py \
  --graph outputs/test_math_vae/decoded_target_copy.json \
  --base-config config/base_demo.yaml \
  --output-config config/test_math_vae_target_copy.yaml
```

模型生成可能因为训练太短产生不合法参数；若失败，记录错误信息和 generated JSON。若成功，执行：

```bash
python scripts/decode_typed_generated_graph.py \
  --typed-graph outputs/test_math_vae/generated_model/sample_000001.json \
  --output-disturbance-graph outputs/test_math_vae/decoded_model.json

python scripts/import_disturbance_graph.py \
  --graph outputs/test_math_vae/decoded_model.json \
  --base-config config/base_demo.yaml \
  --output-config config/test_math_vae_model.yaml
```

成功标准：target-copy 解码和 import 必须通过；model 生成若失败，需要定位为 count、anchor index、duration、24h 时间窗或参数边界问题。

## 6. Build / solve / analyze

```bash
python main.py build --config config/test_math_vae_target_copy.yaml
```

有 Gurobi 时继续：

```bash
python main.py solve            --config config/test_math_vae_target_copy.yaml
python main.py export-timetable --config config/test_math_vae_target_copy.yaml
python main.py analyze          --config config/test_math_vae_target_copy.yaml
```

成功标准：

- build 生成 LP。
- solve 生成 sol。
- export-timetable 生成 adjusted timetable。
- analyze 生成 metrics。

## 7. Failure triage

- `Unsupported graph_type`: VAE reader 只能读取 `vae_math_learning_graph`，不要传 `dataset_profile.json`。
- `anchor_index is out of range`: 检查 generated graph 中 task 的 index 是否落在 `rules.tasks[].target_pool_id` 对应 pool size 内。
- `decodes to non-positive duration/delay`: 检查 params 是否满足 `rules.tasks[].param_bounds`。
- `exceeds 24:00:00`: 检查 start/duration 参数约束，模型生成需要更多训练或更强 repair。
- `No module named torch`: VAE 环境未激活或未安装 PyTorch。
- `gurobipy` 异常：只跳过 solve/export/analyze，不影响 math graph 与 VAE 验证。
