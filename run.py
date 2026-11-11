"""Run Verity from any working directory: python run.py serve"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lwc_tracker.cli import main  # noqa: E402

sys.exit(main())
