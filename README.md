# RailGraph2Gurobi

4-stage pipeline: **build -> solve -> export-timetable -> analyze**.

## Quick Start

Prepare the BaseContext once for the timetable/mileage pair:

```bash
python scripts/prepare_base_context.py \
  --timetable-path inputs/下行计划时刻表.xlsx \
  --mileage-path inputs/区间里程.xlsx
```

Then run the pipeline with any config that references the generated context:

```bash
python main.py run --config config/mixed_scenarios_demo.yaml
```

Or run each stage separately:

```bash
python main.py build            --config config/mixed_scenarios_demo.yaml
python main.py solve            --config config/mixed_scenarios_demo.yaml
python main.py export-timetable --config config/mixed_scenarios_demo.yaml
python main.py analyze          --config config/mixed_scenarios_demo.yaml
```

## BaseContext

`scripts/prepare_base_context.py` converts timetable and mileage Excel files into a stable base context JSON:

```text
inputs/context_<timetable_stem>.json
```

The context stores validated input rows, translated train/event/section data, mileage mapping, `EventAnchor`, and `SectionAnchor`.

```bash
python scripts/prepare_base_context.py \
  --timetable-path inputs/上行计划时刻表.xlsx \
  --mileage-path inputs/区间里程.xlsx

python scripts/prepare_base_context.py \
  --timetable-path inputs/下行计划时刻表.xlsx \
  --mileage-path inputs/区间里程.xlsx
```

Optional arguments:

| Option | Default |
|---|---|
| `--timetable-sheet-name` | `Sheet1` |
| `--mileage-sheet-name` | `Sheet1` |
| `--output-path` | `inputs/context_<timetable_stem>.json` |

## Config

Configs only reference `project.base_context_path`. The timetable and mileage files are no longer read directly during build/solve/export/analyze.

```yaml
project:
  name: my_case
  output_dir: outputs/my_case
  base_context_path: inputs/context_下行计划时刻表.json

build:
  scenarios:
    delays:
      - train_id: G101
        station: 济南西
        event_type: dep
        seconds: 600
    speed_limits:
      - start_station: 济南西
        end_station: 泰安
        start_time: "08:00:00"
        duration: 3600
        limit_speed: 80
      - start_station: 泰安
        end_station: 曲阜东
        start_time: "09:00:00"
        duration: 1800
        limit_speed: 0

solve:
  lp_path: ""
  objective_mode: abs
  objective_delay_weight: 1.0
  cancellation_enabled: false
  cancellation_penalty_weight: 1000.0
  arr_arr_headway_seconds: 180
  dep_dep_headway_seconds: 180
  dwell_seconds_at_stops: 120
  big_m: 100000
  tolerance_delay_seconds: 7200

export-timetable:
  sol_path: ""

analyze:
  enable_metrics: true
  enable_plot: false
  plot_grid: true
  plot_title: Train Timetable
  adj_timetable_path: ""
  adj_timetable_sheet_name: Sheet1
```

Scenario rules:

| Scenario | Fields | Notes |
|---|---|---|
| Delay | `train_id`, `station`, `event_type`, `seconds` | Or use `event_anchor_id` directly |
| Speed limit | `start_station`, `end_station`, `start_time`, `duration`, `limit_speed` | Or use `section_anchor_id` directly |
| Interruption | same as speed limit | Use `limit_speed: 0` |

When both anchor id and semantic fields are provided, they must resolve to the same BaseContext anchor.

Stage outputs:

| Stage | Output |
|---|---|
| build | `{output_dir}/{name}.lp` |
| solve | `{output_dir}/{name}.sol` |
| export-timetable | `{output_dir}/adjusted_timetable.xlsx` |
| analyze | `{output_dir}/analysis_metrics.xlsx`, `{output_dir}/timetable_plot.png` |

## Disturbance Graph JSON

Use disturbance graph JSON as the recommended exchange format for generated scenarios. The graph references an existing `BaseContext`; it does not define new anchors.

```bash
python scripts/export_disturbance_graph.py \
  --config config/mixed_scenarios_demo.yaml \
  --output outputs/mixed_scenarios_demo/disturbance_graph.json

python scripts/import_disturbance_graph.py \
  --graph outputs/mixed_scenarios_demo/disturbance_graph.json \
  --base-config config/base_demo.yaml \
  --output-config config/generated_from_graph.yaml
```

Graph fields are intentionally minimal:

| Field | Meaning |
|---|---|
| `base_context_path` | Source `BaseContext` for all anchor ids |
| `disturbances` | `delay` or `speed_limit` facts |
| `role_edges` | `on_event` or `on_section` anchor links |

`speed_limit: 0` represents an interruption. `end_time` is not stored in the graph; it is always derived as `start_time + duration`.

## Math VAE Graph JSON

`bench_build.py` exports the mathematical model input for the context-conditioned disturbance graph VAE while building the case library. RailGraph2Gurobi owns all railway semantics and compiles them into numeric pools, numeric edges, task rules, and supervision labels. The VAE reads only math graph samples; `dataset_profile.json` is a context-bound explanation file for humans and RailGraph2Gurobi checks.

The math learning graph contains:

| Field | Meaning |
|---|---|
| `rules` | Numeric pool, edge type, task, and parameter-domain rules |
| `graph.pool_x` | Numeric candidate-pool feature matrices |
| `graph.edges` | Numeric typed edges between pool indexes |
| `supervision.targets` | Count, anchor-index, and parameter labels |
| `supervision.target_relations` | Optional numeric relation features for encoder-side learning |
| `decode_handle` | Opaque handle copied back for RailGraph2Gurobi decode |

