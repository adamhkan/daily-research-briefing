"""Stream application output to the console and a credential-redacted log file."""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Iterable, TextIO


def redact_text(text: str, secrets: Iterable[str] = ()) -> str:
    values = [*secrets, *(value for name, value in os.environ.items()
                         if re.search(r'(?:TOKEN|SECRET|PASSWORD|API_KEY)(?:_|$)', name, re.I))]
    for value in sorted({v for v in values if isinstance(v, str) and v}, key=len, reverse=True):
        text = text.replace(value, '[REDACTED]')
    text = re.sub(r'\b(?:sk-[A-Za-z0-9_-]+|gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)',
                  '[REDACTED]', text)
    return re.sub(r'\bBearer\s+[^\s\'\",;}]+', 'Bearer [REDACTED]', text, flags=re.I)


def capture(source: Iterable[str], path: Path, console: TextIO) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as output:
        for line in source:
            safe = redact_text(line)
            output.write(safe)
            output.flush()
            console.write(safe)
            console.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    capture(sys.stdin, args.out, sys.stdout)


if __name__ == '__main__':
    main()
