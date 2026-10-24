from __future__ import annotations


BASE_HISTORY_CATEGORY_IDS = (1, 2, 3, 4)
# The anniversary pool uses raw category 6; category 5 is not supported.
HISTORY_CATEGORY_IDS = frozenset((*BASE_HISTORY_CATEGORY_IDS, 6))
HISTORY_CATEGORY_KEYS = frozenset(str(category) for category in HISTORY_CATEGORY_IDS)
