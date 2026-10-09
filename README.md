# 🇧🇩 BD-IPTV — Custom IPTV Playlist Builder

An automatically updated, customized M3U playlist generated from IPTV-org's public playlist data.

BD-IPTV organizes channels into three sections:

1. **Bangladesh-origin channels** — placed first.
2. **Your favorite channels** — placed next, in the order configured in `favorites.csv`.
3. **All remaining channels** — retained from IPTV-org's master playlist.

The playlist is regenerated automatically using GitHub Actions. Your published playlist URL remains the same while the generated file is updated.

## 📺 Your IPTV Playlist

**Main playlist:**

https://raw.githubusercontent.com/Network-pirate/BD-IPTV/main/playlist.m3u

**Favorite channel configuration:**

https://github.com/Network-pirate/BD-IPTV/blob/main/favorites.csv

**Latest generation report:**

https://github.com/Network-pirate/BD-IPTV/blob/main/playlist-report.txt

Add the main playlist URL to Sparkle TV or another IPTV player that supports remote M3U playlists.

The repository must remain publicly accessible for players that cannot authenticate with GitHub.

## ⚙️ How It Works

BD-IPTV downloads two source playlists maintained by IPTV-org.

| Source                       | Purpose                                            |
| ---------------------------- | -------------------------------------------------- |
| IPTV-org master playlist     | Provides the main collection of channel entries    |
| IPTV-org Bangladesh playlist | Helps identify and organize the Bangladesh section |

Source playlists:

* Master playlist: https://iptv-org.github.io/iptv/index.m3u
* Bangladesh playlist: https://iptv-org.github.io/iptv/countries/bd.m3u
* IPTV-org repository: https://github.com/iptv-org/iptv

The generator processes the available data and produces a single M3U playlist.

### Playlist ordering

The generated playlist follows this structure:

**Section 1: Bangladesh-origin channels**

Channels identified as Bangladesh-origin through their IPTV-org channel IDs are placed first. The Bangladesh country playlist also helps order these entries and can supply eligible entries that are missing from the master playlist.

**Section 2: Your favorites**

The generator reads `favorites.csv` and attempts to find each selected channel. Successfully matched favorites are placed after the Bangladesh section in the order specified by the configuration.

If a favorite is already included in the Bangladesh section, it remains there instead of being duplicated in the favorites section.

**Section 3: All remaining channels**

The remaining master-playlist entries follow the favorites section in their original source order.

The generator is designed to retain all master-playlist entries rather than filtering out channels simply because they are not favorites.

The final playlist assigns sequential `tvg-chno` values to its entries, starting at 1.

## ⭐ Managing Your Favorite Channels

The `favorites.csv` file controls your custom channel lineup.

It uses three columns:

```csv
order,channel_name,channel_id
1,Sony Aath,
2,Star Jalsha,
3,Star Jalsha HD,
4,Zee Bangla,
5,Zee Bangla HD,
```

These are illustrative rows. Your actual configuration is stored in `favorites.csv`.

### Column descriptions

| Column         | Purpose                                                 |
| -------------- | ------------------------------------------------------- |
| `order`        | Determines the order among your selected favorites      |
| `channel_name` | The channel name used when matching the source playlist |
| `channel_id`   | The exact IPTV-org `tvg-id`, when known                 |

You can add, remove, or reorder favorites by editing this file.

There is no fixed limit of 100 favorite entries. You can configure as many as you need.

### How channel numbers are assigned

Suppose the generated Bangladesh section contains 26 entries.

If the next three favorites are successfully matched, they would normally appear at positions 27, 28, and 29, subject to any favorite already included in the Bangladesh section.

If the number of Bangladesh entries changes during a later update, the positions of your favorites can change accordingly.

The order configured in `favorites.csv` controls the ordering of successfully matched favorites, not their permanent numerical positions in the complete playlist.

## 🔎 Finding Channel IDs

Some channels have multiple feeds or similar names.

For example, a broadcaster might have separate SD and HD feeds, or different regional versions. The generator avoids selecting an arbitrary channel simply because its name contains a similar phrase.

When a name cannot be matched confidently, the generator reports it in `playlist-report.txt`.

To find the correct ID, run the search command from PowerShell in the project directory:

```powershell
python playlist_builder.py search "Star Plus"
```

Other examples:

```powershell
python playlist_builder.py search "Sony Max"
python playlist_builder.py search "National Geographic"
python playlist_builder.py search "Cartoon Network"
python playlist_builder.py search "Disney Channel"
```

The command searches IPTV-org's master playlist and displays matching channel names and their `tvg-id` values.

Choose the exact feed you want and copy its ID into the appropriate row in `favorites.csv`.

For example:

```csv
order,channel_name,channel_id
7,Star Plus,PASTE_THE_EXACT_TVG_ID_HERE
```

Replace the placeholder with the actual ID. Never leave the placeholder in the file.

When an exact ID is provided, the generator uses it to identify the intended entry. Without an ID, it attempts an exact normalized title match, ignoring supported resolution and status annotations.

It does not use arbitrary partial-name matching to assign a favorite.

## ⚠️ Understanding Unresolved Favorites

After a build, open `playlist-report.txt`.

The report identifies:

* The number of master-playlist entries.
* The number of Bangladesh-origin entries.
* The number of successfully placed favorites.
* The number of remaining entries.
* Favorites already present in the Bangladesh section.
* Unresolved or ambiguous favorites.
* Entries retained from a previous playlist because an exact-ID favorite disappeared from the current source.

