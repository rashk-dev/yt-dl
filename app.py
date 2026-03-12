import os
import json
import threading
import uuid
from flask import Flask, request, jsonify, send_file, render_template_string
import yt_dlp

app = Flask(__name__)

DOWNLOAD_DIR = "/home/claude/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Track job progress
jobs = {}

def get_ydl_opts(fmt, quality, job_id, output_path):
    def progress_hook(d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            downloaded = d.get('downloaded_bytes', 0)
            if total:
                pct = int(downloaded / total * 100)
                jobs[job_id]['progress'] = pct
                jobs[job_id]['speed'] = d.get('_speed_str', '')
                jobs[job_id]['eta'] = d.get('_eta_str', '')
        elif d['status'] == 'finished':
            jobs[job_id]['progress'] = 95
            jobs[job_id]['status'] = 'processing'

    if fmt == 'audio':
        return {
            'format': 'bestaudio/best',
            'outtmpl': output_path + '/%(title)s.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'progress_hooks': [progress_hook],
        }
    else:
        quality_map = {
            '4k': 'bestvideo[height<=2160]+bestaudio/best',
            '1080p': 'bestvideo[height<=1080]+bestaudio/best',
            '720p': 'bestvideo[height<=720]+bestaudio/best',
            '480p': 'bestvideo[height<=480]+bestaudio/best',
            '360p': 'bestvideo[height<=360]+bestaudio/best',
        }
        fmt_str = quality_map.get(quality, 'bestvideo+bestaudio/best')
        return {
            'format': fmt_str,
            'outtmpl': output_path + '/%(title)s.%(ext)s',
            'merge_output_format': 'mp4',
            'progress_hooks': [progress_hook],
        }

def download_task(job_id, url, fmt, quality):
    try:
        output_path = os.path.join(DOWNLOAD_DIR, job_id)
        os.makedirs(output_path, exist_ok=True)
        opts = get_ydl_opts(fmt, quality, job_id, output_path)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'video')
        # Find downloaded file
        files = os.listdir(output_path)
        if files:
            jobs[job_id]['status'] = 'done'
            jobs[job_id]['progress'] = 100
            jobs[job_id]['filename'] = files[0]
            jobs[job_id]['title'] = title
        else:
            jobs[job_id]['status'] = 'error'
            jobs[job_id]['error'] = 'No file found after download'
    except Exception as e:
        jobs[job_id]['status'] = 'error'
        jobs[job_id]['error'] = str(e)

@app.route('/')
def index():
    return render_template_string(open('/home/claude/index.html').read())

@app.route('/api/info', methods=['POST'])
def get_info():
    data = request.json
    url = data.get('url', '')
    try:
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)
        formats = []
        seen = set()
        for f in info.get('formats', []):
            h = f.get('height')
            if h and h not in seen:
                seen.add(h)
                formats.append({'height': h, 'label': f'{h}p'})
        formats.sort(key=lambda x: x['height'], reverse=True)
        return jsonify({
            'title': info.get('title'),
            'thumbnail': info.get('thumbnail'),
            'duration': info.get('duration_string') or str(info.get('duration', '')),
            'uploader': info.get('uploader'),
            'view_count': info.get('view_count'),
            'formats': formats,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/download', methods=['POST'])
def start_download():
    data = request.json
    url = data.get('url')
    fmt = data.get('format', 'video')
    quality = data.get('quality', '1080p')
    job_id = str(uuid.uuid4())
    jobs[job_id] = {'status': 'downloading', 'progress': 0, 'speed': '', 'eta': ''}
    t = threading.Thread(target=download_task, args=(job_id, url, fmt, quality))
    t.daemon = True
    t.start()
    return jsonify({'job_id': job_id})

@app.route('/api/progress/<job_id>')
def get_progress(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify(job)

@app.route('/api/file/<job_id>')
def get_file(job_id):
    job = jobs.get(job_id)
    if not job or job['status'] != 'done':
        return jsonify({'error': 'Not ready'}), 404
    path = os.path.join(DOWNLOAD_DIR, job_id, job['filename'])
    return send_file(path, as_attachment=True, download_name=job['filename'])

if __name__ == '__main__':
    app.run(debug=False, port=5000)
