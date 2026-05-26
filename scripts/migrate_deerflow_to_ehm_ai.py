"""Migrate data from deerflow to ehm_ai PostgreSQL database."""

import json

import psycopg

SRC_URL = "postgresql://postgres:2012dbkey@182.92.187.198:5432/deerflow"
DST_URL = "postgresql://postgres:2012dbkey@182.92.187.198:5432/ehm_ai"

UDT_MAP = {
    "varchar": None,  # needs length
    "text": "TEXT",
    "int4": "INTEGER",
    "int8": "BIGINT",
    "bool": "BOOLEAN",
    "json": "JSON",
    "jsonb": "JSONB",
    "bytea": "BYTEA",
    "float8": "DOUBLE PRECISION",
    "float4": "REAL",
    "timestamptz": "TIMESTAMPTZ",
    "timestamp": "TIMESTAMP",
    "date": "DATE",
    "uuid": "UUID",
}


def main():
    src = psycopg.connect(SRC_URL)
    dst = psycopg.connect(DST_URL, autocommit=True)
    src_cur = src.cursor()
    dst_cur = dst.cursor()

    # Create sequences first
    src_cur.execute("SELECT sequencename, start_value FROM pg_sequences WHERE schemaname = 'public'")
    sequences = src_cur.fetchall()
    for seq_name, start_val in sequences:
        dst_cur.execute(f"CREATE SEQUENCE IF NOT EXISTS {seq_name} START WITH {start_val}")
        print(f"  Sequence: {seq_name}")

    # Get all tables
    src_cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
    tables = [r[0] for r in src_cur.fetchall()]
    print(f"\nTables: {len(tables)}")

    json_columns = set()

    for table in tables:
        src_cur.execute("""
            SELECT column_name, udt_name, character_maximum_length, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
        """, (table,))
        cols = src_cur.fetchall()

        src_cur.execute("""
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
            WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = 'public' AND tc.table_name = %s
        """, (table,))
        pk_cols = [r[0] for r in src_cur.fetchall()]

        col_defs = []
        col_names = []
        for col_name, udt_name, max_len, nullable, default in cols:
            col_names.append(col_name)
            if udt_name == "varchar":
                type_str = f"VARCHAR({max_len})"
            elif udt_name in UDT_MAP:
                type_str = UDT_MAP[udt_name]
            else:
                type_str = udt_name.upper()

            null_str = "" if nullable == "YES" else " NOT NULL"

            if udt_name == "int4" and default and "nextval" in default:
                col_defs.append(f'"{col_name}" SERIAL{null_str}')
            else:
                default_str = f" DEFAULT {default}" if default else ""
                col_defs.append(f'"{col_name}" {type_str}{null_str}{default_str}')

            if udt_name in ("json", "jsonb"):
                json_columns.add((table, col_name))

        if pk_cols:
            pk_str = ", ".join(f'"{c}"' for c in pk_cols)
            col_defs.append(f"PRIMARY KEY ({pk_str})")

        create_sql = f'CREATE TABLE IF NOT EXISTS "{table}" ({", ".join(col_defs)})'
        dst_cur.execute(create_sql)

        src_cur.execute(f'SELECT COUNT(*) FROM "{table}"')
        count = src_cur.fetchone()[0]
        if count > 0:
            col_str = ", ".join(f'"{c}"' for c in col_names)
            placeholders = ", ".join(["%s"] * len(col_names))
            src_cur.execute(f'SELECT * FROM "{table}"')
            rows = src_cur.fetchall()

            processed = []
            for row in rows:
                new_row = []
                for i, val in enumerate(row):
                    if (table, col_names[i]) in json_columns and val is not None:
                        if isinstance(val, (dict, list)):
                            val = json.dumps(val)
                    new_row.append(val)
                processed.append(new_row)

            dst_cur.executemany(f'INSERT INTO "{table}" ({col_str}) VALUES ({placeholders})', processed)

        marker = " <-- migrated" if count > 0 else ""
        print(f"  {table}: {count} rows{marker}")

    # Update sequences
    for seq_name, _ in sequences:
        src_cur.execute("""
            SELECT column_name, table_name
            FROM information_schema.columns
            WHERE column_default LIKE %s
        """, (f"%{seq_name}%",))
        result = src_cur.fetchone()
        if result:
            col, tbl = result
            src_cur.execute(f'SELECT MAX("{col}") FROM "{tbl}"')
            max_val = src_cur.fetchone()[0]
            if max_val:
                dst_cur.execute(f"SELECT setval('{seq_name}', {max_val})")
                print(f"\n  Sequence {seq_name} -> {max_val}")

    print("\nMigration complete!")
    src.close()
    dst.close()


if __name__ == "__main__":
    main()
