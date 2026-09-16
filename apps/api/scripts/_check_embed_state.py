from app.core.db import init_db, get_meta_pool
from app.scrap_library import embed as e

init_db()
pool = get_meta_pool()
with pool.connection() as conn, conn.cursor() as cur:
    cur.execute(f"SELECT count(*) AS n FROM {e.TABLE}")
    print("total", cur.fetchone()["n"])
    cur.execute(
        f"SELECT count(*) AS n FROM {e.TABLE} WHERE content_sha LIKE %s",
        (f"{e.SKELETON_SHA_PREFIX}:%",),
    )
    print("skeletons", cur.fetchone()["n"])
    cur.execute(
        f"SELECT count(*) AS n FROM {e.TABLE} WHERE COALESCE(source_text,'') LIKE %s",
        ("%女优：%",),
    )
    print("with actress", cur.fetchone()["n"])
