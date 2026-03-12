import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from flask import Flask, render_template, jsonify, request as flask_request
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

GENIUS_TOKEN = os.getenv("GENIUS_ACCESS_TOKEN", "")
GENIUS_BASE = "https://api.genius.com"
MB_BASE = "https://musicbrainz.org/ws/2"
MB_USER_AGENT = "LyricsAtlas/1.0 (https://github.com/lyricsatlas)"

_mb_cache = {}
_mb_lock = threading.Lock()
_mb_last_request_time = 0

_country_artists_cache = {}
_recording_cache = {}

COUNTRIES = [
    {"code": "", "name": "Select country..."},
    {"code": "NG", "name": "Nigeria"},
    {"code": "US", "name": "United States"},
    {"code": "GB", "name": "United Kingdom"},
    {"code": "GH", "name": "Ghana"},
    {"code": "ZA", "name": "South Africa"},
    {"code": "KE", "name": "Kenya"},
    {"code": "TZ", "name": "Tanzania"},
    {"code": "CA", "name": "Canada"},
    {"code": "JM", "name": "Jamaica"},
    {"code": "AU", "name": "Australia"},
    {"code": "FR", "name": "France"},
    {"code": "DE", "name": "Germany"},
    {"code": "BR", "name": "Brazil"},
    {"code": "CO", "name": "Colombia"},
    {"code": "MX", "name": "Mexico"},
    {"code": "JP", "name": "Japan"},
    {"code": "KR", "name": "South Korea"},
    {"code": "IN", "name": "India"},
    {"code": "SE", "name": "Sweden"},
    {"code": "IT", "name": "Italy"},
    {"code": "ES", "name": "Spain"},
    {"code": "PT", "name": "Portugal"},
    {"code": "TR", "name": "Turkey"},
    {"code": "EG", "name": "Egypt"},
    {"code": "MA", "name": "Morocco"},
    {"code": "SN", "name": "Senegal"},
    {"code": "CM", "name": "Cameroon"},
    {"code": "CI", "name": "Ivory Coast"},
    {"code": "CD", "name": "DR Congo"},
    {"code": "ET", "name": "Ethiopia"},
    {"code": "UG", "name": "Uganda"},
    {"code": "RW", "name": "Rwanda"},
    {"code": "BJ", "name": "Benin"},
    {"code": "ML", "name": "Mali"},
    {"code": "NE", "name": "Niger"},
    {"code": "PH", "name": "Philippines"},
    {"code": "ID", "name": "Indonesia"},
    {"code": "TH", "name": "Thailand"},
    {"code": "VN", "name": "Vietnam"},
    {"code": "CN", "name": "China"},
    {"code": "RU", "name": "Russia"},
    {"code": "PL", "name": "Poland"},
    {"code": "NL", "name": "Netherlands"},
    {"code": "BE", "name": "Belgium"},
    {"code": "AT", "name": "Austria"},
    {"code": "CH", "name": "Switzerland"},
    {"code": "IE", "name": "Ireland"},
    {"code": "NZ", "name": "New Zealand"},
    {"code": "AR", "name": "Argentina"},
    {"code": "CL", "name": "Chile"},
    {"code": "PE", "name": "Peru"},
    {"code": "CU", "name": "Cuba"},
    {"code": "PR", "name": "Puerto Rico"},
    {"code": "TT", "name": "Trinidad and Tobago"},
]

COUNTRY_BY_CODE = {c["code"]: c["name"] for c in COUNTRIES if c["code"]}

GENRES = [
    "Afrobeat", "Afropop", "Alternative", "Amapiano", "Blues",
    "Classical", "Country", "Dance", "Dancehall", "Disco",
    "Drill", "Electronic", "Folk", "Funk", "Gospel", "Grime",
    "Highlife", "Hip Hop", "House", "Indie", "Jazz", "K-Pop",
    "Latin", "Metal", "Pop", "Punk", "R&B", "Rap", "Reggae",
    "Reggaeton", "Rock", "Soul", "Techno", "Trap",
]


# ── Genius API ───────────────────────────────────────────────────────────────

def _genius_headers():
    return {"Authorization": f"Bearer {GENIUS_TOKEN}"}


def genius_search(query, per_page=20, page=1):
    try:
        resp = requests.get(
            f"{GENIUS_BASE}/search",
            headers=_genius_headers(),
            params={"q": query, "per_page": per_page, "page": page},
            timeout=12,
        )
        resp.raise_for_status()
        return resp.json().get("response", {}).get("hits", [])
    except requests.RequestException:
        return []


