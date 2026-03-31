import os
import re
import uuid
import threading
import subprocess
import json
from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Track jobs: { job_id: { status, progress, filename, error, file_path } }
jobs = {}

def sanitize_filename(name):
    return re.sub(r'[^\w\-_. ]', '_', name)[:80]

def run_download(job_id, url, fmt, quality):
    try:
        jobs[job_id]["status"] = "fetching"
        out_template = os.path.join(DOWNLOAD_DIR, f"{job_id}_%(title)s.%(ext)s")

        if fmt == "mp3":
            cmd = [
                "yt-dlp",
                "--no-playlist",
                "-x", "--audio-format", "mp3",
                "--audio-quality", "0",
                "-o", out_template,
                "--newline",
                url
            ]
        else:
            # mp4
            height = quality.replace("p", "") if quality else "1080"
            format_sel = f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={height}]+bestaudio/best[height<={height}]"
            cmd = [
                "yt-dlp",
                "--no-playlist",
                "-f", format_sel,
                "--merge-output-format", "mp4",
                "-o", out_template,
                "--newline",
                url
            ]

        jobs[job_id]["status"] = "downloading"
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        for line in process.stdout:
            line = line.strip()
            # Parse progress from yt-dlp output
            if "[download]" in line and "%" in line:
                match = re.search(r'(\d+\.?\d*)%', line)
                if match:
                    pct = float(match.group(1))
                    jobs[job_id]["progress"] = round(pct)
            elif "[ExtractAudio]" in line or "[Merger]" in line or "[ffmpeg]" in line:
                jobs[job_id]["status"] = "processing"
                jobs[job_id]["progress"] = 99

        process.wait()

        if process.returncode != 0:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = "Download failed. Check the URL or try again."
            return

        # Find the output file
        for f in os.listdir(DOWNLOAD_DIR):
            if f.startswith(job_id):
                jobs[job_id]["file_path"] = os.path.join(DOWNLOAD_DIR, f)
                jobs[job_id]["filename"] = f[len(job_id)+1:]  # strip job_id prefix
                break

        jobs[job_id]["status"] = "done"
        jobs[job_id]["progress"] = 100

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)


@app.route("/api/info", methods=["POST"])
def get_info():
    """Get video title and available formats/qualities."""
    data = request.json
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    try:
        result = subprocess.run(
            ["yt-dlp", "--dump-json", "--no-playlist", url],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return jsonify({"error": "Could not fetch video info. Check the URL."}), 400

        info = json.loads(result.stdout)
        title = info.get("title", "Unknown")
        duration = info.get("duration", 0)
        thumbnail = info.get("thumbnail", "")

        # Get unique heights available
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
            "title": title,
            "duration": dur_str,
            "thumbnail": thumbnail,
            "qualities": quality_options[:6]
        })
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Request timed out. Try again."}), 408
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/convert", methods=["POST"])
def convert():
    data = request.json
    url = data.get("url", "").strip()
    fmt = data.get("format", "mp3")  # "mp3" or "mp4"
    quality = data.get("quality", "1080p")

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "status": "queued",
        "progress": 0,
        "filename": None,
        "file_path": None,
        "error": None
    }

    thread = threading.Thread(target=run_download, args=(job_id, url, fmt, quality))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


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

    return send_file(
        file_path,
        as_attachment=True,
        download_name=job["filename"]
    )


if __name__ == "__main__":
    print("🎵 YouTube Converter backend running at http://localhost:5000")
    app.run(debug=False, port=5000, threaded=True)
