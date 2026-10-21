"""Keep the public entry point linked and its real usage evidence visible."""
from html.parser import HTMLParser
from pathlib import Path
import re
import struct
import unittest
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]


class HtmlLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.images = []

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == "img":
            self.images.append(attributes)
        for key in ("src", "href"):
            if attributes.get(key):
                self.links.append(attributes[key])


class PublicReadmeTest(unittest.TestCase):
    def test_readme_and_entry_docs_resolve_repository_links(self):
        for name in (
            "README.md", "INSTALL.md", "docs/ai-connections.md", "docs/ai-collaboration.md",
            "docs/demos/collaboration-demo.md", "docs/demos/quota-example/README.md",
            "docs/assets/aimanager-collaboration-demo.html",
            "docs/assets/collaboration-outputs/source.html",
        ):
            document = ROOT / name
            text = document.read_text(encoding="utf-8")
            html = HtmlLinks()
            html.feed(text)
            links = html.links + re.findall(r"\[[^\]]*\]\(([^)]+)\)", text)
            with self.subTest(document=name):
                for link in links:
                    target = urlsplit(link)
                    if target.scheme or target.netloc or not target.path:
                        continue
                    path = (document.parent / unquote(target.path)).resolve()
                    self.assertIn(ROOT, path.parents, link)
                    self.assertTrue(path.is_file(), f"{name}: {link}")
                self.assertEqual(text.count("```") % 2, 0)
                self.assertEqual(text.count("<details>"), text.count("</details>"))

    def test_real_chatgpt_demo_is_featured_before_management_gallery(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        demo = "docs/assets/chatgpt-labcontext-demo.png"
        self.assertLess(text.index(demo), text.index("## 为什么使用 AImanager"))
        self.assertLess(text.index(demo), text.index("docs/assets/aimanager-accounts.png"))
        self.assertEqual((ROOT / demo).read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_promotional_banner_is_featured_once_before_usage_demos(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        banner = "docs/assets/aimanager-hero-v1.png"
        self.assertEqual(text.count(banner), 1)
        self.assertLess(text.index(banner), text.index("## 先看实际效果"))
        self.assertEqual((ROOT / banner).read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_collaboration_demo_replaces_the_flow_and_has_accessible_text(self):
        demo = "aimanager-collaboration-demo.png"
        self.assertEqual((ROOT / "docs/assets" / demo).read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        for document in ("README.md", "docs/ai-collaboration.md"):
            text = (ROOT / document).read_text(encoding="utf-8")
            html = HtmlLinks()
            html.feed(text)
            images = [image for image in html.images if image.get("src", "").endswith(demo)]
            with self.subTest(document=document):
                self.assertEqual(len(images), 1)
                self.assertIn("CLI", images[0].get("alt", ""))
                self.assertIn("API", images[0].get("alt", ""))
                self.assertIn("demos/collaboration-demo.md", text)
                self.assertNotIn("aimanager-collaboration-flow.svg", text)

    def test_collaboration_demo_keeps_high_resolution_and_original_panels(self):
        demo = ROOT / "docs/assets/aimanager-collaboration-demo.png"
        width, height = struct.unpack(">II", demo.read_bytes()[16:24])
        self.assertGreaterEqual(width, 3000)
        self.assertGreaterEqual(height, 3000)
        for document in ("README.md", "docs/ai-collaboration.md", "docs/demos/collaboration-demo.md"):
            self.assertIn("aimanager-collaboration-demo.png?raw=true", (ROOT / document).read_text(encoding="utf-8"))
        for step in range(1, 7):
            panel = ROOT / f"docs/assets/collaboration-outputs/{step:02}.png"
            data = panel.read_bytes()
            with self.subTest(step=step):
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
                self.assertGreaterEqual(struct.unpack(">I", data[16:20])[0], 1500)

    def test_public_install_and_badge_use_the_current_repository_name(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        install = (ROOT / "INSTALL.md").read_text(encoding="utf-8")
        for text in (readme, install):
            self.assertIn("https://github.com/3241288994/AImanager", text)
            self.assertNotIn("https://github.com/3241288994/codexmanager", text)
        self.assertIn("/AImanager/actions/workflows/ci.yml/badge.svg", readme)


if __name__ == "__main__":
    unittest.main()
