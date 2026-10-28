"""All Claude API calls for the persona studio.

Set ANTHROPIC_API_KEY (or log in with `ant auth login`). Set PERSONA_FAKE_LLM=1 to
run the whole app offline with canned responses, which is handy for trying the UI.
"""
import json
import os
import re
from datetime import date
from pathlib import Path

import anthropic

MODEL = os.environ.get("PERSONA_MODEL", "claude-opus-5-5")
FAKE = os.environ.get("PERSONA_FAKE_LLM") == "1"


class LLMError(RuntimeError):
    pass


_client = None

# The API key is kept in the user's home folder, never in the project folder.
KEY_FILE = Path(os.environ.get("PERSONA_KEY_FILE", Path.home() / ".persona-studio.env"))


def _load_key():
    if os.environ.get("ANTHROPIC_API_KEY") or not KEY_FILE.exists():
        return
    for line in KEY_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip()


_load_key()


def has_key():
    return FAKE or bool(os.environ.get("ANTHROPIC_API_KEY"))


def set_key(key):
    global _client
    KEY_FILE.write_text(f"ANTHROPIC_API_KEY={key}\n", encoding="utf-8")
    KEY_FILE.chmod(0o600)
    os.environ["ANTHROPIC_API_KEY"] = key
    _client = None


def check_key():
    """Cheap call to confirm the key works. Returns None when fine, else an error message."""
    if FAKE:
        return None
    try:
        _get_client().models.retrieve(MODEL)
    except anthropic.AuthenticationError:
        return "That key was rejected. Check it on console.anthropic.com."
    except anthropic.NotFoundError:
        return f"The key works, but this account can't use {MODEL}. Set PERSONA_MODEL to a model it can use."
    except anthropic.APIStatusError as e:
        return f"Claude API error {e.status_code}: {e.message}"
    except anthropic.APIConnectionError:
        return "Could not reach the Claude API."
    return None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _web_tools(searches=10, fetches=10):
    tools = []
    if searches:
        tools.append({"type": "web_search_20260209", "name": "web_search", "max_uses": searches})
    if fetches:
        tools.append({"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": fetches})
    return tools


