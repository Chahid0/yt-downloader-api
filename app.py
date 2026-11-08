# -*- coding: utf-8 -*-
"""
خادم تحميل وسائط من منصات متعددة (YouTube, Instagram, TikTok, Facebook, ...)
يعتمد على yt-dlp و FFmpeg.
"""
import os
import re
import uuid
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS  # أضف هذا السطر
import threading
import imageio_ffmpeg
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})  # وأضف هذا السطر لإعطاء التصريح لجميع المواقع

# ---------------- إعدادات ----------------
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_FOLDER = os.path.join(APP_DIR, "downloads")
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# قاموس في الذاكرة لتتبع نسبة التحميل (مفتاحه task_id)
download_progress = {}

# تعبير نمطي للتحقق من رابط مباشر
URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)

# ---------------- وظائف مساعدة ----------------
def progress_hook(task_id):
    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            downloaded = d.get("downloaded_bytes", 0)
            if total and total > 0:
                pct = (downloaded / total) * 100
                download_progress[task_id] = f"{pct:.1f}%"
        elif d.get("status") == "finished":
            download_progress[task_id] = "100%"
    return hook


def safe_join(folder, filename):
    """التأكد من أن الملف داخل المجلد (منع path traversal)."""
    filename = os.path.basename(filename)
    if not filename or filename in (".", ".."):
        return None
    full = os.path.join(folder, filename)
    if os.path.commonpath([os.path.abspath(full), os.path.abspath(folder)]) != os.path.abspath(folder):
        return None
    return full


def format_options(format_type):
    if format_type == "mp3":
        return {
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }
    if format_type == "mp4_high":
        return {"format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"}
    return {"format": "best[ext=mp4]/best"}


# ---------------- نقاط النهاية ----------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/progress/<task_id>", methods=["GET"])
def get_progress(task_id):
    return jsonify({"progress": download_progress.get(task_id, "0%")})


@app.route("/api/platforms", methods=["GET"])
def list_platforms():
    platforms = [
        {"name": "يوتيوب", "id": "youtube", "icon": "▶"},
        {"name": "إنستقرام", "id": "instagram", "icon": "📸"},
        {"name": "تيك توك", "id": "tiktok", "icon": "♫"},
        {"name": "فيسبوك", "id": "facebook", "icon": "f"},
        {"name": "أكثر من 1000 منصة", "id": "other", "icon": "🌐"},
    ]
    return jsonify({"platforms": platforms})


@app.route("/api/downloads", methods=["GET"])
def list_downloads():
    files = []
    try:
        for name in os.listdir(DOWNLOAD_FOLDER):
            path = os.path.join(DOWNLOAD_FOLDER, name)
            if os.path.isfile(path):
                files.append({"name": name, "size": os.path.getsize(path)})
    except FileNotFoundError:
        pass
    files.sort(key=lambda x: x["name"])
    return jsonify({"files": files})


@app.route("/api/download-file/<path:filename>", methods=["GET"])
def download_file(filename):
    path = safe_join(DOWNLOAD_FOLDER, filename)
    if not path or not os.path.isfile(path):
        return jsonify({"error": "الملف غير موجود"}), 404
    return send_file(path, as_attachment=True)


@app.route("/api/downloads/<path:filename>", methods=["DELETE"])
def delete_download(filename):
    path = safe_join(DOWNLOAD_FOLDER, filename)
    if not path or not os.path.isfile(path):
        return jsonify({"error": "الملف غير موجود"}), 404
    try:
        os.remove(path)
        return jsonify({"status": "deleted"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/download", methods=["POST"])
def download_video():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    format_type = data.get("format", "mp4_high")
    task_id = data.get("task_id") or uuid.uuid4().hex

    if not url:
        return jsonify({"error": "الرابط مطلوب"}), 400

    download_progress[task_id] = "0%"

    # رابط مباشر -> استخدمه كما هو ; عبارة بحث -> بحث يوتيوب (yt-dlp)
    target_url = url if URL_PATTERN.match(url) else f"ytsearch:{url}"

  ydl_opts = {
    "outtmpl": os.path.join(DOWNLOAD_FOLDER, "%(title)s.%(ext)s"),
    "quiet": True,
    "noplaylist": True,
    "progress_hooks": [progress_hook(task_id)],
    "ffmpeg_location": imageio_ffmpeg.get_ffmpeg_exe(),  # هذا هو السطر السحري الجديد
}
    ydl_opts.update(format_options(format_type))

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(target_url, download=True)
            filename = ydl.prepare_filename(info)
            if format_type == "mp3":
                filename = filename.rsplit(".", 1)[0] + ".mp3"

        if not os.path.isfile(filename):
            return jsonify({"error": "لم يتم العثور على الملف بعد التحميل"}), 500

        download_progress[task_id] = "100%"
        return send_file(filename, as_attachment=True)

    except Exception as e:
        download_progress[task_id] = "Error"
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    # جلب المنفذ من الخادم السحابي، وإذا لم يوجد نستخدم 5000 مؤقتاً
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
