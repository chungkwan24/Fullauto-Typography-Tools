#!/usr/bin/env python3
"""Measure one font face and recommend kerning mode and rescue-tracking budgets.

Read-only: opens a font file, never touches a document. Needs fontTools
(`python3 -m pip install fonttools`). The thresholds and budgets are this skill's
house trial values (see references/kerning.md), not properties of the font.

    python3 font_profile.py /path/Font.ttc --list
    python3 font_profile.py /path/Font.ttc --face "Semibold Italic"
    python3 font_profile.py /path/Font.otf --text "results." --size 10.5
"""
import argparse
import json
import logging
import statistics
import sys

try:
    from fontTools.pens.basePen import BasePen
    from fontTools.ttLib import TTCollection, TTFont
except ImportError:  # pragma: no cover
    sys.exit('fontTools is required: python3 -m pip install fonttools '
             '(or classify by observation with references/kerning.md)')

logging.getLogger('fontTools').setLevel(logging.ERROR)

# Pairs a text face with real pair kerning almost always adjusts.
PROBE_PAIRS = ('AV AW AY AT Av Aw Ay FA LT LV LY Ly PA P. TA Ta Te To Tr Ty T. T, VA Va Ve Vo V. '
               'WA Wa We Wo W. YA Ya Ye Yo Y. r. r, y. y, v. w. f.').split()
# Relative letter frequencies in English running text (space included), per 1000 characters.
FREQ = {' ': 182, 'e': 103, 't': 75, 'a': 65, 'o': 62, 'i': 57, 'n': 57, 's': 53, 'r': 50, 'h': 50,
        'l': 33, 'd': 33, 'u': 23, 'c': 22, 'm': 20, 'f': 20, 'w': 17, 'g': 16, 'p': 15, 'y': 14,
        'b': 13, 'v': 8, 'k': 6}
SCRIPT_WORDS = ('script', 'hand', 'brush', 'calligraph', 'cursive', 'chancery')
OPTICAL_WORDS = ('display', 'caption', 'subhead', 'headline', 'poster', 'deck', 'banner', 'micro')


class Flatten(BasePen):
    """Collect closed polylines; curves are sampled, which is enough for scanline measurements."""

    def __init__(self, glyph_set, steps=12):
        super().__init__(glyph_set)
        self.contours, self.steps = [], steps

    def _moveTo(self, pt):
        self.contours.append([pt])

    def _lineTo(self, pt):
        self.contours[-1].append(pt)

    def _curveToOne(self, p1, p2, p3):
        p0 = self.contours[-1][-1]
        for i in range(1, self.steps + 1):
            t = i / self.steps
            u = 1 - t
            self.contours[-1].append(tuple(
                u * u * u * a + 3 * u * u * t * b + 3 * u * t * t * c + t * t * t * d
                for a, b, c, d in zip(p0, p1, p2, p3)))

    def _qCurveToOne(self, p1, p2):
        p0 = self.contours[-1][-1]
        for i in range(1, self.steps + 1):
            t = i / self.steps
            u = 1 - t
            self.contours[-1].append(tuple(u * u * a + 2 * u * t * b + t * t * c
                                           for a, b, c in zip(p0, p1, p2)))


def crossings(contours, level, axis=1):
    """Sorted coordinates where the outline crosses a horizontal (axis=1) or vertical (axis=0) line."""
    out, other = [], 1 - axis
    for contour in contours:
        for a, b in zip(contour, contour[1:] + contour[:1]):
            if (a[axis] <= level) != (b[axis] <= level):
                out.append(a[other] + (level - a[axis]) * (b[other] - a[other]) / (b[axis] - a[axis]))
    return sorted(out)


