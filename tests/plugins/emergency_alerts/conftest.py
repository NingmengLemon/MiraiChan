import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGINS_ROOT = REPO_ROOT / "packages" / "plugins"
if str(PLUGINS_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGINS_ROOT))
