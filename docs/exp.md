# RailGraph2Gurobi -> VAE -> RailGraph2Gurobi 验收流程

本文档是当前主流程的验收手册。核心约定：

- `config/batch_case_configs_demo` 只保存场景模拟输入，不是主流程产物目录。
- `bench_build.py` 每次只生成一个 timestamp run。
- `outputs/bench_build/latest` 是指向最新 build run 的软连接。
- `outputs/train/latest` 是指向最新训练 run 的软连接，生成默认使用 `outputs/train/latest/best_model.pt`。
- `outputs/generate/latest` 是指向最新生成 run 的软连接。
- VAE 训练只读 `config/train.yml`，训练参数不再散落在命令行里。
- 做消融实验时，不要依赖 `latest` 作为最终记录。并行训练、生成和 build 都会更新 latest 软连接，必须及时记录真实 run 目录。

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
  --time-limit 120 \
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

如果服务器 CPU/Gurobi license 允许并行，可以给 solve 加 workers，例如：

```bash
python -u scripts/bench_solve.py \
  --config-root outputs/bench_build/latest/configs \
  --time-limit 120 \
  --workers 4 \
  --threads-per-solve 8 \
  --summary-csv outputs/bench_build/reference_solve_summary.csv \
  --summary-json outputs/bench_build/reference_solve_summary.json \
  > outputs/bench_solve.log 2>&1
```

这里 `--time-limit 120` 是当前消融对比的统一求解限制。后续 generated cases 也必须使用同一个限制，否则 solver difficulty 不可比。

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

## 5A. GNN 传递步数消融训练

消融实验只改变：

```text
model.message_passing_steps = 2 / 3 / 4
```

其它训练设置保持一致：

```text
data.graphs_root = outputs/bench_build/latest
optimization.epochs = 800
optimization.batch_size = 8
model.hidden_dim = 64
model.latent_dim = 16
optimization.lr = 0.0003
optimization.seed = 1
loss_weights.param = 2.0
loss_weights.kl = 0.0015
```

建议把消融配置放在：

```text
outputs/gnn_steps_ablation/configs/train_steps_2.yml
outputs/gnn_steps_ablation/configs/train_steps_3.yml
outputs/gnn_steps_ablation/configs/train_steps_4.yml
```

配置模板如下，只改 `message_passing_steps`：

```yaml
data:
  graphs_root: outputs/bench_build/latest
  limit: 0

model:
  hidden_dim: 64
  latent_dim: 16
  message_passing_steps: 3

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

output:
  publish_latest: true
```

### 5A.1 CUDA 检查

在服务器上先确认 PyTorch 能调用 CUDA：

```bash
conda activate acmmilp

python - <<'PY'
import torch
print("torch:", torch.__version__)
print("torch cuda:", torch.version.cuda)
print("cuda available:", torch.cuda.is_available())
print("device count:", torch.cuda.device_count())
for i in range(torch.cuda.device_count()):
    print(i, torch.cuda.get_device_name(i))
PY
```

只要 `cuda available` 是 `True`，配置里的 `device: auto` 就会使用 CUDA。多卡服务器上，推荐用 `CUDA_VISIBLE_DEVICES` 把不同消融实验分配到不同 GPU。

### 5A.2 多 screen 并行训练

当前训练脚本是单进程单模型，不做 DDP。消融实验之间互相独立，最高效的方式是实验级并行：一个 `message_passing_steps` 占一张 GPU。

在仓库根目录执行：

```bash
mkdir -p outputs/gnn_steps_ablation/logs
```

用 screen 启动 `steps=2/3/4` 三个训练：

