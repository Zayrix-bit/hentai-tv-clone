"""
HentaiTV Scraper - Uses official hentai.tv API endpoints directly.

Discovered API:
  GET /api/browse?page=N&sort=SORT&tag=TAG  -> {videos, total, pages}
  GET /api/search?q=QUERY&page=N           -> {videos}
  GET /api/trending?window=W               -> requires special header (fallback: /trending page RSC)

All video objects contain:
  id, slug, title, ep, views, likes, dislikes, rating, censored,
  brand, quality, year, duration, tags, cover, thumb, backdrop,
  embedUrl, description, releasedAt
"""
import json
import re
import base64
from urllib.parse import urlparse, parse_qs
import aiohttp
import asyncio
from cachetools import TTLCache


class HentaiTVScraper:
    BASE = "https://hentai.tv"

    def __init__(self):
        self._cache = TTLCache(maxsize=2000, ttl=300)  # 5-min TTL
        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://hentai.tv/",
        }
        # Keep RSC headers for page scraping fallback
        self._rsc_headers = {**self._headers, "RSC": "1"}

    # ------------------------------------------------------------------
    # LOW-LEVEL HELPERS
    # ------------------------------------------------------------------

    async def _api_get(self, path: str, params: dict = None) -> dict | list | None:
        """Call a JSON API endpoint. Returns parsed JSON or None on failure."""
        from urllib.parse import urlencode
        qs = f"?{urlencode(params)}" if params else ""
        url = f"{self.BASE}{path}{qs}"

        if url in self._cache:
            return self._cache[url]

        for attempt in range(3):
            try:
                async with aiohttp.ClientSession(headers=self._headers) as s:
                    async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                        if r.status == 429:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        if r.status not in (200, 201):
                            return None
                        data = await r.json(content_type=None)
                        self._cache[url] = data
                        return data
            except Exception as e:
                if attempt == 2:
                    print(f"[Scraper] API error {url}: {e}")
                    return None
                await asyncio.sleep(1.5 ** attempt)
        return None

    async def _rsc_fetch(self, path: str) -> str:
        """Fetch a Next.js RSC page for legacy scraping fallback."""
        url = f"{self.BASE}{path}"
        if url in self._cache:
            return self._cache[url]
        for attempt in range(3):
            try:
                async with aiohttp.ClientSession(headers=self._rsc_headers) as s:
                    async with s.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                        if r.status == 429:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        if r.status != 200:
                            return ""
                        text = await r.text()
                        self._cache[url] = text
                        return text
            except Exception as e:
                if attempt == 2:
                    print(f"[Scraper] RSC fetch error {url}: {e}")
                    return ""
                await asyncio.sleep(1.5 ** attempt)
        return ""

    def _extract_rsc_videos(self, text: str) -> list[dict]:
        """Extract video objects embedded in RSC payload."""
        videos = []
        seen = set()
        # Match full video objects that have the expected structure (id, slug, title, titleSlug, titleId, ... views)
        pattern = r'\{"id":"[^"]+","slug":"[^"]+","title":"[^"]+","titleSlug":"[^"]+","titleId":"[^"]+"[^}]*"views":\d+[^}]*\}'
        matches = re.findall(pattern, text)
        for m in matches:
            try:
                obj = json.loads(m)
                slug = obj.get("slug", "")
                if slug and "title" in obj and slug not in seen:
                    seen.add(slug)
                    videos.append(obj)
            except Exception:
                pass
        return videos

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------

    async def get_recent(self, page: int = 1) -> dict:
        """
        Recent uploads from /api/browse.
        Returns: {videos: [...], total: int, pages: int}
        """
        data = await self._api_get("/api/browse", {"page": page, "sort": "latest"})
        if data and "videos" in data:
            videos = data["videos"]
            total = data.get("total", 0)
            pages = data.get("pages", 1)
            
            # User wants exactly 30 cards per page (Hentai.tv API gives 28)
            # So we borrow 2 cards from the next page (perfect for 5-column grids)
            if len(videos) == 28 and page < pages:
                data2 = await self._api_get("/api/browse", {"page": page + 1, "sort": "latest"})
                if data2 and "videos" in data2:
                    videos.extend(data2["videos"][:2])
                    
            return {"videos": videos, "total": total, "pages": pages}
        return {"videos": [], "total": 0, "pages": 1}

    async def get_trending(self, page: int = 1) -> dict:
        """
        Trending videos - scraped directly from /trending RSC page.
        Returns: {videos: [...], total: int, pages: int}
        """
        # Hentai.tv's API sort=trending doesn't work correctly, so we scrape the page directly
        text = await self._rsc_fetch("/trending")
        videos = self._extract_rsc_videos(text)
        return {"videos": videos, "total": len(videos), "pages": 1}

    async def get_by_tag(self, tag_slug: str, page: int = 1) -> dict:
        """
        Videos filtered by genre/tag - scraped directly from /genre/SLUG RSC page.
        Returns: {videos: [...], total: int, pages: int}
        """
        # API's tag parameter is ignored, so we must scrape the specific genre RSC page directly
        text = await self._rsc_fetch(f"/genre/{tag_slug}?page={page}")
        all_videos = self._extract_rsc_videos(text)
        
        # Filter to only videos that actually have this tag (case-insensitive)
        # This removes sidebar/trending videos that might be included in the RSC payload
        videos = []
        target_slug = tag_slug.lower().replace("-", "")
        for v in all_videos:
            tags = [t.lower().replace(" ", "").replace("-", "") for t in v.get("tags", [])]
            if target_slug in tags:
                videos.append(v)
                
        # If filtering removed everything (unlikely, but possible if tag matching fails),
        # fallback to the first 28 videos (standard page size)
        if not videos and all_videos:
            videos = all_videos[:28]
        # Extract total pages from RSC payload links (e.g. "?page=25")
        pages = 1
        page_matches = re.findall(r'\?page=(\d+)', text)
        if page_matches:
            pages = max(int(p) for p in page_matches)
            
        # Estimate total based on pages (frontend needs total > items to show pagination)
        total = max(len(videos), pages * 28)
            
        return {"videos": videos, "total": total, "pages": pages}

    async def search(self, query: str, page: int = 1) -> list[dict]:
        """
        Search videos via /api/search?q=QUERY.
        Returns list of video objects.
        """
        data = await self._api_get("/api/search", {"q": query, "page": page})
        if data and "videos" in data:
            return data["videos"]
        return []

    async def get_genres(self) -> list[dict]:
        """
        Fetch genre list by scraping the /search RSC page (no dedicated API).
        Returns list of {slug, name} dicts.
        """
        # Cache key for genres specifically
        cache_key = "__genres__"
        if cache_key in self._cache:
            return self._cache[cache_key]

        text = await self._rsc_fetch("/search")
        genres = []
        matches = re.findall(r'\\\\"genres\\\\":(\\[.*?\\])(?:,|\\\\})', text)
        if not matches:
            matches = re.findall(r'"genres":(\[.*?\])(?:,|})', text)

        for m in matches:
            try:
                decoded = m.encode().decode("unicode_escape") if '\\"' in m else m
                data = json.loads(decoded.replace('\\"', '"').replace('\\\\', '\\'))
                if isinstance(data, list) and data and "slug" in data[0]:
                    genres = data
                    break
            except Exception:
                pass

        self._cache[cache_key] = genres
        return genres

    async def get_video_details(self, slug: str) -> dict:
        """
        Deep metadata for a specific episode by scraping its RSC page.
        Returns {description, characters, studio, related_videos, is_uncensored}
        """
        text = await self._rsc_fetch(f"/hentai/{slug}/")

        details = {
            "description": "",
            "characters": [],
            "studio": "",
            "release_date": "",
            "related_videos": [],
            "is_uncensored": False,
        }

        try:
            all_videos = self._extract_rsc_videos(text)
            details["related_videos"] = [v for v in all_videos if v.get("slug") != slug]
            for v in all_videos:
                if v.get("slug") == slug:
                    details["is_uncensored"] = not v.get("censored", True) or "Uncensored" in v.get("tags", [])
                    break
        except Exception:
            pass

        try:
            matches = re.findall(r'\{[^{]*?"description":"[^"]+".*?\}', text)
            for m in matches:
                try:
                    obj = json.loads(m.replace('\\"', '"').replace('\\\\', '\\'))
                    if "description" in obj and "title" in obj:
                        details["description"] = obj.get("description", "")
                        details["studio"] = obj.get("brand", obj.get("studio", ""))
                        chars = obj.get("characters", [])
                        details["characters"] = chars if chars else obj.get("tags", [])
                        break
                except Exception:
                    pass
        except Exception:
            pass

        return details

    async def get_video_streams(self, embed_url: str) -> dict | None:
        """Extract direct MP4 and subtitle links from the embed player."""
        if not embed_url:
            return None
        hdrs = {**self._headers, "Referer": "https://hentai.tv/"}
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(embed_url, headers=hdrs, timeout=aiohttp.ClientTimeout(total=12)) as r:
                    if r.status != 200:
                        return None
                    text = await r.text()

            match = re.search(r'data-id=["\'](/player\.php\?.*?)["\']', text)
            if not match:
                return None

            player_url = match.group(1)
            qs = parse_qs(urlparse(player_url).query)
            result = {}

            if "vid" in qs:
                try:
                    decoded = base64.b64decode(qs["vid"][0]).decode("utf-8")
                    result["mp4"] = decoded.split("|")[0]
                except Exception:
                    pass

            if "s" in qs:
                try:
                    result["subtitle"] = base64.b64decode(qs["s"][0]).decode("utf-8")
                except Exception:
                    pass

            return result or None
        except Exception:
            return None
