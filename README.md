# jiosaavn-cli

Unofficial JioSaavn client for the terminal. Search songs, browse the home charts, play with radio stations, grab podcast episodes, and download them.

Single file, one dependency (`requests`). It's menu-driven, so there are no flags to remember.

```
  LastPerson07  |  JioSaavn downloader   (files land in ./downloads)

  1) Search songs
  2) Home
  3) Radio
  4) Download from link or id
  5) Quit
  >
```

## Usage

```
pip install -r requirements.txt
python jiosaavn.py
```

Needs Python 3.8+.

### Search

Type a query and you get a numbered table. Pick results with `1`, `1,3`, `2-4`, or `a` for all.

```
  #  Title                                    Artist                        Time  320
  ----------------------------------------------------------------------------------
  1  Tum Hi Ho                                Mithoon, Arijit Singh         4:22  yes
  2  Tum Hi Ho Bandhu                         Pritam, Neeraj Shridhar, Kav  4:43  yes
```

### Home

Mirrors the sections on the site's home page (Hindi by default; change `LANGUAGE` at the top of the file to switch).

```
  1) Trending songs
  2) Trending albums
  3) Top charts
  4) Featured playlists
  5) Decades and genres
  6) Top artists
  7) Trending podcasts
  8) Back
```

### Radio

Lists the featured stations. Pick one and it fetches the current queue.

### Links and ids

Paste any song, playlist, album, artist or `/shows/` link, or a bare id. Separate multiple entries with spaces. Anything that can't be resolved prints `nothing found` and the rest carry on.

Before each download it asks for a bitrate (320 / 160 / 96, default 320) and whether to save the metadata JSON.

## Output

```
downloads/
  Artist - Title.m4a        AAC at 320 / 160 / 96 kbps
  Show - Episode.mp3        podcast episodes are MP3
  Artist - Title.json       optional, raw song object from the API
```

Existing files are never overwritten. Downloading the same track again gives you `Title (2).m4a`. If a track has no 320 kbps version, it falls back to 160.

## How it works

Everything goes through `https://www.jiosaavn.com/api.php`. The calls below were captured from the site's own traffic and checked with plain requests.

| What | Call |
| --- | --- |
| Search | `search.getResults&q=` |
| Song | `song.getDetails&pids=` (8-char id) or `webapi.get&token=&type=song` (perma id) |
| Playlist / album / artist | `webapi.get&token=&type=playlist`, `album` or `artist` |
| Show (podcast) | `webapi.get&token=&type=show&season_number=1` |
| Home | `content.getTrending`, `content.getCharts`, `content.getFeaturedPlaylists`, `webapi.getFooterDetails`, `social.getTopArtists` |
| Radio | `webradio.getFeaturedStations`, `webradio.createFeaturedStation`, `webradio.getSong` |
| Download URL | `song.generateAuthToken&url=&bitrate=&pid=` returns a signed CDN URL |

There are two id formats and each endpoint only accepts one, so the tool tries both. The old DES decryption for media URLs isn't needed anymore, since the API hands back a signed CDN path.

Headless browsers get a `403 Access Denied` from the site's edge, but plain HTTP clients go through fine. That's why there's no browser involved here.

## Disclaimer

Not affiliated with JioSaavn. Meant for personal and educational use. Downloading copyrighted music may violate their terms of service and your local law. You get no rights to any content you download with this.

## License

MIT
