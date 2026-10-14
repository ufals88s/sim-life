#!/usr/bin/env python3
"""Extract reviewable evidence from a short vertical product clip (Shopee Video / TikTok / Reels).

Produces, inside OUT_DIR:
  frames/f_001.jpg ...        1 frame per second (f_001 ~ t=0s)
  sheet_p1.jpg ...            timestamped contact sheets (18 frames each) - open these with an image viewer / Read tool
  hook_strip.jpg              first 3.2 s at 2.5 fps (8 frames, left to right)
  metrics.json                duration, scene cuts, avg shot length, loudness, speech timing (if VAD available)
  transcript.json / .txt      Thai transcript (only if --whisper-dir is given and sherpa-onnx is installed)

Requirements: ffmpeg + ffprobe on PATH, Pillow. Optional for speech: `pip install sherpa-onnx soundfile numpy`
and a Whisper model folder from
https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-whisper-large-v3.tar.bz2
(plus silero_vad.onnx from the same release page for speech-timing stats).

Usage:
  python3 extract_evidence.py CLIP.mp4 OUT_DIR [--whisper-dir DIR] [--vad PATH/silero_vad.onnx] [--lang th]
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def probe_duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path])
    return float(r.stdout.strip())


def scene_cuts(path, threshold=0.30):
    r = run(["ffmpeg", "-v", "info", "-i", path, "-vf", f"select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-"])
    return [round(float(x), 2) for x in re.findall(r"pts_time:([0-9.]+)", r.stderr)]


def loudness(path):
    r = run(["ffmpeg", "-v", "info", "-i", path, "-af", "ebur128", "-f", "null", "-"])
    m = re.findall(r"I:\s+(-?[0-9.]+) LUFS", r.stderr)
    return float(m[-1]) if m else None


def contact_sheets(frame_dir, out_dir, per_sheet=18, cols=6):
    from PIL import Image, ImageDraw
    files = sorted(glob.glob(os.path.join(frame_dir, "f_*.jpg")))
    sheets = []
    for p, start in enumerate(range(0, len(files), per_sheet), 1):
        chunk = files[start:start + per_sheet]
        w, h = Image.open(chunk[0]).size
        rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * w, rows * (h + 18)), "white")
        draw = ImageDraw.Draw(sheet)
        for i, f in enumerate(chunk):
            x, y = (i % cols) * w, (i // cols) * (h + 18)
            sheet.paste(Image.open(f), (x, y + 18))
            draw.text((x + 4, y + 3), f"t={start + i}s", fill="black")
        out = os.path.join(out_dir, f"sheet_p{p}.jpg")
        sheet.save(out, quality=85)
        sheets.append(out)
    return sheets


def speech_stats(wav, vad_model):
    import numpy as np
    import sherpa_onnx
    import soundfile as sf
    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = vad_model
    cfg.silero_vad.min_silence_duration = 0.25
    cfg.silero_vad.min_speech_duration = 0.2
    cfg.sample_rate = 16000
    audio, _ = sf.read(wav, dtype="float32")
    vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=180)
    segs = []
    ws = cfg.silero_vad.window_size
    for i in range(0, len(audio), ws):
        vad.accept_waveform(audio[i:i + ws])
        while not vad.empty():
            segs.append((vad.front.start, vad.front.start + len(vad.front.samples)))
            vad.pop()
    vad.flush()
    while not vad.empty():
        segs.append((vad.front.start, vad.front.start + len(vad.front.samples)))
        vad.pop()
    mask = np.zeros(len(audio), bool)
    for a, b in segs:
        mask[a:b] = True
    return {
        "first_speech_s": round(segs[0][0] / 16000, 2) if segs else None,
        "speech_coverage": round(float(mask.mean()), 3),
        "speech_segments_s": [[round(a / 16000, 2), round(b / 16000, 2)] for a, b in segs],
    }


def transcribe(wav, model_dir, lang):
    """Whisper via sherpa-onnx, chunked at quiet points (3.5-7 s).

    sherpa-onnx caps decoding at ~6 tokens per second of input audio; Thai needs far more,
    so each chunk is zero-padded to ~29 s. Without the padding, Thai text gets cut off mid-sentence.
    """
    import numpy as np
    import sherpa_onnx
    import soundfile as sf
    pre = os.path.basename(model_dir.rstrip("/")).replace("sherpa-onnx-whisper-", "")
    rec = sherpa_onnx.OfflineRecognizer.from_whisper(
        encoder=os.path.join(model_dir, f"{pre}-encoder.int8.onnx"),
        decoder=os.path.join(model_dir, f"{pre}-decoder.int8.onnx"),
        tokens=os.path.join(model_dir, f"{pre}-tokens.txt"),
        language=lang, task="transcribe", num_threads=os.cpu_count() or 4)
    sr, hop = 16000, 320
    audio, _ = sf.read(wav, dtype="float32")
    e = np.array([np.sqrt(np.mean(audio[i:i + hop] ** 2) + 1e-12) for i in range(0, len(audio), hop)])
    e = np.convolve(e, np.ones(5) / 5, mode="same")
    bounds, s, n = [], 0, len(e)
    while s < n:
        if (n - s) * hop / sr <= 7.0:
            bounds.append((s, n))
            break
        a, b = s + int(3.5 * sr / hop), min(n, s + int(7.0 * sr / hop))
        cut = a + int(np.argmin(e[a:b]))
        bounds.append((s, cut))
        s = cut
    out = []
    for a, b in bounds:
        seg = audio[a * hop:b * hop]
        if len(seg) == 0:
            continue
        if np.sqrt(np.mean(seg ** 2)) < 0.003:
            out.append({"start": round(a * hop / sr, 2), "end": round(b * hop / sr, 2), "text": "(silence)"})
            continue
        st = rec.create_stream()
        st.accept_waveform(sr, np.concatenate([seg, np.zeros(max(0, 29 * sr - len(seg)), dtype=np.float32)]))
        rec.decode_stream(st)
        out.append({"start": round(a * hop / sr, 2), "end": round(b * hop / sr, 2), "text": st.result.text.strip()})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clip")
    ap.add_argument("out_dir")
    ap.add_argument("--whisper-dir", help="sherpa-onnx Whisper model folder (e.g. sherpa-onnx-whisper-large-v3)")
    ap.add_argument("--vad", help="path to silero_vad.onnx for speech timing stats")
    ap.add_argument("--lang", default="th")
    args = ap.parse_args()

    out = os.path.abspath(args.out_dir)
    frames = os.path.join(out, "frames")
    os.makedirs(frames, exist_ok=True)

    run(["ffmpeg", "-v", "error", "-y", "-i", args.clip, "-vf", "fps=1,scale=240:-1", os.path.join(frames, "f_%03d.jpg")])
    run(["ffmpeg", "-v", "error", "-y", "-t", "3.2", "-i", args.clip, "-vf", "fps=2.5,scale=320:-1,tile=8x1",
         "-frames:v", "1", os.path.join(out, "hook_strip.jpg")])
    sheets = contact_sheets(frames, out)

    duration = probe_duration(args.clip)
    cuts = scene_cuts(args.clip)
    metrics = {
        "clip": os.path.abspath(args.clip),
        "duration_s": round(duration, 2),
        "scene_cuts_s": cuts,
        "cuts_count": len(cuts),
        "avg_shot_len_s": round(duration / (len(cuts) + 1), 2),
        "integrated_loudness_lufs": loudness(args.clip),
        "contact_sheets": sheets,
        "hook_strip": os.path.join(out, "hook_strip.jpg"),
        "note": "Downloaded Shopee clips end with ~3 s orange 'Shopee Video' outro; exclude it from content length.",
    }

    if args.whisper_dir or args.vad:
        wav = os.path.join(out, "audio16k.wav")
        run(["ffmpeg", "-v", "error", "-y", "-i", args.clip, "-ac", "1", "-ar", "16000", wav])
        try:
            if args.vad:
                metrics.update(speech_stats(wav, args.vad))
            if args.whisper_dir:
                tr = transcribe(wav, args.whisper_dir, args.lang)
                json.dump(tr, open(os.path.join(out, "transcript.json"), "w"), ensure_ascii=False, indent=1)
                with open(os.path.join(out, "transcript.txt"), "w") as f:
                    for t in tr:
                        f.write(f"[{t['start']:6.2f}-{t['end']:6.2f}] {t['text']}\n")
                chars = sum(len(t["text"].replace(" ", "")) for t in tr if t["text"] != "(silence)")
                audio_len = tr[-1]["end"] if tr else duration  # audio stops before the silent Shopee outro
                metrics["speech_chars_per_s"] = round(chars / max(audio_len, 1e-6), 1)
        except ImportError as exc:
            metrics["speech_error"] = f"sherpa-onnx/soundfile/numpy not installed: {exc}"

    json.dump(metrics, open(os.path.join(out, "metrics.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in metrics.items() if k != "speech_segments_s"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(main())