class Face:
    def __init__(self, font, path):
        self.font, self.path = font, path
        self.upm = font['head'].unitsPerEm
        self.cmap = font.getBestCmap() or {}
        self.glyphs = font.getGlyphSet()
        self.hmtx = font['hmtx']
        self._outline = {}
        self._kern = None

    def name(self, *ids):
        for i in ids:
            value = self.font['name'].getDebugName(i)
            if value:
                return value
        return ''

    def glyph(self, char):
        return self.cmap.get(ord(char))

    def advance(self, char):
        g = self.glyph(char)
        return self.hmtx[g][0] if g else None

    def outline(self, char):
        if char not in self._outline:
            g, pen = self.glyph(char), Flatten(self.glyphs)
            if g:
                self.glyphs[g].draw(pen)
            self._outline[char] = [c for c in pen.contours if len(c) > 2]
        return self._outline[char]

    def bounds(self, char):
        points = [p for c in self.outline(char) for p in c]
        if not points:
            return None
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        return min(xs), min(ys), max(xs), max(ys)

    # ---- kerning data -------------------------------------------------
    def kern_tables(self):
        if self._kern is None:
            lookups, records = [], 0
            gpos = self.font.get('GPOS')
            if gpos is not None and gpos.table.FeatureList and gpos.table.LookupList:
                wanted = set()
                for record in gpos.table.FeatureList.FeatureRecord:
                    if record.FeatureTag == 'kern':
                        wanted.update(record.Feature.LookupListIndex)
                for index in sorted(wanted):
                    lookup, subtables = gpos.table.LookupList.Lookup[index], []
                    for sub in lookup.SubTable:
                        kind = lookup.LookupType
                        if kind == 9:
                            kind, sub = sub.ExtensionLookupType, sub.ExtSubTable
                        if kind != 2:
                            continue
                        subtables.append(sub)
                        if sub.Format == 1:
                            records += sum(len(ps.PairValueRecord) for ps in sub.PairSet)
                        else:
                            records += sum(1 for c1 in sub.Class1Record for c2 in c1.Class2Record
                                           if c2.Value1 is not None and getattr(c2.Value1, 'XAdvance', 0))
                    if subtables:
                        lookups.append(subtables)
            legacy = {}
            if 'kern' in self.font:
                for table in getattr(self.font['kern'], 'kernTables', []):
                    legacy.update(getattr(table, 'kernTable', None) or {})
            self._kern = (lookups, legacy, records + (0 if lookups else len(legacy)))
        return self._kern

    def kern(self, left, right):
        """Pair adjustment in font units as a GPOS/kern-reading application would apply it."""
        a, b = self.glyph(left), self.glyph(right)
        if not a or not b:
            return None
        lookups, legacy, _ = self.kern_tables()
        if not lookups:
            return legacy.get((a, b), 0)
        total = 0
        for subtables in lookups:
            for sub in subtables:  # the first subtable that covers the pair ends the lookup
                if a not in sub.Coverage.glyphs:
                    continue
                if sub.Format == 1:
                    pair_set = sub.PairSet[sub.Coverage.glyphs.index(a)]
                    hit = next((r for r in pair_set.PairValueRecord if r.SecondGlyph == b), None)
                    if hit is None:
                        continue
                    value = hit.Value1
                else:
                    c1 = sub.ClassDef1.classDefs.get(a, 0)
                    c2 = sub.ClassDef2.classDefs.get(b, 0)
                    value = sub.Class1Record[c1].Class2Record[c2].Value1
                total += getattr(value, 'XAdvance', 0) or 0 if value is not None else 0
                break
        return total

    def text_width_em(self, text):
        """Advance-width sum in em (pair kerning ignored); None when a glyph is missing."""
        total = 0
        for char in text:
            adv = self.advance(char)
            if adv is None:
                return None
            total += adv
        return total / self.upm


