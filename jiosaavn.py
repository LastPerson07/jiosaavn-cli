"""JioSaavn downloader - interactive terminal client. Requires requests only."""

import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

import requests

API = "https://www.jiosaavn.com/api.php"
SITE = "https://www.jiosaavn.com/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
DOWNLOAD_DIR = Path("downloads")
BITRATES = (320, 160, 96)
SEARCH_LIMIT = 15
COLLECTION_LIMIT = 500
RADIO_COUNT = 20
LANGUAGE = "hindi"
CHUNK = 64 * 1024
ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Referer": SITE,
})


def api(call, **params):
    """Call api.php; raise if the API rejects the request."""
    query = {"__call": call, "api_version": 4, "_format": "json", "_marker": 0,
             "ctx": "web6dot0", **params}
    response = SESSION.get(API, params=query, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and (payload.get("status") == "failure" or "error" in payload):
        error = payload.get("error") or {}
        raise RuntimeError(error.get("msg") or payload.get("msg") or "request rejected by the API")
    return payload


def text(value):
    """Unescape entities and collapse whitespace."""
    return re.sub(r"\s+", " ", html.unescape(str(value or "")).replace("\u200b", "")).strip()


def perma(item):
    """Pull the perma id out of a url - the one webapi.get expects."""
    for key in ("perma_url", "action"):
        value = text(item.get(key))
        if value:
            return value.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
    return text(item.get("id"))


def safe_name(value):
    """Strip characters that are illegal in filenames."""
    return re.sub(r"\s+", " ", ILLEGAL.sub("", value)).strip(" .")[:120] or "track"


def unique_path(path):
    """Append (2), (3) ... instead of overwriting an existing file."""
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
    return path


def clock(seconds):
    return f"{seconds // 60}:{seconds % 60:02d}" if seconds else "--:--"


def entry(title, subtitle, kind, key, song=None, language=None):
    return {"title": title, "subtitle": subtitle, "kind": kind, "key": key,
            "song": song, "language": language}


def card(item, kind):
    """Turn a home-section card into an entry."""
    if kind == "song" or item.get("type") == "song":
        song = parse(item)
        return entry(song["title"], f"{song['artist']}  {clock(song['duration'])}",
                     "song", song["id"], song if song["encrypted_url"] else None)
    subtitle = text(item.get("subtitle")) or (f"{item['follower_count']} followers"
                                              if item.get("follower_count") else "")
    return entry(text(item.get("title") or item.get("name")), subtitle, kind, perma(item))


def parse(item):
    """Flatten a song or episode object into the fields we use."""
    info = item.get("more_info") or {}
    artists = []
    for group in ("primary_artists", "featured_artists"):
        for artist in (info.get("artistMap") or {}).get(group, []):
            name = text(artist.get("name"))
            if name and name not in artists:
                artists.append(name)
    return {
        "id": text(item.get("id")),
        "title": text(item.get("title")),
        "artist": (", ".join(artists)
                   or text(item.get("subtitle")).split(" - ")[0]
                   or text(info.get("show_title"))
                   or "Unknown artist"),
        "duration": int(info.get("duration") or 0),
        "encrypted_url": text(info.get("encrypted_media_url")),
        "hd": str(info.get("320kbps")).lower() == "true",
        "raw": item,
    }


def search(query):
    results = api("search.getResults", q=query, p=1, n=SEARCH_LIMIT).get("results", [])
    return [parse(item) for item in results
            if item.get("type") == "song"
            and (item.get("more_info") or {}).get("encrypted_media_url")]


def trending(entity_type):
    """Home: Trending Now. entity_type is song, album, playlist or artist."""
    items = api("content.getTrending", entity_type=entity_type, entity_language=LANGUAGE)
    return [card(item, entity_type) for item in items or []]


def charts():
    """Home: Top Charts (playlists)."""
    return [card(item, "playlist") for item in api("content.getCharts") or []]


def featured_playlists():
    """Home: Editorial Picks / Top Playlists."""
    data = api("content.getFeaturedPlaylists", fetch_from_serialized_files="true", p=1, n=50)
    return [card(item, "playlist") for item in data.get("data") or []]


def decades():
    """Home: decades and genres from the footer menu."""
    data = api("webapi.getFooterDetails", language=LANGUAGE)
    return [card(item, "playlist") for item in data.get("playlist") or []]


def top_artists():
    """Home: most followed artists."""
    return [card(item, "artist") for item in api("social.getTopArtists").get("top_artists") or []]


def podcasts():
    """Home: Trending Podcasts. Shows have no list endpoint, so read the home page."""
    page = SESSION.get(SITE, timeout=30).text
    entries, seen = [], set()
    for path in re.findall(r'href="(/shows/[^"]+)"', page):
        parts = unquote(path).strip("/").split("/")
        if len(parts) < 2 or path in seen:
            continue
        seen.add(path)
        entries.append(entry(parts[1].replace("-", " ").title(), "podcast", "show", parts[-1]))
    return entries


def radio_stations():
    """Radio: the featured station list."""
    entries = []
    for item in api("webradio.getFeaturedStations") or []:
        subtitle = text(item.get("subtitle"))
        language = (subtitle.split() or [LANGUAGE])[0].lower()
        entries.append(entry(text(item.get("title")), subtitle, "radio_station",
                             text(item.get("id")), language=language))
    return entries


def radio_songs(station):
    """Radio: create a station from a featured name, then pull its current queue."""
    created = api("webradio.createFeaturedStation",
                  language=station.get("language") or LANGUAGE, name=station["key"])
    station_id = (created or {}).get("stationid")
    if not station_id:
        return []
    queue = api("webradio.getSong", stationid=station_id, k=RADIO_COUNT, next=1)
    items = [value.get("song") for value in (queue or {}).values() if isinstance(value, dict)]
    return [parse(item) for item in items
            if item and (item.get("more_info") or {}).get("encrypted_media_url")]


def show_songs(key):
    """Podcast: every episode of a show that carries a playable url."""
    data = api("webapi.get", token=key, type="show", season_number=1, includeMetaTags=0)
    return [parse(episode) for episode in data.get("episodes") or []
            if (episode.get("more_info") or {}).get("encrypted_media_url")]


def fetch_songs(kind, key):
    """Songs behind one entity: a track, playlist, album or artist."""
    if kind == "song":
        for call, param in (("webapi.get", "token"), ("song.getDetails", "pids")):
            params = {param: key, **({"type": "song"} if call == "webapi.get" else {})}
            songs = api(call, **params).get("songs") or []
            if songs:
                return [parse(song) for song in songs]
        return []

    data = api("webapi.get", token=key, type=kind, p=1, n=COLLECTION_LIMIT, includeMetaTags=0)
    items = ((data.get("topSongs") or []) if kind == "artist" else (data.get("list") or []))
    songs, seen = [], set()
    for item in items:
        if item.get("type") not in (None, "song"):
            continue
        if not (item.get("more_info") or {}).get("encrypted_media_url"):
            continue
        song = parse(item)
        if song["id"] not in seen:
            seen.add(song["id"])
            songs.append(song)
    return songs


def kind_of(value):
    """Read the entity type out of a url."""
    for marker, kind in (("/featured/", "playlist"), ("/album/", "album"), ("/artist/", "artist"),
                         ("/shows/", "show"), ("/song/", "song")):
        if marker in value.lower():
            return kind
    return None


def resolve(value):
    """Resolve any link or id - song, playlist, album, artist, show - into songs."""
    key = value.strip().strip("'\"")
    hint = kind_of(key)
    key = key.split("?")[0].rstrip("/").rsplit("/", 1)[-1] if "/" in key else key
    if not key:
        return []
    order = [hint] if hint else []
    order += [k for k in ("song", "playlist", "album", "artist") if k != hint]
    for kind in order:
        try:
            songs = show_songs(key) if kind == "show" else fetch_songs(kind, key)
        except Exception:
            continue
        if songs:
            return songs
    return []


def open_entry(chosen):
    """Turn a picked card into songs."""
    if chosen.get("song"):
        return [chosen["song"]]
    if chosen["kind"] == "radio_station":
        return radio_songs(chosen)
    if chosen["kind"] == "show":
        return show_songs(chosen["key"])
    if chosen["kind"] in ("playlist", "album", "artist", "song"):
        return fetch_songs(chosen["kind"], chosen["key"])
    return []


def signed_url(song, bitrate):
    """Signed CDN url for the requested bitrate, falling back to lower ones."""
    reason = "the API returned no download link for this track"
    for rate in (bitrate, *(rate for rate in BITRATES if rate < bitrate)):
        try:
            payload = api("song.generateAuthToken", url=song["encrypted_url"],
                          bitrate=rate, pid=song["id"])
        except RuntimeError as error:
            reason = str(error)
            continue
        if payload.get("auth_url"):
            return payload["auth_url"]
    raise RuntimeError(reason)


def extension(response):
    """Songs are AAC in an MP4 container, podcast episodes are plain MP3."""
    content_type = (response.headers.get("content-type") or "").lower()
    if "mpeg" in content_type or response.url.split("?")[0].lower().endswith(".mp3"):
        return ".mp3"
    return ".m4a"


def download(song, bitrate, save_meta=False):
    url = signed_url(song, bitrate)
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    with SESSION.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        name = safe_name(song["artist"] + " - " + song["title"])
        path = unique_path(DOWNLOAD_DIR / f"{name}{extension(response)}")
        total = int(response.headers.get("content-length") or 0)
        done = 0
        with open(path, "wb") as handle:
            for chunk in response.iter_content(CHUNK):
                handle.write(chunk)
                done += len(chunk)
                if total:
                    sys.stdout.write(f"\r  {done * 100 // total:3d}%  {done // 1024} KB")
                    sys.stdout.flush()
    print()
    if save_meta:
        meta = path.with_suffix(".json")
        meta.write_text(json.dumps(song["raw"], indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  metadata -> {meta.name}")
    return path


def show(songs):
    print(f"\n  {'#':>3}  {'Title':<40} {'Artist':<28} {'Time':>5}  320")
    print("  " + "-" * 82)
    for index, song in enumerate(songs, 1):
        print(f"  {index:>3}  {song['title'][:40]:<40} {song['artist'][:28]:<28} "
              f"{clock(song['duration']):>5}  {'yes' if song['hd'] else 'no':>3}")


def prompt(question):
    try:
        return input(question)
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(0) from None


def choose(songs):
    """Parse '1', '1,3', '2-4' or 'a' into a list of songs."""
    answer = prompt("  Select: 1 / 1,3 / 2-4 / a=all / Enter=back : ").strip().lower()
    if answer in ("a", "all", "*"):
        return songs
    picked = set()
    for part in answer.replace(" ", "").split(","):
        if "-" in part:
            low, _, high = part.partition("-")
            if low.isdigit() and high.isdigit():
                picked.update(range(int(low), int(high) + 1))
        elif part.isdigit():
            picked.add(int(part))
    return [songs[index - 1] for index in sorted(picked) if 1 <= index <= len(songs)]


def pick(entries):
    """Numbered list of cards; returns the chosen one or None."""
    print(f"\n  {'#':>3}  {'Title':<46} Subtitle")
    print("  " + "-" * 88)
    for index, item in enumerate(entries, 1):
        print(f"  {index:>3}  {item['title'][:46]:<46} {item['subtitle'][:34]}")
    answer = prompt("  Select: number / Enter=back : ").strip()
    if answer.isdigit() and 1 <= int(answer) <= len(entries):
        return entries[int(answer) - 1]
    return None


def fetch(songs):
    """Ask how to download the given songs, then download them."""
    if not songs:
        print("  nothing playable found")
        return
    show(songs)
    picked = choose(songs)
    if not picked:
        return
    if len(picked) > 20:
        if prompt(f"  Download {len(picked)} songs? [y/N]: ").strip().lower() not in ("y", "yes"):
            return
    options = "/".join(str(rate) for rate in BITRATES)
    answer = prompt(f"  Bitrate [{options}] (Enter = 320): ").strip()
    bitrate = int(answer) if answer.isdigit() and int(answer) in BITRATES else 320
    save_meta = prompt("  Also save metadata (.json)? [y/N]: ").strip().lower() in ("y", "yes")
    for song in picked:
        rate = 160 if bitrate == 320 and not song["hd"] else bitrate
        print(f"\n  {song['title']} - {song['artist']} ({rate} kbps)")
        try:
            print(f"  saved -> {download(song, rate, save_meta)}")
        except Exception as error:
            print(f"  skipped: {error}")


HOME_SECTIONS = (
    ("Trending songs", lambda: trending("song")),
    ("Trending albums", lambda: trending("album")),
    ("Top charts", charts),
    ("Featured playlists", featured_playlists),
    ("Decades and genres", decades),
    ("Top artists", top_artists),
    ("Trending podcasts", podcasts),
)


def browse(title, loader):
    print(f"  loading {title.lower()}...")
    try:
        entries = loader()
    except Exception as error:
        print(f"  failed: {error}")
        return
    if not entries:
        print("  nothing found")
        return
    chosen = pick(entries)
    if chosen:
        fetch(open_entry(chosen))


def home_menu():
    while True:
        print()
        for index, (label, _) in enumerate(HOME_SECTIONS, 1):
            print(f"  {index}) {label}")
        print(f"  {len(HOME_SECTIONS) + 1}) Back")
        answer = prompt("  > ").strip()
        if not answer.isdigit():
            continue
        number = int(answer)
        if number == len(HOME_SECTIONS) + 1:
            return
        if 1 <= number <= len(HOME_SECTIONS):
            label, loader = HOME_SECTIONS[number - 1]
            browse(label, loader)


def LastPerson07():
    """Interactive session loop."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("\n  LastPerson07  |  JioSaavn downloader   (files land in ./downloads)")
    while True:
        print("\n  1) Search songs\n  2) Home\n  3) Radio"
              "\n  4) Download from link or id\n  5) Quit")
        choice = prompt("  > ").strip().lower()
        if choice == "1":
            query = prompt("  Search: ").strip()
            if query:
                fetch(search(query))
        elif choice == "2":
            home_menu()
        elif choice == "3":
            browse("radio stations", radio_stations)
        elif choice == "4":
            for value in prompt("  Link(s) or id(s), space separated: ").strip().split():
                songs = resolve(value)
                if songs:
                    fetch(songs)
                else:
                    print(f"  nothing found for {value} (dead link? try searching by name)")
        elif choice in ("5", "q", "quit", "exit"):
            print("  bye\n")
            return
        elif choice:
            print("  unknown option")


if __name__ == "__main__":
    LastPerson07()