`bench_build.py` writes the timestamped graph library under `outputs/bench_build/<timestamp>/case_graph_library/` and publishes the latest copy to `outputs/bench_build/case_graph_library/`. The profile is bound to one `base_context_path` and retains feature names, anchor ids, task/edge descriptions, exporter settings, source config paths, and decode contracts. VAE code reads `graphs/` and does not read the profile.

Train and generate from the repository root:

```bash
python scripts/train_vae.py \
  --graphs-root outputs/bench_build/case_graph_library \
  --epochs 3 \
  --batch-size 1 \
  --message-passing-steps 2

python scripts/generate_vae.py \
  --checkpoint outputs/train/model/model.pt \
  --context-graphs outputs/bench_build/case_graph_library \
  --num-samples 100 \
  --mode model
```

Each generate run creates `outputs/generate/YYYY-MM-DD_HH-MM-SS/`; generated math graph JSON files are written under that run's `math_sample/` directory.

Generated math graph decode:

```bash
python scripts/decode_import_generated_graphs.py \
  --generated-graphs outputs/generate/<run> \
  --base-config config/base_demo.yaml
```

The generated math graph contains only `decode_handle` and numeric `task_outputs`. RailGraph2Gurobi decodes task ids, pool indexes, and parameter vectors back into a standard `disturbance_graph`.

VAE output boundary:

| Direction | Format |
|---|---|
| RailGraph2Gurobi -> VAE | `vae_math_learning_graph` |
| VAE -> RailGraph2Gurobi | `vae_math_generated_graph` |
| RailGraph2Gurobi internal/import | `disturbance_graph` |

## Batch Pipeline

Prepare the context first:

```bash
python scripts/prepare_base_context.py \
  --timetable-path inputs/下行计划时刻表.xlsx \
  --mileage-path inputs/区间里程.xlsx
```

Generate case configs:

```bash
python -u scripts/case_library_builder.py \
  --output-root config/batch_case_configs_demo \
  --interruption-count 10 \
  --clean > outputs/case_library_builder.log 2>&1
```

Run all 4 batch stages in order:

```bash
python -u scripts/bench_build.py            --config-root config/batch_case_configs_demo
python -u scripts/bench_solve.py            --config-root outputs/bench_build/case_library > outputs/bench_solve.log 2>&1
python -u scripts/bench_export_timetable.py --config-root outputs/bench_build/case_library > outputs/bench_export_timetable.log 2>&1
python -u scripts/bench_analyze.py          --config-root outputs/bench_build/case_library > outputs/bench_analyze.log 2>&1
```

`bench_build.py` creates `outputs/bench_build/<timestamp>/case_library/` and `outputs/bench_build/<timestamp>/case_graph_library/`, then publishes the latest copies to `outputs/bench_build/case_library/` and `outputs/bench_build/case_graph_library/`. It writes `summary.csv`, `summary.json`, and `bench_build.log` in the timestamped run directory while also printing to the terminal.

### bench_solve.py Options

| Option | Default | Description |
|---|---|---|
| `--start-index` | `1` | 1-based start index, inclusive |
| `--end-index` | `0` | 1-based end index, inclusive, `0` means no upper bound |
| `--workers` | `1` | parallel solver processes |
| `--threads-per-solve` | `0` | Gurobi threads per solve, `0` means `cpu_count // workers` |
| `--time-limit` | `0` | seconds per solve, `0` means no limit |
| `--mip-gap` | `0` | relative MIP gap, `0` uses Gurobi default |

## Import External Solutions

### Import `.sol` files

```bash
python -u scripts/import_solutions.py \
  --solutions-root tests/solutions \
  --base-config config/base_demo.yaml \
  --generated-config-root tests/generated_configs \
  --output-root outputs/solutions_import > outputs/import_solutions.log 2>&1

python -u scripts/bench_export_timetable.py --config-root tests/generated_configs > outputs/bench_export_timetable.log 2>&1
python -u scripts/bench_analyze.py          --config-root tests/generated_configs > outputs/bench_analyze.log 2>&1
```

### Legacy import `.lp` files

Prefer disturbance graph JSON for scenario exchange. `import_lp.py` is kept only for external LP compatibility and best-effort scenario inference.

```bash
python -u scripts/import_lp.py \
  --lp-root tests/lp \
  --base-config config/base_demo.yaml \
  --generated-config-root tests/generated_configs_lp \
  --output-root outputs/lp_import \
  --scenario-inference require > outputs/import_lp.log 2>&1
```

If the LP uses a different base context than the base config, pass `--base-context-path inputs/context_下行计划时刻表.json`. To skip scenario inference, use `--scenario-inference off`.

```bash
python -u scripts/bench_solve.py            --config-root tests/generated_configs_lp > outputs/bench_solve.log 2>&1
python -u scripts/bench_export_timetable.py --config-root tests/generated_configs_lp > outputs/bench_export_timetable.log 2>&1
python -u scripts/bench_analyze.py          --config-root tests/generated_configs_lp \
  --scenario-report on --scenario-report-scope batch > outputs/bench_analyze.log 2>&1
```

`bench_analyze.py` scenario report options: `--scenario-report on|off`, `--scenario-report-scope batch|per_case|both`.

## Common Errors

| Error | Fix |
|---|---|
| `No module named core` | Run from repository root |
| `Missing dependency` | Install `pyyaml openpyxl pandas matplotlib gurobipy` |
| `Missing required config field: project.base_context_path` | Run `prepare_base_context.py` and reference the generated JSON |
| `Unknown event_anchor_id` or `Unknown section_anchor_id` | Use anchors from the referenced BaseContext |
| `No stations found for plotting` | Set `analyze.enable_plot: false` |
| `scenario_inference_status=failed` | Verify LP naming convention and the selected BaseContext |
