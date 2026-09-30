"""Make the offline evaluation tooling importable the way its scripts import it."""

import sys
from pathlib import Path

_EVALUATIONS = Path(__file__).resolve().parents[1] / "evaluations"
for path in (_EVALUATIONS, _EVALUATIONS / "datasets", _EVALUATIONS / "experiments"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
