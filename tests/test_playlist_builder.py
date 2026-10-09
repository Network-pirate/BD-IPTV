import unittest

from playlist_builder import Favorite, make_playlist, parse_m3u

MASTER = '''#EXTM3U x-tvg-url="https://guide.example/epg.xml"
#EXTINF:-1 tvg-id="bd.one" group-title="News",Bangla One
https://streams.example/one.m3u8
#EXTINF:-1 tvg-id="bd.two" group-title="General",Bangla Two
https://streams.example/two.m3u8
#EXTINF:-1 tvg-id="in.sony" group-title="Entertainment",Sony Entertainment
https://streams.example/sony.m3u8
#EXTINF:-1 tvg-id="in.gold" group-title="Movies" tvg-chno="999",Star Gold
#EXTVLCOPT:http-user-agent=ExampleAgent
https://streams.example/gold.m3u8
#EXTINF:-1 tvg-id="us.news" group-title="News",World News
https://streams.example/news.m3u8
#EXTINF:-1 group-title="International",Channel Without ID
https://streams.example/three.m3u8
'''

BANGLADESH = '''#EXTM3U
#EXTINF:-1 tvg-id="bd.two" group-title="General",Bangla Two
https://streams.example/two.m3u8
#EXTINF:-1 tvg-id="bd.one" group-title="News",Bangla One
https://streams.example/one.m3u8
'''


class PlaylistBuilderTests(unittest.TestCase):
    def test_order_is_bangladesh_then_favorites_then_rest_and_keeps_all_master_entries(self):
        favorites = [Favorite(1, "Star Gold"), Favorite(2, "Sony Entertainment")]
        output, report = make_playlist(MASTER, favorites, BANGLADESH, min_entries=1)
        _, entries = parse_m3u(output)
        self.assertEqual(len(entries), 6)
        self.assertEqual(
            [e.channel_id for e in entries],
            ["bd.two", "bd.one", "in.gold", "in.sony", "us.news", ""],
        )
        self.assertEqual([e.attributes.get("tvg-chno") for e in entries], ["1", "2", "3", "4", "5", "6"])
        self.assertIn("#EXTVLCOPT:http-user-agent=ExampleAgent", output)
        self.assertEqual(report["bangladesh_entries"], 2)
        self.assertEqual(report["resolved_favorites"], 2)
        self.assertEqual(report["output_entries"], 6)

    def test_favorite_that_is_already_in_bangladesh_is_not_duplicated(self):
        output, report = make_playlist(
            MASTER, [Favorite(1, "Bangla One")], BANGLADESH, min_entries=1
        )
        _, entries = parse_m3u(output)
        self.assertEqual(len(entries), 6)
        self.assertEqual([e.channel_id for e in entries[:2]], ["bd.two", "bd.one"])
        self.assertEqual(report["resolved_favorites"], 0)
        self.assertEqual(len(report["already_in_bangladesh"]), 1)

    def test_ambiguous_favorite_does_not_remove_any_source_entry(self):
        source = MASTER.replace(
            '#EXTINF:-1 tvg-id="in.sony" group-title="Entertainment",Sony Entertainment',
            '#EXTINF:-1 tvg-id="in.sony" group-title="Entertainment",Sony Entertainment'
        ) + '#EXTINF:-1 tvg-id="in.sony2" group-title="Entertainment",Sony Movies\nhttps://streams.example/sony2.m3u8\n'
        output, report = make_playlist(source, [Favorite(1, "Sony")], BANGLADESH, min_entries=1)
        _, entries = parse_m3u(output)
        self.assertEqual(len(entries), 7)
        self.assertEqual(len(report["unresolved_favorites"]), 1)

    def test_extra_bangladesh_entry_missing_from_master_is_preserved(self):
        bd = BANGLADESH + '#EXTINF:-1 tvg-id="bd.extra" group-title="News",Bangla Extra\nhttps://streams.example/extra.m3u8\n'
        output, report = make_playlist(MASTER, [], bd, min_entries=1)
        _, entries = parse_m3u(output)
        self.assertEqual(len(entries), 7)
        self.assertEqual(entries[2].channel_id, "bd.extra")
        self.assertEqual(report["bangladesh_entries"], 3)

    def test_missing_favorite_can_be_kept_from_previous_generated_playlist(self):
        previous, _ = make_playlist(MASTER, [Favorite(1, "Star Gold")], BANGLADESH, min_entries=1)
        new_source = '''#EXTM3U\n#EXTINF:-1 tvg-id="bd.one" group-title="News",Bangla One\nhttps://streams.example/one.m3u8\n'''
        output, report = make_playlist(
            new_source, [Favorite(1, "Star Gold", "in.gold")],
            '#EXTM3U\n#EXTINF:-1 tvg-id="bd.one" group-title="News",Bangla One\nhttps://streams.example/one.m3u8\n',
            previous_text=previous, min_entries=1
        )
        _, entries = parse_m3u(output)
        self.assertIn("in.gold", [e.channel_id for e in entries])
        self.assertEqual(report["stale_fallbacks"], 1)

    def test_minimum_entry_guard(self):
        with self.assertRaisesRegex(ValueError, "Safety check failed"):
            make_playlist(MASTER, [], BANGLADESH, min_entries=100)


if __name__ == "__main__":
    unittest.main()
