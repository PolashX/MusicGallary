# ♫ Cloud Music Gallery (AWS EC2 + S3)

A login-free music gallery: **upload, stream, download and share** tracks. Audio lives in a **private S3 bucket**;
Flask on **EC2** serves the site; EC2 talks to S3 through an **IAM role** (no keys in code).

## Features
- Drag-and-drop multi-file upload with progress bars (MP3, WAV, OGG, FLAC, M4A, AAC, up to 50 MB)
- Gallery grid with search, play counts and generated cover art
- Sticky player: play/pause, next/previous, seek, volume, auto-advance, spacebar, lock-screen controls
- Share: unique link `/s/<id>` with its own player page + social preview tags (native share sheet on phones)
- Download via short-lived pre-signed S3 URLs (bucket stays private; audio streams straight from S3 with seeking)
- No login: uploaders get a secret delete token saved in their browser, so only they see the Delete button
- Safety: magic-byte file validation, size limit, per-IP upload rate limit, S3 server-side encryption

## AWS setup
1. **S3**: create a bucket, keep *Block all public access* ON.
2. **IAM**: policy from `iam-policy.json` (put your bucket name in) → role for EC2 (e.g. `MusicGalleryEC2Role`).
3. **EC2**: Ubuntu 24.04, t3.micro, attach the role. Security group: SSH 22 (My IP), HTTP 80 (anywhere).

## Deploy
```bash
ssh -i key.pem ubuntu@EC2_IP
sudo apt update && sudo apt install -y git
git clone https://github.com/YOUR_USERNAME/music-gallery.git && cd music-gallery
cp .env.example .env && nano .env        # set S3_BUCKET and AWS_REGION
bash deploy/setup-ec2.sh                 # installs Gunicorn + Nginx + systemd service
```
Open `http://EC2_IP/`. Logs: `journalctl -u music-gallery -f`.

## Run locally
```bash
pip install -r requirements.txt
export S3_BUCKET=... AWS_REGION=... FLASK_ENV=dev   # needs AWS credentials locally
python app.py                                        # http://localhost:5000
```
Tests (no AWS needed): `pip install moto && python test_app.py`

## Notes and limits
- Anyone with the site URL can upload, so keep limits sensible and watch your S3 bill; lower `UPLOADS_PER_HOUR` if needed.
- Share links work for anyone who has them; deleting a track kills its link.
- Delete tokens live in the uploader's browser: clearing site data or switching device loses delete access.
- Add HTTPS (Route 53 domain + `certbot --nginx`, or CloudFront/ALB) before real use.
- Scaling ideas: direct-to-S3 uploads via pre-signed POST, DynamoDB/RDS instead of SQLite, CloudFront for streaming, S3 lifecycle rules.
