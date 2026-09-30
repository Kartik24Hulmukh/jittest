"""Permit floating v0 advancement only for canonical final v0.x.y releases."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path


def stable_v0_tag(ref: str) -> bool:
    # rc/dev/alpha/beta (with or without a hyphen), local and post-release tags
    # are not canonical final Action releases; none may advance stable v0.
    return re.fullmatch(r'refs/tags/v0\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)', ref) is not None


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit('expected one full tag ref')
    stable = stable_v0_tag(sys.argv[1])
    with Path(os.environ['GITHUB_OUTPUT']).open('a', encoding='utf-8') as output:
        output.write(f'stable={str(stable).lower()}\n')
    print('floating v0 eligible' if stable else 'floating v0 unchanged: not a canonical final v0 release')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
