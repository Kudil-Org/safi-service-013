"""Create git history for the demo repositories if missing (fresh clones)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from safi.demo import ensure_demo_repos  # noqa: E402


def main():
    created = ensure_demo_repos(ROOT)
    if created:
        print("created demo repository history:", ", ".join(created))
    else:
        print("demo repository history already present")


if __name__ == "__main__":
    main()
