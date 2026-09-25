#!/usr/bin/env python3
"""Write materials.ly and every material/combination lab, check each one, write proofs.txt.

usage: python3 build_labs.py        (run after build_sk.py; takes about half a minute)

Every lab is a four-variable LilyPond file (unused voices are rests). Each is run through
tools/check.py (ck.sh, with the ricercar ranges) and strict.py; the summary lines and every
remaining flag (D4?, DIR, MEL, CROS, CLASH, XREL) are written to proofs.txt.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fl  # noqa: E402

oc = fl.octave

# ------------------------------------------------------------------------------------------------
# MATERIALS at reference pitch (the pitch of their first appearance in SK_final.ly unless noted)
# name -> (LilyPond, first use / note)
M = {
    'themeMinor': ("bes'2. bes'8 a'8 | bes'2. bes'8 a'8 | bes'4. c''8 c''4. ees''8 | ees''2. des''8 bes'8 | "
                   "c''4. a'8 f'4 des''8 bes'8 | c''2. f''8 bes'8 | ees''4. des''8 des''4. c''8 | c''1 | c''2 r2",
                   "reference: the whole theme in B-flat minor (THEME.md), never stated complete in the minor"),
    'themeMajor': ("bes'2. bes'8 a'8 | bes'2. bes'8 a'8 | bes'4. c''8 c''4. ees''8 | ees''2. d''8 bes'8 | "
                   "c''4. a'8 f'4 d''8 bes'8 | c''2. f''8 bes'8 | ees''4. d''8 d''4. c''8 | c''1 | c''2 r2",
                   "reference: the theme as the user knows it (THEME.md)"),
    'subjectOne': ("bes'2. bes'8 a'8 | bes'2. bes'8 a'8 | bes'4. c''8 c''4. ees''8 | ees''2. des''8 bes'8 | "
                   "c''4. a'8 f'4 r4", "S1 = theme bars 1 to 5 beat 3; soprano bar 1"),
    'answerOne': ("f'2. f'8 e'8 | f'2. f'8 e'8 | f'4. g'8 g'4. bes'8 | bes'2. aes'8 f'8 | g'4. e'8 c'4 r4",
                  "real answer in F minor; alto bar 5"),
    'csOne': ("r2. f4 | des'2. c'4 | bes4 a4 aes2 | ges2. f4 | a4. c'8 f4 r4",
              "CS1 lament, subject level; alto 9:4 (enters on the subject's beat 4)"),
    'csOneAnswer': ("r2. c''4 | aes''2. g''4 | f''4 e''4 ees''2 | des''2. c''4 | e''4. g''8 c''4 r4",
                    "CS1 at the answer level; soprano 5:4"),
    'csTwo': ("r1 | bes'8 a'8 bes'8 c''8 des''8 c''8 ees''8 ges'8 | des''4 c''8 f''8~ f''2 | "
              "ees''8 f''8 ees''8 des''8 ces''4 des''4 | f'2. r4",
              "CS2 motor, subject level; soprano bar 10 (landing note free: f'' at bar 13)"),
    'csTwoAnswer': ("r1 | f'8 e'8 f'8 g'8 aes'8 g'8 bes'8 des'8 | aes'4 g'8 c''8~ c''2 | "
                    "bes'8 c''8 bes'8 aes'8 ges'4 aes'4 | c'2. r4",
                    "CS2 at the answer level; alto bar 14 (landing free: c'' at bar 17)"),
    'subjectTwo': ("c''4. a'8 f'4 des''8 bes'8 | c''2. f''8 bes'8 | ees''4. des''8 des''4. c''8 | c''1",
                   "S2 = theme bars 5-8; soprano bar 30 (arioso), alto bar 42"),
    'inversion': ("f''2. f''8 ges''8 | f''2. f''8 ges''8 | f''4. ees''8 ees''4. c''8 | c''2. des''8 f''8 | "
                  "ees''4. ges''8 bes''4 r4",
                  "INV = tonal mirror of S1 (bes<->f, c<->ees, a<->ges, aes<->g, des fixed); reference pitch"),
    'inversionA': ("e2. e8 f8 | e2. e8 f8 | e4. d8 d4. b,8 | b,2. c8 e8 | d4. f8 a4 r4",
                   "INV in A minor; bass bar 35"),
    'inversionE': ("b2. b8 c'8 | b2. b8 c'8 | b4. a8 a4. fis8 | fis2. g8 b8 | a4. c'8 e'4 r4",
                   "INV in E minor (stretto at the 5th above, 2 bars); tenor bar 37"),
    'csOneInv': ("r2. a'4 | c'2. d'4 | e'4 f'4 fis'2 | gis'2. a'4 | f'4. d'8 a'2",
                 "CS1 inverted (the lament rising), A minor; alto 35:4"),
    'csTwoInv': ("e''8 f''8 e''8 d''8 c''8 d''8 b'8 g''8 | c''4 d''8 a'8~ a'4 b'4 | b'8 a'8 b'8 c''8 d''4 c''4",
                 "CS2 inverted, A minor; soprano bar 36 (three notes altered from the strict mirror)"),
    'inversionAug': ("f,1 | f,2 f,4 ges,4 | f,1 | f,2 f,4 ges,4 | f,2. ees,4 | ees,2. c,4 | c,1 | "
                     "c,2 des,4 f,4 | ees,2. ges,4 | bes,2 r2",
                     "INV in exact 2x augmentation = the dominant pedal; bass bar 42, lands on bes, at 51:1"),
    'headH': ("e2. e8 ees8", "the subject's head, x2. x8 (x-1)8; liquidation on E, G, B-flat, D-flat (26-28)"),
    'episodeCell': ("c''4. des''8 des''4. f''8 | ges''4. f''8 f''4. ees''8 | f''4 r2.",
                    "cell b = S1 bar 3 rhythm in sequence over the bass fifths F B-flat E-flat A-flat; soprano bar 18, lands on F (the third of D-flat) at 20:1"),
    'descantEntryFour': ("f''2 c''2~ | c''2. des''4 | c''4. e''8 g''4 ees''4 | f''2 ges''4 f''4 | e''2. d''4",
                         "free soprano over exposition entry 4, completing every chord (13:3 C, 15:2.5 E, G-flat on the N6/4); bar 13"),
    'subjectOneDflat': ("des'2. des'8 c'8 | des'2. des'8 c'8 | des'4. ees'8 ees'4. ges'8 | ges'2. f'8 des'8 | ees'4. c'8 aes4",
                        "S1 in D-flat major (III), the stretto leader; tenor bar 20"),
    'subjectOneGflat': ("ges''2. ges''8 f''8 | ges''2. ges''8 f''8 | ges''4. aes''8 aes''4. ces'''8 | ces'''2. bes''8 ges''8 | aes''4. f''8 des''4",
                        "S1 in G-flat major (VI), the stretto follower a 4th + octave above, 2 bars later; soprano bar 22"),
    'csOneDflat': ("r2. aes,4 | f2. ees4 | des4 c4 ces2 | bes,2. aes,4 | c4. ees8 aes,4",
                   "CS1 (the lament) in D-flat major under the stretto leader; bass 20:4"),
    'inversionAthird': ("e''2. e''8 f''8 | e''2. e''8 f''8 | e''4. d''8 d''4. b'8 | b'2. c''8 e''8 | d''4. f''8 a''4",
                        "INV in A minor, the third inverted entry (after the tenor's E-minor answer); soprano bar 41"),
    'csOneInvBass': ("r2. a,4 | c2. d4 | e4 f4 fis2 | gis2. a4 | f4. d8 a,4 e,4",
                     "CS1 inverted (the lament rising) in the bass under the third entry; cadence iv-i and the E that resolves to F; bass 41:4"),
    'csTwoInvLow': ("e'8 f'8 e'8 d'8 c'8 d'8 b8 g'8 | c'4 d'8 a8~ a4 b4 | b8 a8 b8 c'8 d'4 c'4",
                    "CS2 inverted an octave lower; alto bar 42"),
    'lamentLeadIn': ("bes2 a2 | aes2 g4 c'4", "tenor lead-in over the dominant pedal, the lament's fall, then C into its S1 entry; bar 46"),
    'headDiminution': ("f''4. f''16 ees''16",
                       "S1's head in diminution (x4. x16 (x-1)16); Climax II heads on F, G-flat, A, C (soprano) and E (alto), 50:3-53:3; the first neighbour is diatonic (E-flat) against the E-flat bass"),
    'climaxHeads': ("r2 f''4. f''16 ees''16 | ges''4. ges''16 f''16 a''4. a''16 aes''16 | g''2 c'''4. c'''16 bes''16 | bes''2. a''4",
                    "soprano 50-53: the diminution heads rising to C6 (52:3, the peak note) and B-flat 5 over C7 (53:1), then the A at the V fermata"),
    'hingeDescent': ("a''4 | f''4 ees''4 c''4 a'4 | bes'2.",
                     "the dominant hinge 53:4-55:1: V7 arpeggio falling to the leading tone A, which resolves to the tune's first note"),
    'themeCantusFirmus': ("bes'2. bes'8 a'8 | bes'2. bes'8 a'8 | bes'4. c''8 c''4. ees''8 | ees''2. d''8 bes'8 | "
                          "c''4. a'8 f'4 d''8 bes'8 | c''2. f''8 bes'8 | ees''4. d''8 d''4. c''8 | c''1 | d''1~ | d''1",
                          "the whole theme untouched in B-flat major; its open c'' rises to d''; soprano bar 55"),
    'csOneMajor': ("bes,2. f,4 | d2. c4 | bes,4 a,4 aes,2 | ges,2. f,4",
                   "CS1 (the lament) in B-flat major under the tune, entering on beat 4 over the tonic; bass bar 55 (A-flat, G-flat: the one minor shadow)"),
    'csTwoMajor': ("bes8 a8 bes8 c'8 d'8 c'8 ees'8 g8 | d4 c8 f8~ f2 | ees8 f8 ees8 d8 c4 d4",
                   "CS2 in B-flat major (bars 2-3 an octave lower to leave the alto room); tenor bar 56"),
    'answerMajor': ("f,2. f,8 e,8 | f,2. f,8 e,8 | f,4. g,8 g,4. bes,8 | bes,2. a,8 f,8",
                    "the answer in F major under the tune's second half; bass bar 59"),
    'answerMirrorTail': ("f4. e8 e4. c8 | c2. ees4",
                         "the answer's mirror, bars 3-4 only (contrary to the answer's F-G-B-flat), tail landing on the seventh of V7; tenor bar 61"),
    'inversionHeadMajor': ("f'2. f'8 g'8 | f'4",
                           "the inversion's head in major (5-6-5, G natural for the old G-flat) under the held d''; alto bar 63"),
    'codaHead': ("bes2. bes8 a8 | bes1", "the subject's head as the last word (V7 over the tonic pedal); tenor bar 65"),
}


def write_materials():
    out = ['\\version "2.24.0"',
           '% MATERIALS of the final ricercar, one \\absolute variable per material at its reference pitch.',
           '% Machine-readable: tools/lyparse.parse_voice(src, NAME) reads any of them. Generated by build_labs.py.',
           '% B-flat minor unless stated; bar lines mark 4/4 bars of the material itself (bar 1 = its first bar).', '']
    for k, (s, note) in M.items():
        out.append(f"% {k}: {note}")
        out.append(f"{k} = \\absolute {{")
        out.append(f"  {s} |")
        out.append("}")
        out.append('')
    open(os.path.join(HERE, 'materials.ly'), 'w').write("\n".join(out))


S1, CS1, CS2 = M['subjectOne'][0], M['csOne'][0], M['csTwo'][0]
SK = fl.read(os.path.join(HERE, 'SK_final.ly'))


def win(a, b, voices):
    w = fl.window(SK, a, b)
    return {v: (w[v] if v in voices else ['r1'] * (b - a + 1)) for v in fl.VOICES}


LABS = [
    # name, claim, score
    ('T1_C1-C2-S', "triple counterpoint: CS1 top (f'), CS2 middle (bes), S1 bass (bes,)",
     fl.lab({'alto': oc(CS1, 1), 'tenor': oc(CS2, -1), 'bass': oc(S1, -2)})),
    ('T2_C1-S-C2', 'triple counterpoint: CS1 top, S1 middle (bes), CS2 bass (bes,)',
     fl.lab({'alto': oc(CS1, 1), 'tenor': oc(S1, -1), 'bass': oc(CS2, -2)})),
    ('T3_C2-C1-S', "triple counterpoint: CS2 top (bes'), CS1 middle (f), S1 bass (bes,)",
     fl.lab({'soprano': CS2, 'tenor': CS1, 'bass': oc(S1, -2)})),
    ('T4_C2-S-C1', 'triple counterpoint: CS2 top, S1 middle (bes), CS1 bass (f,)',
     fl.lab({'soprano': CS2, 'tenor': oc(S1, -1), 'bass': oc(CS1, -1)})),
    ('T5_S-C2-C1', "triple counterpoint: S1 top (bes'), CS2 middle (bes), CS1 bass (f,)",
     fl.lab({'alto': S1, 'tenor': oc(CS2, -1), 'bass': oc(CS1, -1)})),
    ('T6_S-C1-C2', "triple counterpoint: S1 top (bes'), CS1 middle (f), CS2 bass (bes,)",
     fl.lab({'alto': S1, 'tenor': CS1, 'bass': oc(CS2, -2)})),
    ('X1_E2_cs1_over_answer', 'exposition entry 2 in two voices: CS1 (answer level) above the answer, bars 5-9',
     win(5, 9, ('soprano', 'alto'))),
    ('X2_stretto_Db_Gb', 'S1 stretto in the relative major: tenor D-flat (20), soprano G-flat a 4th + octave above, 2 bars later (20-26)',
     win(20, 26, ('soprano', 'tenor'))),
    ('X2b_stretto_over_lament', 'the stretto pair over CS1 (the lament) in D-flat major in the bass (20-26)',
     win(20, 26, ('soprano', 'tenor', 'bass'))),
    ('X3_liquidation', 'four heads accumulate the complete E dim7 (28:1-4), then all slide a semitone together into A dim7 over E-flat (26-29)',
     win(26, 29, fl.VOICES)),
    ('X4_mirror_trio', 'fuga inversa: INV (bass) + CS1 inverted (alto) + CS2 inverted (soprano), A minor (35-39)',
     win(35, 39, ('soprano', 'alto', 'bass'))),
    ('X5_stretto_INV_5th', 'INV stretto: bass a-minor (35) and tenor e-minor a 5th above, 2 bars later (35-41)',
     win(35, 41, ('tenor', 'bass'))),
    ('X10_inv_third_entry', 'third inverted entry: INV (soprano, A minor) over CS2 inverted (alto) and CS1 inverted (bass, the lament rising), a new order of the mirrored triple counterpoint, cadencing in A minor (41-45)',
     win(41, 45, ('soprano', 'alto', 'bass'))),
    ('X6_S2_with_S1', 'S2 (alto) and S1 (tenor) entering together, the pair alone (48-52)',
     win(48, 52, ('alto', 'tenor'))),
    ('X11_three_speeds', 'Climax II: S1 heads in diminution (soprano) + S1 in normal values (tenor) + INV in augmentation (bass), 50-53',
     win(50, 53, ('soprano', 'tenor', 'bass'))),
    ('X7_combination_pedal', 'the whole pedal: lead-in, S2 + S1 over INV augmented, the diminution heads, the dominant hinge (46-54)',
     win(46, 54, fl.VOICES)),
    ('X8_tune_over_triple_major', 'apotheosis: the whole tune (major) over CS1 (bass) and CS2 (tenor) in B-flat major, then over the answer, into the cadence at 63 (55-63)',
     win(55, 63, ('soprano', 'tenor', 'bass'))),
    ('X9_answer_vs_mirror', 'the answer (bass) against its own mirror (tenor) in contrary motion, into the cadence (61-63)',
     win(61, 63, ('tenor', 'bass'))),
]
COPIES = [
    ('R1_S2_over_S1_iv', '../proposal-2/lab/L12_S2_over_S1_iv.ly',
     'resource (not in the skeleton): S2 over S1 in the subdominant, full length, 2 voices'),
]

def flags(lines, slines):
    keep = [l for l in lines if l.split() and l.split()[0] in ('PAR!', 'BEAT', 'DIS!', 'D4?', 'DIR', 'MEL', 'CROS', 'ERR')
            or l.startswith('range') or 'out of range' in l]
    keep += [s for s in slines if s.startswith(('CLASH', 'XREL'))]
    return keep


def main():
    write_materials()
    rep = ['# proofs.txt: generated by build_labs.py. check = tools/check.py with S 60-84, A 53-77, T 48-72, B 36-62;',
           '# strict = strict.py (CLASH aug. unison/8ve, XREL cross relation within a quarter, ACC/ACC2 accented',
           '# dissonance that is not a prepared suspension; ACC items are listed in BLUEPRINT.md where they matter).', '']
    for name, claim, sc in LABS:
        p = os.path.join(HERE, name + '.ly')
        fl.write(p, sc, f"{name}: {claim}\nGenerated by build_labs.py from materials/SK_final.ly; do not edit by hand.")
    for name, src, claim in COPIES:
        shutil.copy(os.path.join(HERE, src), os.path.join(HERE, name + '.ly'))
    allrows = [(n, c) for n, c, _ in LABS] + [(n, c) for n, _, c in COPIES]
    allrows += [('sections/' + os.path.basename(f)[:-3], 'section starter (skeleton window), spliced and checked with joins')
                for f in sorted(os.listdir(os.path.join(HERE, 'sections'))) if f.endswith('.ly')]
    allrows += [('SK_final', 'THE WHOLE PIECE, bars 1-66')]
    for name, claim in allrows:
        p = os.path.join(HERE, name + '.ly')
        if name.startswith('sections/'):
            r = subprocess.run([sys.executable, os.path.join(HERE, 'splice_check.py'), p], capture_output=True, text=True)
            out = r.stdout.splitlines()
            summ = [l.strip() for l in out if l.strip().startswith('-- totals')]
            strict = [l.strip() for l in out if l.strip().startswith('strict:')]
            fl_ = [l.strip() for l in out if l.strip().split() and l.strip().split()[0] in
                   ('PAR!', 'BEAT', 'DIS!', 'D4?', 'DIR', 'MEL', 'CROS', 'CLASH', 'XREL', 'BOUNDARY', 'LOCK')]
            rep.append(f"{name}: {claim}\n  {out[-1]}\n  check: {summ[0].split(';')[-1].strip() if summ else '?'}\n"
                       f"  {strict[0] if strict else ''}")
            rep += ['    ' + x for x in fl_]
            continue
        lines, slines = fl.check(p)
        summ = lines[-1].split(';')[-1].strip() if lines else '?'
        rep.append(f"{name}: {claim}\n  check: {summ}\n  {slines[-1] if slines else ''}")
        rep += ['    ' + x for x in flags(lines, slines)]
    open(os.path.join(HERE, 'proofs.txt'), 'w').write("\n".join(rep) + "\n")
    print("\n".join(rep))


if __name__ == '__main__':
    main()
