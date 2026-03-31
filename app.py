import os
import re
import uuid
import threading
import subprocess
import json
import zipfile
import bcrypt
import stripe
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_file, send_from_directory, session
from flask_cors import CORS
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, User, DownloadLog

app = Flask(__name__, static_folder=".")
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
CORS(app, supports_credentials=True)

# ── Database ──────────────────────────────────────────────────────────────────
db_url = os.environ.get("DATABASE_URL", "sqlite:///app.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

# ── Flask-Login ───────────────────────────────────────────────────────────────
login_manager = LoginManager(app)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# ── Stripe ────────────────────────────────────────────────────────────────────
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRO_PRICE_ID = os.environ.get("STRIPE_PRO_PRICE_ID", "")
APP_URL = os.environ.get("APP_URL", "http://localhost:5000")

# ── Config ────────────────────────────────────────────────────────────────────
DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

COOKIES_PATH = os.path.join(os.path.dirname(__file__), "cookies.txt")
_env_cookies = os.environ.get("YOUTUBE_COOKIES", "")
if _env_cookies and not os.path.exists(COOKIES_PATH):
    with open(COOKIES_PATH, "w") as f:
        f.write(_env_cookies)

FREE_DAILY_LIMIT = 3
jobs = {}

with app.app_context():
    db.create_all()


# ── Helpers ───────────────────────────────────────────────────────────────────
def cookies_args():
    return ["--cookies", COOKIES_PATH] if os.path.exists(COOKIES_PATH) else []

def get_client_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0].strip()

def downloads_today(user_id=None, ip=None):
    cutoff = datetime.utcnow() - timedelta(hours=24)
    q = DownloadLog.query.filter(DownloadLog.created_at >= cutoff)
    if user_id:
        q = q.filter_by(user_id=user_id)
    else:
        q = q.filter_by(user_id=None, ip_address=ip)
    return q.count()

def check_limit():
    """Returns (allowed: bool, error_msg: str|None, count: int)"""
    if current_user.is_authenticated and current_user.is_pro:
        return True, None, 0
    if current_user.is_authenticated:
        count = downloads_today(user_id=current_user.id)
    else:
        count = downloads_today(ip=get_client_ip())
    if count >= FREE_DAILY_LIMIT:
        return False, f"Daily limit reached ({FREE_DAILY_LIMIT}/day on free plan). Upgrade to Pro for unlimited downloads.", count
    return True, None, count

def record_download():
    log = DownloadLog(
        user_id=current_user.id if current_user.is_authenticated else None,
        ip_address=get_client_ip()
    )
    db.session.add(log)
    db.session.commit()


# ── Download workers ──────────────────────────────────────────────────────────
def run_download(job_id, url, fmt, quality):
    try:
        jobs[job_id]["status"] = "fetching"
        out_template = os.path.join(DOWNLOAD_DIR, f"{job_id}_%(title)s.%(ext)s")

        if fmt == "mp3":
            cmd = [
                "yt-dlp", "--no-playlist",
                "--extractor-args", "youtube:player_client=android,web",
                *cookies_args(),
                "-x", "--audio-format", "mp3", "--audio-quality", "0",
                "-o", out_template, "--newline", url
            ]
        else:
            height = quality.replace("p", "") if quality else "1080"
            format_sel = (
                f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]"
                f"/bestvideo[height<={height}]+bestaudio/best[height<={height}]"
            )
            cmd = [
                "yt-dlp", "--no-playlist",
                "--extractor-args", "youtube:player_client=android,web",
                *cookies_args(),
                "-f", format_sel, "--merge-output-format", "mp4",
                "-o", out_template, "--newline", url
            ]

        jobs[job_id]["status"] = "downloading"
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

        for line in process.stdout:
            line = line.strip()
            if "[download]" in line and "%" in line:
                m = re.search(r"(\d+\.?\d*)%", line)
                if m:
                    jobs[job_id]["progress"] = round(float(m.group(1)))
            elif "[ExtractAudio]" in line or "[Merger]" in line or "[ffmpeg]" in line:
                jobs[job_id]["status"] = "processing"
                jobs[job_id]["progress"] = 99

        process.wait()
        if process.returncode != 0:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = "Download failed. Check the URL or try again."
            return

        for f in os.listdir(DOWNLOAD_DIR):
            if f.startswith(job_id) and not f.endswith(".zip"):
                jobs[job_id]["file_path"] = os.path.join(DOWNLOAD_DIR, f)
                jobs[job_id]["filename"] = f[len(job_id) + 1:]
                break

        jobs[job_id]["status"] = "done"
        jobs[job_id]["progress"] = 100

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)


