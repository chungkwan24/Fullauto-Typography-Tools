# Font-Aware Kerning, Tracking and Rescue Spacing

Read this before changing a kerning mode, tightening headings, or using letter-spacing to remove a runt, widow or orphan. SKILL.md step 6 has the workflow; this file has the method, the numbers and their limits.

All thresholds and budgets here are the user's house trial values. They order trials and bound them; the composed page at reading size is what decides.

## Contents

1. Font profile: what is measured and how it is used
2. Classifying without the font file
3. Kerning mode decision
4. Rescue-tracking budgets
5. The rescue pass and its planner
6. Timing: why local fixes come last
7. Other backends
8. Visual letter-pair inspection (headings and display lines)

## 1. Font profile

`python3 scripts/font_profile.py <file> [--face "<style>"]` reads one face with fontTools and prints JSON. `--list` shows the faces in a `.ttc`; `--text "word" --size 10.5` also returns that text's advance width. It is read-only and never touches a document. Profile every face that carries a text role, including italics and any font the user selected themselves: families differ, and so do faces within a family.

| Field | How it is measured | What it drives |
| --- | --- | --- |
| `classification.class` | Monospace from equal advances; script/decorative from PANOSE, OS/2 class or the name; otherwise from the outlines: the ink width at the foot of single stems (I, T, l, r, i) divided by the stem width is 1.0 for sans and above 1.3 for serif. Low stroke contrast on a serif face gives `slab`. | House default mode; whether rescue tracking is allowed |
| `classification.confidence` | High when the outline measure is decisive or agrees with the font's metadata | Low or medium: confirm by eye first |
| `kerning_data.grade` | Share of 44 classic problem pairs (AV, To, Ty, P., r. …) that the font's GPOS `kern` feature or legacy `kern` table actually adjusts: `none`, `sparse` (<25%), `partial`, `rich` (≥60%) | Metrics is only meaningful when this is partial or rich |
| `fit.gap_nn`, `fit.gap_oo` | Side-bearing sum of n and o in 1/1000 em. For a serif face `gap_nn` is the serif-to-serif gap of n–n | Tightening budget |
| `fit.avg_text_advance`, `fit.space` | Frequency-weighted mean advance of English text; word-space width | Loosening budget; width estimates |
| `font.optical_size` | `opsz` axis, or a Display/Caption/Subhead master in the name | Heading tightening starts from 0 |

Things the profile cannot see: the document's applied kerning mode, tracking already in the styles, the composer's justification settings, and Apple-only `kerx` kerning (reported as not read; Adobe composition does not read it either, so such a font behaves as unkerned under Metrics).

Example readings on stock macOS fonts, to show why one rule per class is not enough: Times New Roman is a serif with rich kerning but an n–n serif gap of only 10 units; Georgia is a serif with **no** pair kerning; Arial is a sans with rich kerning and a 135-unit gap. They need three different treatments.

## 2. Classifying without the font file

When the file or fontTools is unavailable, decide by observation at high zoom and say the profile was not measured:

- **Class:** look at the foot of I, l and r. A foot wider than the stem on both sides is a serif; a plain stem is a sans. One serifed letter (often capital I) in an otherwise plain face is still a sans. Equal widths for i and m mean monospace; joined letters mean script.
- **Kerning data:** set `AV To Ty P. r.` in the font, switch that sample between Metrics and 0 kerning. No visible change means the font carries no usable pairs.
- **Budget:** use the conservative fallback of −4 comfort / −6 limit for tightening and +5 / +8 for loosening.

## 3. Kerning mode decision

Apply the first row that matches, per face and text role:

| Evidence | Mode | Why |
| --- | --- | --- |
| Monospace | Metrics | Optical breaks the fixed advance |
| Connected script | Metrics | Optical and tracking break the joins |
| Kerning grade `none` or `sparse` | Optical | Metrics has nothing to apply |
| Decorative with its own kerning | Metrics, pairs inspected by eye | The spacing is part of the design |
| Serif or slab, grade `partial` or `rich` | Optical | House default for serif text |
| Sans, grade `partial` or `rich` | Metrics | House default for sans text |
| Class unknown | Metrics if `rich`, otherwise Optical | Evidence only |

Overrides that apply inside any of these: tabular figures in tables and aligned columns use Metrics; a pair that spans two fonts or two sizes gets Optical or a manual value on that pair only; an explicit user requirement wins over the table.

A serif with rich kerning is the one case where the house default and the font designer disagree most often. Keep Optical, but when it produces abnormal pairs (around quotation marks, f-ligature neighbours, figures), compare the same lines under Metrics and report the difference before switching that role. Changing the mode of an approved style is a specification change, never a silent fix.

## 4. Rescue-tracking budgets

The profile's `recommendation.rescue_tracking` gives a comfort value and a limit for each direction, in 1/1000 em:

