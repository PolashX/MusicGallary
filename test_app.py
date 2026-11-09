import io, os, re, tempfile
os.environ.update(S3_BUCKET="test-music-bucket", AWS_REGION="ap-south-1", AWS_ACCESS_KEY_ID="t", AWS_SECRET_ACCESS_KEY="t",
                  DB_PATH=tempfile.mktemp(suffix=".db"), MAX_UPLOAD_MB="2", UPLOADS_PER_HOUR="50")
from moto import mock_aws

def ok(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: raise SystemExit(1)

with mock_aws():
    import boto3, app
    s3 = boto3.client("s3", region_name="ap-south-1")
    s3.create_bucket(Bucket="test-music-bucket", CreateBucketConfiguration={"LocationConstraint": "ap-south-1"})
    c = app.app.test_client()
    up = lambda data, name, **kw: c.post("/api/upload", data={"file": (io.BytesIO(data), name), **kw}, content_type="multipart/form-data")

    ok("home page loads (no login)", c.get("/").status_code == 200 and b"Drop music here" in c.get("/").data)
    ok("static js served", c.get("/static/app.js").status_code == 200)
    ok("health", c.get("/health").json == {"status": "ok"})

    r = up(b"ID3\x03\x00\x00\x00" + b"0" * 500, "my_cool-song.mp3", artist="DJ Cloud"); j = r.json
    ok("mp3 upload 201", r.status_code == 201)
    pid, tok = j["track"]["id"], j["delete_token"]
    ok("title derived from filename", j["track"]["title"] == "my cool song" and j["track"]["artist"] == "DJ Cloud")
    ok("object stored in S3 (encrypted)", s3.head_object(Bucket="test-music-bucket", Key=f"music/{pid}.mp3")["ServerSideEncryption"] == "AES256")
    ok("delete hash not exposed", "delete_hash" not in j["track"] and tok not in c.get("/api/tracks").text)

    up(b"RIFF\x00\x00\x00\x00WAVEfmt " + b"0"*100, "beat.wav", title="Zed Beat")
    up(b"fLaC" + b"0"*50, "x.flac"); up(b"\x00\x00\x00\x18ftypM4A " + b"0"*50, "y.m4a"); up(b"OggS" + b"0"*50, "z.ogg")
    ok("5 formats accepted", len(c.get("/api/tracks").json) == 5)
    ok("search by title", [t["title"] for t in c.get("/api/tracks?q=zed").json] == ["Zed Beat"])
    ok("search by artist", len(c.get("/api/tracks?q=dj cloud").json) == 1)

    ok("renamed exe rejected", up(b"MZ\x90\x00 evil", "virus.mp3").status_code == 400)
    ok("bad extension rejected", up(b"ID3" + b"0"*20, "doc.pdf").status_code == 400)
    ok("oversize rejected", up(b"ID3" + b"0" * (3 * 1024 * 1024), "big.mp3").status_code == 413)

    r = c.get(f"/api/tracks/{pid}/stream")
    ok("stream -> presigned inline S3 URL", r.status_code == 302 and "test-music-bucket" in r.headers["Location"] and "inline" in r.headers["Location"])
    r = c.get(f"/api/tracks/{pid}/download")
    ok("download -> attachment", r.status_code == 302 and "attachment" in r.headers["Location"])
    ok("presigned URL actually fetches object", s3.get_object(Bucket="test-music-bucket", Key=f"music/{pid}.mp3")["ContentLength"] == 507)

    ok("play counter", c.post(f"/api/tracks/{pid}/play").json["plays"] == 1)
    r = c.get(f"/s/{pid}")
    ok("share page with OG tags + player", r.status_code == 200 and b"og:title" in r.data and b"my cool song" in r.data and b"<audio" in r.data)
    ok("unknown share id -> 404 page", c.get("/s/nope").status_code == 404)
    ok("unknown api id -> json 404", c.get("/api/tracks/nope/stream").json == {"error": "Not found."})

    ok("delete w/o token forbidden", c.delete(f"/api/tracks/{pid}").status_code == 403)
    ok("delete wrong token forbidden", c.delete(f"/api/tracks/{pid}", headers={"X-Delete-Token": "bad"}).status_code == 403)
    ok("delete right token 204", c.delete(f"/api/tracks/{pid}", headers={"X-Delete-Token": tok}).status_code == 204)
    keys = [o["Key"] for o in s3.list_objects_v2(Bucket="test-music-bucket").get("Contents", [])]
    ok("removed from S3 and DB", f"music/{pid}.mp3" not in keys and len(c.get("/api/tracks").json) == 4)

    app.UPLOADS_PER_HOUR = 1; app._hits.clear()
    up(b"OggS" + b"0"*20, "a.ogg"); ok("rate limit -> 429", up(b"OggS" + b"0"*20, "b.ogg").status_code == 429)
print("ALL TESTS PASSED")