def run_playlist_download(job_id, url, fmt, quality):
    try:
        jobs[job_id]["status"] = "fetching"
        playlist_dir = os.path.join(DOWNLOAD_DIR, job_id)
        os.makedirs(playlist_dir, exist_ok=True)
        out_template = os.path.join(playlist_dir, "%(playlist_index)s_%(title)s.%(ext)s")

        if fmt == "mp3":
            cmd = [
                "yt-dlp",
                "--extractor-args", "youtube:player_client=android,web",
                *cookies_args(),
                "-x", "--audio-format", "mp3", "--audio-quality", "0",
                "-o", out_template, "--newline", url
            ]
        else:
            height = quality.replace("p", "") if quality else "1080"
            format_sel = (
                f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]"
                f"/bestvideo[height<={height}]+bestaudio/best[height<={height}]"
            )
            cmd = [
                "yt-dlp",
                "--extractor-args", "youtube:player_client=android,web",
                *cookies_args(),
                "-f", format_sel, "--merge-output-format", "mp4",
                "-o", out_template, "--newline", url
            ]

        jobs[job_id]["status"] = "downloading"
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

        for line in process.stdout:
            line = line.strip()
            if "[download]" in line and "%" in line:
                m = re.search(r"(\d+\.?\d*)%", line)
                if m:
                    jobs[job_id]["progress"] = min(round(float(m.group(1))), 98)
            elif "[ExtractAudio]" in line or "[Merger]" in line or "[ffmpeg]" in line:
                jobs[job_id]["status"] = "processing"

        process.wait()
        if process.returncode != 0:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = "Playlist download failed."
            return

        jobs[job_id]["status"] = "processing"
        jobs[job_id]["progress"] = 99
        zip_path = os.path.join(DOWNLOAD_DIR, f"{job_id}_playlist.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname in sorted(os.listdir(playlist_dir)):
                zf.write(os.path.join(playlist_dir, fname), fname)

        jobs[job_id]["file_path"] = zip_path
        jobs[job_id]["filename"] = "playlist.zip"
        jobs[job_id]["status"] = "done"
        jobs[job_id]["progress"] = 100

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)


# ── Static ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(".", "index.html")


# ── Auth routes ───────────────────────────────────────────────────────────────
@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.json
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already registered"}), 409
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    user = User(email=email, password_hash=pw_hash)
    db.session.add(user)
    db.session.commit()
    login_user(user)
    return jsonify({"id": user.id, "email": user.email, "is_pro": user.is_pro})


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.json
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    user = User.query.filter_by(email=email).first()
    if not user or not bcrypt.checkpw(password.encode(), user.password_hash.encode()):
        return jsonify({"error": "Invalid email or password"}), 401
    login_user(user)
    return jsonify({"id": user.id, "email": user.email, "is_pro": user.is_pro})


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    logout_user()
    return jsonify({"ok": True})


@app.route("/api/auth/me", methods=["GET"])
def me():
    if current_user.is_authenticated:
        count = downloads_today(user_id=current_user.id)
        return jsonify({
            "user": {"id": current_user.id, "email": current_user.email, "is_pro": current_user.is_pro},
            "downloads_today": count,
            "limit": None if current_user.is_pro else FREE_DAILY_LIMIT
        })
    ip = get_client_ip()
    count = downloads_today(ip=ip)
    return jsonify({"user": None, "downloads_today": count, "limit": FREE_DAILY_LIMIT})