- **Tightening limit** = 15% of the mean of `gap_nn` and `gap_oo`, and for serif and slab faces never more than `gap_nn` itself, because beyond it the serifs of neighbouring letters touch. Clamped to 6–20.
- **Loosening limit** = 3% of the average text advance, clamped to 8–20.
- **Comfort** = 60% of the limit. Inside comfort the change is normally invisible; between comfort and limit, compare the paragraph with its neighbours at reading size before keeping it.
- **Roles:** `body` uses the values as measured; `small_text` (captions, notes, anything below about 9 pt) halves the tightening; `display` halves the loosening.
- Monospace, script and decorative faces get no budget: solve those with breaks, hyphenation or geometry.

Typical results: Times New Roman −4/−6 and +7/+12; Georgia −5/−9 and +8/+13; Arial −9/−15 and +8/+13; Minion Pro −6/−10 and +7/+12.

## 5. The rescue pass and its planner

Levers, gentlest first: recomposition under the style-level settings; no-break on a paragraph's last two words (runts); a planned tracking trial; pagination or permitted geometry; report.

In InDesign, the read-only payload `scripts/inspect_spacing.jsx` (run through `scripts/prepare_indesign_job.py`) lists the document's fonts with their file locations and every runt candidate with its composed lines, applied font, size, kerning method and justification settings, already in the planner's input shape. Its `kind` is `single-word`, `fragment` (the last line is the tail of a hyphenated word) or `fragment-plus-word`.

`python3 scripts/spacing_rescue.py --font <file> --size <pt> --goal <goal> --paragraphs <json>` plans the tracking trial. The JSON is one paragraph or a list: `{"id": "p2", "start": 51618, "lines": ["composed line with its trailing space ", "…", "results."]}`; `start` is the optional story index of the first character.

| Goal | Use for | What it plans |
| --- | --- | --- |
| `runt` | One stranded word on a paragraph's last line | Tighten the lines above to absorb the last line, or loosen the line above so a second word drops down |
| `lose-line` | A widow or orphan that disappears if a paragraph before the break sets one line shorter | Tightening trials for each paragraph supplied, cheapest first (short last lines are cheapest) |
| `gain-line` | The same, when one line longer is the cure; needs `--measure` | Loosening trials, cheapest first (nearly full last lines are cheapest) |

How to read a trial:

- `scope_lines` / `ranges`: whole lines counted up from the last full line, already split into ≤128-character ranges for the MCP `prepare_tracking_edit` tool. Never track part of a line or part of a word.
- `estimate_units`: low and high estimate. The high value assumes tracking does all the work; the low value assumes a justified line also gives up word space down to the minimum (`--wordspace-flex`, default 0.2; use `--ragged` for unjustified text).
- `status`: `likely` (high estimate inside comfort), `possible` (inside the limit), `trial-at-limit` (loosening only: just the low estimate is inside the limit; one trial is justified, expect it to fail often). Tightening that would only work if the composer also squeezed the word spaces is not offered at all.
- `trial_ladder_units`: apply the first value, recompose, and move up only if the defect is still there.

The planner prefers the smallest scope that stays inside comfort and otherwise the gentlest value, which usually means spreading a small value over two to four lines instead of forcing one line. When the last line is a hyphenated fragment it lists tightening first, because loosening only drops the rest of that word and still leaves one word alone.

A kept trial between comfort and limit is not automatically acceptable. In the live qualification run (InDesign 21.2, Minion Pro 10.5/15, justified, 306 pt measure) trials of −4 and +3 were invisible, while a −12 trial against what was then a −13 limit removed the runt but left two visibly tight lines, because the composer had also squeezed the word spaces. The tightening limit was lowered from 20% to 15% of the side gap after that run, and squeeze-dependent tightening trials were dropped. Compare such a paragraph with its neighbours at reading size and prefer reporting it over keeping a visibly tight fix. Without `--font` it falls back to estimated widths and the conservative budget.

After each trial: read the recomposed lines; confirm the defect is gone; check for a new runt, widow, orphan, river or collision from that paragraph to the end of the spread; confirm later page breaks did not move unintentionally. If any check fails, restore the trial before the next one. Keep a ledger of kept fixes (page, paragraph, range, value, defect, budget).

## 6. Timing: why local fixes come last

A local tracking value is tuned to one set of line breaks. Changing a heading's wording or size, a frame's width or height, a margin, an image position or a single repaired character upstream re-breaks the lines, and the value then tightens text that no longer needs it. So:

- Kerning mode, hyphenation, keep options and justification limits are style-level and go in early.
- Local tracking and pair kerning wait for the layout freeze described in SKILL.md, and run front to back within each story.
- After any post-freeze change, re-audit every ledger entry from the first changed line to the end of the story; restore entries whose defect is gone before adding anything new.
- Heading pair kerning waits until the heading's text, size and line breaks are final.

## 7. Other backends

