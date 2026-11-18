# FullAuto-Typography-Tools

A set of tools package that connect your Adobe Indesign to your agent, on MacOS and Windows
A skill reviews and refines the typography of Latin-script books (English, French, German, Latin and other languages written in the Latin alphabet) the way a careful typesetter would. It works on the real document, follows your house rules, and logs every change it makes.

Skill folder: [`latin-book-typography/`](latin-book-typography/)
Indesign-Bridge-folder： [`indesign-bridge`](indesign-bridge/)

Comming Soon:
Windows COM control your Indesign
Rich-image book layout
Typefaces recommading and commercial use checking


---

## 1. What this skill does

Long documents pick up small typographic faults that are easy to miss and tedious to fix by hand: a single word left alone on the last line of a paragraph, a lone line stranded at the top or bottom of a page, loose or tight spacing, chapters starting on the wrong side of a spread, page numbers that no longer match the contents page. This skill finds these faults in the composed pages and fixes them, or reports them if you only want a review.

What makes it different from a generic "check my layout" prompt:

- **It does not change what you approved.** Body font, size, leading, indents and paragraph spacing are recorded at the start and treated as locked. Problems are solved with hyphenation, spacing, pagination and other permitted levers, never by quietly shrinking the type.
- **It does not rewrite your text.** Wording, spelling, names and numbers stay as they are. Only clearly accidental punctuation, whitespace and line-break faults are repaired, and each repair is logged with its location and before/after value.
- **Spacing decisions come from your actual font.** A bundled script measures the font file to choose the kerning mode and to set how far tracking may move in each direction. Local fixes stay inside that budget, so a tightly fitted serif is treated more carefully than an open sans.
- **Review comes first.** Unless you ask for edits, it only inspects and reports, giving the page, the text range, the evidence and the proposed fix for each problem.
- **It tells you what it could not check.** If a rule cannot be verified (missing fonts, a PDF with no source, a backend that cannot see composition), the report says so instead of claiming a pass.

## 2. Demo

![Runt, widow and orphan, each removed with −4/1000 em tracking](assets/demo/demo.gif)

Three defects and the kind of fix the skill makes for each:

1. **Runt** – one word alone on the last line of a paragraph. Tracking of −4/1000 em on the paragraph pulls the word back up.
2. **Widow** – the last line of a paragraph alone at the top of the next page. Tightening an earlier paragraph saves one line, and the widow rejoins its paragraph.
3. **Orphan** – the first line of a paragraph alone at the foot of a page. Saving a line higher up the page lifts the paragraph's second line up to join it, so two lines stand before the page turn.



## 3. What it is for, and which software it supports

**Good for**

- Final typesetting of academic books, monographs and theses, and design-led books where appearance comes first. The skill asks which one you are making, because they follow different alignment and page conventions.
- Removing widows, orphans and runts; checking rivers, hyphenation, justification, kerning and tracking.
- Book structure: right-hand (recto) chapter starts, Roman front-matter and Arabic body page numbering, headings kept with their text, and a final check of every contents-page entry against the real page numbers.
- Cleaning up manuscripts: straight quotes used as quotation marks, stray leading spaces, and paragraph marks left after every line of text pasted from a PDF.
- Pre-flight checks for a print-ready PDF.

**Not for**

- Editing prose, grammar or style.
- LaTeX documents.
- Typesetting Chinese, Japanese, Korean or other non-Latin scripts. Such text can appear in the book; the skill leaves it unchanged and lists it in the report.

**Software**

| Application | Status |
| --- | --- |
| Adobe InDesign (INDD, IDML) | Supported. Inspection and edits through a local MCP connection, ExtendScript (JSX) jobs or a UXP bridge. Qualified on InDesign 2026 (21.2) on macOS. |
| PDF or screenshots | Review only. Visible layout can be checked; native settings cannot. |
| Microsoft Word (.docx) | Planned. The rules are mapped but not yet verified in Word. |
| Apple Pages | Planned. The rules are mapped but not yet verified in Pages. |
| Google Docs | Not supported. |

## 4. Installation and requirements

### Install

In Claude Code, say:

```text
Install this skill: https://github.com/chungkwan24/typography-skills
```

Or use the [skills](https://www.npmjs.com/package/skills) command-line tool:

```bash
npx skills add chungkwan24/typography-skills
```

Or copy it by hand:

```bash
git clone https://github.com/chungkwan24/typography-skills.git
```

```bash
cp -r typography-skills/latin-book-typography ~/.claude/skills/
```

To install it for one project only, copy the folder into that project's `.claude/skills/` directory instead.

### Requirements

- **Claude Code**, or another agent that loads `SKILL.md` skills. Interface metadata for Codex is included in `agents/openai.yaml`.
- **Python 3.10 or later** for the bundled scripts.
- **fontTools** for font profiling: `python3 -m pip install fonttools`. Without it the skill falls back to a conservative spacing budget and says that the font was not measured.
- **Adobe InDesign** with your document open, plus one way for the agent to reach it:

| Route | What you need | Best for |
| --- | --- | --- |
| MCP connection (recommended) | macOS, Adobe UXP Developer Tools, and the Python `mcp` package (`mcp==1.30.0`). Windows is not validated yet. | Repeated inspection and tracking edits from the agent. |
| JSX jobs | macOS with AppleScript, or any system where you can run a script from InDesign's Scripts panel. | Read-only inspection and one-off edits without setting up MCP. |
| Manual | Nothing extra. The agent prepares the script, you run it from the Scripts panel and send back the result. | Browser chats and locked-down machines. |

The MCP server and its InDesign plugin are not inside the skill folder. They live in [`indesign-bridge/`](indesign-bridge/README.md) at the top of this repository, so several skills can share one connection. Keep a clone of the repository for them; copying only the skill folder is enough for the JSX and manual routes. The MCP route needs a one-time pairing between the agent and InDesign. Ask the agent to "set up the InDesign MCP connection" and it will walk you through it; the full steps are in [`references/indesign-mcp.md`](latin-book-typography/references/indesign-mcp.md).

## 5. How to use it

Open your document in InDesign and describe the job. You do not need the word "typography"; mentioning widows, kerning, page numbers, a print PDF or your INDD file is enough. Requests in other languages work too, and the skill replies in the language you write in.

```text
Review the typography of Atlas.indd. It's an academic monograph going to print.
```

```text
Fix the widows, orphans and runts in chapters 2 to 4 on a working copy. Don't touch the body specs.
```

```text
I've finished editing. Check the contents page and the page numbering before I export the PDF.
```

```text
帮我检查这本英文书的排版，只出报告，先不要改。
```

**What happens next**

1. **Intake.** On a new project it asks its questions in one message: academic or design-led, digital PDF or printed book, facing pages, and whether to review, edit a working copy or edit the file itself.
2. **Baseline.** It records the approved body specifications and leaves them alone from then on.
3. **Audit.** It inspects the composed pages and lists each problem with its page, text range, evidence and proposed fix.
4. **Edit (only if you ask).** Text repairs come first, then spacing. Local spacing fixes are made last, once the wording, headings, frames and page count are settled, because each of those changes reflows the lines a fix was tuned for.
5. **Delivery.** You get the edited file, a change log, and a status report that separates what was applied, what was checked, and what still needs your eye.

**Modes.** *Review* (the default) never changes the document. *Edit* changes only what you authorised. *Pause* stops all changes until you resume. Installing or discussing the skill never starts editing.

## License

MIT License

Copyright (c) 2026 Yijun Zhong

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
