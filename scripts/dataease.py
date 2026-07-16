#!/usr/bin/env python3
import sys

for stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

from dataease_skill.cli import main


if __name__ == "__main__":
    main()
