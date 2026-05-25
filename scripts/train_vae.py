from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VAE_ROOT = REPO_ROOT / "VAE"
if str(VAE_ROOT) not in sys.path:
    sys.path.insert(0, str(VAE_ROOT))
os.chdir(REPO_ROOT)

from src.train import main


if __name__ == "__main__":
    main()
