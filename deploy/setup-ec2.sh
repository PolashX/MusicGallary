#!/usr/bin/env bash
# Run on a fresh Ubuntu 24.04 EC2 instance, from inside the cloned repo:  bash deploy/setup-ec2.sh
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "Create .env first (cp .env.example .env and edit S3_BUCKET / AWS_REGION)"; exit 1; }
sudo apt update && sudo apt install -y python3 python3-venv python3-pip nginx
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
sudo cp deploy/music-gallery.service /etc/systemd/system/
sudo cp deploy/nginx.conf /etc/nginx/sites-available/music-gallery
sudo ln -sf /etc/nginx/sites-available/music-gallery /etc/nginx/sites-enabled/music-gallery
sudo rm -f /etc/nginx/sites-enabled/default
sudo systemctl daemon-reload && sudo systemctl enable --now music-gallery
sudo nginx -t && sudo systemctl restart nginx
echo "Done. Open http://$(curl -s ifconfig.me)/"
