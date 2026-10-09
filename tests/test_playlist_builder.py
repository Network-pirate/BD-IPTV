import unittest

from playlist_builder import Favorite, build_playlist, parse_m3u

MASTER = '''#EXTM3U x-tvg-url="https://guide.example/epg.xml"
#EXTINF:-1 tvg-id="BanglaOne.bd@SD" group-title="News",Bangla One
https://streams.example/bd-one.m3u8
#EXTINF:-1 tvg-id="BanglaTwo.bd@SD" group-title="General",Bangla Two
https://streams.example/bd-two.m3u8
#EXTINF:-1 tvg-id="in.sony@SD" group-title="Entertainment",Sony (576p)
https://streams.example/sony.m3u8
#EXTINF:-1 tvg-id="in.gold@SD" group-title="Movies",Star Gold (576p)
#EXTVLCOPT:http-user-agent=ExampleAgent
https://streams.example/gold.m3u8
#EXTINF:-1 tvg-id="us.news@SD" group-title="News",World News
https://streams.example/news.m3u8
#EXTINF:-1 tvg-id="uk.talkingpictures@SD" group-title="Undefined",Talking Pictures TV (576p)
https://streams.example/talking.m3u8
#EXTINF:-1 group-title="International",Channel Without ID
https://streams.example/three.m3u8
'''

BANGLADESH = '''#EXTM3U
#EXTINF:-1 tvg-id="BanglaTwo.bd@SD" group-title="General",Bangla Two
https://streams.example/bd-two.m3u8
#EXTINF:-1 tvg-id="in.sony@SD" group-title="Entertainment",Sony (576p)
https://streams.example/sony.m3u8
#EXTINF:-1 tvg-id="BanglaOne.bd@SD" group-title="News",Bangla One
https://streams.example/bd-one.m3u8
#EXTINF:-1 tvg-id="BanglaExtra.bd@SD" group-title="News",Bangla Extra
https://streams.example/bd-extra.m3u8
'''


class PlaylistBuilderTests(unittest.TestCase):
    def test_order_is_bd_origin_then_favorites_then_rest(self):
        favorites = [Favorite(1, "Star Gold"), Favorite(2, "Sony")]
        output, report = build_playlist(MASTER, favorites, BANGLADESH, min_entries=1)
        _, entries = parse_m3u(output)
        self.assertEqual(
            [e.channel_id for e in entries],
            ["BanglaTwo.bd@SD", "BanglaOne.bd@SD", "BanglaExtra.bd@SD", "in.gold@SD", "in.sony@SD",
             "us.news@SD", "uk.talkingpictures@SD", ""],
        )
        self.assertEqual([e.attributes.get("tvg-chno") for e in entries], [str(i) for i in range(1, 9)])
        self.assertIn("#EXTVLCOPT:http-user-agent=ExampleAgent", output)
        self.assertEqual(report["bangladesh_entries"], 3)
        self.assertEqual(report["favorites_placed"], 2)
        self.assertEqual(report["output_entries"], 8)

    def test_indian_channel_in_bd_country_playlist_is_not_promoted_into_bd_section(self):
        output, report = build_playlist(MASTER, [], BANGLADESH, min_entries=1)
        _, entries = parse_m3u(output)
        ids = [e.channel_id for e in entries]
        self.assertEqual(ids[:3], ["BanglaTwo.bd@SD", "BanglaOne.bd@SD", "BanglaExtra.bd@SD"])
        self.assertEqual(report["bangladesh_entries"], 3)
        self.assertIn("in.sony@SD", ids[3:])

    def test_ampersand_pictures_does_not_false_match_talking_pictures_tv(self):
        output, report = build_playlist(MASTER, [Favorite(1, "&pictures")], BANGLADESH, min_entries=1)
        _, entries = parse_m3u(output)
        self.assertEqual(len(entries), 8)
        self.assertEqual(report["favorites_placed"], 0)
        self.assertTrue(any("&pictures" in item for item in report["unresolved"]))
        self.assertTrue(any(e.title.startswith("Talking Pictures TV") for e in entries))

    def test_exact_id_can_select_hd_or_sd_without_collapsing_variants(self):
        master = MASTER + '''#EXTINF:-1 tvg-id="in.gold@HD" group-title="Movies",Star Gold HD (1080p)
https://streams.example/gold-hd.m3u8
'''
        favorites = [Favorite(1, "Star Gold", "in.gold@SD"), Favorite(2, "Star Gold HD", "in.gold@HD")]
        output, report = build_playlist(master, favorites, BANGLADESH, min_entries=1)
        _, entries = parse_m3u(output)
        selected = [e.channel_id for e in entries if e.channel_id.startswith("in.gold")]
        self.assertEqual(selected, ["in.gold@SD", "in.gold@HD"])
        self.assertEqual(report["favorites_placed"], 2)

    def test_ambiguous_exact_title_is_reported_and_not_guessed(self):
        master = MASTER + '''#EXTINF:-1 tvg-id="in.sony2@HD" group-title="Entertainment",Sony (1080p)
https://streams.example/sony-hd.m3u8
'''
        output, report = build_playlist(master, [Favorite(1, "Sony")], BANGLADESH, min_entries=1)
        _, entries = parse_m3u(output)
        self.assertEqual(len(entries), 9)
        self.assertEqual(report["favorites_placed"], 0)
        self.assertTrue(any("ambiguous exact title" in item for item in report["unresolved"]))

    def test_missing_id_favorite_can_be_retained_from_previous_playlist(self):
        previous, _ = build_playlist(MASTER, [Favorite(1, "Star Gold", "in.gold@SD")], BANGLADESH, min_entries=1)
        changed_master = '''#EXTM3U
#EXTINF:-1 tvg-id="BanglaOne.bd@SD",Bangla One
https://streams.example/bd-one.m3u8
'''
        changed_bd = '''#EXTM3U
#EXTINF:-1 tvg-id="BanglaOne.bd@SD",Bangla One
https://streams.example/bd-one.m3u8
'''
        output, report = build_playlist(
            changed_master, [Favorite(1, "Star Gold", "in.gold@SD")], changed_bd,
            previous_text=previous, min_entries=1,
        )
        _, entries = parse_m3u(output)
        self.assertIn("in.gold@SD", [e.channel_id for e in entries])
        self.assertEqual(report["stale_kept"], 1)

    def test_minimum_entry_guard(self):
        with self.assertRaisesRegex(ValueError, "Safety check"):
            build_playlist(MASTER, [], BANGLADESH, min_entries=100)


if __name__ == "__main__":
    unittest.main()
