"""Print an acceptance spec's context (yaml, page, attachments, ...) as payload JSON.

Lets the simulate-users skill reuse a spec's setup as stock context without
copying it. The spec's own turn, history and session meta are left out.

Usage: PYTHONPATH=services poetry run python -m testing.spec_context <spec.md>
"""

import json
import sys
from pathlib import Path

from testing.spec_parser import parse_spec


def main() -> None:
    settings = parse_spec(Path(sys.argv[1])).settings
    settings.pop("meta", None)
    json.dump(settings, sys.stdout, indent=2)


if __name__ == "__main__":
    main()
