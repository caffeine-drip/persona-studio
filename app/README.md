# Persona Studio

A small local web app for building personas of public figures from source material, pulling current news, and drafting labelled comments in each persona's voice for Instagram, Reddit or X. Drafts are for human review; nothing is posted automatically.

## Run it

```bash
cd app
pip install -r requirements.txt
python3 app.py                           # open http://127.0.0.1:5000
```

Then paste your Claude API key (from console.anthropic.com) into **Settings**. It is tested on save and stored in `~/.persona-studio.env`, outside the project folder. Setting `ANTHROPIC_API_KEY` in your shell works too.

### Daily run

```bash
python3 daily.py                                  # 5 stories, an Instagram draft from every persona
python3 daily.py --count 3 --platform reddit --topic "AI and labor" --personas jodi-dean
```

The drafts appear on the Drafts page for review. Schedule it with cron or Task Scheduler if you want a fresh batch every morning.

To click through the app without an API key, start it with `PERSONA_FAKE_LLM=1 python3 app.py`; every Claude call returns placeholder text.

## What it does

1. **Personas.** "Add a person" takes a name plus links, files (txt, md, html, pdf) and notes. Claude reads the links, searches the web, and writes `persona.md` (system prompt, background, ideas, positions, style, examples, rules) and `sources.md`, using the Jodi Dean brief as the template. "Add sources and rebuild" updates an existing persona; the previous version is saved in its `history/` folder. You can also edit both files by hand.
2. **News.** Search for recent stories (optionally on a topic, steered toward the personas you tick), or add a story by hand.
3. **Drafts.** On any story, tick one or more personas, pick a platform and an optional angle, and draft. Each draft ends with the persona's disclosure line, which the app re-adds if an edit removes it. Approve, edit, reject, copy, or mark as posted.

## Where things are stored

- `personas/<slug>/persona.md`, `sources.md`, `uploads/`, `history/` (next to this folder)
- `studio-data/news/*.json` and `studio-data/drafts/*.json`

Override with `PERSONA_DIR` and `STUDIO_DATA_DIR`. `PERSONA_MODEL` picks the Claude model (default `claude-opus-5-5`); `PERSONA_TEMPLATE` picks which persona is the format template (default `jodi-dean`).

## Ground rules baked in

Personas are simulations and say so. Every draft carries a disclosure line (set per persona in the `disclosure:` frontmatter field). The persona prompts forbid claiming to be the person, inventing quotes or facts, calling for violence, and targeting private individuals.