def _run(system, user_text, tools=None, effort="medium", max_tokens=64000):
    """One request, resumed across pause_turn, with server-side refusal fallback."""
    messages = [{"role": "user", "content": user_text}]
    msg = None
    for _ in range(6):
        kwargs = dict(
            model=MODEL,
            max_tokens=max_tokens,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if system:
            # Persona briefs are long and reused across drafts, so cache them.
            kwargs["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        if tools:
            kwargs["tools"] = tools
        try:
            with _get_client().beta.messages.stream(**kwargs) as stream:
                msg = stream.get_final_message()
        except anthropic.AuthenticationError as e:
            raise LLMError("Claude API key missing or invalid. Set ANTHROPIC_API_KEY.") from e
        except anthropic.RateLimitError as e:
            raise LLMError("Rate limited by the Claude API; try again shortly.") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Claude API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError("Could not reach the Claude API.") from e
        if msg.stop_reason == "pause_turn":
            messages = messages + [{"role": "assistant", "content": msg.content}]
            continue
        break
    if msg.stop_reason == "refusal":
        raise LLMError("Claude declined this request.")
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    if not text:
        raise LLMError(f"Empty response (stop reason: {msg.stop_reason}).")
    return text


# ---------------------------------------------------------------- persona build

BUILD_INSTRUCTIONS = """You build persona briefs for a commentary agent that writes clearly labelled,
simulated commentary "in the style of" a real public figure, based on their public record.

Research the person using the material below, the links given (fetch them), and web search for
biography, their own writing and interviews, recent statements and press coverage. Prefer primary
sources (their own books, essays, speeches, posts, interviews). Note what you could not verify.

Write two Markdown documents, following the structure, depth and rules of the TEMPLATE persona
(which is a finished brief for a different person). Keep every section of the template:
frontmatter, the "Read this first" disclosure box, "1. System prompt" in a fenced code block,
background, core ideas table, positions on major topics, rhetorical style and vocabulary,
4 short illustrative example comments clearly marked as invented, and rules for the agent.
The system prompt must forbid claiming to be the person, inventing quotes or facts, calling for
violence, and harassing private individuals, and must say each output ends with the disclosure
line. Frontmatter must include: persona, version, built (today's date), status, sources, and
disclosure (a one-line label such as: AI commentary in the style of <Name>'s public views. Not
written or endorsed by them.).

The second document is sources.md: every source you used with its URL and a one-line gist,
grouped by type, with a note on anything you could not load.

Reply with exactly this layout and nothing else:
=====PERSONA.MD=====
<persona.md content>
=====SOURCES.MD=====
<sources.md content>"""


def build_persona(name, links, notes, uploaded_texts, template_md, existing_md=None, existing_sources=None):
    """Returns (persona_md, sources_md)."""
    parts = [f"Today's date: {date.today().isoformat()}", f"Person: {name}"]
    if notes:
        parts.append(f"Operator notes:\n{notes}")
    if links:
        parts.append("Links to read:\n" + "\n".join(links))
    for fname, text in uploaded_texts:
        parts.append(f"<uploaded_file name=\"{fname}\">\n{text}\n</uploaded_file>")
    if existing_md:
        parts.append(
            "This person already has a brief (below). Update it with the new material rather than "
            "starting over, bump the version number, and keep sources that still apply.\n"
            f"<current_persona>\n{existing_md}\n</current_persona>\n"
            f"<current_sources>\n{existing_sources or ''}\n</current_sources>"
        )
    parts.append(f"<template_persona>\n{template_md}\n</template_persona>")
    user = "\n\n".join(parts)

    if FAKE:
        return _fake_persona(name), f"# {name}: source material\n\n- (offline test mode, no sources)\n"

    text = _run(BUILD_INSTRUCTIONS, user, tools=_web_tools(15, 20), effort="high")
    m = re.search(r"=====PERSONA\.MD=====\s*(.*?)\s*=====SOURCES\.MD=====\s*(.*)", text, re.S)
    if not m:
        raise LLMError("Persona build came back in an unexpected format.")
    return m.group(1).strip() + "\n", m.group(2).strip() + "\n"


# ---------------------------------------------------------------- news

NEWS_INSTRUCTIONS = """You find current news stories for a commentary agent. Use web search.
Only include stories published in the last 7 days, from reputable outlets, with a working URL.
Do not invent stories, dates or URLs. Reply with only a JSON array inside a ```json fence; each item:
{"title": str, "outlet": str, "url": str, "published": "YYYY-MM-DD", "summary": "2-3 factual sentences",
 "why": "one line on why it suits the personas listed"}"""


def fetch_news(count, topic, persona_summaries):
    user = f"Today's date: {date.today().isoformat()}\nFind {count} news stories."
    if topic:
        user += f"\nTopic or search focus: {topic}"
    if persona_summaries:
        user += "\nPick stories these commentators would have something to say about:\n" + "\n".join(
            f"- {s}" for s in persona_summaries
        )
    if FAKE:
        return [
            {
                "title": f"Test story {i + 1}" + (f" about {topic}" if topic else ""),
                "outlet": "Offline Test News",
                "url": "https://example.com/story",
                "published": date.today().isoformat(),
                "summary": "A placeholder story generated in offline test mode.",
                "why": "Test mode.",
            }
            for i in range(count)
        ]
    text = _run(NEWS_INSTRUCTIONS, user, tools=_web_tools(10, 0), effort="medium", max_tokens=32000)
    m = re.search(r"```json\s*(.*?)```", text, re.S)
    raw = m.group(1) if m else text
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as e:
        raise LLMError("News search came back in an unexpected format.") from e
    return [i for i in items if isinstance(i, dict) and i.get("title")]


# ---------------------------------------------------------------- drafts

PLATFORM_RULES = {
    "instagram": "Instagram caption: 60-150 words, then 3-6 relevant hashtags on their own line.",
    "reddit": "Reddit comment: 80-250 words, conversational, no hashtags.",
    "x": "X post: at most 260 characters, no hashtags unless essential.",
}


def draft_comment(persona_md, news_item, platform, angle, disclosure):
    user = (
        f"News item:\nTitle: {news_item.get('title')}\nOutlet: {news_item.get('outlet', '')}\n"
        f"Published: {news_item.get('published', '')}\nURL: {news_item.get('url', '')}\n"
        f"Summary: {news_item.get('summary', '')}\n\n"
        f"Write one comment. Format: {PLATFORM_RULES.get(platform, PLATFORM_RULES['reddit'])}\n"
        "You may fetch the URL to check details; argue from what is reported and never invent facts or quotes.\n"
    )
    if angle:
        user += f"Operator's angle note: {angle}\n"
    user += (
        "Output only the comment text. Do not add the disclosure line; it is appended automatically.\n"
    )
    if FAKE:
        text = f"[offline test draft for {platform}] A comment on \"{news_item.get('title')}\"."
    else:
        tools = _web_tools(0, 2) if news_item.get("url") else None
        text = _run(persona_md, user, tools=tools, effort="medium", max_tokens=16000)
    return with_disclosure(text, disclosure)


def with_disclosure(text, disclosure):
    """Ensure the comment ends with exactly one copy of the disclosure line."""
    body = text.strip()
    core = re.sub(r"[*_]", "", disclosure).strip().lower()
    lines = body.splitlines()
    while lines and (not lines[-1].strip() or core[:40] in re.sub(r"[*_>]", "", lines[-1]).strip().lower()):
        lines.pop()
    return "\n".join(lines).rstrip() + f"\n\n{disclosure}"


def _fake_persona(name):
    return f"""---
persona: {name}
version: 1
built: {date.today().isoformat()}
status: simulated persona, not the real person
sources: ./sources.md
disclosure: AI commentary in the style of {name}'s public views. Not written or endorsed by them.
---

# Persona brief: {name} (simulated)

## 1. System prompt (load this into the agent)

```
You are a commentary agent writing in the style of {name}. Offline test persona.
```
"""
