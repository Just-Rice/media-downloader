# Media Downloader

A small Flask app that wraps [yt-dlp](https://github.com/yt-dlp/yt-dlp) to download video (MP4) or audio (MP3) from a URL. Intended for personal use on your own machine.

The server binds to `127.0.0.1:5000` only, so it is reachable from this computer and not from the rest of your network.

## Requirements

- Python 3
- [Homebrew](https://brew.sh) (macOS)
- **ffmpeg** — required. yt-dlp uses it to convert audio to MP3 and to merge separate video and audio streams into one MP4. Without it, MP3 and the higher-quality MP4 options will fail.

```bash
brew install ffmpeg
```

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
./run.sh
```

Then open <http://127.0.0.1:5000>, paste a video URL, pick a format and click Download.

`run.sh` activates the virtual environment and starts `app.py`. Stop it with Ctrl+C.

> **Use `127.0.0.1`, not `localhost`.** On recent macOS the AirPlay Receiver also listens on port 5000, and `localhost` can resolve to it (you will see a blank 403 page). Either open the `127.0.0.1` address above, or turn off System Settings > General > AirDrop & Handoff > AirPlay Receiver.

## Formats

| Value       | Result                          |
|-------------|---------------------------------|
| `best_mp4`  | Best available MP4              |
| `1080p`     | MP4, up to 1080p                |
| `720p`      | MP4, up to 720p                 |
| `mp3`       | Audio only, MP3 320 kbps        |

Any other value is rejected with HTTP 400.

## Notes

- Files are written to `downloads/` while a request is processed and are deleted once they have been sent to your browser.
- Errors are logged in the terminal running the app; the browser only sees a generic message.
- Only http(s) URLs are accepted, requests must be addressed to `127.0.0.1` or `localhost`, and at most 2 downloads run at once.
- `requirements.txt` installs `yt-dlp[default]`, which includes `certifi`. This matters for the python.org build of Python, which ships without a CA bundle and otherwise fails every HTTPS request with `CERTIFICATE_VERIFY_FAILED`.
- yt-dlp may warn that no JavaScript runtime was found. YouTube works without one, but some formats can be missing. `brew install deno` removes the warning.
- yt-dlp breaks when sites change. If downloads start failing, upgrade it: `source venv/bin/activate && pip install -U yt-dlp`, then update the pin in `requirements.txt`.
- Only download content you have the right to download.