def _extract_songs(hits, seen_urls):
    songs = []
    for hit in hits:
        if hit.get("type") != "song":
            continue
        song = hit.get("result", {})
        url = song.get("url", "")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        artist = song.get("primary_artist") or {}
        songs.append({
            "track_name": song.get("title", ""),
            "artist_name": artist.get("name", "Unknown"),
            "artist_image": artist.get("image_url", ""),
            "album_art": song.get("song_art_image_thumbnail_url", ""),
            "genius_url": url,
            "release_date": song.get("release_date_for_display", ""),
        })
    return songs


# ── MusicBrainz ──────────────────────────────────────────────────────────────

def _mb_rate_limit():
    global _mb_last_request_time
    with _mb_lock:
        now = time.time()
        wait = 1.05 - (now - _mb_last_request_time)
        if wait > 0:
            time.sleep(wait)
        _mb_last_request_time = time.time()


def mb_artist_lookup(artist_name):
    key = artist_name.strip().lower()
    with _mb_lock:
        if key in _mb_cache:
            return _mb_cache[key]

    _mb_rate_limit()

    empty = {"country_code": "", "country_name": "", "genres": []}
    try:
        resp = requests.get(
            f"{MB_BASE}/artist/",
            headers={"User-Agent": MB_USER_AGENT, "Accept": "application/json"},
            params={"query": f'artist:"{artist_name}"', "fmt": "json", "limit": 1},
            timeout=10,
        )
        resp.raise_for_status()
        artists = resp.json().get("artists", [])
        if not artists:
            with _mb_lock:
                _mb_cache[key] = empty
            return empty

        a = artists[0]
        result = _parse_mb_artist(a)
        with _mb_lock:
            _mb_cache[key] = result
        return result

    except requests.RequestException:
        with _mb_lock:
            _mb_cache[key] = empty
        return empty


def _parse_mb_artist(a):
    country_code = (a.get("country") or "").upper()
    area = a.get("area") or {}
    country_name = area.get("name", "")
    tags = [t["name"] for t in (a.get("tags") or []) if t.get("count", 0) >= 0]
    return {"country_code": country_code, "country_name": country_name, "genres": tags}


def get_artists_from_country(country_code, limit=100):
    """Fetch top artists from a country via MusicBrainz (cached)."""
    if country_code in _country_artists_cache:
        return _country_artists_cache[country_code]

    _mb_rate_limit()

    try:
        resp = requests.get(
            f"{MB_BASE}/artist/",
            headers={"User-Agent": MB_USER_AGENT, "Accept": "application/json"},
            params={"query": f"country:{country_code}", "fmt": "json", "limit": limit},
            timeout=15,
        )
        resp.raise_for_status()
        artists = resp.json().get("artists", [])

        result = []
        for a in artists:
            name = a.get("name", "").strip()
            if not name:
                continue
            info = _parse_mb_artist(a)
            result.append(name)
            with _mb_lock:
                _mb_cache[name.lower()] = info

        _country_artists_cache[country_code] = result
        return result

    except requests.RequestException:
        return []


def mb_recording_search(query, limit=100):
    """Search MusicBrainz for recordings (songs) with query in the title."""
    cache_key = query.lower().strip()
    if cache_key in _recording_cache:
        return _recording_cache[cache_key]

    _mb_rate_limit()

    try:
        resp = requests.get(
            f"{MB_BASE}/recording/",
            headers={"User-Agent": MB_USER_AGENT, "Accept": "application/json"},
            params={"query": f'recording:{query}', "fmt": "json", "limit": limit},
            timeout=15,
        )
        resp.raise_for_status()
        recordings = resp.json().get("recordings", [])
        _recording_cache[cache_key] = recordings
        return recordings
    except requests.RequestException:
        return []


def _genre_matches(artist_genres, genre_filter):
    gf = genre_filter.lower().replace("-", " ").replace("_", " ")
    for g in artist_genres:
        gl = g.lower().replace("-", " ").replace("_", " ")
        if gf in gl or gl in gf:
            return True
    return False


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/countries")
def countries():
    return jsonify(COUNTRIES)


@app.route("/api/genres")
def genres():
    return jsonify([{"name": g} for g in GENRES])


