# Rail Disturbance Math VAE

This package contains the VAE side of the RailGraph2Gurobi disturbance-generation workflow.

The supported boundary is:

```text
RailGraph2Gurobi -> vae_math_learning_graph
VAE              -> vae_math_generated_graph
RailGraph2Gurobi -> disturbance_graph/config/MILP validation
```

The VAE does not read railway semantic strings, anchor ids, YAML configs, LP files, or MPS files. It reads only numeric math graph samples exported by RailGraph2Gurobi.

## Train

From the repository root, export a dataset first:

```bash
python scripts/export_typed_vae_learning_graph.py \
  --config-glob "config/batch_case_configs_demo/**/*.yaml" \
  --output-dir outputs/vae_math_dataset
```

Then train from `VAE/`:

```bash
cd VAE
python -m src.train \
  --graphs-root ../outputs/vae_math_dataset \
  --output-dir outputs/math_graph_vae \
  --epochs 3 \
  --batch-size 1 \
  --message-passing-steps 2
```

## Generate

```bash
cd VAE
python -m src.generate \
  --checkpoint outputs/math_graph_vae/model.pt \
  --context-graphs ../outputs/vae_math_dataset \
  --output-dir ../outputs/generated_math_graphs \
  --num-samples 100 \
  --mode model
```

## Evaluate

Graph-output similarity can be evaluated directly on numeric graph JSON files:

```bash
cd VAE
python -m src.evaluate \
  --reference-graphs ../outputs/vae_math_dataset \
  --generated-graphs ../outputs/generated_math_graphs \
  --output ../outputs/generated_math_graphs/evaluation.json
```

Solver difficulty comparison is still retained as a downstream benchmark. Run RailGraph2Gurobi build/solve for the reference and generated configs, then pass the `bench_solve.py --summary-csv` outputs to:

```bash
python -m src.evaluate \
  --reference-solve-csv ../outputs/reference_bench_solve/summary.csv \
  --generated-solve-csv ../outputs/generated_bench_solve/summary.csv \
  --output ../outputs/solver_difficulty_evaluation.json
```

For decode/import/build validation, use the root project commands in `docs/exp.md` and `docs/test.md`.