def foot_ratio(face, char, height):
    """Ink extent at the foot of a single stem divided by the stem's own width: 1.0 sans, >1.3 serif."""
    box, contours = face.bounds(char), face.outline(char)
    if not box or not height:
        return None
    base = box[1]
    stem = crossings(contours, base + 0.45 * height)
    if len(stem) != 2:
        return None
    foot = 0
    for step in (0.01, 0.02, 0.03, 0.04):
        xs = crossings(contours, base + step * face.upm)
        if len(xs) >= 2:
            foot = max(foot, xs[-1] - xs[0])
    width = stem[1] - stem[0]
    return round(foot / width, 2) if width > 0 and foot else None


def contrast(face):
    """Thick/thin stroke ratio of 'o' (vertical-stress approximation)."""
    box, contours = face.bounds('o'), face.outline('o')
    if not box:
        return None
    xs = crossings(contours, (box[1] + box[3]) / 2, axis=1)
    ys = crossings(contours, (box[0] + box[2]) / 2, axis=0)
    if len(xs) != 4 or len(ys) != 4:
        return None
    side, cap = xs[1] - xs[0], ys[1] - ys[0]
    if min(side, cap) <= 0 or max(side, cap) / min(side, cap) > 12:  # overlapping contours: not measurable
        return None
    return round(max(side, cap) / min(side, cap), 2)


def classify(face):
    font, os2 = face.font, face.font.get('OS/2')
    names = ' '.join([face.name(16, 1), face.name(17, 2), face.name(4)]).lower()
    panose = getattr(os2, 'panose', None)
    family_kind = getattr(panose, 'bFamilyType', 0)
    serif_style = getattr(panose, 'bSerifStyle', 0) if family_kind == 2 else 0
    ibm_class = (getattr(os2, 'sFamilyClass', 0) >> 8) & 0xFF
    cap = getattr(os2, 'sCapHeight', 0) or (face.bounds('H') or (0, 0, 0, 0))[3]
    xh = getattr(os2, 'sxHeight', 0) or (face.bounds('x') or (0, 0, 0, 0))[3]
    ratios = {c: foot_ratio(face, c, h) for c, h in (('I', cap), ('T', cap), ('l', cap), ('r', xh), ('i', xh))}
    measured = [v for v in ratios.values() if v]
    evidence = {'foot_ratio': ratios, 'stroke_contrast': contrast(face),
                'panose_family_kind': family_kind, 'panose_serif_style': serif_style,
                'os2_family_class': ibm_class}
    widths = {face.advance(c) for c in 'imW.' if face.advance(c)}
    if getattr(font['post'], 'isFixedPitch', 0) or (len(widths) == 1 and all(face.advance(c) for c in 'imW.')):
        return 'monospace', 'high', evidence
    if family_kind == 3 or ibm_class == 10 or any(w in names for w in SCRIPT_WORDS):
        return 'script', 'medium' if family_kind != 3 and ibm_class != 10 else 'high', evidence
    if family_kind in (4, 5) or ibm_class in (9, 12):
        return 'decorative', 'medium', evidence
    meta = None
    if serif_style >= 11 or ibm_class == 8:
        meta = 'sans'
    elif 2 <= serif_style <= 10 or ibm_class in (1, 2, 3, 4, 5, 7):
        meta = 'serif'
    if len(measured) >= 3:
        shape = 'serif' if statistics.median(measured) >= 1.3 else 'sans'
        evidence['metadata_class'] = meta
        if shape == 'serif' and (evidence['stroke_contrast'] or 9) < 1.35:
            shape = 'slab'
        agree = meta is None or meta == ('serif' if shape == 'slab' else shape)
        decisive = statistics.median(measured) >= 2 or max(measured) <= 1.1
        return shape, 'high' if agree and (meta or decisive) else 'medium', evidence
    if meta:
        return meta, 'low', evidence
    return 'unknown', 'low', evidence


