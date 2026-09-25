#!/usr/bin/env python3
"""Keyboard evenness and per-note stereo from two qa_notes.py result files (before/after).

Per velocity (20, 30, 45, 70, 110): K-weighted 400 ms level of every isolated key against a
quartic keyboard trend (max and rms deviation, worst three-key sample groups) and the five
group-vs-neighbour comparisons the QA flagged (e.g. G#3-A#3 against G3 and B3). Stereo: L/R
correlation and mono fold-down of all 440 notes. Velocity sweeps: span and largest steps.

    git show 06e0494:ricercar/audio/piano/qa/results/notes_raw.json > /tmp/notes_before.json
    python3 qa/qa_notes.py
    python3 qa/qa_evenness.py /tmp/notes_before.json qa/results/notes_raw.json qa/results/evenness.json
"""
import json
import sys

import numpy as np
def load(p): return json.load(open(p))
NAMES=['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
nm=lambda k: f"{NAMES[k%12]}{k//12-1}"
def summ(r, label):
    out={}
    for vel, d in r['iso'].items():
        rows=[x for x in d['notes']]
        keys=np.array([x['key'] for x in rows]); lv=np.array([x['k400_db'] for x in rows])
        trend=np.polyval(np.polyfit(keys,lv,4),keys)
        dev=lv-trend
        # group deviation (3 keys per sample root): roots at 21 + 3i ; group = root-1..root+1 (A0: 21-22, C8: 107-108)
        groups=[]
        for root in range(21,109,3):
            sel=(keys>=root-1)&(keys<=root+1)
            groups.append((root, float(dev[sel].mean())))
        worst=sorted(groups,key=lambda g:-abs(g[1]))[:4]
        out[vel]=dict(max_abs_key_dev=round(float(np.abs(dev).max()),2), rms_key_dev=round(float(np.sqrt((dev**2).mean())),2),
                      worst_groups=[(nm(g[0]-1)+'-'+nm(g[0]+1), round(g[1],2)) for g in worst])
        # specific QA-flagged comparisons
        k=dict(zip(keys.tolist(),lv.tolist()))
        f=lambda a,b: round(float(np.mean([k[x] for x in a])-np.mean([k[x] for x in b])),2)
        out[vel]['G#3-A#3 vs G3,B3']=f([56,57,58],[55,59])
        out[vel]['G#5-A#5 vs G5,B5']=f([80,81,82],[79,83])
        out[vel]['D6-E6 vs C#6,F6']=f([86,87,88],[85,89])
        out[vel]['D5-E5 vs C#5,F5']=f([74,75,76],[73,77])
        out[vel]['B5-C#6 vs A#5,D6']=f([83,84,85],[82,86])
    st=[x for d in r['iso'].values() for x in d['notes']]
    corr=np.array([x['lr_corr'] for x in st]); ml=np.array([x['mono_loss_db'] for x in st])
    out['stereo']=dict(corr_min=round(float(corr.min()),2), corr_median=round(float(np.median(corr)),2), n_negative=int((corr<0).sum()), n_total=len(corr),
                       mono_loss_worst=round(float(ml.min()),2), mono_loss_median=round(float(np.median(ml)),2))
    if 'sweep' in r:
        sw={}
        for key, rows in r['sweep'].items():
            lvv=np.array([x['rms_db'] for x in rows]); steps=np.diff(lvv)
            sw[key]=dict(span_db=round(float(lvv[-1]-lvv[0]),1), max_step=round(float(steps.max()),2), min_step=round(float(steps.min()),2))
        out['sweep']=sw
    return out
a=summ(load(sys.argv[1]),'before'); b=summ(load(sys.argv[2]),'after')
for k in a:
    print(k); print('  before', a[k]); print('  after ', b[k])
json.dump({'before':a,'after':b},open(sys.argv[3],'w'),indent=1)
