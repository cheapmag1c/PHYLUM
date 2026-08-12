from __future__ import annotations

import unittest
from pathlib import Path

from phylum import __version__
from phylum.storage import ROOT


class ConvergenceTests(unittest.TestCase):
    def test_version(self):
        self.assertGreaterEqual(tuple(int(x) for x in __version__.split(".")), (2, 0, 1))

    def test_orrery_is_single_observatory_shell(self):
        index = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="life.html">LIFE</a>', index)
        self.assertIn("ORRERY interface · VIVARIUM engine", index)
        self.assertNotIn('href="vivarium.html">VIVARIUM</a>', index)

    def test_life_is_vivarium_subview(self):
        life = (ROOT / "docs" / "life.html").read_text(encoding="utf-8")
        self.assertIn("PHYLUM / ORRERY", life)
        self.assertIn("powered by the VIVARIUM continuous living-world engine", life)
        self.assertIn('class="active" href="life.html">LIFE</a>', life)
        self.assertTrue((ROOT / "renders" / "life.svg").exists())
        self.assertTrue((ROOT / "docs" / "life.svg").exists())
        self.assertTrue((ROOT / "docs" / "life-data.json").exists())

    def test_old_vivarium_url_is_compatibility_redirect(self):
        old = (ROOT / "docs" / "vivarium.html").read_text(encoding="utf-8")
        self.assertIn('url=life.html', old)
        self.assertNotIn("VIVARIUM / LIVING WORLD", old)
        # Compatibility render aliases remain so older tests and links do not break.
        self.assertTrue((ROOT / "renders" / "vivarium.svg").exists())
        self.assertTrue((ROOT / "docs" / "vivarium-data.json").exists())

    def test_readme_has_one_visual_hierarchy(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("## Living world — VIVARIUM", text)
        self.assertNotIn("![PHYLUM VIVARIUM living-world engine]", text)
        self.assertIn("VIVARIUM is the engine. ORRERY is the interface.", text)
        self.assertIn("## Living engine — VIVARIUM", text)
        self.assertIn("docs/life.html", text)


if __name__ == "__main__":
    unittest.main()
