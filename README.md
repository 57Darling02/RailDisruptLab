# RailGraph2Gurobi

RailGraph2Gurobi builds, solves, exports, and analyzes railway disturbance cases. The workflow is project-oriented: one project config defines shared settings, and scenario files define individual cases.

No `latest` directory is created or read.

## Quick Start

Prepare the shared BaseContext once:

```bash
python scripts/prepare_base_context.py \
  --timetable-path inputs/下行计划时刻表.xlsx \
  --mileage-path inputs/区间里程.xlsx
```

Build and benchmark the scenarios referenced by `config/demo.yml`:

```bash
python scripts/project.py dataset build \
  --config config/demo.yml \
  --dataset demo

python scripts/project.py dataset benchmark \
  --config config/demo.yml \
  --dataset demo \
  --time-limit 120
```

Generate a larger scenario library and benchmark it with the same project config:

```bash
python -u scripts/case_library_builder.py \
  --output-root config/scenario/generated_reference \
  --clean

python scripts/project.py dataset build \
  --config config/demo.yml \
  --dataset reference \
  --scenarios config/scenario/generated_reference

python scripts/project.py dataset benchmark \
  --config config/demo.yml \
  --dataset reference \
  --time-limit 120
```

## Config Model

`config/demo.yml` is the project config. It contains:

| Section | Meaning |
|---|---|
| `project` | project name and `base_context_path` |
| `build.scenarios` | scenario file or directory reference |
| `solve` | solver defaults |
| `export-timetable` | timetable export defaults |
| `analyze` | analysis defaults |
| `train` | VAE training defaults |

Scenario files live under `config/scenario/` and contain only case-level disturbances:

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

`limit_speed: 0` represents an interruption.

## Output Layout

```text
outputs/<project>/
  project.json
  datasets/<dataset>/
    manifest.json
    configs/*.yaml
    cases/<case_id>/<case_id>.lp
    graph/context.json
    graph/samples/*.json
    graph/dataset_profile.json
    benchmark/build_summary.csv
    benchmark/solve_summary.csv
    benchmark/export_timetable_summary.csv
    benchmark/analyze_summary.csv
    logs/*.log
  models/<model>/
  generations/<generation>/
  comparisons/<comparison>/
```

Rerunning the same project/dataset/model/generation name overwrites that target.

## Dataset Commands

Use the scenarios referenced by the project config:

```bash
python scripts/project.py dataset build \
  --config config/demo.yml \
  --dataset demo
```

Override the scenario source without creating another project config:

```bash
python scripts/project.py dataset build \
  --config config/demo.yml \
  --dataset reference \
  --scenarios config/scenario/generated_reference
```

Benchmark:

```bash
python scripts/project.py dataset benchmark \
  --config config/demo.yml \
  --dataset reference \
  --time-limit 120 \
  --workers 4 \
  --threads-per-solve 8
```

Useful benchmark flags:

| Option | Meaning |
|---|---|
| `--limit N` | Run only the first N configs |
| `--skip-solve` | Skip solver stage |
| `--skip-export` | Skip timetable export stage |
| `--skip-analyze` | Skip analysis stage |
| `--scenario-report on/off` | Enable or disable scenario statistics |
| `--scenario-report-scope batch/per_case/both` | Scenario report granularity |

## Math VAE Flow

Training and generation are optional.

```bash
python scripts/project.py model train \
  --config config/demo.yml \
  --model vae_reference \
  --dataset reference

python scripts/project.py generation create \
  --config config/demo.yml \
  --generation gen_reference \
  --dataset reference \
  --model vae_reference \
  --num-samples 100

python scripts/project.py generation decode \
  --config config/demo.yml \
  --generation gen_reference
```

Build and benchmark generated configs as a normal dataset:

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

Compare solver difficulty:

```bash
python scripts/project.py compare solver \
  --config config/demo.yml \
  --reference reference \
  --candidate generated_reference \
  --generation gen_reference
```

## Graph Formats

VAE training reads:

```text
outputs/<project>/datasets/<dataset>/graph/context.json
outputs/<project>/datasets/<dataset>/graph/samples/*.json
```

Generation writes:

```text
outputs/<project>/generations/<generation>/math_graphs/*.json
```

Decode writes:

```text
outputs/<project>/generations/<generation>/disturbance_graphs/*.json
outputs/<project>/generations/<generation>/configs/*.yaml
outputs/<project>/generations/<generation>/case_outputs/<case_id>/
```

## Common Errors

| Error | Fix |
|---|---|
| `No module named core` | Run from repository root |
| `Missing dependency` | Install `pyyaml openpyxl pandas matplotlib gurobipy` in the active environment |
| `Missing required config field: project.base_context_path` | Run `prepare_base_context.py` and reference the generated context JSON |
| `Unknown event_anchor_id` or `Unknown section_anchor_id` | Use anchors from the referenced BaseContext |
| `No stations found for plotting` | Set `analyze.enable_plot: false` |
