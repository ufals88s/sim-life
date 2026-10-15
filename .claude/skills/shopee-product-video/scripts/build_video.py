#!/usr/bin/env python3
"""Assemble a 9:16 product video from an edit plan (images and/or clips + per-beat voiceover).

Each beat is one voiceover line (an audio file). The beat's shots share the beat's duration, so every
cut lands on the start of a spoken line. A Thai headline is burned in from frame 0 with libass
(HarfBuzz shaping, so Thai vowels and tone marks render correctly).

Usage:
  python3 build_video.py PLAN.json [--keep-temp]

Plan format (paths are relative to the plan file): see references/edit-plan.md
Outputs: <output>.mp4, <output>.timeline.json, <output>.srt (voiceover text, for captions or checking)
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import numpy as np
import soundfile as sf
from PIL import Image, ImageFilter, ImageOps

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_FONT_DIR = os.path.join(SKILL_DIR, "assets", "fonts")
SR = 48000

# Camera moves for still images: zoom (start, end) and window centre fx, fy (start, end) as 0-1 of the frame.
MOTIONS = {
    "push_in": {"z": [1.0, 1.15], "fx": [0.5, 0.5], "fy": [0.5, 0.5]},
    "pull_out": {"z": [1.15, 1.0], "fx": [0.5, 0.5], "fy": [0.5, 0.5]},
    "pan_left": {"z": [1.15, 1.15], "fx": [0.62, 0.38], "fy": [0.5, 0.5]},
    "pan_right": {"z": [1.15, 1.15], "fx": [0.38, 0.62], "fy": [0.5, 0.5]},
    "pan_up": {"z": [1.15, 1.15], "fx": [0.5, 0.5], "fy": [0.62, 0.38]},
    "pan_down": {"z": [1.15, 1.15], "fx": [0.5, 0.5], "fy": [0.38, 0.62]},
    "still": {"z": [1.02, 1.05], "fx": [0.5, 0.5], "fy": [0.5, 0.5]},
}


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.stderr.write(" ".join(cmd) + "\n" + r.stderr[-3000:] + "\n")
        raise SystemExit(f"command failed: {cmd[0]}")
    return r


def probe_duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path])
    return float(r.stdout.strip())


def atempo_chain(tempo):
    """ffmpeg atempo accepts 0.5-2.0 per stage; chain stages for anything outside that."""
    parts, t = [], tempo
    while t > 2.0:
        parts.append("atempo=2.0"); t /= 2.0
    while t < 0.5:
        parts.append("atempo=0.5"); t /= 0.5
    parts.append(f"atempo={t:.4f}")
    return ",".join(parts)


def prepare_beat_audio(src, dst, tempo, trim_db):
    """Trim leading/trailing silence, speed up without changing pitch, resample to 48 kHz mono."""
    trim = (f"silenceremove=start_periods=1:start_threshold={trim_db}dB:start_silence=0.02,areverse,"
            f"silenceremove=start_periods=1:start_threshold={trim_db}dB:start_silence=0.04,areverse")
    af = trim + ("," + atempo_chain(tempo) if abs(tempo - 1.0) > 1e-3 else "")
    run(["ffmpeg", "-v", "error", "-y", "-i", src, "-af", af, "-ar", str(SR), "-ac", "1", dst])
    audio, _ = sf.read(dst, dtype="float32")
    return audio


def composite_still(src, dst, w, h, fit):
    """Render a still at 2x output size: 'cover' crops to fill, 'fit' puts the whole product on a blurred backdrop."""
    W, H = w * 2, h * 2
    img = ImageOps.exif_transpose(Image.open(src)).convert("RGBA")
    aspect = img.width / img.height
    if fit == "auto":
        fit = "cover" if 0.5 <= aspect <= 0.65 else "fit"
    bg = ImageOps.fit(img.convert("RGB"), (W, H), Image.LANCZOS)
    if fit == "cover":
        bg.save(dst)
        return
    bg = bg.filter(ImageFilter.GaussianBlur(60)).point(lambda v: int(v * 0.55 + 20))
    scale = min(W * 0.94 / img.width, H * 0.62 / img.height)
    fg = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS)
    x = (W - fg.width) // 2
    y = int(H * 0.56 - fg.height / 2)  # keep the top band (10-30%) free for the headline
    bg.paste(fg, (x, y), fg)
    bg.save(dst)


def render_still(src, dst, frames, cfg, tmp, idx):
    w, h, fps = cfg["width"], cfg["height"], cfg["fps"]
    comp = os.path.join(tmp, f"still_{idx}.png")
    composite_still(src, comp, w, h, cfg.get("fit", "auto"))
    m = dict(MOTIONS.get(cfg.get("motion", "push_in"), MOTIONS["push_in"]))
    for k in ("z", "fx", "fy"):
        if k in cfg:
            m[k] = cfg[k]
    n = max(frames - 1, 1)
    p = f"(on/{n})"
    e = f"({p}*{p}*(3-2*{p}))"  # smoothstep easing
    z = f"({m['z'][0]}+({m['z'][1]}-{m['z'][0]})*{e})"
    fx = f"({m['fx'][0]}+({m['fx'][1]}-{m['fx'][0]})*{e})"
    fy = f"({m['fy'][0]}+({m['fy'][1]}-{m['fy'][0]})*{e})"
    x = f"max(0,min(iw-iw/zoom,{fx}*iw-iw/zoom/2))"
    y = f"max(0,min(ih-ih/zoom,{fy}*ih-ih/zoom/2))"
    vf = f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={fps},format=yuv420p"
    run(["ffmpeg", "-v", "error", "-y", "-i", comp, "-vf", vf, "-frames:v", str(frames),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-r", str(fps), dst])


def render_clip(src, dst, frames, cfg):
    """Trim a video clip to the shot length, fill 9:16 (crop or blurred backdrop), freeze the last frame if short."""
    w, h, fps = cfg["width"], cfg["height"], cfg["fps"]
    start, speed = float(cfg.get("start", 0)), float(cfg.get("speed", 1.0))
    dur = frames / fps
    fill = cfg.get("fit", "cover")
    if fill == "fit":
        chain = (f"split[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=30:5,"
                 f"eq=brightness=-0.08[bg];[b]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
                 f"[bg][fg]overlay=(W-w)/2:(H-h)/2")
    else:
        chain = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    vf = (f"setpts=(PTS-STARTPTS)/{speed},{chain},fps={fps},tpad=stop_mode=clone:stop_duration={dur:.3f},"
          f"format=yuv420p")
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-i", src, "-an", "-filter_complex", vf,
         "-frames:v", str(frames), "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-r", str(fps), dst])


def ass_time(t):
    t = max(0.0, t)
    hh, rem = divmod(t, 3600)
    mm, ss = divmod(rem, 60)
    return f"{int(hh)}:{int(mm):02d}:{ss:05.2f}"


def ass_color(hex_rgb):
    hex_rgb = hex_rgb.lstrip("#")
    r, g, b = hex_rgb[0:2], hex_rgb[2:4], hex_rgb[4:6]
    return f"&H00{b}{g}{r}&".upper()


def write_ass(path, cfg, headline_windows, labels):
    w, h = cfg["width"], cfg["height"]
    hl = cfg.get("headline", {})
    font = hl.get("font", "Kanit")
    sizes = hl.get("sizes", [104, 84])  # line 1 ends up ~50-60% of the frame width, like the reference clips
    colors = hl.get("colors", ["FFFFFF", "FFE14D"])
    margin_v = int(h * float(hl.get("top", 0.12)))
    lines = []
    for i, text in enumerate(hl.get("lines", [])):
        size = sizes[min(i, len(sizes) - 1)]
        col = ass_color(colors[min(i, len(colors) - 1)])
        lines.append(f"{{\\fs{size}\\c{col}}}{text}")
    body = "\\N".join(lines)
    out = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}", "WrapStyle: 2",
        "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Headline,{font},{sizes[0]},&H00FFFFFF,&H00FFFFFF,&H00101010,&H64000000,-1,0,0,0,100,100,0,0,1,"
        f"{hl.get('outline', 6)},2,8,60,60,{margin_v},1",
        f"Style: Label,{font},64,&H00FFFFFF,&H00FFFFFF,&H00101010,&H64000000,-1,0,0,0,100,100,0,0,1,5,2,5,60,60,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if body:
        for a, b in headline_windows:
            out.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Headline,,0,0,0,,{body}")
    for lb in labels:
        pos = ""
        if "x" in lb and "y" in lb:
            pos = f"{{\\pos({int(lb['x'] * w)},{int(lb['y'] * h)})}}"
        col = f"{{\\c{ass_color(lb['color'])}}}" if lb.get("color") else ""
        size = f"{{\\fs{lb['size']}}}" if lb.get("size") else ""
        out.append(f"Dialogue: 1,{ass_time(lb['start'])},{ass_time(lb['end'])},Label,,0,0,0,,{pos}{col}{size}{lb['text']}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


def spoken_text(text):
    """Drop ElevenLabs audio tags like [excited] so they are not counted or shown as captions."""
    return re.sub(r"\[[^\]]*\]", "", text).strip()


def srt_time(t):
    ms = int(round(t * 1000))
    hh, ms = divmod(ms, 3600000)
    mm, ms = divmod(ms, 60000)
    ss, ms = divmod(ms, 1000)
    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan")
    ap.add_argument("--keep-temp", action="store_true")
    args = ap.parse_args()

    plan_path = os.path.abspath(args.plan)
    base = os.path.dirname(plan_path)
    plan = json.load(open(plan_path, encoding="utf-8"))
    rel = lambda p: p if os.path.isabs(p) else os.path.join(base, p)

    cfg = {"width": int(plan.get("width", 1080)), "height": int(plan.get("height", 1920)),
           "fps": int(plan.get("fps", 30)), "headline": plan.get("headline", {})}
    fps = cfg["fps"]
    voice = plan.get("voice", {})
    tempo_cfg = voice.get("tempo", "auto")
    gap, lead_in, tail = float(voice.get("gap", 0.08)), float(voice.get("lead_in", 0.1)), float(voice.get("tail", 0.2))
    out_mp4 = rel(plan.get("output", "final.mp4"))
    os.makedirs(os.path.dirname(out_mp4) or ".", exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="pv_")

    # 1) Voiceover: one cleaned, sped-up clip per beat, laid end to end with short gaps.
    beats = plan["beats"]
    trim_db = voice.get("trim_db", -45)
    if tempo_cfg == "auto":
        # TTS reads Thai at ~12-14 chars/s; the reference creators talk at ~17-19. Speed up to the target rate.
        raw = [prepare_beat_audio(rel(b["audio"]), os.path.join(tmp, f"raw_{i}.wav"), 1.0, trim_db)
               for i, b in enumerate(beats)]
        chars = sum(len(spoken_text(b.get("text", ""))) for b in beats)
        secs = sum(len(a) for a in raw) / SR
        rate = chars / secs if secs and chars else 0
        tempo = min(max(float(voice.get("target_cps", 17.5)) / rate, 1.0), float(voice.get("max_tempo", 1.35))) \
            if rate else 1.0
    else:
        tempo = float(tempo_cfg)
    pieces, timeline, t = [np.zeros(int(lead_in * SR), dtype=np.float32)], [], lead_in
    for i, beat in enumerate(beats):
        audio = prepare_beat_audio(rel(beat["audio"]), os.path.join(tmp, f"beat_{i}.wav"), tempo, trim_db)
        d = len(audio) / SR
        pad = tail if i == len(beats) - 1 else gap
        timeline.append({"beat": beat.get("name", f"beat{i + 1}"), "text": spoken_text(beat.get("text", "")),
                         "speech_start": round(t, 3), "speech_end": round(t + d, 3)})
        pieces += [audio, np.zeros(int(pad * SR), dtype=np.float32)]
        t += d + pad
    total = t
    voice_wav = os.path.join(tmp, "voice.wav")
    sf.write(voice_wav, np.concatenate(pieces), SR)
    total_frames = int(round(total * fps))

    # 2) Shots: each beat's window (from its speech start to the next beat's start) is shared by its shots.
    seg_files, shot_log, frame_cursor = [], [], 0
    for i, beat in enumerate(beats):
        win_start = 0.0 if i == 0 else timeline[i]["speech_start"]
        win_end = timeline[i + 1]["speech_start"] if i + 1 < len(beats) else total
        f0 = frame_cursor
        f1 = total_frames if i + 1 == len(beats) else int(round(win_end * fps))
        n_frames = max(f1 - f0, 1)
        shots = beat["shots"]
        fixed = {j: int(round(s["dur"] * fps)) for j, s in enumerate(shots) if "dur" in s}
        free = [j for j in range(len(shots)) if j not in fixed]
        remaining = max(n_frames - sum(fixed.values()), len(free))
        weights = [float(shots[j].get("weight", 1)) for j in free]
        alloc = dict(fixed)
        acc = 0
        for k, j in enumerate(free):
            share = remaining - acc if k == len(free) - 1 else int(round(remaining * weights[k] / sum(weights)))
            alloc[j] = max(share, 1)
            acc += alloc[j]
        drift = n_frames - sum(alloc.values())  # absorb rounding in the last shot
        alloc[len(shots) - 1] = max(alloc[len(shots) - 1] + drift, 1)
        for j, shot in enumerate(shots):
            fr = alloc[j]
            seg = os.path.join(tmp, f"seg_{len(seg_files):03d}.mp4")
            scfg = dict(cfg, **shot)
            src = rel(shot["src"])
            if os.path.splitext(src)[1].lower() in (".jpg", ".jpeg", ".png", ".webp"):
                render_still(src, seg, fr, scfg, tmp, len(seg_files))
                kind = "image"
            else:
                render_clip(src, seg, fr, scfg)
                kind = "video"
            seg_files.append(seg)
            shot_log.append({"beat": timeline[i]["beat"], "src": shot["src"], "kind": kind,
                             "start": round(frame_cursor / fps, 3), "end": round((frame_cursor + fr) / fps, 3),
                             "motion": shot.get("motion"), "ai": bool(shot.get("ai", False)),
                             "in_use": bool(shot.get("in_use", kind == "video"))})
            frame_cursor += fr

    concat_list = os.path.join(tmp, "concat.txt")
    with open(concat_list, "w") as f:
        f.writelines(f"file '{s}'\n" for s in seg_files)
    video_only = os.path.join(tmp, "video.mp4")
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", video_only])

    # 3) Headline window: from 0 to the first cut at or after `min_end` seconds (default 3.5 s).
    hl = cfg["headline"]
    cuts = [s["start"] for s in shot_log[1:]]
    if hl.get("end") in (None, "auto"):
        min_end = float(hl.get("min_end", 3.5))
        hl_end = next((c for c in cuts if c >= min_end), total)
    else:
        hl_end = float(hl["end"])
    windows = [(0.0, hl_end)] if hl.get("lines") else []
    if hl.get("lines") and hl.get("repeat_in_last_beat"):
        windows.append((timeline[-1]["speech_start"], total))
    ass_path = os.path.join(tmp, "overlay.ass")
    write_ass(ass_path, cfg, windows, plan.get("labels", []))
    font_dir = rel(plan["font_dir"]) if plan.get("font_dir") else DEFAULT_FONT_DIR

    # 4) Final pass: burn text, add voice, normalise loudness to the target (default -14 LUFS).
    loud = voice.get("loudness", -14)
    shutil.copy(ass_path, os.path.join(tmp, "o.ass"))
    shutil.copytree(font_dir, os.path.join(tmp, "fonts"), dirs_exist_ok=True)
    run(["ffmpeg", "-v", "error", "-y", "-i", "video.mp4", "-i", "voice.wav",
         "-filter_complex", f"[0:v]ass=o.ass:fontsdir=fonts[v];[1:a]loudnorm=I={loud}:TP=-1.5:LRA=11,"
                            f"aresample={SR}[a]",
         "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", os.path.abspath(out_mp4)], cwd=tmp)

    stem = os.path.splitext(out_mp4)[0]
    info = {"output": out_mp4, "duration": round(probe_duration(out_mp4), 3), "fps": fps, "tempo": round(tempo, 3),
            "width": cfg["width"], "height": cfg["height"], "voice_gap": gap,
            "headline_lines": hl.get("lines", []), "headline_windows": windows, "beats": timeline, "shots": shot_log}
    json.dump(info, open(stem + ".timeline.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(stem + ".srt", "w", encoding="utf-8") as f:
        for k, b in enumerate(timeline, 1):
            f.write(f"{k}\n{srt_time(b['speech_start'])} --> {srt_time(b['speech_end'])}\n{b['text']}\n\n")
    if not args.keep_temp:
        shutil.rmtree(tmp, ignore_errors=True)
    print(json.dumps({"output": out_mp4, "duration": info["duration"], "tempo": info["tempo"], "shots": len(shot_log),
                      "headline_until": round(hl_end, 2), "first_cut": cuts[0] if cuts else None},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
