"""Quotas from kapell.toml, reported pass/fail (C section 5).

    [quotas]
    strong_suspensions = 20      # at least 20 prepared strong-beat suspensions
    max_dis7 = 0                 # "max_" keys are upper bounds on a measured count

measure(score, cfg) returns the counts quotas can refer to; evaluate(quotas, measured) compares.
Measured keys: strong_suspensions, weak_suspensions (kapell.analysis.suspensions.count, or the
vendored final-lab/suspensions.py by subprocess when the module is unavailable), plus whatever the
caller adds (xray adds dis7, unresolved, uncued_features, form_violations).
"""
import re
import subprocess
import sys
from pathlib import Path


def suspensions(score, voices=None, measure=None) -> dict:
    """{strong, weak, source}: in-process when kapell.analysis.suspensions exists, else vendored."""
    try:
        from kapell.analysis import suspensions as sus
        r = sus.count(str(score), voices=voices, measure=measure)
        return dict(strong=r["strong"], weak=r["weak"], source="module")
    except ImportError:
        pass
    script = Path(__file__).resolve().parents[3] / "vendor" / "fugue-jp" / "design" / "final-lab" / "suspensions.py"
    out = subprocess.run([sys.executable, str(script), str(score)], capture_output=True, text=True, timeout=120).stdout
    ms = re.search(r"prepared suspensions:\s*(\d+)", out)
    mw = re.search(r"weak-beat suspensions[^:]*:\s*(\d+)", out)
    if not (ms and mw):
        raise RuntimeError(f"cannot read the vendored suspensions.py output: {out[-200:]}")
    return dict(strong=int(ms.group(1)), weak=int(mw.group(1)), source="vendored-subprocess")


def evaluate(quotas: dict, measured: dict) -> dict:
    """{ok, quotas: [{name, target, measured, ok, status}], violations}"""
    rows, viol = [], []
    for name, target in (quotas or {}).items():
        upper = name.startswith("max_")
        key = name[4:] if upper else name
        if key not in measured:
            rows.append(dict(name=name, target=target, measured=None, ok=None, status="not measured"))
            continue
        got = measured[key]
        ok = got <= target if upper else got >= target
        row = dict(name=name, target=target, measured=got, ok=ok,
                   status="pass" if ok else ("above" if upper else "below"))
        rows.append(row)
        if not ok:
            viol.append(dict(code="QUOTA", name=name, target=target, measured=got, ok=False,
                             message=f"{name}: {got} {'above the limit' if upper else 'below the target'} {target}"))
    return dict(ok=not viol, quotas=rows, violations=viol)
