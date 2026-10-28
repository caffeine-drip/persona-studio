"""End-to-end test of every screen in offline mode (no Claude calls).

    python -m unittest discover tests
"""
import io
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp())
shutil.copytree(REPO / "personas", TMP / "personas")
os.environ.update(PERSONA_FAKE_LLM="1", PERSONA_DIR=str(TMP / "personas"),
                  STUDIO_DATA_DIR=str(TMP / "data"), PERSONA_KEY_FILE=str(TMP / "key.env"))
sys.path.insert(0, str(REPO / "app"))

import app as studio  # noqa: E402
import llm  # noqa: E402
import store  # noqa: E402

DISCLOSURE = "AI commentary in the style of Jodi Dean's political theory. Not written or endorsed by her."


class OfflineFlow(unittest.TestCase):
    def setUp(self):
        self.c = studio.app.test_client()

    def wait(self, resp):
        loc = resp.headers["Location"]
        for _ in range(100):
            r = self.c.get(loc)
            if r.status_code == 302:
                return r.headers["Location"]
            self.assertNotIn(b"Failed:", r.data)
            time.sleep(0.05)
        self.fail("job did not finish")

    def test_full_flow(self):
        self.assertIn(b"Jodi Dean", self.c.get("/").data)
        self.assertEqual(store.get_persona("jodi-dean")["disclosure"], DISCLOSURE)

        r = self.c.post("/personas/new", content_type="multipart/form-data", data={
            "name": "Test Person", "links": "https://example.com", "notes": "n",
            "files": (io.BytesIO(b"<p>hello</p>"), "a.html")})
        self.assertEqual(self.wait(r), "/personas/test-person")
        r = self.c.post("/personas/test-person/update", data={"notes": "more"})
        self.wait(r)
        self.assertTrue((TMP / "personas/test-person/history").exists())

        self.wait(self.c.post("/news/fetch", data={"topic": "AI", "count": "2", "focus": ["jodi-dean"]}))
        item = store.list_news()[0]["items"][0]
        r = self.c.post(f"/news/{item['id']}/draft",
                        data={"personas": ["jodi-dean", "test-person"], "platform": "instagram"})
        self.assertEqual(self.wait(r), "/drafts")
        drafts = store.list_drafts()
        self.assertEqual(len(drafts), 2)

        d = next(x for x in drafts if x["persona"] == "jodi-dean")
        self.assertTrue(d["text"].endswith(DISCLOSURE))
        self.c.post(f"/drafts/{d['id']}", data={"text": "Edited, no label", "action": "approved"})
        d = next(x for x in store.list_drafts() if x["id"] == d["id"])
        self.assertEqual(d["status"], "approved")
        self.assertEqual(d["text"], "Edited, no label\n\n" + DISCLOSURE)

        for url in ["/news", "/drafts", "/drafts?status=", "/settings",
                    "/personas/jodi-dean", "/personas/jodi-dean/edit", "/personas/new"]:
            self.assertEqual(self.c.get(url).status_code, 200, url)

    def test_disclosure_not_duplicated(self):
        text = llm.with_disclosure(f"Body\n\n*{DISCLOSURE}*", DISCLOSURE)
        self.assertEqual(text, f"Body\n\n{DISCLOSURE}")


if __name__ == "__main__":
    unittest.main()