# ── Stripe routes ─────────────────────────────────────────────────────────────
@app.route("/api/stripe/create-checkout", methods=["POST"])
@login_required
def create_checkout():
    if not STRIPE_PRO_PRICE_ID:
        return jsonify({"error": "Stripe not configured"}), 503
    try:
        customer_id = current_user.stripe_customer_id
        if not customer_id:
            customer = stripe.Customer.create(email=current_user.email)
            current_user.stripe_customer_id = customer.id
            db.session.commit()
            customer_id = customer.id

        session_obj = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{"price": STRIPE_PRO_PRICE_ID, "quantity": 1}],
            mode="subscription",
            success_url=f"{APP_URL}/?upgraded=1",
            cancel_url=f"{APP_URL}/",
        )
        return jsonify({"checkout_url": session_obj.url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/stripe/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception:
        return jsonify({"error": "Invalid signature"}), 400

    if event["type"] in ("customer.subscription.created", "customer.subscription.updated"):
        sub = event["data"]["object"]
        user = User.query.filter_by(stripe_customer_id=sub["customer"]).first()
        if user:
            user.is_pro = sub["status"] == "active"
            user.stripe_subscription_id = sub["id"]
            db.session.commit()

    elif event["type"] == "customer.subscription.deleted":
        sub = event["data"]["object"]
        user = User.query.filter_by(stripe_customer_id=sub["customer"]).first()
        if user:
            user.is_pro = False
            db.session.commit()

    return jsonify({"ok": True})


# ── Video info ────────────────────────────────────────────────────────────────
@app.route("/api/info", methods=["POST"])
def get_info():
    data = request.json
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    # Detect playlist
    is_playlist = "list=" in url and "watch?v=" not in url

    if is_playlist:
        try:
            result = subprocess.run(
                ["yt-dlp", "--flat-playlist", "--dump-single-json",
                 "--extractor-args", "youtube:player_client=android,web",
                 *cookies_args(), url],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                return jsonify({"error": result.stderr.strip() or "Could not fetch playlist info."}), 400
            info = json.loads(result.stdout)
            return jsonify({
                "type": "playlist",
                "title": info.get("title", "Unknown Playlist"),
                "video_count": len(info.get("entries", [])),
                "thumbnail": (info.get("entries") or [{}])[0].get("thumbnails", [{}])[-1].get("url", ""),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"error": "Request timed out."}), 408
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    try:
        result = subprocess.run(
            ["yt-dlp", "--dump-json", "--no-playlist",
             "--extractor-args", "youtube:player_client=android,web",
             *cookies_args(), url],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return jsonify({"error": result.stderr.strip() or "Could not fetch video info. Check the URL."}), 400

        info = json.loads(result.stdout)
        title = info.get("title", "Unknown")
        duration = info.get("duration", 0)
        thumbnail = info.get("thumbnail", "")
        formats = info.get("formats", [])
        heights = sorted(set(
            f["height"] for f in formats
            if f.get("height") and f.get("vcodec") != "none"
        ), reverse=True)
        quality_options = [f"{h}p" for h in heights if h] or ["1080p", "720p", "480p", "360p"]

        hours = int(duration // 3600)
        minutes = int((duration % 3600) // 60)
        seconds = int(duration % 60)
        dur_str = f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"

        return jsonify({
            "type": "video",
            "title": title,
            "duration": dur_str,
            "thumbnail": thumbnail,
            "qualities": quality_options[:6]
        })
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Request timed out. Try again."}), 408
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Convert (single video) ────────────────────────────────────────────────────
@app.route("/api/convert", methods=["POST"])
def convert():
    data = request.json
    url = data.get("url", "").strip()
    fmt = data.get("format", "mp3")
    quality = data.get("quality", "1080p")
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    allowed, err, _ = check_limit()
    if not allowed:
        return jsonify({"error": err, "upgrade_required": True}), 429

    record_download()

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"status": "queued", "progress": 0, "filename": None, "file_path": None, "error": None}
    threading.Thread(target=run_download, args=(job_id, url, fmt, quality), daemon=True).start()
    return jsonify({"job_id": job_id})


# ── Convert (playlist, Pro only) ──────────────────────────────────────────────
@app.route("/api/convert/playlist", methods=["POST"])
def convert_playlist():
    if not current_user.is_authenticated or not current_user.is_pro:
        return jsonify({"error": "Playlist download requires a Pro subscription.", "upgrade_required": True}), 403

    data = request.json
    url = data.get("url", "").strip()
    fmt = data.get("format", "mp3")
    quality = data.get("quality", "1080p")
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"status": "queued", "progress": 0, "filename": None, "file_path": None, "error": None}
    threading.Thread(target=run_playlist_download, args=(job_id, url, fmt, quality), daemon=True).start()
    return jsonify({"job_id": job_id})


# ── Status / Download ─────────────────────────────────────────────────────────
@app.route("/api/status/<job_id>", methods=["GET"])
def status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@app.route("/api/download/<job_id>", methods=["GET"])
def download(job_id):
    job = jobs.get(job_id)
    if not job or job["status"] != "done":
        return jsonify({"error": "File not ready"}), 404
    file_path = job["file_path"]
    if not file_path or not os.path.exists(file_path):
        return jsonify({"error": "File not found on server"}), 404
    return send_file(file_path, as_attachment=True, download_name=job["filename"])


# ── Cookies ───────────────────────────────────────────────────────────────────
@app.route("/api/cookies", methods=["POST"])
def upload_cookies():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    request.files["file"].save(COOKIES_PATH)
    return jsonify({"ok": True})


@app.route("/api/cookies", methods=["DELETE"])
def delete_cookies():
    if os.path.exists(COOKIES_PATH):
        os.remove(COOKIES_PATH)
    return jsonify({"ok": True})


@app.route("/api/cookies/status", methods=["GET"])
def cookies_status():
    return jsonify({"active": os.path.exists(COOKIES_PATH)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"YouTube Converter running at http://localhost:{port}")
    app.run(debug=False, host="0.0.0.0", port=port, threaded=True)
