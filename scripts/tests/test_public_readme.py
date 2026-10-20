"""Keep the public entry point linked and its real usage evidence visible."""
from html.parser import HTMLParser
from pathlib import Path
import re
import unittest
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]


class HtmlLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        for key in ("src", "href"):
            if attributes.get(key):
                self.links.append(attributes[key])


class PublicReadmeTest(unittest.TestCase):
    def test_readme_and_entry_docs_resolve_repository_links(self):
        for name in ("README.md", "INSTALL.md", "docs/ai-connections.md", "docs/ai-collaboration.md"):
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

    def test_collaboration_graph_is_static_and_accessible(self):
        root = ET.parse(ROOT / "docs/assets/aimanager-collaboration-flow.svg").getroot()
        tags = {node.tag.rsplit("}", 1)[-1] for node in root.iter()}
        self.assertFalse(tags & {"script", "foreignObject", "image"})
        self.assertEqual(root.attrib.get("role"), "img")
        ids = {node.attrib.get("id") for node in root.iter()}
        self.assertTrue(set(root.attrib["aria-labelledby"].split()) <= ids)
        for node in root.iter():
            self.assertFalse(any(key.lower().startswith("on") for key in node.attrib))
        for document in ("README.md", "docs/ai-collaboration.md"):
            self.assertIn("aimanager-collaboration-flow.svg", (ROOT / document).read_text(encoding="utf-8"))

    def test_public_install_and_badge_use_the_current_repository_name(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        install = (ROOT / "INSTALL.md").read_text(encoding="utf-8")
        for text in (readme, install):
            self.assertIn("https://github.com/3241288994/AImanager", text)
            self.assertNotIn("https://github.com/3241288994/codexmanager", text)
        self.assertIn("/AImanager/actions/workflows/ci.yml/badge.svg", readme)


if __name__ == "__main__":
    unittest.main()
