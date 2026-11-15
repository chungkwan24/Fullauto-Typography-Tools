#!/usr/bin/env python3
"""Plan a local tracking trial that rescues a runt, widow or orphan.

Read-only arithmetic on the composed lines you supply; it never touches a document.
The output is a ranked list of trials, not a result: apply one trial, recompose, look
at the page, and restore it if the defect is still there or a new one appeared.

Input (--paragraphs): a JSON file holding one paragraph or a list of them:
    {"id": "p2", "start": 51618, "lines": ["first composed line ", "...", "results."]}
`lines` are the composed lines in order, each with its trailing space; `start` is the
optional story index of the paragraph's first character.

    python3 spacing_rescue.py --font Body.otf --size 10.5 --goal runt --paragraphs p.json
    python3 spacing_rescue.py --font Body.otf --size 10.5 --goal lose-line --paragraphs page.json
    python3 spacing_rescue.py --font Body.otf --size 10.5 --goal gain-line --measure 312 --paragraphs page.json

Goals: `runt` (one stranded word on the last line), `lose-line` (a widow/orphan that goes
away if some paragraph before the break sets one line shorter), `gain-line` (… one line longer).
"""
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import font_profile  # noqa: E402

FALLBACK_BAND = {'tighten_comfort': -4, 'tighten_limit': -6, 'loosen_comfort': 5, 'loosen_limit': 8}
MCP_CHUNK = 128


class Measure:
    def __init__(self, face, avg_advance, space):
        self.face, self.avg, self.space = face, avg_advance / 1000, space / 1000

    def em(self, text):
        width = self.face.text_width_em(text) if self.face else None
        return width if width is not None else len(text) * self.avg


def scopes(lines):
    """Whole-line scopes growing upward from the last full line; never part of a line."""
    full, out, offset = lines[:-1], [], sum(len(l) for l in lines[:-1])
    for count in range(1, len(full) + 1):
        offset -= len(full[-count])
        out.append({'lines': count, 'offset': offset, 'length': sum(len(l) for l in full[-count:]),
                    'spaces': sum(l.rstrip().count(' ') for l in full[-count:])})
    return out


def grade(high, low, comfort, limit, tighten):
    if high <= abs(comfort):
        return 'likely'
    if high <= abs(limit):
        return 'possible'
    # Tightening that only works if the composer also squeezes the word spaces looks tight
    # even inside the limit (live run: -12 against -13), so it is not offered.
    if low <= abs(limit) and not tighten:
        return 'trial-at-limit'
    return 'not-by-tracking'


def chunks(start, offset, length):
    out, at = [], offset
    while at < offset + length:
        size = min(MCP_CHUNK, offset + length - at)
        out.append({'offset_in_paragraph': at, 'length': size,
                    **({'story_start': start + at} if start is not None else {})})
        at += size
    return out


def trial(paragraph, scope, sign, high, low, band, size, why):
    comfort = band['tighten_comfort' if sign < 0 else 'loosen_comfort']
    limit = band['tighten_limit' if sign < 0 else 'loosen_limit']
    status = grade(high, low, comfort, limit, sign < 0)
    first = min(high, abs(limit)) if status != 'not-by-tracking' else None
    ladder = sorted({v for v in (max(1, low), math.ceil((low + high) / 2), first) if first and v <= abs(limit)})
    return {'paragraph': paragraph.get('id'), 'direction': 'tighten' if sign < 0 else 'loosen',
            'scope_lines': scope['lines'], 'characters': scope['length'], 'status': status,
            'estimate_units': [sign * low, sign * high], 'budget': {'comfort': comfort, 'limit': limit},
            'trial_ladder_units': [sign * v for v in ladder],
            'ranges': chunks(paragraph.get('start'), scope['offset'], scope['length']),
            'word_equivalent_pt_per_unit': round(size / 1000, 4),
            'why': why}


def pull_up(paragraph, m, band, size, flex):
    """Tighten so the last line's content fits on the line above (paragraph sets one line shorter)."""
    lines = paragraph['lines']
    need = m.space + m.em(lines[-1].rstrip())
    out = []
    for scope in scopes(lines):
        high = math.ceil(need * 1000 / scope['length'])
        low = max(1, math.ceil((need - scope['spaces'] * m.space * flex) * 1000 / scope['length']))
        out.append(trial(paragraph, scope, -1, high, low, band, size,
                         'needs %.2f em (%.1f pt) to absorb the last line' % (need, need * size)))
    return out


