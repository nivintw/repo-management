# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Keep the docs site's hand-maintained search index honest.

The index (docs/search-index.js) lists page#anchor targets in parallel with the HTML
pages; renaming a heading id would silently break search links without this check.
"""

from __future__ import annotations

import re
from pathlib import Path

DOCS = Path(__file__).parent.parent / "docs"


def test_search_index_anchors_exist() -> None:
    """Every href in the search index resolves to a real id in the referenced page."""
    index = (DOCS / "search-index.js").read_text(encoding="utf-8")
    hrefs = re.findall(r'href: "([a-z0-9-]+\.html)#([A-Za-z0-9_-]+)"', index)
    assert hrefs, "search index parsed to zero entries — regex or format drifted"
    assert len(hrefs) == index.count('href: "'), (
        "some index entries did not parse — an anchor escaped validation"
    )
    for page, anchor in hrefs:
        html = (DOCS / page).read_text(encoding="utf-8")
        assert f'id="{anchor}"' in html, f"search index points at missing {page}#{anchor}"
