"""Frozen executable entry point; the development CLI remains unchanged."""
import json
import sys

from lyrics_pro.bridge import main
from lyrics_pro.self_check import self_check


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-check"]:
        print(json.dumps(self_check(), ensure_ascii=False), flush=True)
    else:
        main()
