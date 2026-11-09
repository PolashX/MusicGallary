"""Cloud Music Gallery - upload, stream, download and share music. Flask + Amazon S3 (private bucket).

No login: every track gets an unguessable public id (used in share links) and the uploader's
browser receives a secret delete token, so only the uploader can remove their track.
"""
import hashlib
import os
import re
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

import boto3
from flask import Flask, abort, jsonify, redirect, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

BUCKET = os.environ["S3_BUCKET"]
REGION = os.environ["AWS_REGION"]
DB_PATH = os.environ.get("DB_PATH", "music.db")
MAX_MB = int(os.environ.get("MAX_UPLOAD_MB", "50"))
UPLOADS_PER_HOUR = int(os.environ.get("UPLOADS_PER_HOUR", "20"))
URL_TTL = 3600  # pre-signed URL lifetime (seconds)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_MB * 1024 * 1024 + 1024 * 1024
if os.environ.get("TRUST_PROXY") == "1":  # behind Nginx / ALB
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

s3 = boto3.client("s3", region_name=REGION)

MIME = {"mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg",
        "flac": "audio/flac", "m4a": "audio/mp4", "aac": "audio/aac"}


def looks_like(ext, h):
    """Magic-byte check so a renamed .exe cannot be stored as music."""
    if ext == "mp3":
        return h.startswith(b"ID3") or (len(h) > 1 and h[0] == 0xFF and (h[1] & 0xE0) == 0xE0)
    if ext == "wav":
        return h[:4] == b"RIFF" and h[8:12] == b"WAVE"
    if ext == "ogg":
        return h[:4] == b"OggS"
    if ext == "flac":
        return h[:4] == b"fLaC"
    if ext == "m4a":
        return h[4:8] == b"ftyp"
    if ext == "aac":
        return len(h) > 1 and h[0] == 0xFF and (h[1] & 0xF0) == 0xF0
    return False


# ---------- database ----------
def db():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("""CREATE TABLE IF NOT EXISTS tracks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        public_id TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL,
        artist TEXT NOT NULL DEFAULT '',
        filename TEXT NOT NULL,
        s3_key TEXT NOT NULL,
        ext TEXT NOT NULL,
        size INTEGER NOT NULL,
        plays INTEGER NOT NULL DEFAULT 0,
        delete_hash TEXT NOT NULL,
        created_at TEXT NOT NULL)""")
    con.commit()
    con.close()


def track_json(r):
    return {"id": r["public_id"], "title": r["title"], "artist": r["artist"],
            "ext": r["ext"], "size": r["size"], "plays": r["plays"],
            "created_at": r["created_at"]}


def get_track(pid):
    con = db()
    row = con.execute("SELECT * FROM tracks WHERE public_id = ?", (pid,)).fetchone()
    con.close()
    if row is None:
        abort(404)
    return row


# ---------- simple per-IP upload rate limit ----------
_hits = defaultdict(deque)


def rate_limited(ip):
    now, q = time.time(), _hits[ip]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= UPLOADS_PER_HOUR:
        return True
    q.append(now)
    return False


# ---------- pages ----------
@app.route("/")
def index():
    return render_template("index.html", max_mb=MAX_MB)


@app.route("/s/<pid>")
def share_page(pid):
    t = get_track(pid)
    return render_template("share.html", t=track_json(t), url=request.url)


@app.route("/health")
def health():
    return {"status": "ok"}


# ---------- API ----------
@app.route("/api/tracks")
def list_tracks():
    q = request.args.get("q", "").strip()
    con = db()
    if q:
        like = f"%{q.replace('%', '').replace('_', '')}%"
        rows = con.execute("SELECT * FROM tracks WHERE title LIKE ? OR artist LIKE ? "
                           "ORDER BY id DESC", (like, like)).fetchall()
    else:
        rows = con.execute("SELECT * FROM tracks ORDER BY id DESC").fetchall()
    con.close()
    return jsonify([track_json(r) for r in rows])


@app.route("/api/upload", methods=["POST"])
def upload():
    if rate_limited(request.remote_addr or "unknown"):
        return jsonify(error="Upload limit reached. Try again later."), 429
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(error="No file selected."), 400
    name = secure_filename(f.filename)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in MIME:
        return jsonify(error="Allowed types: " + ", ".join(sorted(MIME))), 400
    data = f.read()
    if len(data) > MAX_MB * 1024 * 1024:
        return jsonify(error=f"File too large (max {MAX_MB} MB)."), 413
    if not looks_like(ext, data[:16]):
        return jsonify(error="File content is not valid " + ext.upper() + " audio."), 400

    pid = secrets.token_urlsafe(6)
    key = f"music/{pid}.{ext}"
    s3.put_object(Bucket=BUCKET, Key=key, Body=data, ContentType=MIME[ext],
                  ServerSideEncryption="AES256")
    title = request.form.get("title", "").strip()[:120] or re.sub(r"[_-]+", " ", name.rsplit(".", 1)[0])
    artist = request.form.get("artist", "").strip()[:80]
    token = secrets.token_urlsafe(24)
    con = db()
    con.execute("INSERT INTO tracks (public_id,title,artist,filename,s3_key,ext,size,delete_hash,created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (pid, title, artist, name, key, ext, len(data),
                 hashlib.sha256(token.encode()).hexdigest(),
                 datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")))
    con.commit()
    row = con.execute("SELECT * FROM tracks WHERE public_id = ?", (pid,)).fetchone()
    con.close()
    return jsonify(track=track_json(row), delete_token=token), 201


def _signed(t, disposition):
    fname = re.sub(r"[^A-Za-z0-9._-]", "_", f"{t['title']}.{t['ext']}")
    return s3.generate_presigned_url("get_object", ExpiresIn=URL_TTL, Params={
        "Bucket": BUCKET, "Key": t["s3_key"], "ResponseContentType": MIME[t["ext"]],
        "ResponseContentDisposition": f'{disposition}; filename="{fname}"'})


@app.route("/api/tracks/<pid>/stream")
def stream(pid):
    return redirect(_signed(get_track(pid), "inline"))


@app.route("/api/tracks/<pid>/download")
def download(pid):
    return redirect(_signed(get_track(pid), "attachment"))


@app.route("/api/tracks/<pid>/play", methods=["POST"])
def played(pid):
    get_track(pid)
    con = db()
    con.execute("UPDATE tracks SET plays = plays + 1 WHERE public_id = ?", (pid,))
    con.commit()
    n = con.execute("SELECT plays FROM tracks WHERE public_id = ?", (pid,)).fetchone()[0]
    con.close()
    return {"plays": n}


@app.route("/api/tracks/<pid>", methods=["DELETE"])
def delete(pid):
    t = get_track(pid)
    sent = hashlib.sha256(request.headers.get("X-Delete-Token", "").encode()).hexdigest()
    if not secrets.compare_digest(sent, t["delete_hash"]):
        return jsonify(error="Only the uploader can delete this track."), 403
    s3.delete_object(Bucket=BUCKET, Key=t["s3_key"])
    con = db()
    con.execute("DELETE FROM tracks WHERE public_id = ?", (pid,))
    con.commit()
    con.close()
    return "", 204


@app.errorhandler(413)
def too_large(_e):
    return jsonify(error=f"File too large (max {MAX_MB} MB)."), 413


@app.errorhandler(404)
def not_found(_e):
    if request.path.startswith("/api/"):
        return jsonify(error="Not found."), 404
    return render_template("share.html", t=None, url=request.url), 404


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
