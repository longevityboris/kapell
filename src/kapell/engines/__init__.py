"""Sound engines (piano, strings, organ, orchestra), moved from fugue-jp/audio/.

Each engine is a directory of scripts that import their siblings through sys.path, as they did in
fugue-jp; their command lines and CONTRACT.md / README.md contracts are unchanged. Large assets
live under kapell.config.lib_dir(), never in the kit.
"""
from pathlib import Path

ENGINES = Path(__file__).resolve().parent
SRC = ENGINES.parents[1]          # .../src, so scripts run as files can import kapell