An unresolved favorite is not automatically added to the custom favorites section.

If a matching channel entry exists in the master playlist, it can remain in the remaining channels section. If the channel is unavailable in all configured source data, the generator cannot add it automatically.

If a favorite with an exact configured ID was present in the previous generated playlist but disappears from the current source, the generator can retain the previous entry as a fallback. Its streaming URL may be outdated.

A successful channel match does not guarantee successful playback. A stream may be unavailable, geographically restricted, discontinued, or incompatible with the player.

## 🔄 Automatic Updates

The project uses GitHub Actions to generate the playlist automatically.

Workflow:

`.github/workflows/update-playlist.yml`

The workflow is scheduled to run every day at **01:30 UTC**, which corresponds to **07:30 Bangladesh Standard Time (UTC+6)**.

The process is:

1. GitHub Actions checks out the repository.
2. Python is configured.
3. The automated tests run.
4. The latest source playlists are downloaded.
5. The generator reads `favorites.csv`.
6. `playlist.m3u` and `playlist-report.txt` are generated.
7. GitHub commits the generated files if their contents have changed.

GitHub Actions may start a scheduled workflow later than its configured time. Successful completion is also dependent on the availability of GitHub Actions and the upstream source data.

### Do I need to run the workflow manually?

Not for normal daily updates.

GitHub Actions runs the workflow automatically according to its schedule.

However, if you edit `favorites.csv` and want the changes applied immediately, commit your changes and run the workflow manually.

To do that:

1. Open the repository on GitHub.
2. Select **Actions**.
3. Select **Update IPTV playlist**.
4. Click **Run workflow**.
5. Select the appropriate branch and start the run.
6. Wait for the workflow to finish successfully.

### What happens if nothing changes?

The workflow still runs, but if the generated playlist and report have not changed, it skips the unnecessary Git commit.

## 📱 Using the Playlist in Sparkle TV

Use this URL:

```text
https://raw.githubusercontent.com/Network-pirate/BD-IPTV/main/playlist.m3u
```

Add it to Sparkle TV as an M3U playlist source.

The URL remains the same as long as the repository, branch, and file path stay unchanged.

When GitHub updates the generated file, Sparkle TV can retrieve the updated contents when it refreshes the source.

**Important:** Updating the playlist in GitHub does not guarantee that Sparkle TV reloads it immediately. The app may need to refresh its source.

If you import a downloaded M3U file instead of using the remote URL, that local copy will not update automatically. You must download the new file again.

## 🛠️ Running the Project Locally

Python 3.10 or newer is recommended.

The generator uses Python's standard library and does not require a separate package installation.

Open PowerShell in the project directory.

### Run the tests

```powershell
python -m unittest discover -s tests -v
```

### Search the channel source

```powershell
python playlist_builder.py search "Star Plus"
```

### Generate the playlist

```powershell
python playlist_builder.py build
```

The generator writes:

* `playlist.m3u`
* `playlist-report.txt`

The generated files are committed to the repository by GitHub Actions when their contents change.

## 🧪 Safety and Data Preservation

The generator includes checks to help avoid publishing an invalid playlist if the source data is incomplete or malformed.

It validates the master playlist structure and checks that the master contains a minimum expected number of entries before writing output.

The generator also preserves source entry blocks and uses temporary files when writing output.

These safeguards reduce the risk of replacing a valid playlist with an empty or obviously incomplete one. They cannot guarantee that an upstream playlist is complete or that every stream works.

The generator does not test stream playback or repair unavailable URLs.

IPTV-org's master playlist represents its chosen stream entry for each channel. It does not necessarily include every alternative feed or stream available elsewhere.

Only use streaming links you are authorized to access.

## 📂 Project Structure

```text
BD-IPTV/
│
├── playlist_builder.py
├── favorites.csv
├── playlist.m3u
├── playlist-report.txt
├── README.md
│
├── tests/
│
└── .github/
    └── workflows/
        └── update-playlist.yml
```

| File                                    | Description                                                         |
| --------------------------------------- | ------------------------------------------------------------------- |
| `playlist_builder.py`                   | Downloads, matches, orders, numbers, and generates playlist entries |
| `favorites.csv`                         | Stores the ordered list of selected favorite channels               |
| `playlist.m3u`                          | Generated playlist for IPTV players                                 |
| `playlist-report.txt`                   | Latest build statistics and favorite-matching results               |
| `tests/`                                | Automated tests executed by the workflow                            |
| `.github/workflows/update-playlist.yml` | Daily and manual playlist-generation workflow                       |
| `README.md`                             | Project documentation                                               |

## 📌 Important Notes

* The Bangladesh section is based on available channel-origin IDs and eligible entries from the Bangladesh country playlist.
* Favorites are matched using exact channel IDs or supported exact normalized title matching.
* Favorite positions are dynamic because the number of Bangladesh entries may change.
* Unresolved favorites are reported rather than guessed.
* The remaining master-playlist entries are retained in the generated output.
* Source changes can cause channels to appear, disappear, or move.
* Stream availability is not guaranteed.
* The public playlist URL stays the same while the generated file is updated.

---

**Project repository:**
https://github.com/Network-pirate/BD-IPTV

**Generated playlist:**
https://raw.githubusercontent.com/Network-pirate/BD-IPTV/main/playlist.m3u
