"""Plain-file storage. Personas live in personas/<slug>/; news and drafts in studio-data/."""
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PERSONAS = Path(os.environ.get("PERSONA_DIR", ROOT / "personas"))
DATA = Path(os.environ.get("STUDIO_DATA_DIR", ROOT / "studio-data"))
NEWS = DATA / "news"
DRAFTS = DATA / "drafts"
TEMPLATE_SLUG = os.environ.get("PERSONA_TEMPLATE", "jodi-dean")

for d in (PERSONAS, NEWS, DRAFTS):
    d.mkdir(parents=True, exist_ok=True)


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "persona"


def _read(p):
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _write_json(p, obj):
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def frontmatter(md):
    m = re.match(r"---\n(.*?)\n---", md, re.S)
    out = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                out[k.strip()] = v.strip()
    return out


def default_disclosure(name):
    return f"AI commentary in the style of {name}'s public views. Not written or endorsed by them."


# ---------------------------------------------------------------- personas

def list_personas():
    out = []
    for d in sorted(PERSONAS.iterdir()):
        if d.is_dir() and (d / "persona.md").exists():
            out.append(get_persona(d.name))
    return out


def get_persona(slug):
    d = PERSONAS / slug
    md = _read(d / "persona.md")
    if not md:
        return None
    fm = frontmatter(md)
    name = fm.get("persona", slug)
    # The tagline is the first lens summary line, used to steer news search.
    m = re.search(r"Who (?:she|he|they) (?:is|are):\s*(.+?)\n\n", md, re.S)
    return {
        "slug": slug,
        "name": name,
        "version": fm.get("version", "?"),
        "built": fm.get("built", ""),
        "disclosure": fm.get("disclosure") or default_disclosure(name),
        "persona_md": md,
        "sources_md": _read(d / "sources.md"),
        "summary": " ".join(m.group(1).split())[:300] if m else name,
        "uploads": sorted(p.name for p in (d / "uploads").glob("*")) if (d / "uploads").exists() else [],
    }


def save_persona(slug, persona_md, sources_md):
    d = PERSONAS / slug
    d.mkdir(parents=True, exist_ok=True)
    if (d / "persona.md").exists():
        hist = d / "history"
        hist.mkdir(exist_ok=True)
        stamp = now().replace(":", "")
        (hist / f"persona-{stamp}.md").write_text(_read(d / "persona.md"), encoding="utf-8")
        (hist / f"sources-{stamp}.md").write_text(_read(d / "sources.md"), encoding="utf-8")
    (d / "persona.md").write_text(persona_md, encoding="utf-8")
    (d / "sources.md").write_text(sources_md, encoding="utf-8")


def save_upload(slug, filename, data):
    d = PERSONAS / slug / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename) or "upload"
    (d / safe).write_bytes(data)
    return d / safe


def template_md():
    return _read(PERSONAS / TEMPLATE_SLUG / "persona.md")


# ---------------------------------------------------------------- news

def save_news_batch(items, topic):
    batch_id = now().replace(":", "") + "-" + uuid.uuid4().hex[:4]
    for i, item in enumerate(items):
        item["id"] = f"{batch_id}-{i}"
    _write_json(NEWS / f"{batch_id}.json", {"id": batch_id, "fetched": now(), "topic": topic, "items": items})
    return batch_id


def add_manual_news(item):
    return save_news_batch([item], "added by hand")


def list_news(limit=10):
    batches = []
    for p in sorted(NEWS.glob("*.json"), reverse=True)[:limit]:
        batches.append(json.loads(p.read_text(encoding="utf-8")))
    return batches


def get_news_item(item_id):
    batch_id = item_id.rsplit("-", 1)[0]
    p = NEWS / f"{batch_id}.json"
    if p.exists():
        for item in json.loads(p.read_text(encoding="utf-8"))["items"]:
            if item["id"] == item_id:
                return item
    return None


# ---------------------------------------------------------------- drafts

def save_draft(persona_slug, persona_name, news_item, platform, text, angle):
    draft_id = now().replace(":", "") + "-" + uuid.uuid4().hex[:6]
    draft = {
        "id": draft_id,
        "created": now(),
        "persona": persona_slug,
        "persona_name": persona_name,
        "platform": platform,
        "angle": angle,
        "news": {k: news_item.get(k, "") for k in ("id", "title", "outlet", "url", "published", "summary")},
        "text": text,
        "status": "draft",
    }
    _write_json(DRAFTS / f"{draft_id}.json", draft)
    return draft


def list_drafts(status=None, persona=None):
    out = []
    for p in sorted(DRAFTS.glob("*.json"), reverse=True):
        d = json.loads(p.read_text(encoding="utf-8"))
        if (not status or d["status"] == status) and (not persona or d["persona"] == persona):
            out.append(d)
    return out


def update_draft(draft_id, **fields):
    p = DRAFTS / f"{draft_id}.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d.update(fields)
    d["updated"] = now()
    _write_json(p, d)
    return d
