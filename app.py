import glob
import os
import re
import shutil
import threading
import uuid
from urllib.parse import urlparse

import yt_dlp
from flask import Flask, after_this_request, jsonify, request, send_file

HOST = "127.0.0.1"
PORT = 5000

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024  # request bodies are tiny JSON

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

ALLOWED_FORMATS = {"best_mp4", "1080p", "720p", "mp3"}
MAX_URL_LENGTH = 2048
MAX_CONCURRENT_JOBS = 2
# Only requests addressed to this machine are served. This blocks DNS-rebinding
# attacks, where a hostile web page points its own domain at 127.0.0.1.
ALLOWED_HOSTS = {HOST, "localhost", f"{HOST}:{PORT}", f"localhost:{PORT}"}

PARTIAL_SUFFIXES = (".part", ".ytdl", ".temp")
# yt-dlp intermediate streams look like "name.f137.mp4"
INTERMEDIATE_RE = re.compile(r"\.f[\w-]+\.\w+$")

_job_slots = threading.BoundedSemaphore(MAX_CONCURRENT_JOBS)

if shutil.which("ffmpeg") is None:
    app.logger.warning(
        "ffmpeg was not found on PATH. MP3 conversion and MP4 merging will fail. "
        "Install it with: brew install ffmpeg"
    )

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="dark light">
<title>Clean Media Downloader</title>
<style>
  :root {
    --bg: #14171a;
    --panel: #1c2024;
    --panel-2: #23282d;
    --line: #2f353b;
    --text: #e8eaed;
    --muted: #8f99a3;
    --accent: #ffb000;
    --accent-ink: #1a1200;
    --accent-glow: rgba(255, 176, 0, 0.35);
    --danger: #ff7a6b;
    --ok: #6fd3a0;
    --radius: 10px;
    --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  }
  @media (prefers-color-scheme: light) {
    :root {
      --bg: #eceeed;
      --panel: #f8f9f8;
      --panel-2: #e3e6e5;
      --line: #cfd4d3;
      --text: #181b1d;
      --muted: #5b6770;
      --accent: #b86e00;
      --accent-ink: #ffffff;
      --accent-glow: rgba(184, 110, 0, 0.18);
      --danger: #b3261e;
      --ok: #1d7a4c;
    }
  }
  * { box-sizing: border-box; }
  html { -webkit-text-size-adjust: 100%; }
  body {
    margin: 0;
    min-height: 100vh;
    background: var(--bg);
    color: var(--text);
    font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
    display: flex;
    justify-content: center;
    padding: 3.5rem 1.25rem 3rem;
  }
  main { width: 100%; max-width: 560px; }
  header { margin-bottom: 1.75rem; }
  h1 { margin: 0; font-size: 1.6rem; font-weight: 650; letter-spacing: -0.02em; }
  .sub { margin: 0.35rem 0 0; color: var(--muted); font-size: 0.95rem; }

  .readout {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 1.1rem 1.25rem 1rem;
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.25rem 1.25rem;
    align-items: center;
    margin-bottom: 1.25rem;
  }
  .counter {
    grid-row: span 2;
    font: 600 2.6rem/1 var(--mono);
    font-variant-numeric: tabular-nums;
    letter-spacing: 0.02em;
    color: var(--muted);
    transition: color .2s, text-shadow .2s;
  }
  .readout.busy .counter { color: var(--accent); text-shadow: 0 0 18px var(--accent-glow); }
  .readout.done .counter { color: var(--ok); }
  .readout.error .counter { color: var(--danger); }
  #status { font-weight: 550; overflow-wrap: anywhere; }
  #detail { color: var(--muted); font-size: 0.88rem; overflow-wrap: anywhere; }

  form { display: grid; gap: 1.1rem; }
  label.field, legend { font-size: 0.88rem; font-weight: 600; color: var(--muted); padding: 0; }
  .url-row { display: flex; gap: 0.5rem; margin-top: 0.4rem; }
  input[type="text"] {
    flex: 1; min-width: 0;
    background: var(--panel); color: var(--text);
    border: 1px solid var(--line); border-radius: var(--radius);
    padding: 0.8rem 0.9rem; font: inherit;
  }
  input[type="text"]::placeholder { color: var(--muted); opacity: .8; }
  button, .tile { font: inherit; }
  .ghost {
    background: var(--panel-2); color: var(--text);
    border: 1px solid var(--line); border-radius: var(--radius);
    padding: 0 1rem; cursor: pointer; font-weight: 550;
  }
  .ghost:hover { border-color: var(--muted); }

  fieldset { border: 0; margin: 0; padding: 0; }
  .tiles { display: grid; grid-template-columns: 1fr 1fr; gap: 0.6rem; margin-top: 0.4rem; }
  .tile { position: relative; }
  .tile input { position: absolute; opacity: 0; inset: 0; width: 100%; height: 100%; margin: 0; cursor: pointer; }
  .tile span {
    display: block; height: 100%;
    background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius);
    padding: 0.7rem 0.9rem; transition: border-color .15s, background .15s;
  }
  .tile b { display: block; font-weight: 650; }
  .tile small { color: var(--muted); font-size: 0.82rem; }
  .tile:hover span { border-color: var(--muted); }
  .tile input:checked + span { border-color: var(--accent); background: var(--panel-2); box-shadow: inset 0 0 0 1px var(--accent); }
  .tile input:focus-visible + span { outline: 2px solid var(--accent); outline-offset: 2px; }

  #btn {
    background: var(--accent); color: var(--accent-ink);
    border: 0; border-radius: var(--radius);
    padding: 0.95rem 1rem; font-size: 1.05rem; font-weight: 700; cursor: pointer;
  }
  #btn:hover:not(:disabled) { filter: brightness(1.08); }
  #btn:disabled { background: var(--panel-2); color: var(--muted); cursor: progress; }
  :is(#btn, .ghost, input[type="text"]):focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

  .history { margin-top: 2rem; }
  .history h2 { font-size: 0.88rem; color: var(--muted); font-weight: 600; margin: 0 0 0.5rem; }
  .history ul { list-style: none; margin: 0; padding: 0; border-top: 1px solid var(--line); }
  .history li { display: flex; justify-content: space-between; gap: 1rem; padding: 0.55rem 0; border-bottom: 1px solid var(--line); font-size: 0.92rem; }
  .history .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .history .meta { color: var(--muted); white-space: nowrap; font-variant-numeric: tabular-nums; }
  footer { margin-top: 2rem; color: var(--muted); font-size: 0.8rem; }

  @media (max-width: 440px) {
    .readout { grid-template-columns: 1fr; }
    .counter { grid-row: auto; font-size: 2.2rem; }
  }
  @media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style>
</head>
<body>
<main>
  <header>
    <h1>Reliable Video &amp; Audio Downloader</h1>
    <p class="sub">Paste a link, pick a format, and the file lands in your Downloads folder.</p>
  </header>

  <section class="readout" id="readout" aria-live="polite">
    <div class="counter" id="counter">00:00</div>
    <div id="status">Ready</div>
    <div id="detail">Waiting for a link.</div>
  </section>

  <form id="form" novalidate>
    <div>
      <label class="field" for="url">Video or audio URL</label>
      <div class="url-row">
        <input type="text" id="url" placeholder="https://" autocomplete="off" autocapitalize="off" spellcheck="false" inputmode="url" required>
        <button type="button" class="ghost" id="paste">Paste</button>
      </div>
    </div>

    <fieldset>
      <legend>Format</legend>
      <div class="tiles">
        <label class="tile"><input type="radio" name="format" value="best_mp4" checked><span><b>Best video</b><small>MP4, up to 4K</small></span></label>
        <label class="tile"><input type="radio" name="format" value="1080p"><span><b>1080p</b><small>MP4</small></span></label>
        <label class="tile"><input type="radio" name="format" value="720p"><span><b>720p</b><small>MP4, smaller file</small></span></label>
        <label class="tile"><input type="radio" name="format" value="mp3"><span><b>Audio only</b><small>MP3, 320 kbps</small></span></label>
      </div>
    </fieldset>

    <button type="submit" id="btn">Download</button>
  </form>

  <section class="history" id="history" hidden>
    <h2>This session</h2>
    <ul id="historyList"></ul>
  </section>

  <footer>Runs only on this computer. Files are removed from the server once they reach your browser.</footer>
</main>

<script>
  const $ = (id) => document.getElementById(id);
  const readout = $('readout'), counter = $('counter'), statusEl = $('status'), detail = $('detail');
  const btn = $('btn'), urlInput = $('url');
  let timer = null;

  function fmtTime(s) {
    const m = Math.floor(s / 60), r = s % 60;
    return String(m).padStart(2, '0') + ':' + String(r).padStart(2, '0');
  }
  function fmtSize(bytes) {
    if (bytes < 1024 * 1024) return Math.max(1, Math.round(bytes / 1024)) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  }
  function setState(state, title, text) {
    readout.className = 'readout' + (state ? ' ' + state : '');
    statusEl.textContent = title;
    detail.textContent = text;
  }
  function startTimer() {
    const t0 = Date.now();
    counter.textContent = '00:00';
    timer = setInterval(() => { counter.textContent = fmtTime(Math.floor((Date.now() - t0) / 1000)); }, 250);
  }
  function stopTimer() { clearInterval(timer); timer = null; }

  function parseFilename(header) {
    if (!header) return null;
    let m = /filename\*=UTF-8''([^;]+)/i.exec(header);
    if (m) { try { return decodeURIComponent(m[1]); } catch (e) { /* fall through */ } }
    m = /filename="?([^";]+)"?/i.exec(header);
    return m ? m[1] : null;
  }
  function addHistory(name, size) {
    $('history').hidden = false;
    const li = document.createElement('li');
    const n = document.createElement('span'); n.className = 'name'; n.textContent = name; n.title = name;
    const s = document.createElement('span'); s.className = 'meta'; s.textContent = fmtSize(size);
    li.append(n, s);
    $('historyList').prepend(li);
  }

  $('paste').addEventListener('click', async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) { urlInput.value = text.trim(); urlInput.focus(); }
    } catch (e) {
      setState('', 'Clipboard unavailable', 'Allow clipboard access, or paste with Cmd+V.');
    }
  });

  $('form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const url = urlInput.value.trim();
    const format = document.querySelector('input[name="format"]:checked').value;

    if (!url) {
      setState('error', 'Link needed', 'Paste a video or audio URL first.');
      urlInput.focus();
      return;
    }

    btn.disabled = true;
    btn.textContent = 'Working...';
    setState('busy', 'Downloading', 'The server is fetching and converting the media. Large files can take a few minutes.');
    startTimer();

    try {
      const res = await fetch('/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, format })
      });

      if (!res.ok) {
        let message = 'Download failed';
        try { message = (await res.json()).error || message; } catch (e) { /* non-JSON error */ }
        throw new Error(message);
      }

      const blob = await res.blob();
      const filename = parseFilename(res.headers.get('Content-Disposition')) || 'media_download';

      const a = document.createElement('a');
      const objectUrl = URL.createObjectURL(blob);
      a.href = objectUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 10000);

      stopTimer();
      setState('done', 'Download complete', filename + ' (' + fmtSize(blob.size) + ')');
      addHistory(filename, blob.size);
    } catch (e) {
      stopTimer();
      setState('error', 'Download failed', e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Download';
    }
  });