```bash
screen -dmS vae_s2 bash -lc '
cd /path/to/RailGraph2Gurobi &&
eval "$(conda shell.bash hook)" &&
conda activate acmmilp &&
CUDA_VISIBLE_DEVICES=1 python scripts/train_vae.py \
  outputs/gnn_steps_ablation/configs/train_steps_2.yml \
  > outputs/gnn_steps_ablation/logs/train_steps_2.log 2>&1
'

screen -dmS vae_s3 bash -lc '
cd /path/to/RailGraph2Gurobi &&
eval "$(conda shell.bash hook)" &&
conda activate acmmilp &&
CUDA_VISIBLE_DEVICES=2 python scripts/train_vae.py \
  outputs/gnn_steps_ablation/configs/train_steps_3.yml \
  > outputs/gnn_steps_ablation/logs/train_steps_3.log 2>&1
'

screen -dmS vae_s4 bash -lc '
cd /path/to/RailGraph2Gurobi &&
eval "$(conda shell.bash hook)" &&
conda activate acmmilp &&
CUDA_VISIBLE_DEVICES=3 python scripts/train_vae.py \
  outputs/gnn_steps_ablation/configs/train_steps_4.yml \
  > outputs/gnn_steps_ablation/logs/train_steps_4.log 2>&1
'
```

查看 screen：

```bash
screen -ls
```

查看训练日志：

```bash
tail -f outputs/gnn_steps_ablation/logs/train_steps_3.log
```

训练结束后，不要只记 `outputs/train/latest`。用配置内容识别真实 run：

```bash
python - <<'PY'
import json
from pathlib import Path

for path in sorted(Path("outputs/train").glob("*/training_config.json")):
    cfg = json.loads(path.read_text())
    print(
        "steps=", cfg.get("message_passing_steps"),
        "run=", path.parent,
        "best=", path.parent / "best_model.pt",
    )
PY
```

建议手动记录：

```text
STEPS_2_TRAIN_RUN=outputs/train/<time_for_steps_2>
STEPS_3_TRAIN_RUN=outputs/train/<time_for_steps_3>
STEPS_4_TRAIN_RUN=outputs/train/<time_for_steps_4>
```

也可以归档到统一目录：

```bash
mkdir -p outputs/gnn_steps_ablation/steps_2 outputs/gnn_steps_ablation/steps_3 outputs/gnn_steps_ablation/steps_4
cp outputs/train/<time_for_steps_2>/training_summary.json outputs/gnn_steps_ablation/steps_2/
cp outputs/train/<time_for_steps_2>/history.json outputs/gnn_steps_ablation/steps_2/
```

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

消融实验建议不要用 `outputs/train/latest`。对每组显式指定 checkpoint：

```bash
STEPS=3
TRAIN_RUN=outputs/train/<time_for_steps_3>

python scripts/generate_vae.py \
  --checkpoint ${TRAIN_RUN}/best_model.pt \
  --context-graph outputs/bench_build/latest/context.json \
  --num-samples 100 \
  --mode model \
  --device auto

GENERATE_RUN=$(readlink -f outputs/generate/latest)
mkdir -p outputs/gnn_steps_ablation/steps_${STEPS}
echo "${TRAIN_RUN}" > outputs/gnn_steps_ablation/steps_${STEPS}/train_run.txt
echo "${GENERATE_RUN}" > outputs/gnn_steps_ablation/steps_${STEPS}/generate_run.txt
```

## 7. Evaluate Generated Graphs

```bash
python scripts/evaluate_vae.py \
  --reference-graphs outputs/bench_build/latest \
  --generated-graphs outputs/generate/latest \
  --output outputs/generate/latest/evaluation.json
```

这里主要比较 count、anchor 分布和参数分布。求解难度等生成配置 solve 后再比较。

消融实验写到对应 generate run：

```bash
python scripts/evaluate_vae.py \
  --reference-graphs outputs/bench_build/latest \
  --generated-graphs ${GENERATE_RUN} \
  --output ${GENERATE_RUN}/evaluation.json
```

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

消融实验使用真实 generate run：

```bash
python scripts/decode_import_generated_graphs.py \
  --generated-graphs ${GENERATE_RUN} \
  --base-config config/base_demo.yaml
```

## 9. Build Generated Configs

```bash
python -u scripts/bench_build.py \
  --config-root outputs/generate/latest/configs
```

这会创建新的 `outputs/bench_build/<time>/`，并把 `outputs/bench_build/latest` 软连接切到这次生成配置的 build run。

消融实验必须记录这次 generated build 的真实目录：

