"""嵌入文本拼装：主语义用标题/影片名，文件名只补番号。"""

from __future__ import annotations

from app.sehua_embed import (
    build_embed_text,
    content_sha,
    display_hit_label,
    normalize_filename,
)


def test_normalize_filename():
    assert normalize_filename("SONE-123.mp4") == "SONE-123"
    assert normalize_filename("foo%20bar.mkv") == "foo bar"


def test_prefers_film_and_skips_duplicate_resource():
    text = build_embed_text(
        board_name="亚洲有码原创",
        title="【HD】SONE-123 被寝取的人妻 4K",
        description="【影片名称】：被寝取的人妻\n【资源名称】：被寝取的人妻\n【出演女优】：三上悠亜",
        filename="SONE-123.mp4",
    )
    assert "板块：亚洲有码原创" in text
    assert "影片：被寝取的人妻" in text or "标题：" in text
    assert text.count("被寝取的人妻") >= 1
    assert "资源：被寝取的人妻" not in text
    assert "女优：三上悠亜" in text
    assert "文件：SONE-123" in text


def test_resource_kept_when_different_from_film():
    text = build_embed_text(
        board_name="有码中字",
        title="合集更新帖",
        description="【影片名称】：人妻NTR\n【资源名称】：JUR-024-UC",
        filename="JUR-024.mp4",
    )
    assert "影片：人妻NTR" in text
    assert "资源：JUR-024-UC" in text


def test_filename_only_still_embeds():
    text = build_embed_text(
        board_name="",
        title="",
        description="",
        filename="IPZZ-001.mp4",
    )
    assert "IPZZ-001" in text


def test_content_sha_stable():
    a = content_sha("标题：foo")
    b = content_sha("标题：foo")
    c = content_sha("标题：bar")
    assert a == b
    assert a != c


def test_display_hit_prefers_film_over_discuz():
    label = display_hit_label(
        title="336KNB-070 全国人妻 - 亚洲有码原创 - 98堂[原色花堂] - Powered by Discuz!",
        description="【影片名称】：全国人妻えろ図鑑 人妻全国募集",
        filename="336KNB-070.mp4",
    )
    assert "Discuz" not in label
    assert "98堂" not in label
    assert "全国人妻" in label
    assert "KNB-070" in label


def test_compact_hits_strips_discuz():
    from app.ai_chat_routes import compact_hits

    rows = compact_hits(
        [
            {
                "title": "亚洲有码原创 - 98堂[原色花堂] - Powered by Discuz!",
                "description": "【影片名称】：全国人妻えろ図鑑",
                "name": "336KNB-070.mp4",
                "board_name": "亚洲有码原创",
                "score": 0.581,
            }
        ]
    )
    assert rows[0]["n"] == 1
    assert "Discuz" not in rows[0]["title"]
    assert "全国人妻" in rows[0]["title"]
    assert rows[0]["score"] == 0.58


def test_discuz_chrome_title_dropped():
    text = build_embed_text(
        board_name="亚洲有码原创",
        title="亚洲有码原创 - 98堂[原色花堂] - Powered by Discuz!",
        description="【影片名称】：madm-120 寝取られ人妻",
        filename="madm-120.mp4",
    )
    assert "Powered by Discuz" not in text
    assert "影片：madm-120 寝取られ人妻" in text


if __name__ == "__main__":
    test_normalize_filename()
    test_prefers_film_and_skips_duplicate_resource()
    test_resource_kept_when_different_from_film()
    test_filename_only_still_embeds()
    test_content_sha_stable()
    test_display_hit_prefers_film_over_discuz()
    test_compact_hits_strips_discuz()
    test_discuz_chrome_title_dropped()
    print("ok")
