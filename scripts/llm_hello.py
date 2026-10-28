#!/usr/bin/env python3
"""Send a single-turn test message to Claude Opus 5.5 (or configured model) via Bedrock Mantle.

Usage:
    python scripts/llm_hello.py [--model <model_id>]
"""

import sys
from pathlib import Path

# Add backend directory to sys.path so app modules can be imported
backend_dir = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

from app.llm_hello import main  # noqa: E402

if __name__ == "__main__":
    main()