@app.route("/api/search")
def search():
    query = flask_request.args.get("q", "").strip()
    country_code = flask_request.args.get("country", "").strip().upper()
    genre_filter = flask_request.args.get("genre", "").strip()

    if not query:
        return jsonify({"tracks": [], "error": "Please enter lyrics keywords to search."})

    if not GENIUS_TOKEN:
        return jsonify({
            "tracks": [],
            "error": (
                "Genius API token not configured. "
                "Get a free token at genius.com/api-clients and add "
                "GENIUS_ACCESS_TOKEN to your .env file."
            ),
        })

    has_filters = bool(country_code or genre_filter)

    if not has_filters:
        seen = set()
        all_songs = []

        def _fetch_page(page):
            return genius_search(query, per_page=25, page=page)

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(_fetch_page, p): p for p in range(1, 5)}
            page_results = {}
            for future in as_completed(futures):
                page = futures[future]
                try:
                    page_results[page] = future.result()
                except Exception:
                    page_results[page] = []
            for p in sorted(page_results):
                all_songs.extend(_extract_songs(page_results[p], seen))

        return jsonify({"tracks": all_songs, "total": len(all_songs), "filtered": False})

    # ── Filtered search ────────────────────────────────────────────────

    country_name = COUNTRY_BY_CODE.get(country_code, "")
    seen_urls = set()
    all_songs = []

    # Step 1: Get known artists from the target country (100 artists, cached)
    country_artist_names = []
    known_country_set = set()
    if country_code:
        country_artist_names = get_artists_from_country(country_code, limit=100)
        known_country_set = {n.lower() for n in country_artist_names}

    # Step 2: Search MusicBrainz for recordings with the keyword in the
    # title, then cross-reference with known country artists.
    # This finds exact title matches like "In Your Eyes" by 2Baba.
    recording_genius_queries = []
    if country_code:
        recordings = mb_recording_search(query, limit=100)
        for rec in recordings:
            credits = rec.get("artist-credit", [])
            for credit in credits:
                artist_name = (credit.get("artist") or credit).get("name", "") if isinstance(credit, dict) else ""
                if not artist_name:
                    artist_name = credit.get("name", "") if isinstance(credit, dict) else ""
                if artist_name and artist_name.lower() in known_country_set:
                    title = rec.get("title", "")
                    recording_genius_queries.append(
                        (f"{title} {artist_name}", 3, 1)
                    )

    # Step 3: Build Genius search queries from all strategies.
    genius_queries = []

    # 3a: Targeted artist + lyrics keyword (all country artists)
    if country_artist_names:
        for artist_name in country_artist_names:
            genius_queries.append((f"{query} {artist_name}", 5, 1))

    # 3b: Recording title matches from MusicBrainz
    genius_queries.extend(recording_genius_queries)

    # 3c: Country/genre name as keyword
    if country_name:
        genius_queries.append((f"{query} {country_name}", 20, 1))
    if genre_filter:
        genius_queries.append((f"{query} {genre_filter}", 20, 1))

    # 3d: Genre-only (no country): broad search
    if not country_code:
        for pg in range(1, 4):
            genius_queries.append((query, 25, pg))

    # Run all Genius searches in parallel
    def _do_search(args):
        q, per_page, page = args
        return genius_search(q, per_page=per_page, page=page)

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(_do_search, q): q for q in genius_queries}
        for future in as_completed(futures):
            try:
                hits = future.result()
                all_songs.extend(_extract_songs(hits, seen_urls))
            except Exception:
                pass

    if not all_songs:
        return jsonify({"tracks": [], "total": 0, "filtered": True})

    # Step 4: Verify unknown artists on MusicBrainz (limited lookups)
    MAX_NEW_LOOKUPS = 10
    new_lookups = 0
    unique_artists = list(dict.fromkeys(s["artist_name"] for s in all_songs))
    for name in unique_artists:
        key = name.strip().lower()
        with _mb_lock:
            already_cached = key in _mb_cache
        if not already_cached:
            if new_lookups >= MAX_NEW_LOOKUPS:
                continue
            mb_artist_lookup(name)
            new_lookups += 1

    # Step 5: Filter results by country and/or genre
    filtered = []
    for song in all_songs:
        info = _mb_cache.get(song["artist_name"].strip().lower(), {})
        ac = (info.get("country_code") or "").upper()
        ag = info.get("genres") or []

        if country_code and ac != country_code:
            continue
        if genre_filter and not _genre_matches(ag, genre_filter):
            continue

        song["artist_country"] = ac
        song["artist_country_name"] = info.get("country_name", "")
        song["genres"] = ag[:4]
        filtered.append(song)

    return jsonify({"tracks": filtered, "total": len(filtered), "filtered": True})


@app.route("/api/artist-info")
def artist_info():
    name = flask_request.args.get("name", "").strip()
    if not name:
        return jsonify({"error": "Missing artist name"}), 400
    info = mb_artist_lookup(name)
    return jsonify(info)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
