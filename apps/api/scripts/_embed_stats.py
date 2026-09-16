from app.core.db import init_db, get_meta_pool, data_dir

init_db()
pool = get_meta_pool()
with pool.connection() as conn, conn.cursor() as cur:
    cur.execute("SELECT COUNT(*) AS n FROM scrap_library_embed")
    print("embed rows", cur.fetchone()["n"])
    cur.execute(
        """
        SELECT COUNT(*) AS n FROM scrap_library_embed
        WHERE COALESCE(source_text,'') LIKE %s
        """,
        ("%女优：%",),
    )
    print("with actress line", cur.fetchone()["n"])
print("facets", data_dir() / "cache" / "facets")
