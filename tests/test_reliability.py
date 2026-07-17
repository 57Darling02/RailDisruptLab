from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.analysis.model import normalize_loss_point
from backend.task_contracts import normalize_task_params
from backend.task_resources import TaskResourceConflict, ensure_no_active_conflict
from core.file_ops import atomic_write_text
from core.project_layout import replace_dir_with_rollback


class ReliabilityTests(unittest.TestCase):
    def test_loss_point_keeps_relation_loss(self) -> None:
        point = normalize_loss_point(
            {
                "step": 1,
                "epoch": 1,
                "epoch_step": 1,
                "total_steps": 3,
                "loss": 2.0,
                "relation_loss": 0.25,
            }
        )

        self.assertEqual(point["relation_loss"], 0.25)

    def test_train_params_reject_non_positive_and_non_finite_values(self) -> None:
        with self.assertRaisesRegex(ValueError, r"train\.epochs must be a positive integer"):
            normalize_task_params("train", {"model_id": "model", "scenario_set_id": "set", "epochs": 0})
        with self.assertRaisesRegex(ValueError, r"train\.lr must be a finite number"):
            normalize_task_params(
                "train",
                {"model_id": "model", "scenario_set_id": "set", "lr": math.nan},
            )

    def test_atomic_write_preserves_previous_file_on_publish_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            path.write_text("old", encoding="utf-8")

            with patch("core.file_ops.os.replace", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    atomic_write_text(path, "new")

            self.assertEqual(path.read_text(encoding="utf-8"), "old")
            self.assertEqual(list(path.parent.glob(".state.json.*.tmp")), [])

    def test_directory_replacement_restores_previous_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "model"
            artifact.mkdir()
            (artifact / "old.txt").write_text("old", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "training failed"):
                with replace_dir_with_rollback(artifact, allowed_root=root):
                    (artifact / "new.txt").write_text("new", encoding="utf-8")
                    raise RuntimeError("training failed")

            self.assertEqual((artifact / "old.txt").read_text(encoding="utf-8"), "old")
            self.assertFalse((artifact / "new.txt").exists())
            self.assertEqual(list(root.glob(".model.backup-*")), [])

    def test_directory_replacement_restores_previous_artifact_when_preparation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "model"
            artifact.mkdir()
            (artifact / "old.txt").write_text("old", encoding="utf-8")

            with patch.object(Path, "mkdir", side_effect=PermissionError("permission denied")):
                with self.assertRaises(PermissionError):
                    with replace_dir_with_rollback(artifact, allowed_root=root):
                        pass

            self.assertEqual((artifact / "old.txt").read_text(encoding="utf-8"), "old")
            self.assertEqual(list(root.glob(".model.backup-*")), [])

    def test_resource_conflict_blocks_model_replacement_while_training(self) -> None:
        active_tasks = [
            {
                "id": 7,
                "status": "Running",
                "action": "train",
                "params": {"model_id": "model_a", "scenario_set_id": "source"},
            }
        ]

        with self.assertRaises(TaskResourceConflict):
            ensure_no_active_conflict(
                active_tasks,
                action="generation",
                params={
                    "model_id": "model_a",
                    "scenario_set_id": "output",
                    "source_scenario_set_id": "",
                    "run_graph": {"set_id": "graphs", "graph_id": "baseline"},
                },
            )


if __name__ == "__main__":
    unittest.main()
