"""Persona Studio: build personas of public figures, pull current news, draft labelled comments.

Run:  python3 app.py   (then open http://127.0.0.1:5000)
"""
import html
import io
import os
import re
import threading
import traceback
import uuid

from flask import Flask, abort, flash, redirect, render_template, request, url_for

import llm
import store

app = Flask(__name__)
app.secret_key = "persona-studio-local"

MAX_UPLOAD_CHARS = 400_000  # across all files in one build, to stay well inside the context window

# ---------------------------------------------------------------- background jobs
# Persona builds and news searches take minutes, so they run in threads and the
# browser polls the job page.

JOBS = {}


def start_job(label, fn, done_url=None):
    job_id = uuid.uuid4().hex[:10]
    JOBS[job_id] = {"id": job_id, "label": label, "status": "running", "error": None,
                    "done_url": done_url, "started": store.now()}

    def run():
        try:
            fn()
            JOBS[job_id]["status"] = "done"
        except llm.LLMError as e:
            JOBS[job_id].update(status="failed", error=str(e))
        except Exception as e:  # surface anything else on the job page
            traceback.print_exc()
            JOBS[job_id].update(status="failed", error=f"{type(e).__name__}: {e}")

    threading.Thread(target=run, daemon=True).start()
    return redirect(url_for("job", job_id=job_id))


@app.route("/jobs/<job_id>")
def job(job_id):
    j = JOBS.get(job_id) or abort(404)
    if j["status"] == "done" and j["done_url"]:
        return redirect(j["done_url"])
    return render_template("job.html", job=j)


@app.context_processor
def running_jobs():
    return {"running_jobs": [j for j in JOBS.values() if j["status"] == "running"],
            "needs_key": not llm.has_key()}


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        key = request.form.get("api_key", "").strip()
        if key:
            llm.set_key(key)
        problem = llm.check_key() if llm.has_key() else "No key saved yet."
        flash(problem or "Key saved and working.")
        return redirect(url_for("settings"))
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    return render_template("settings.html", key_hint=f"…{key[-4:]}" if key else None,
                           key_file=llm.KEY_FILE, model=llm.MODEL, fake=llm.FAKE)


# ---------------------------------------------------------------- helpers

def extract_text(filename, data):
    name = filename.lower()
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except ImportError:
            raise llm.LLMError("Install pypdf to read PDF uploads (pip install pypdf).")
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    text = data.decode("utf-8", errors="replace")
    if name.endswith((".html", ".htm")):
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
        text = html.unescape(re.sub(r"<[^>]+>", " ", text))
        text = re.sub(r"\s+\n", "\n", re.sub(r"[ \t]+", " ", text))
    return text


def valid_id(s):
    if not re.fullmatch(r"[A-Za-z0-9-]+", s or ""):
        abort(404)
    return s


# ---------------------------------------------------------------- personas

@app.route("/")
def index():
    return render_template(
        "index.html",
        personas=store.list_personas(),
        draft_count=len(store.list_drafts(status="draft")),
        news=store.list_news(limit=1),
    )


@app.route("/personas/new", methods=["GET", "POST"])
@app.route("/personas/<slug>/update", methods=["GET", "POST"], endpoint="update_persona")
def new_persona(slug=None):
    existing = store.get_persona(valid_id(slug)) if slug else None
    if slug and not existing:
        abort(404)
    if request.method == "GET":
        return render_template("persona_form.html", persona=existing)

    name = existing["name"] if existing else request.form.get("name", "").strip()
    if not name:
        flash("Give the person's name.")
        return redirect(request.url)
    target = existing["slug"] if existing else store.slugify(name)
    if not existing and store.get_persona(target):
        flash(f"{name} already exists; use Update instead.")
        return redirect(url_for("persona", slug=target))

    links = [l.strip() for l in request.form.get("links", "").splitlines() if l.strip()]
    notes = request.form.get("notes", "").strip()
    uploads, total = [], 0
    for f in request.files.getlist("files"):
        if not f or not f.filename:
            continue
        data = f.read()
        store.save_upload(target, f.filename, data)
        try:
            text = extract_text(f.filename, data)
        except llm.LLMError as e:
            flash(str(e))
            return redirect(request.url)
        if total + len(text) > MAX_UPLOAD_CHARS:
            flash(f"{f.filename} pushes the uploads past {MAX_UPLOAD_CHARS:,} characters. "
                  "Upload excerpts or split the build into several updates.")
            return redirect(request.url)
        total += len(text)
        uploads.append((f.filename, text))
    if not (links or notes or uploads) and existing:
        flash("Add links, files or notes to update with.")
        return redirect(request.url)

    template = store.template_md()

    def work():
        persona_md, sources_md = llm.build_persona(
            name, links, notes, uploads, template,
            existing_md=existing and existing["persona_md"],
            existing_sources=existing and existing["sources_md"],
        )
        store.save_persona(target, persona_md, sources_md)

    verb = "Updating" if existing else "Building"
    return start_job(f"{verb} persona: {name}", work, url_for("persona", slug=target))


