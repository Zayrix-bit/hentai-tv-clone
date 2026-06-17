from flask import Flask, jsonify, request
from flask_cors import CORS
from hentai_scraper import HentaiTVScraper

app = Flask(__name__)
CORS(app)

scraper = HentaiTVScraper()


# -----------------------------------------------------------------------
# Helper
# -----------------------------------------------------------------------
def _ok(data, **extra):
    return jsonify({"success": True, "data": data, **extra})

def _err(msg, code=500):
    return jsonify({"success": False, "error": str(msg)}), code


# -----------------------------------------------------------------------
# Recent / Browse  (GET /api/recent?page=N)
# -----------------------------------------------------------------------
@app.route('/api/recent', methods=['GET'])
async def get_recent():
    page = request.args.get('page', 1, type=int)
    try:
        result = await scraper.get_recent(page=page)
        return jsonify({
            "success": True,
            "data": result["videos"],
            "total": result["total"],
            "pages": result["pages"],
            "page": page,
        })
    except Exception as e:
        return _err(e)


# -----------------------------------------------------------------------
# Trending  (GET /api/trending?page=N)
# -----------------------------------------------------------------------
@app.route('/api/trending', methods=['GET'])
async def get_trending():
    page = request.args.get('page', 1, type=int)
    try:
        result = await scraper.get_trending(page=page)
        return jsonify({
            "success": True,
            "data": result["videos"],
            "total": result["total"],
            "pages": result["pages"],
            "page": page,
        })
    except Exception as e:
        return _err(e)


# -----------------------------------------------------------------------
# Search  (GET /api/search?q=QUERY&page=N)
# -----------------------------------------------------------------------
@app.route('/api/search', methods=['GET'])
async def search():
    query = request.args.get('q', '').strip()
    page  = request.args.get('page', 1, type=int)
    if not query:
        return _err("Query parameter 'q' is required", 400)
    try:
        videos = await scraper.search(query, page=page)
        return _ok(videos)
    except Exception as e:
        return _err(e)


# -----------------------------------------------------------------------
# Genres  (GET /api/genres)
# -----------------------------------------------------------------------
@app.route('/api/genres', methods=['GET'])
async def get_genres():
    try:
        genres = await scraper.get_genres()
        return _ok(genres)
    except Exception as e:
        return _err(e)


# -----------------------------------------------------------------------
# Genre / Tag videos  (GET /api/genre/<slug>?page=N)
# -----------------------------------------------------------------------
@app.route('/api/genre/<slug>', methods=['GET'])
async def get_by_genre(slug):
    page = request.args.get('page', 1, type=int)
    try:
        result = await scraper.get_by_tag(slug, page=page)
        return jsonify({
            "success": True,
            "data": result["videos"],
            "total": result["total"],
            "pages": result["pages"],
            "page": page,
        })
    except Exception as e:
        return _err(e)


# -----------------------------------------------------------------------
# Video details  (GET /api/details/<slug>)
# -----------------------------------------------------------------------
@app.route('/api/details/<slug>', methods=['GET'])
async def get_details(slug):
    try:
        details = await scraper.get_video_details(slug)
        return _ok(details)
    except Exception as e:
        return _err(e)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
