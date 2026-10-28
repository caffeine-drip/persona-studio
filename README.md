# InstaCommunist: Persona Studio

Build personas of public figures from their published work, pull current news, and draft clearly labelled comments in each persona's voice for Instagram, Reddit or X. Drafts are for human review; nothing is posted automatically.

- `app/` is the web app and the `daily.py` command. See [app/README.md](app/README.md) to run it.
- `personas/<slug>/` holds each persona's brief (`persona.md`) and sources (`sources.md`).
- `tests/` runs every screen offline: `python -m unittest discover tests`.
