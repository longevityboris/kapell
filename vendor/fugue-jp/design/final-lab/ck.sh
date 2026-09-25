#!/bin/sh
# Project checker with the ricercar ranges (S 60-84, A 53-77, T 48-72, B 36-62).
# usage: sh ck.sh FILE.ly [extra check.py args]
HERE=$(cd "$(dirname "$0")" && pwd)
exec python3 "$HERE/../../tools/check.py" "$@" --voices soprano,alto,tenor,bass \
  --range soprano=60-84 --range alto=53-77 --range tenor=48-72 --range bass=36-62