def push_down(paragraph, m, band, size, flex, measure_pt=None):
    """Loosen so the last line gains a word (runt) or overflows into a new line (gain-line)."""
    lines, out = paragraph['lines'], []
    for scope in scopes(lines):
        if measure_pt is None:  # runt: break the fit of the line above so its last word drops
            if scope['lines'] > 2:
                continue
            slack = lines[-2].rstrip().count(' ') * m.space * flex
            why = 'must exceed the word-space shrink of the line above (up to %.2f em)' % slack
        else:  # gain-line: the last line itself must overflow the measure
            scope = {'lines': len(lines), 'offset': 0, 'length': sum(len(l) for l in lines),
                     'spaces': 0}
            slack = measure_pt / size - m.em(lines[-1].rstrip())
            why = 'last line is %.2f em short of the measure' % slack
        high = max(1, math.ceil(slack * 1000 / scope['length']))
        out.append(trial(paragraph, scope, +1, high, 1 if measure_pt is None else high, band, size, why))
        if measure_pt is not None:
            break
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--paragraphs', required=True)
    parser.add_argument('--goal', required=True, choices=('runt', 'lose-line', 'gain-line'))
    parser.add_argument('--size', type=float, required=True, help='point size of the text')
    parser.add_argument('--font', help='font file; without it, widths use --avg-advance and the fallback budget')
    parser.add_argument('--face')
    parser.add_argument('--role', default='body', choices=('body', 'small_text', 'display'))
    parser.add_argument('--measure', type=float, help='line measure in points (required for gain-line)')
    parser.add_argument('--ragged', action='store_true', help='text is not justified: no word-space give')
    parser.add_argument('--wordspace-flex', type=float, default=0.2,
                        help='share of a word space the composer may give up (1 - minimum word spacing; default 0.2)')
    parser.add_argument('--avg-advance', type=float, default=420, help='1/1000 em, used only without --font')
    args = parser.parse_args()
    if args.goal == 'gain-line' and not args.measure:
        parser.error('--measure is required for gain-line')
    data = json.loads(Path(args.paragraphs).read_text(encoding='utf-8'))
    paragraphs = data if isinstance(data, list) else [data]
    face = band = None
    notes = []
    measure = Measure(None, args.avg_advance, 250)
    if args.font:
        faces = font_profile.open_faces(args.font)
        if args.face:
            faces = [f for f in faces if args.face.lower() in f.name(4).lower()]
        if len(faces) != 1:
            sys.exit('Select exactly one face with --face')
        face = faces[0]
        prof = font_profile.profile(face)
        tracking = prof['recommendation']['rescue_tracking']
        if tracking is None:
            sys.exit('%s is %s: do not rescue with tracking; use breaks, hyphenation or geometry.'
                     % (prof['font']['full_name'], prof['classification']['class']))
        band = tracking[args.role]
        measure = Measure(face, prof['fit']['avg_text_advance'] or args.avg_advance, prof['fit']['space'] or 250)
        notes.append('Budget from %s (%s, n–n gap %s, mean advance %s).' % (
            prof['font']['full_name'], prof['classification']['class'], prof['fit']['gap_nn'],
            prof['fit']['avg_text_advance']))
    else:
        band = FALLBACK_BAND
        notes.append('No font file: widths are estimated and the conservative fallback budget applies.')
    flex = 0 if args.ragged else args.wordspace_flex
    trials = []
    for paragraph in paragraphs:
        lines = paragraph.get('lines') or []
        if len(lines) < 2 or not all(isinstance(l, str) and l for l in lines):
            notes.append('Skipped %s: needs at least two composed lines.' % paragraph.get('id'))
            continue
        if args.goal in ('runt', 'lose-line'):
            trials += pull_up(paragraph, measure, band, args.size, flex)
        if args.goal == 'runt':
            pushed = push_down(paragraph, measure, band, args.size, flex)
            if not lines[-2][-1:].isspace():
                # The last line starts mid-word: dropping the rest of that word still leaves one word.
                for t in pushed:
                    t['after_tightening'] = True
                    t['why'] += '; last line is a hyphenated fragment, so a whole extra word must drop as well'
            trials += pushed
        if args.goal == 'gain-line':
            trials += push_down(paragraph, measure, band, args.size, flex, args.measure)
    order = {'likely': 0, 'possible': 1, 'trial-at-limit': 2, 'not-by-tracking': 3}
    # Smallest scope that stays inside the comfort band first; then the gentlest value.
    can_tighten = any(t['direction'] == 'tighten' and t['status'] != 'not-by-tracking' for t in trials)
    trials.sort(key=lambda t: (bool(t.get('after_tightening')) and can_tighten,
                               order[t['status']], t['characters'] if t['status'] == 'likely' else 0,
                               abs(t['estimate_units'][1]), t['characters']))
    usable = [t for t in trials if t['status'] != 'not-by-tracking']
    print(json.dumps({
        'goal': args.goal, 'size_pt': args.size, 'role': args.role, 'notes': notes,
        'trials': usable[:6],
        'rejected': len(trials) - len(usable),
        'verdict': 'Try trials in order, one at a time.' if usable else
                   'No tracking value inside the budget can do this: use hyphenation, a no-break on the last '
                   'two words, another paragraph before the break, or report it.',
        'after_each_trial': ['recompose and read the actual lines', 'defect gone?', 'no new runt, widow, orphan, '
                             'river or collision in the story from this paragraph to the end of the spread',
                             'page count and later page breaks unchanged, or the change is intended',
                             'otherwise restore the trial before the next one'],
    }, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