```bash
python -u scripts/bench_build.py \
  --config-root ${GENERATE_RUN}/configs

GENERATED_BUILD_RUN=$(readlink -f outputs/bench_build/latest)
echo "${GENERATED_BUILD_RUN}" > outputs/gnn_steps_ablation/steps_${STEPS}/generated_build_run.txt
```

## 10. Validate Generated Cases

```bash
python -u scripts/bench_solve.py \
  --config-root outputs/bench_build/latest/configs \
  --time-limit 120 \
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

消融实验建议显式读取 `GENERATED_BUILD_RUN`，不要依赖 latest：

```bash
python -u scripts/bench_solve.py \
  --config-root ${GENERATED_BUILD_RUN}/configs \
  --time-limit 120 \
  --workers 4 \
  --threads-per-solve 8 \
  --summary-csv ${GENERATE_RUN}/bench_solve_summary.csv \
  --summary-json ${GENERATE_RUN}/bench_solve_summary.json \
  > ${GENERATE_RUN}/bench_solve.log 2>&1

python -u scripts/bench_export_timetable.py \
  --config-root ${GENERATED_BUILD_RUN}/configs \
  --summary-csv ${GENERATE_RUN}/bench_export_timetable_summary.csv \
  --summary-json ${GENERATE_RUN}/bench_export_timetable_summary.json \
  > ${GENERATE_RUN}/bench_export_timetable.log 2>&1

python -u scripts/bench_analyze.py \
  --config-root ${GENERATED_BUILD_RUN}/configs \
  --summary-csv ${GENERATE_RUN}/bench_analyze_summary.csv \
  --summary-json ${GENERATE_RUN}/bench_analyze_summary.json \
  > ${GENERATE_RUN}/bench_analyze.log 2>&1
```

如果 Gurobi license 不允许多个 solver 进程，把 solve 命令改为：

```bash
python -u scripts/bench_solve.py \
  --config-root ${GENERATED_BUILD_RUN}/configs \
  --time-limit 120 \
  --workers 1 \
  --threads-per-solve 16 \
  --summary-csv ${GENERATE_RUN}/bench_solve_summary.csv \
  --summary-json ${GENERATE_RUN}/bench_solve_summary.json \
  > ${GENERATE_RUN}/bench_solve.log 2>&1
```

## 11. Compare Solver Difficulty

```bash
python scripts/evaluate_vae.py \
  --reference-solve-csv outputs/bench_build/reference_solve_summary.csv \
  --generated-solve-csv outputs/generate/latest/bench_solve_summary.csv \
  --output outputs/generate/latest/solver_difficulty.json
```

到这里，当前主链路验收完成。

消融实验对每组写入对应 generate run：

```bash
python scripts/evaluate_vae.py \
  --reference-solve-csv outputs/bench_build/reference_solve_summary.csv \
  --generated-solve-csv ${GENERATE_RUN}/bench_solve_summary.csv \
  --output ${GENERATE_RUN}/solver_difficulty.json

cp ${GENERATE_RUN}/evaluation.json outputs/gnn_steps_ablation/steps_${STEPS}/
cp ${GENERATE_RUN}/solver_difficulty.json outputs/gnn_steps_ablation/steps_${STEPS}/
cp ${GENERATE_RUN}/decode_import_summary.csv outputs/gnn_steps_ablation/steps_${STEPS}/
cp ${GENERATE_RUN}/bench_solve_summary.csv outputs/gnn_steps_ablation/steps_${STEPS}/
```

三组都完成后，`docs/GNN传递次数消融报告.md` 应比较：

- training: best loss、best epoch、count/anchor/param/KL 分项。
- generated graph: count、anchor、param 分布相似性。
- decoded disturbance graph: 扰动节点数、kind 组合、role edge 数和时间/空间关系。
- generated build: 变量数、约束数、非零项数等 MILP 规模。
- generated solve: `--time-limit 120` 下的 ok/timeout/failed 数量、duration、objective、MIP gap。

注意：同一个 BaseContext 下 context graph 的候选节点数是固定的，不能作为“学没学到位”的核心证据。真正要比较的是生成扰动图结构、build 后 MILP 实例规模和 solver 行为是否接近 reference。
