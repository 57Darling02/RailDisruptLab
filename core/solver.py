from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional


class GurobiSolveError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status: int,
        sol_count: int,
        node_count: Optional[float],
        timed_out: bool,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.sol_count = sol_count
        self.node_count = node_count
        self.timed_out = timed_out


class SolveResult:
    def __init__(
        self,
        objective: float,
        values: Dict[str, float],
        mip_gap: float,
        node_count: float,
        timed_out: bool,
    ) -> None:
        self.objective = objective
        self.values = values
        self.mip_gap = mip_gap
        self.node_count = node_count
        self.timed_out = timed_out


def solve_lp(
    lp_path: Path,
    solution_path: Path,
    quiet: bool = False,
    threads: int = 0,
    time_limit: float = 0.0,
    mip_gap: float = 0.0,
) -> SolveResult:
    try:
        import gurobipy as gp
        from gurobipy import GRB
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Missing dependency: gurobipy") from exc

    env = gp.Env(empty=True)
    if quiet:
        env.setParam("OutputFlag", 0)
    if threads > 0:
        env.setParam("Threads", threads)
    if time_limit > 0:
        env.setParam("TimeLimit", time_limit)
    if mip_gap > 0:
        env.setParam("MIPGap", mip_gap)
    env.start()
    model = gp.read(str(lp_path), env)
    model.optimize()

    timed_out = model.status == GRB.TIME_LIMIT
    node_count = _safe_float_attr(model, "NodeCount")
    if model.status not in (GRB.OPTIMAL, GRB.TIME_LIMIT) or model.SolCount == 0:
        raise GurobiSolveError(
            f"Gurobi optimize failed, status={model.status}, SolCount={model.SolCount}",
            status=int(model.status),
            sol_count=int(model.SolCount),
            node_count=node_count,
            timed_out=timed_out,
        )

    solution_path.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(solution_path))

    values = {var.VarName: float(var.X) for var in model.getVars()}
    achieved_gap = float(model.MIPGap) if model.SolCount > 0 else float("inf")
    return SolveResult(
        objective=float(model.objVal),
        values=values,
        mip_gap=achieved_gap,
        node_count=node_count or 0.0,
        timed_out=timed_out,
    )


def _safe_float_attr(model: object, attr_name: str) -> Optional[float]:
    try:
        return float(getattr(model, attr_name))
    except Exception:
        return None


def load_solution_values(solution_path: Path) -> Dict[str, float]:
    values: Dict[str, float] = {}
    if not solution_path.exists():
        raise FileNotFoundError(f"Solution file not found: {solution_path}")

    with solution_path.open("r", encoding="utf-8") as file:
        for line in file:
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            parts = text.split()
            if len(parts) < 2:
                continue
            var_name = parts[0]
            try:
                var_value = float(parts[1])
            except ValueError:
                continue
            values[var_name] = var_value
    return values
