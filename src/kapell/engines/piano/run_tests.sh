#!/usr/bin/env bash
# Both dynamics tests, end to end (about 25 s; more under heavy load). Nothing is played through the speakers.
#   1. direct:  make_test_midi.py (calibrated velocities, CC11 ramp, voicing, pedal)
#   2. chain:   tests/chain_test.ly + plan -> tools/perform.py --target piano -> renderer
# Writes out/{dynamics_test,chain_test}.{mid,segments.json,wav,m4a,render.json,analysis.json}.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
python3 make_test_midi.py
python3 render_piano.py out/dynamics_test.mid -o out/dynamics_test --stems out/dynamics_test_stems \
  --json out/dynamics_test.render.json >/dev/null
python3 analyse_dynamics.py --json out/dynamics_test.analysis.json
echo
python3 make_chain_test.py
python3 render_piano.py out/chain_test.mid -o out/chain_test --stems out/chain_test_stems \
  --json out/chain_test.render.json >/dev/null
python3 analyse_dynamics.py --wav out/chain_test.wav --stems out/chain_test_stems \
  --segments out/chain_test.segments.json --json out/chain_test.analysis.json