@app.route("/personas/<slug>")
def persona(slug):
    p = store.get_persona(valid_id(slug)) or abort(404)
    return render_template("persona.html", p=p, drafts=store.list_drafts(persona=slug)[:20])


@app.route("/personas/<slug>/edit", methods=["GET", "POST"])
def edit_persona(slug):
    p = store.get_persona(valid_id(slug)) or abort(404)
    if request.method == "POST":
        store.save_persona(slug, request.form["persona_md"].replace("\r\n", "\n"),
                           request.form["sources_md"].replace("\r\n", "\n"))
        flash("Saved. The previous version is in the persona's history folder.")
        return redirect(url_for("persona", slug=slug))
    return render_template("persona_edit.html", p=p)


# ---------------------------------------------------------------- news

@app.route("/news")
def news():
    return render_template("news.html", batches=store.list_news(), personas=store.list_personas(),
                           platforms=llm.PLATFORM_RULES)


@app.route("/news/fetch", methods=["POST"])
def fetch_news():
    topic = request.form.get("topic", "").strip()
    count = max(1, min(int(request.form.get("count") or 5), 15))
    focus = request.form.getlist("focus")
    summaries = [f"{p['name']}: {p['summary']}" for p in store.list_personas() if p["slug"] in focus]

    def work():
        items = llm.fetch_news(count, topic, summaries)
        store.save_news_batch(items, topic or "general")

    return start_job("Searching for news" + (f": {topic}" if topic else ""), work, url_for("news"))


@app.route("/news/add", methods=["POST"])
def add_news():
    title = request.form.get("title", "").strip()
    if not title:
        flash("A headline is required.")
        return redirect(url_for("news"))
    store.add_manual_news({
        "title": title,
        "outlet": request.form.get("outlet", "").strip(),
        "url": request.form.get("url", "").strip(),
        "published": request.form.get("published", "").strip(),
        "summary": request.form.get("summary", "").strip(),
        "why": "",
    })
    return redirect(url_for("news"))


@app.route("/news/<item_id>/draft", methods=["POST"])
def draft(item_id):
    item = store.get_news_item(valid_id(item_id)) or abort(404)
    platform = request.form.get("platform", "reddit")
    angle = request.form.get("angle", "").strip()
    personas = [store.get_persona(s) for s in request.form.getlist("personas")]
    personas = [p for p in personas if p]
    if not personas:
        flash("Pick at least one persona.")
        return redirect(url_for("news"))

    def work():
        for p in personas:
            text = llm.draft_comment(p["persona_md"], item, platform, angle, p["disclosure"])
            store.save_draft(p["slug"], p["name"], item, platform, text, angle)

    names = ", ".join(p["name"] for p in personas)
    return start_job(f"Drafting {platform} comments as {names}", work, url_for("drafts"))


# ---------------------------------------------------------------- drafts

@app.route("/drafts")
def drafts():
    status = request.args.get("status", "draft")
    persona = request.args.get("persona") or None
    return render_template("drafts.html", drafts=store.list_drafts(status=status or None, persona=persona),
                           status=status, persona=persona, personas=store.list_personas())


@app.route("/drafts/<draft_id>", methods=["POST"])
def update_draft(draft_id):
    valid_id(draft_id)
    action = request.form.get("action")
    fields = {}
    if "text" in request.form:
        d = next((x for x in store.list_drafts() if x["id"] == draft_id), None) or abort(404)
        p = store.get_persona(d["persona"])
        disclosure = p["disclosure"] if p else store.default_disclosure(d["persona_name"])
        # Edits keep the disclosure line, whatever the editor did to it.
        fields["text"] = llm.with_disclosure(request.form["text"].replace("\r\n", "\n"), disclosure)
    if action in ("approved", "rejected", "draft", "posted"):
        fields["status"] = action
    store.update_draft(draft_id, **fields)
    return redirect(request.referrer or url_for("drafts"))


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)), debug=False)
