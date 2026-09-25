#!/usr/bin/env python3
"""Within-voice note overlap in the demo fugue: each voice split into alternating odd/even stems
(run qa_chain.py first). Prints the previous note level relative to the current in its first 100 ms."""

import sys, json, numpy as np, mido
sys.path.insert(0,'/Users/biobook/Music/llm-music/fugue-jp/ricercar/audio/piano/qa')
from qa_lib import *
notes=midi_notes(TMP/'fugue_demo.mid')
out={}
for voice,tr in (('pedal',-12),('tenor',0),('soprano',0)):
    vn=[n for n in notes if n['voice']==voice]
    # replicate the renderer's perform-scale velocity mapping by writing a perform-marked file
    evs={'odd':[], 'even':[]}
    for i,n in enumerate(vn):
        v='odd' if i%2 else 'even'
        evs[v]+= [(n['start'], mido.Message('note_on',note=n['key']+tr,velocity=n['vel'])),(n['end'], mido.Message('note_off',note=n['key']+tr,velocity=0))]
    p=TMP/f'split_{voice}.mid'
    write_midi(p, evs, marker='perform.py target=piano')
    render(p, TMP/f'split_{voice}', '--no-reverb','--no-m4a')
    st={v: read(TMP/f'split_{voice}_stems'/f'{v}.wav') for v in ('odd','even')}
    ov=[];ovk=[]
    for i in range(1,len(vn)):
        cur='odd' if i%2 else 'even'; prev='even' if i%2 else 'odd'
        a=int((vn[i]['start']+LEAD_IN)*SR); b=a+int(0.1*SR)
        ov.append(rms_db(st[prev][a:b])-rms_db(st[cur][a:b]))
        ovk.append(rms_db(kweight(st[prev][a:b]))-rms_db(kweight(st[cur][a:b])))
    ov=np.array(ov); ovk=np.array(ovk)
    out[voice]=dict(n=len(ov), overlap_db_median=round(float(np.median(ov)),1), overlap_db_p90=round(float(np.percentile(ov,90)),1),
                    frac_prev_within_6db=round(float(np.mean(ov>-6)),3), frac_prev_louder=round(float(np.mean(ov>0)),3),
                    k_overlap_db_median=round(float(np.median(ovk)),1), k_frac_prev_within_6db=round(float(np.mean(ovk>-6)),3))
    print(voice, out[voice])
json.dump(out, open('/tmp/pianoqa/split_overlap.json','w'), indent=1)
