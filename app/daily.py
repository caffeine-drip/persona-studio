"""One-command daily run: find recent news, then draft a comment from every persona.

    python3 daily.py                       # 5 stories, Instagram drafts, all personas
    python3 daily.py --count 3 --platform reddit --topic "AI and labor"
    python3 daily.py --personas jodi-dean

Drafts land in the Drafts page for review, the same as drafts made in the app.
Nothing is posted. Schedule it with cron or Task Scheduler if you want a fresh batch each morning.
"""
import argparse
import sys

import llm
import store


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--count", type=int, default=5, help="news stories to find (1-15)")
    ap.add_argument("--topic", default="", help="optional topic or search focus")
    ap.add_argument("--platform", default="instagram", choices=sorted(llm.PLATFORM_RULES))
    ap.add_argument("--personas", nargs="*", help="persona slugs (default: all)")
    args = ap.parse_args()

    if not llm.has_key():
        sys.exit("No Claude API key. Add it in the app's Settings page or set ANTHROPIC_API_KEY.")

    personas = store.list_personas()
    if args.personas:
        personas = [p for p in personas if p["slug"] in args.personas]
    if not personas:
        sys.exit("No matching personas.")

    count = max(1, min(args.count, 15))
    print(f"Searching for {count} stories…", flush=True)
    items = llm.fetch_news(count, args.topic, [f"{p['name']}: {p['summary']}" for p in personas])
    store.save_news_batch(items, args.topic or "daily run")
    print(f"Found {len(items)}.")

    made, failed = 0, 0
    for item in items:
        for p in personas:
            try:
                text = llm.draft_comment(p["persona_md"], item, args.platform, "", p["disclosure"])
            except llm.LLMError as e:
                failed += 1
                print(f"  ✗ {p['name']} on “{item['title']}”: {e}", flush=True)
                continue
            store.save_draft(p["slug"], p["name"], item, args.platform, text, "")
            made += 1
            print(f"  ✓ {p['name']} on “{item['title']}”", flush=True)
    print(f"Done: {made} drafts waiting for review" + (f", {failed} failed" if failed else "") + ".")


if __name__ == "__main__":
    main()