- **Word:** no Optical mode, so the profile's mode advice does not apply; the budgets do. Convert units × size ÷ 1000 to points (−8 units at 10.5 pt ≈ −0.08 pt). Character spacing is stored in twentieths of a point, so the smallest step is 0.05 pt, about 5 units at 10.5 pt: a comfort-band value may round to a single step or to nothing. Say so instead of rounding up past the limit.
- **Pages:** character spacing is a percentage and unverified here; treat the budget as guidance for a manual checklist.
- **PDF only:** the profile can still be run on a supplied font file to propose values, but nothing can be applied or verified.

## 8. Visual letter-pair inspection (headings and display lines)

These are the user's geometric observation methods and trial preferences, not a standardized A–Z kerning table. Results depend on glyph shape, case, size, weight, font version, and existing kerning. Pair work applies to headings and display lines after their text and size are final, not to body text.

### How to inspect

Examine negative space between adjacent glyphs and the rhythm of the whole word, rather than comparing only the horizontal distance between outer edges. These groups contain representative shapes; they are not mutually exclusive categories covering all 26 letters:

- Straight-sided: I, H, M, N.
- Curved: O, C, Q, G.
- Diagonal or open: A, V, W, Y, T, L.

After inspecting enlarged outlines, return to the final print size and assess the whole word. Geometric perfection under magnification does not guarantee even spacing at reading size. Confirm the font and size before making local adjustments.

### Pairs to inspect for tighter spacing

| Pair | What to inspect |
|---|---|
| AV / VA / AW / AY | Diagonals may create excessive empty space; try tightening if needed. |
| Ta / Te / To / Ti | The following letter may fit beneath the T crossbar; check whether inward adjustment helps. |
| Ly / Li / Lo | The open upper-right area of L can make the following letter appear too distant. |
| Wo / Wa / We | The W diagonal and the following contour may benefit from tighter spacing. |

The user's **-40 to -80** values are candidate trials for problematic combinations such as AV/VA/AW/AY at display sizes, in 1/1000 em. They are manual values for one pair, separate from the rescue-tracking budgets in section 4, which bound a range of body text and are much smaller. **They are neither required targets nor fixed amounts to subtract from existing values.** Check the font profile first: when the pair is already kerned by the font (it is not listed in `unkerned_probes`) or the font has an optical-size design, expect little or no manual change and start from the small end. Inspect the current Optical/Metrics result, then adjust in small steps. Leave already-even spacing alone; do not pair-kern body text. Verify how manual values interact with automatic kerning using the application's actual readings, mode, and rendering; do not blindly add adjustments.

After tightening, check for contact between strokes, serifs, and diacritics, and for letters that could be mistaken for ligatures or other glyphs. Natural visual breathing room matters more than reaching a number.

### Geometric comparisons for sans-serif text

Start with the mode chosen in section 3 (Metrics for most sans faces). Compare HH/II, HO/IC, and OO/CG in the same font and size:

- Straight–straight pairs often create enclosed rectangular negative space and may need a larger physical gap.
- Straight–curved pairs have more open space above and below and may allow a slightly tighter physical gap.
- Curved–curved pairs may allow closer spacing to compensate for open space above and below.

These are starting observations, not instructions that two round letters must always be closest or nearly touching. Do not create collisions to equalize negative space. Do not assume pairs with different side shapes, such as HH and II, have equal widths.

### Inspection priorities for serif text

Start with the mode chosen in section 3 (Optical for most serif faces), then consider these house-style preferences:

- T/V/W followed by lowercase letters, such as Ta, Vo, and We: moderate tightening may help, while preserving breathing room between serifs.
- OO/CC/OQ: inspect the visual weight of the sides of round letters. Loosen an excessively tight trial where useful; do not assume every serif font needs wider spacing.
- HH/IL/NN: prioritize natural, stable spacing. Built-in Metrics kerning may serve as a comparison. Leave a natural Optical result unchanged; this example does not authorize silently switching all serif text to Metrics.

Serif construction and stroke stress vary by font. Do not assume every round letter is thickest at its left and right sides.

### When to stop

Pair kerning cannot replace paragraph-level line breaking, hyphenation or word-spacing control, and it is not the tool for runts, widows or orphans: those go through the rescue pass in section 5. If a pair adjustment changes a heading's line breaks, creates a collision, or makes the word's rhythm uneven, undo it. Locked specifications, content integrity and widow/orphan control take priority over the short-word line-ending preference.

## Software references

These sources explain software mechanisms; they do not endorse this skill's house style or trial values:

- [Adobe: Kerning and tracking](https://helpx.adobe.com/uk/indesign/desktop/format-and-style-text/tabs-indents-and-spacing/about-kerning-and-tracking.html)
- [Adobe: Tracking scope and units](https://helpx.adobe.com/indesign/desktop/format-and-style-text/tabs-indents-and-spacing/adjust-tracking.html)
- [Adobe: Metrics, Optical, and manual kerning](https://helpx.adobe.com/ph_fil/indesign/desktop/format-and-style-text/tabs-indents-and-spacing/adjust-kerning.html)
