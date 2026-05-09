import sqlite3, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

conn = sqlite3.connect('db.sqlite3')
cursor = conn.cursor()

cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
tables = cursor.fetchall()

print("=" * 60)
print("  ALL TABLES IN db.sqlite3")
print("=" * 60)
for t in tables:
    cursor.execute(f"SELECT COUNT(*) FROM [{t[0]}]")
    count = cursor.fetchone()[0]
    print(f"  - {t[0]}  ({count} rows)")

for t in tables:
    tname = t[0]
    print(f"\n{'─' * 60}")
    print(f"  TABLE: {tname}")
    print(f"{'─' * 60}")
    cursor.execute(f"PRAGMA table_info([{tname}]);")
    cols = cursor.fetchall()
    print(f"  {'COLUMN':30s} | {'TYPE':15s} | {'NOT NULL':8s} | DEFAULT")
    print(f"  {'-'*30}-+-{'-'*15}-+-{'-'*8}-+-{'-'*15}")
    for col in cols:
        nn = "YES" if col[3] else "NO"
        default = col[4] if col[4] is not None else ""
        print(f"  {col[1]:30s} | {col[2]:15s} | {nn:8s} | {default}")

    # Show sample data (first 3 rows)
    cursor.execute(f"SELECT * FROM [{tname}] LIMIT 3")
    rows = cursor.fetchall()
    if rows:
        col_names = [c[1] for c in cols]
        print(f"\n  Sample data (max 3 rows):")
        for row in rows:
            print(f"    {dict(zip(col_names, row))}")

conn.close()