</script>
</body>
</html>
"""


def error(message, status):
    return jsonify({"error": message}), status


@app.before_request
def only_local_hosts():
    if request.host not in ALLOWED_HOSTS:
        return error("Invalid host", 400)


@app.errorhandler(404)
def not_found(_e):
    return error("Not found", 404)


@app.errorhandler(405)
def method_not_allowed(_e):
    return error("Method not allowed", 405)


@app.errorhandler(413)
def too_large(_e):
    return error("Request too large", 413)


@app.route("/")
def index():
    return HTML_TEMPLATE


def pick_output(job_pattern, fmt):
    """Return the finished file for this job, or None if nothing usable exists."""
    wanted = ".mp3" if fmt == "mp3" else ".mp4"
    files = [
        p for p in glob.glob(job_pattern)
        if os.path.isfile(p)
        and not p.endswith(PARTIAL_SUFFIXES)
        and not INTERMEDIATE_RE.search(p)
    ]
    preferred = [p for p in files if p.lower().endswith(wanted)]
    pool = preferred or files
    return max(pool, key=os.path.getsize) if pool else None


@app.route("/download", methods=["POST"])
def download():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    url = data.get("url")
    fmt = data.get("format", "best_mp4")

    if not url or not isinstance(url, str):
        return error("No URL provided", 400)
    url = url.strip()
    if len(url) > MAX_URL_LENGTH or urlparse(url).scheme not in ("http", "https"):
        return error("Enter a valid http or https URL", 400)

    if fmt not in ALLOWED_FORMATS:
        return error("Invalid format", 400)

    if shutil.which("ffmpeg") is None:
        app.logger.error("ffmpeg not found on PATH")
        return error("ffmpeg is not installed on the server. Run: brew install ffmpeg", 503)

    if not _job_slots.acquire(blocking=False):
        return error("The server is busy with other downloads. Try again shortly.", 429)

    job_id = uuid.uuid4().hex[:8]
    output_template = os.path.join(DOWNLOAD_DIR, f"{job_id}_%(title)s.%(ext)s")
    # job_id is hex, but DOWNLOAD_DIR is arbitrary, so escape glob characters in it
    job_pattern = os.path.join(glob.escape(DOWNLOAD_DIR), f"{job_id}_*")

    ydl_opts = {
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": True,
        "noprogress": True,
        "socket_timeout": 30,
    }

    if fmt == "mp3":
        ydl_opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            }],
        })
    elif fmt == "1080p":
        ydl_opts.update({
            "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best",
            "merge_output_format": "mp4",
        })
    elif fmt == "720p":
        ydl_opts.update({
            "format": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best",
            "merge_output_format": "mp4",
        })
    else:
        ydl_opts.update({
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "merge_output_format": "mp4",
        })

    def cleanup_job_files():
        # Removes only files carrying this request's unique job_id prefix:
        # the final file plus any .part / intermediate leftovers.
        for path in glob.glob(job_pattern):
            try:
                os.remove(path)
            except OSError:
                app.logger.exception("Could not remove %s", path)

    try:
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)
        finally:
            _job_slots.release()

        downloaded_file = pick_output(job_pattern, fmt)
        if downloaded_file is None:
            cleanup_job_files()
            return error("Download finished but no output file was found", 500)

        clean_name = os.path.basename(downloaded_file).split("_", 1)[-1]

        @after_this_request
        def remove_file(response):
            cleanup_job_files()
            return response

        return send_file(downloaded_file, as_attachment=True, download_name=clean_name)

    except Exception:
        app.logger.exception("Download failed (format=%s)", fmt)
        cleanup_job_files()
        return error("Download failed. Check the URL and try again.", 500)


if __name__ == "__main__":
    app.run(host=HOST, port=PORT)