def kerning_data(face):
    lookups, legacy, records = face.kern_tables()
    tested = [(p, face.kern(p[0], p[1])) for p in PROBE_PAIRS]
    tested = [(p, v) for p, v in tested if v is not None]
    hits = [p for p, v in tested if v]
    coverage = len(hits) / len(tested) if tested else 0
    grade = 'none' if not hits else 'sparse' if coverage < 0.25 else 'partial' if coverage < 0.6 else 'rich'
    source = 'GPOS' if lookups else 'kern' if legacy else 'none'
    aat = [t for t in ('kerx',) if t in face.font]
    return {'source': source, 'records': records, 'probe_pairs': len(tested), 'probe_hits': len(hits),
            'coverage': round(coverage, 2), 'grade': grade, 'unkerned_probes': [p for p, v in tested if not v][:12],
            'aat_tables_not_read': aat}


def fit(face):
    def gap(char):
        box, adv = face.bounds(char), face.advance(char)
        return round((adv - (box[2] - box[0])) * 1000 / face.upm) if box and adv else None
    weight = total = 0
    for char, share in FREQ.items():
        adv = face.advance(char)
        if adv:
            total += adv * share
            weight += share
    space = face.advance(' ')
    return {'gap_nn': gap('n'), 'gap_oo': gap('o'),
            'space': round(space * 1000 / face.upm) if space else None,
            'avg_text_advance': round(total * 1000 / face.upm / weight) if weight else None}


def optical_size(face):
    if 'fvar' in face.font and any(a.axisTag == 'opsz' for a in face.font['fvar'].axes):
        return 'axis'
    names = ' '.join([face.name(16, 1), face.name(17, 2)]).lower().split()
    hit = next((w for w in OPTICAL_WORDS if w in names), None)
    return 'named-master:' + hit if hit else 'none'


def budgets(kind, fit_data):
    """Rescue-tracking budgets in 1/1000 em, sized from the font's own fit.

    Tightening: 15% of the mean n/o side gap, and for serif faces never more than the
    serif-to-serif gap of n–n (beyond it the serifs touch). Loosening: 3% of the average
    text advance. Both clamped; comfort is 60% of the limit.
    """
    if kind in ('script', 'monospace', 'decorative'):
        return None
    gaps = [g for g in (fit_data['gap_nn'], fit_data['gap_oo']) if g is not None]
    tighten = round(0.15 * sum(gaps) / len(gaps)) if gaps else 8
    if kind in ('serif', 'slab') and fit_data['gap_nn'] is not None:
        tighten = min(tighten, fit_data['gap_nn'])
    tighten = max(6, min(20, tighten))
    loosen = max(8, min(20, round(0.03 * (fit_data['avg_text_advance'] or 400))))

    def band(t, l):
        return {'tighten_comfort': -max(2, round(tighten * t * 0.6)), 'tighten_limit': -max(3, round(tighten * t)),
                'loosen_comfort': max(2, round(loosen * l * 0.6)), 'loosen_limit': max(3, round(loosen * l))}
    return {'body': band(1, 1), 'small_text': band(0.5, 1), 'display': band(1, 0.5)}


