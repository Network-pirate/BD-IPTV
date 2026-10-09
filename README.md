# Custom IPTV Playlist Builder

Generate a single M3U playlist in this order:

1. **Every channel from IPTV-org's Bangladesh country playlist first**.
2. **Your selected favorites next**, in the exact order in `favorites.csv` (except a favorite already present in the Bangladesh section stays there and is not duplicated).
3. **Every remaining entry from IPTV-org's public master playlist**.

The generated M3U gives all entries sequential `tvg-chno` numbers starting from 1. The numbers of favorites are dynamic: they follow the number of Bangladesh entries and the order of favorites. Remaining entries follow afterward. The playlist retains category, logo, stream URL, and other source metadata where present.

The project starts with the favorite channel names discussed so far. This is an initial list, not a complete list; add more rows to `favorites.csv` as needed.

## Data sources

- Master playlist: `https://iptv-org.github.io/iptv/index.m3u`
- Bangladesh country playlist: `https://iptv-org.github.io/iptv/countries/bd.m3u`

The generator uses the Bangladesh playlist to create the first section, preferring the matching master-playlist entry where it can identify the same channel. If a channel appears in the Bangladesh list but not the master list, it is added to the Bangladesh section. Every entry from the master playlist is retained once in the output; favorites are moved, not copied, so a source channel is not intentionally duplicated.

IPTV-org's public playlists choose a best available stream for each channel; its `index.m3u` is not a catalogue of every alternative feed/stream URL. The generator doesn't probe playback or repair broken source URLs. Use streams only when you are authorized to access them.

## How to edit the favorite channel list

Open `favorites.csv`. It has these columns:

- `order`: display order among your favorites. Use 1, 2, 3, and so on.
- `channel_name`: the title or a search phrase for the channel you want.
- `channel_id`: optional, but recommended when a name is ambiguous. Fill in the exact `tvg-id` obtained from the search command below.

The starter file includes the channel names you mentioned so far: Sony, Star Gold, Star Gold 2, Star Jalsha, Star Movies, Star Movies Select, Zee Bangla, Zee Action, Zee Cinema, Nickelodeon, Nickelodeon HD Plus, Nickelodeon Junior, National Geographic, National Geographic Wild, Jalsha Movies, Disney Channel, Disney International, Goldmines Action, Goldmines, Goldmines 2, Goldmines Movies, Goldmines Bollywood, Hungama TV, Cartoon Network, Discovery, Colors Bangla, and Colors Hindi.

Name-only matching succeeds when the name exactly matches an entry title or when it uniquely identifies a title. Generic names such as `Sony`, `Discovery`, or `National Geographic` can be ambiguous because several feeds/channels may match. Ambiguous or missing favorites are listed in `playlist-report.txt`; those channel entries are still preserved in the rest of the playlist, but they're not moved into the favorites section until you disambiguate them with `channel_id`.

### Find an exact ID on Windows

Install Python 3.10+ if needed, extract/clone the project, open PowerShell in the project folder, and run:

```powershell
python playlist_builder.py search "Sony"
python playlist_builder.py search "Star Gold"
python playlist_builder.py search "National Geographic"
```

Copy the correct `tvg-id` into the row's `channel_id` column. If there are several results, choose the exact feed/channel you want. After editing, save the file and commit it to GitHub.

## Set up on GitHub

1. Create a public repository, e.g. `my-iptv-playlist`.
2. Upload all project files and preserve `.github/workflows/update-playlist.yml` exactly.
3. Open **Actions → Update IPTV playlist → Run workflow** to make the first playlist.
4. If the workflow cannot push its generated files, open **Settings → Actions → General → Workflow permissions** and enable **Read and write permissions**.
5. The workflow runs daily at 01:30 UTC, after IPTV-org's daily public-playlist generation. It commits both `playlist.m3u` and `playlist-report.txt` when they change.

Your playlist URL will be:

```text
https://raw.githubusercontent.com/YOUR_GITHUB_USERNAME/YOUR_REPOSITORY/main/playlist.m3u
```

Replace the placeholders and add this M3U URL to Sparkle TV. The repository must remain public for a TV app without GitHub authentication to retrieve it. The URL itself stays the same; Sparkle TV must refresh the playlist to retrieve updated contents.

## Numbering details

- Bangladesh country entries are numbered first, following the order of `countries/bd.m3u` where possible.
- Favorites not already in the Bangladesh section follow, in `favorites.csv` order.
- Remaining master entries follow in source order.
- Channel numbers can shift if IPTV-org adds or removes channels, because the Bangladesh section and favorite section are intentionally dynamic.
- `tvg-chno` is commonly supported but isn't enforced by a universal M3U standard. Sparkle TV's own settings and version determine how it handles explicit numbering.
- No custom count limit is imposed on `favorites.csv`; add as many ordered favorite rows as you like.

## Run locally

```powershell
python -m unittest discover -s tests -v
python playlist_builder.py search "channel name"
python playlist_builder.py build
```

For offline tests against a small fixture, call the Python `make_playlist()` function from tests or use `--source-file` with `--min-entries 1`. To provide both local sources, use `--source-file master.m3u --bangladesh-source-file bangladesh.m3u --min-entries 1`.

## Files

- `playlist_builder.py` — playlist parser, favorite resolution, ordering, numbering, report generation.
- `favorites.csv` — ordered channel names and optional exact `tvg-id` mappings.
- `.github/workflows/update-playlist.yml` — daily and manual GitHub Actions workflow.
- `tests/` — offline tests.
