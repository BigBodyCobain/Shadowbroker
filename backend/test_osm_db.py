import sqlite3

try:
    conn = sqlite3.connect('cctv.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT source_agency, COUNT(*) as count FROM cameras WHERE id LIKE 'OSM-%' GROUP BY source_agency")
    rows = cur.fetchall()
    print('OSM Cameras by City:')
    for r in rows:
        print(f"{r['source_agency']}: {r['count']}")
except Exception as e:
    print('DB Error:', e)
