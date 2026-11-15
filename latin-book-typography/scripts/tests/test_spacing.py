"""Run: python3 -m unittest discover -s scripts/tests -v  (needs fontTools; font tests skip without the fonts)."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
FONTS = Path('/System/Library/Fonts/Supplemental')
PARAGRAPH = {'id': 'p2', 'start': 51618, 'lines': [
    'The second series repeated the protocol with a shorter interval between ',
    'samples, which reduced drift but introduced a small seasonal bias in the ',
    'coastal stations. Correcting for that bias produced the adjusted series ',
    'shown in Table 4, and the comparison below summarises the principal ',
    'results.']}


def run(script, *args):
    done = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True)
    return done.returncode, done.stdout, done.stderr


def profile(name):
    code, out, err = run('font_profile.py', FONTS / name)
    assert code == 0, err
    return json.loads(out)


def plan(*args):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'p.json'
        path.write_text(json.dumps(PARAGRAPH))
        code, out, err = run('spacing_rescue.py', '--paragraphs', path, '--size', 10.5, *args)
    return code, json.loads(out) if code == 0 else err


def needs(*names):
    return unittest.skipUnless(all((FONTS / n).exists() for n in names), 'stock macOS fonts not installed')


class FontProfile(unittest.TestCase):
    @needs('Times New Roman.ttf', 'Arial.ttf', 'Verdana.ttf')
    def test_class_comes_from_outlines(self):
        self.assertEqual(profile('Times New Roman.ttf')['classification']['class'], 'serif')
        self.assertEqual(profile('Arial.ttf')['classification']['class'], 'sans')
        # Verdana's capital I has serifs; the other stems decide.
        self.assertEqual(profile('Verdana.ttf')['classification']['class'], 'sans')

    @needs('Georgia.ttf', 'Arial.ttf', 'Courier New.ttf')
    def test_mode_follows_kerning_data(self):
        georgia, arial, courier = profile('Georgia.ttf'), profile('Arial.ttf'), profile('Courier New.ttf')
        self.assertEqual(georgia['kerning_data']['grade'], 'none')
        self.assertEqual(georgia['recommendation']['kerning_mode'], 'Optical')
        self.assertEqual(arial['kerning_data']['grade'], 'rich')
        self.assertEqual(arial['recommendation']['kerning_mode'], 'Metrics')
        self.assertEqual(courier['classification']['class'], 'monospace')
        self.assertIsNone(courier['recommendation']['rescue_tracking'])

    @needs('Times New Roman.ttf', 'Arial.ttf')
    def test_budget_follows_fit(self):
        times = profile('Times New Roman.ttf')
        tight = times['recommendation']['rescue_tracking']['body']
        open_ = profile('Arial.ttf')['recommendation']['rescue_tracking']['body']
        self.assertLessEqual(abs(tight['tighten_limit']), times['fit']['gap_nn'])  # serifs must not touch
        self.assertLess(abs(tight['tighten_limit']), abs(open_['tighten_limit']))
        self.assertLess(abs(tight['tighten_comfort']), abs(tight['tighten_limit']))


class RescuePlanner(unittest.TestCase):
    def check(self, result):
        for trial in result['trials']:
            limit = abs(trial['budget']['limit'])
            self.assertTrue(all(abs(v) <= limit for v in trial['trial_ladder_units']))
            self.assertTrue(all(r['length'] <= 128 for r in trial['ranges']))
            self.assertEqual(sum(r['length'] for r in trial['ranges']), trial['characters'])
            first = trial['ranges'][0]['offset_in_paragraph']  # whole lines only
            self.assertIn(first, (0, 72, 145, 217))

    def test_fallback_without_font(self):
        code, result = plan('--goal', 'runt')
        self.assertEqual(code, 0)
        self.assertTrue(result['trials'])
        self.assertEqual(result['trials'][0]['direction'], 'loosen')
        self.check(result)

    def test_gain_line_needs_measure(self):
        self.assertNotEqual(plan('--goal', 'gain-line')[0], 0)

    @needs('Arial.ttf', 'Courier New.ttf')
    def test_font_budget_and_refusal(self):
        code, result = plan('--goal', 'lose-line', '--font', FONTS / 'Arial.ttf')
        self.assertEqual(code, 0)
        self.assertTrue(all(t['direction'] == 'tighten' for t in result['trials']))
        self.assertEqual(result['trials'][0]['ranges'][0]['story_start'], 51618)
        self.check(result)
        self.assertNotEqual(plan('--goal', 'runt', '--font', FONTS / 'Courier New.ttf')[0], 0)


if __name__ == '__main__':
    unittest.main()
