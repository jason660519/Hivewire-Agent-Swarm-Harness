"""Makes the flat co-routing/ modules importable as `import ssrf_guard`
etc. regardless of how pytest is invoked (plain `pytest`, `uv run pytest`,
or `python -m pytest` all behave differently re: sys.path)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
