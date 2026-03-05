import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), 'cctv.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("DELETE FROM cameras WHERE id LIKE 'OSM-%'")
print(f"Deleted {cur.rowcount} OSM cameras from DB.")
conn.commit()
conn.close()
