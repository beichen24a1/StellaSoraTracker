"""Qt compatibility exports; presentation logic is shared with the desktop engine."""
from datetime import datetime
from ..service import Snapshot
from ..presentation import Overview, is_up, categories, activity_pools, overview

def demo_snapshot() -> Snapshot:
    """Deterministic illustrative records kept entirely in memory."""
    specs = [
        (10160, '2026-07-28', [(42, 160), (27, 110), (64, 160)], 18),
        (11133, '2026-08-08', [(36, 133)], 0),
        (10157, '2026-08-20', [(53, 157), (24, 157)], 23),
        (20160, '2026-07-29', [(38, 214055)], 0),
        (20157, '2026-08-22', [(46, 214057), (31, 214057)], 14),
        (1, '2026-06-10', [(59, 125), (32, 134), (46, 145)], 41),
        (2, '2026-06-11', [(34, 214015), (52, 214004)], 9),
    ]
    data = {}
    for gid, date, hits, trailing in specs:
        cat = 1 if 10000 <= gid < 20000 else 3 if gid >= 20000 else 2 if gid == 1 else 4
        filler = 103 if cat in (1,2) else 211001
        base = int(datetime.fromisoformat(date).timestamp())
        groups = data.setdefault(cat, [])
        for offset, (interval, item) in enumerate(hits):
            groups.append({'Gid': gid, 'Time': base + offset * 3600,
                           'Ids': [filler] * (interval - 1) + [item]})
        if trailing:
            groups.append({'Gid': gid, 'Time': base + len(hits) * 3600,
                           'Ids': [filler] * trailing})
    return Snapshot([g for groups in data.values() for g in groups], gacha_categories=data)