def recommend(kind, confidence, kern, fit_data, optical):
    notes, grade = [], kern['grade']
    house = {'serif': 'Optical', 'slab': 'Optical', 'sans': 'Metrics'}.get(kind)
    if kind == 'monospace':
        mode, reason = 'Metrics', 'Fixed-pitch design: Optical kerning would break the fixed advance.'
    elif kind == 'script':
        mode, reason = 'Metrics', 'Connecting strokes depend on the designed spacing; Optical and tracking break the joins.'
    elif grade in ('none', 'sparse'):
        mode = 'Optical'
        reason = 'The font carries %s pair kerning (%d of %d probe pairs), so Metrics would leave pairs unkerned.' % (
            'no' if grade == 'none' else 'almost no', kern['probe_hits'], kern['probe_pairs'])
    elif kind == 'decorative':
        mode, reason = 'Metrics', 'Display design with its own pair kerning; keep the designed spacing and inspect pairs by eye.'
    elif house:
        mode = house
        reason = 'House default for %s text; the font has %s pair kerning (%d of %d probe pairs).' % (
            'serif' if kind == 'slab' else kind, grade, kern['probe_hits'], kern['probe_pairs'])
        if house == 'Optical' and grade == 'rich':
            notes.append('Pair kerning is rich: if Optical gives abnormal pairs (quotes, f-ligature neighbours, '
                         'figures), compare with Metrics on that text role and report before switching.')
        if house == 'Metrics' and grade == 'partial':
            notes.append('Pair kerning is only partial: inspect the unkerned probe pairs at display sizes.')
    else:
        mode, reason = 'Metrics' if grade == 'rich' else 'Optical', 'Class not established; decided from kerning data alone.'
    if confidence == 'low':
        notes.append('Classification confidence is low: confirm serif/sans by eye before applying the mode.')
    if kern['aat_tables_not_read']:
        notes.append('The font has Apple AAT tables (%s) that this profile and Adobe composition do not read.'
                     % ', '.join(kern['aat_tables_not_read']))
    if optical != 'none':
        notes.append('Optical-size design (%s): spacing is already drawn for its size range, so start display '
                     'tightening trials from 0 rather than from -10.' % optical)
    notes.append('Tabular figures in tables and aligned columns: Metrics, never Optical. '
                 'Pairs that span two fonts: Optical or a manual pair value.')
    return {'kerning_mode': mode, 'house_default_for_class': house, 'reason': reason,
            'rescue_tracking': budgets(kind, fit_data), 'notes': notes}


def profile(face):
    kind, confidence, evidence = classify(face)
    kern, fit_data, optical = kerning_data(face), fit(face), optical_size(face)
    italic = bool(face.font['head'].macStyle & 2) or bool(getattr(face.font['post'], 'italicAngle', 0))
    axes = [a.axisTag for a in face.font['fvar'].axes] if 'fvar' in face.font else []
    return {'font': {'family': face.name(16, 1), 'style': face.name(17, 2), 'full_name': face.name(4),
                     'file': str(face.path), 'units_per_em': face.upm, 'italic': italic,
                     'variable_axes': axes, 'optical_size': optical},
            'classification': {'class': kind, 'confidence': confidence, 'evidence': evidence},
            'kerning_data': kern, 'fit': fit_data,
            'recommendation': recommend(kind, confidence, kern, fit_data, optical),
            'scope': 'Measured from the font file. House trial values; the composed page decides.'}


def open_faces(path):
    with open(path, 'rb') as handle:
        collection = handle.read(4) == b'ttcf'
    fonts = TTCollection(path, lazy=True).fonts if collection else [TTFont(path, lazy=True)]
    return [Face(f, path) for f in fonts]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('font', help='.ttf, .otf or .ttc file (in InDesign, Font.location gives the path)')
    parser.add_argument('--face', help='full-name or style substring for a collection, e.g. "Bold Italic"')
    parser.add_argument('--list', action='store_true', help='list the faces in the file and exit')
    parser.add_argument('--text', help='also measure this text (advance sum, pair kerning ignored)')
    parser.add_argument('--size', type=float, help='point size for --text')
    args = parser.parse_args()
    faces = open_faces(args.font)
    if args.list:
        print(json.dumps([f.name(4) for f in faces], indent=2, ensure_ascii=False))
        return
    if args.face:
        wanted = args.face.lower()
        exact = [f for f in faces if wanted in (f.name(4).lower(), f.name(17, 2).lower())]
        faces = exact or [f for f in faces if wanted in f.name(4).lower()]
    if len(faces) != 1:
        sys.exit('Select exactly one face with --face; candidates: '
                 + ', '.join(f.name(4) for f in faces or open_faces(args.font)))
    result = profile(faces[0])
    if args.text:
        em = faces[0].text_width_em(args.text)
        result['text'] = {'text': args.text, 'width_em': round(em, 4) if em is not None else None,
                          'width_pt': round(em * args.size, 2) if em is not None and args.size else None}
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
