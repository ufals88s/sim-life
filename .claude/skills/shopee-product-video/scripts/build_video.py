#!/usr/bin/env python3
"""Assemble a 9:16 product video from an edit plan (images and/or clips + per-beat voiceover).

Each beat is one voiceover line (an audio file). The beat's shots share the beat's duration, so every
cut lands on the start of a spoken line. A Thai headline is burned in from frame 0 with libass
(HarfBuzz shaping, so Thai vowels and tone marks render correctly).

Usage:
  python3 build_video.py PLAN.json [--keep-temp]
  python3 build_video.py --frame IMAGE OUT.jpg [--fit auto|fit|cover]   # 1080x1920 frame, e.g. an AI start frame

Plan format (paths are relative to the plan file): see references/edit-plan.md
Outputs: <output>.mp4, <output>.timeline.json, <output>.srt (voiceover text, for captions or checking)
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

import numpy as np
import soundfile as sf
from PIL import Image, ImageFilter, ImageFont, ImageOps, ImageStat

try:  # iPhone photos
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_FONT_DIR = os.path.join(SKILL_DIR, "assets", "fonts")
SR = 48000
STILL_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".avif", ".heic", ".heif")
BT709 = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]
TO709 = "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p"
HDR_TO_SDR = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,"
              "zscale=t=bt709:m=bt709:r=tv,format=yuv420p,")
# libass sizes text by the font's full line height, so Kanit at \fs100 is as wide as PIL's Kanit at size ~62.5.
LIBASS_PER_PIL = 0.625

# Camera moves for still images: zoom (start, end) and window centre fx, fy (start, end) as 0-1 of the frame.
MOTIONS = {
    "push_in": {"z": [1.0, 1.15], "fx": [0.5, 0.5], "fy": [0.5, 0.5]},
    "pull_out": {"z": [1.15, 1.0], "fx": [0.5, 0.5], "fy": [0.5, 0.5]},
    "pan_left": {"z": [1.25, 1.25], "fx": [0.6, 0.4], "fy": [0.5, 0.5]},
    "pan_right": {"z": [1.25, 1.25], "fx": [0.4, 0.6], "fy": [0.5, 0.5]},
    "pan_up": {"z": [1.25, 1.25], "fx": [0.5, 0.5], "fy": [0.6, 0.4]},
    "pan_down": {"z": [1.25, 1.25], "fx": [0.5, 0.5], "fy": [0.4, 0.6]},
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


def count_frames(path):
    r = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
             "stream=nb_read_packets", "-of", "csv=p=0", path])
    return int(r.stdout.strip() or 0)


def spoken_text(text):
    """Drop ElevenLabs audio tags like [excited] so they are not counted or shown as captions."""
    return re.sub(r"\[[^\]]*\]", "", text or "").strip()


def char_count(text):
    """Thai characters as the formula counts them: vowels and tone marks included, spaces and tags not."""
    return len(re.sub(r"\s", "", spoken_text(text)))


def atempo_chain(tempo):
    """ffmpeg atempo accepts 0.5-2.0 per stage; chain stages for anything outside that."""
    if not (0.25 <= tempo <= 4.0):
        raise SystemExit(f"voice.tempo must be between 0.25 and 4.0, got {tempo}")
    parts, t = [], tempo
    while t > 2.0:
        parts.append("atempo=2.0"); t /= 2.0
    while t < 0.5:
        parts.append("atempo=0.5"); t /= 0.5
    parts.append(f"atempo={t:.4f}")
    return ",".join(parts)


def prepare_beat_audio(src, dst, tempo, trim_db):
    """Trim leading/trailing silence, speed up without changing pitch, resample to 48 kHz mono."""
    trim = (f"silenceremove=start_periods=1:start_threshold={trim_db}dB:start_silence=0.05,areverse,"
            f"silenceremove=start_periods=1:start_threshold={trim_db}dB:start_silence=0.05,areverse")
    af = trim + ("," + atempo_chain(tempo) if abs(tempo - 1.0) > 1e-3 else "")
    run(["ffmpeg", "-v", "error", "-y", "-i", src, "-af", af, "-ar", str(SR), "-ac", "1", dst])
    audio, _ = sf.read(dst, dtype="float32")
    return audio


def load_rgb(src):
    """Open any still (alpha flattened onto white, EXIF rotation applied)."""
    img = ImageOps.exif_transpose(Image.open(src)).convert("RGBA")
    return Image.alpha_composite(Image.new("RGBA", img.size, (255, 255, 255, 255)), img).convert("RGB")


def border_stats(img):
    w, h = img.size
    m = max(2, min(w, h) // 40)
    strips = [img.crop((0, 0, w, m)), img.crop((0, h - m, w, h)), img.crop((0, 0, m, h)), img.crop((w - m, 0, w, h))]
    stats = [ImageStat.Stat(s) for s in strips]
    mean = [sum(s.mean[c] for s in stats) / 4 for c in range(3)]
    spread = sum(sum(s.stddev) / 3 for s in stats) / 4
    return mean, spread


def composite_still(src, dst, w, h, fit, scale=2):
    """Render a still at `scale` x output size.

    cover: crop to fill the frame. fit: the whole product is shown; a studio packshot (plain light border) sits on
    its own background colour, any other photo sits on a darkened blur of itself.
    """
    W, H = w * scale, h * scale
    img = load_rgb(src)
    aspect = img.width / img.height
    if fit == "auto":
        fit = "cover" if 0.5 <= aspect <= 0.65 else "fit"
    if fit == "cover":
        ImageOps.fit(img, (W, H), Image.LANCZOS).save(dst)
        return
    mean, spread = border_stats(img)
    packshot = min(mean) > 200 and spread < 12
    if packshot:  # studio photo: crop to the product, then extend its own background instead of a grey blur
        img = crop_to_product(img, mean)
        bg = Image.new("RGB", (W, H), tuple(int(v) for v in mean))
        ratio = min(W * 0.84 / img.width, H * 0.58 / img.height)
    else:
        bg = ImageOps.fit(img, (W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(60))
        bg = bg.point(lambda v: int(v * 0.55 + 20))
        ratio = min(W * 0.94 / img.width, H * 0.62 / img.height)
    fg = img.resize((max(1, int(img.width * ratio)), max(1, int(img.height * ratio))), Image.LANCZOS)
    x = (W - fg.width) // 2
    y = int(H * 0.58 - fg.height / 2)  # keep the top band (10-30%) free for the headline
    mask = None
    if packshot:  # feather the edges so the photo's own gradient melts into the flat background
        r = max(4, int(min(fg.size) * 0.06))
        mask = Image.new("L", fg.size, 0)
        mask.paste(255, (r, r, fg.width - r, fg.height - r))
        mask = mask.filter(ImageFilter.GaussianBlur(r / 2))
    bg.paste(fg, (x, y), mask)
    bg.save(dst)


def crop_to_product(img, bg_rgb, thresh=28, pad=0.10):
    """Bounding box of pixels that differ from the studio background, with some padding."""
    diff = Image.eval(Image.merge("RGB", [ch.point(lambda v, b=int(b): abs(v - b)) for ch, b in
                                          zip(img.split(), bg_rgb)]).convert("L"), lambda v: 255 if v > thresh else 0)
    box = diff.getbbox()
    if not box:
        return img
    bw, bh = box[2] - box[0], box[3] - box[1]
    px, py = int(bw * pad), int(bh * pad)
    return img.crop((max(0, box[0] - px), max(0, box[1] - py), min(img.width, box[2] + px), min(img.height, box[3] + py)))


def render_still(src, dst, frames, cfg, tmp, idx):
    w, h, fps = cfg["width"], cfg["height"], cfg["fps"]
    comp = os.path.join(tmp, f"still_{idx}.png")
    composite_still(src, comp, w, h, cfg.get("fit", "auto"))
    m = dict(MOTIONS.get(cfg.get("motion", "push_in"), MOTIONS["push_in"]))
    for k in ("z", "fx", "fy"):
        if k in cfg:
            m[k] = [float(v) for v in cfg[k]]
    for k in ("fx", "fy"):  # the centre must stay where the window fits, or the move stalls against the edge
        m[k] = [min(max(float(v), 0.5 / max(float(zz), 1.0)), 1 - 0.5 / max(float(zz), 1.0))
                for v, zz in zip(m[k], m["z"])]
    n = max(frames - 1, 1)
    p = f"(on/{n})"
    e = f"({p}*{p}*(3-2*{p}))"  # smoothstep easing
    z = f"({m['z'][0]}+({m['z'][1]}-{m['z'][0]})*{e})"
    fx = f"({m['fx'][0]}+({m['fx'][1]}-{m['fx'][0]})*{e})"
    fy = f"({m['fy'][0]}+({m['fy'][1]}-{m['fy'][0]})*{e})"
    x = f"max(0,min(iw-iw/zoom,{fx}*iw-iw/zoom/2))"
    y = f"max(0,min(ih-ih/zoom,{fy}*ih-ih/zoom/2))"
    vf = f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={fps},{TO709}"
    run(["ffmpeg", "-v", "error", "-y", "-i", comp, "-vf", vf, "-frames:v", str(frames),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-r", str(fps)] + BT709 + [dst])


def render_clip(src, dst, frames, cfg):
    """Trim a video clip to the shot length, fill 9:16 (crop or blurred backdrop), freeze the last frame if short."""
    w, h, fps = cfg["width"], cfg["height"], cfg["fps"]
    start, speed = float(cfg.get("start", 0)), float(cfg.get("speed", 1.0))
    if speed <= 0:
        raise SystemExit(f"{src}: speed must be > 0")
    meta = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=color_transfer:format=duration", "-of", "json", src]).stdout)
    if not meta.get("streams"):
        raise SystemExit(f"{src}: no video stream")
    src_dur = float(meta.get("format", {}).get("duration") or 0)
    if src_dur and start >= src_dur - 0.05:
        raise SystemExit(f"{src}: start={start:.2f}s is at or past the end of the clip ({src_dur:.2f}s)")
    hdr = HDR_TO_SDR if meta["streams"][0].get("color_transfer") in ("arib-std-b67", "smpte2084") else ""
    dur = frames / fps
    if cfg.get("fit", "cover") == "fit":
        chain = (f"split[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=30:5,"
                 f"eq=brightness=-0.08[bg];[b]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
                 f"[bg][fg]overlay=(W-w)/2:(H-h)/2")
    else:
        chain = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    vf = (f"{hdr}setpts=(PTS-STARTPTS)/{speed},{chain},fps={fps},tpad=stop_mode=clone:stop_duration={dur:.3f},"
          f"{TO709}")
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-i", src, "-an", "-filter_complex", vf,
         "-frames:v", str(frames), "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-r", str(fps)]
        + BT709 + [dst])


def split_frames(total, weights):
    """Whole frames, at least 1 each, in proportion to weights, adding up to exactly `total`."""
    spare, tw = total - len(weights), float(sum(weights))
    out, acc, cum = [], 0, 0.0
    for wt in weights:
        cum += wt
        edge = int(round(spare * cum / tw))
        out.append(1 + edge - acc)
        acc = edge
    return out


def allocate(shots, n_frames, fps, label):
    """Frames per shot for one beat: `dur` shots get their length, `weight` shots share what is left.

    If the `dur` values do not leave ~0.3 s for each weighted shot (or overrun the beat), every shot is scaled to fit
    so the next cut still lands on the next line. With no weighted shot, the last shot absorbs the remainder.
    """
    if not shots:
        raise SystemExit(f"{label}: needs at least one shot")
    if len(shots) > n_frames:
        raise SystemExit(f"{label}: {len(shots)} shots do not fit in {n_frames} frames ({n_frames / fps:.2f}s)")
    fixed = {j: max(1, int(round(float(s["dur"]) * fps))) for j, s in enumerate(shots) if "dur" in s}
    free = [j for j in range(len(shots)) if j not in fixed]
    min_free = max(1, int(0.3 * fps))
    if fixed and sum(fixed.values()) + len(free) * min_free > n_frames:
        sys.stderr.write(f"warning: {label}: shot dur values ({sum(fixed.values()) / fps:.2f}s) leave too little of "
                         f"the {n_frames / fps:.2f}s line; scaling all shots to fit\n")
        weights = [float(s["dur"]) if "dur" in s else min_free / fps for s in shots]
        return split_frames(n_frames, weights)
    alloc = [0] * len(shots)
    for j, f in fixed.items():
        alloc[j] = f
    if free:
        weights = [max(float(shots[j].get("weight", 1)), 1e-6) for j in free]
        for j, f in zip(free, split_frames(n_frames - sum(fixed.values()), weights)):
            alloc[j] = f
    else:
        alloc[-1] = max(1, alloc[-1] + n_frames - sum(alloc))
    return alloc


def ass_time(t, end=False):
    """ASS times are centiseconds. Round an end time down so text is gone on the frame that starts at `t`."""
    cs = max(0, int(math.floor(t * 100 + 1e-6)) if end else int(round(t * 100)))
    hh, cs = divmod(cs, 360000)
    mm, cs = divmod(cs, 6000)
    ss, cs = divmod(cs, 100)
    return f"{hh}:{mm:02d}:{ss:02d}.{cs:02d}"


def ass_color(hex_rgb):
    hex_rgb = hex_rgb.lstrip("#")
    r, g, b = hex_rgb[0:2], hex_rgb[2:4], hex_rgb[4:6]
    return f"&H00{b}{g}{r}&".upper()


def ass_escape(text):
    """Literal text for an ASS event: keep braces/backslashes visible, turn real newlines into \\N."""
    return (str(text).replace("\\", "\\⁠").replace("{", "\\{").replace("}", "\\}")
            .replace("\r", "").replace("\n", "\\N"))


def auto_sizes(lines, font_dir, width):
    """Headline sizes so line 1 spans ~50% of the frame (reference clips: 48-63%), line 2 a bit smaller."""
    path = os.path.join(font_dir, "Kanit-Bold.ttf")
    if not lines or not os.path.exists(path):
        return [104, 84]
    font = ImageFont.truetype(path, 100)
    px_at_100 = [max(1, font.getbbox(t)[2] - font.getbbox(t)[0]) * LIBASS_PER_PIL for t in lines]
    s1 = min(max(0.52 * width * 100 / px_at_100[0], 72), 120)
    s1 = min(s1, 0.90 * width * 100 / px_at_100[0])
    sizes = [int(s1)]
    if len(lines) > 1:
        sizes.append(int(min(0.82 * s1, 0.90 * width * 100 / px_at_100[1])))
    return sizes


def write_ass(path, cfg, lines, headline_windows, labels, font_dir):
    w, h = cfg["width"], cfg["height"]
    hl = cfg.get("headline", {})
    font = hl.get("font", "Kanit")
    sizes = hl.get("sizes") or auto_sizes(lines, font_dir, w)
    colors = hl.get("colors", ["FFFFFF", "FFE14D"])
    margin_v = int(h * float(hl.get("top", 0.11)))
    parts = []
    for i, text in enumerate(lines):
        size = sizes[min(i, len(sizes) - 1)]
        col = ass_color(colors[min(i, len(colors) - 1)])
        parts.append(f"{{\\fs{size}\\c{col}}}{ass_escape(text)}")
    body = "\\N".join(parts)
    out = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}", "WrapStyle: 2",
        "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Headline,{font},{sizes[0]},&H00FFFFFF,&H00FFFFFF,&H00101010,&H64000000,-1,0,0,0,100,100,0,0,1,"
        f"{hl.get('outline', 6)},2,8,40,40,{margin_v},1",
        f"Style: Label,{font},64,&H00FFFFFF,&H00FFFFFF,&H00101010,&H64000000,-1,0,0,0,100,100,0,0,1,5,2,5,60,60,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if body:
        for a, b in headline_windows:
            out.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b, end=True)},Headline,,0,0,0,,{body}")
    for lb in labels:
        pos = f"{{\\pos({int(lb['x'] * w)},{int(lb['y'] * h)})}}" if "x" in lb and "y" in lb else ""
        col = f"{{\\c{ass_color(lb['color'])}}}" if lb.get("color") else ""
        size = f"{{\\fs{lb['size']}}}" if lb.get("size") else ""
        out.append(f"Dialogue: 1,{ass_time(lb['start'])},{ass_time(lb['end'], end=True)},Label,,0,0,0,,"
                   f"{pos}{col}{size}{ass_escape(lb['text'])}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    return sizes


def normalize_loudness(src, dst, target):
    """Two-pass EBU R128 loudnorm (single pass lands ~1 LU short of the target)."""
    tp, lra = -1.5, 11
    out = run(["ffmpeg", "-hide_banner", "-nostats", "-i", src, "-af",
               f"loudnorm=I={target}:TP={tp}:LRA={lra}:print_format=json", "-f", "null", "-"]).stderr
    m = json.loads(out[out.rindex("{"):out.rindex("}") + 1])
    af = (f"loudnorm=I={target}:TP={tp}:LRA={lra}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,"
          f"aresample={SR}")
    run(["ffmpeg", "-v", "error", "-y", "-i", src, "-af", af, "-ar", str(SR), "-ac", "1", dst])


def srt_time(t):
    ms = int(round(t * 1000))
    hh, ms = divmod(ms, 3600000)
    mm, ms = divmod(ms, 60000)
    ss, ms = divmod(ms, 1000)
    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan", nargs="?")
    ap.add_argument("--keep-temp", action="store_true")
    ap.add_argument("--frame", nargs=2, metavar=("IMAGE", "OUT"), help="only render a 1080x1920 still and exit")
    ap.add_argument("--fit", default="auto")
    args = ap.parse_args()

    if args.frame:
        composite_still(args.frame[0], args.frame[1], 1080, 1920, args.fit, scale=1)
        print(args.frame[1])
        return
    if not args.plan:
        ap.error("PLAN.json is required")

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
    out_mp4 = rel(plan.get("output", "out/final.mp4"))
    os.makedirs(os.path.dirname(out_mp4) or ".", exist_ok=True)
    font_dir = rel(plan["font_dir"]) if plan.get("font_dir") else DEFAULT_FONT_DIR
    tmp = tempfile.mkdtemp(prefix="pv_")

    # 1) Voiceover: one cleaned, sped-up clip per beat, laid end to end with short gaps.
    beats = plan["beats"]
    trim_db = voice.get("trim_db", -55)
    if tempo_cfg == "auto":
        # TTS reads Thai at ~12-14 chars/s; the reference creators talk at ~17-19. Speed up to the target rate.
        raw = [prepare_beat_audio(rel(b["audio"]), os.path.join(tmp, f"raw_{i}.wav"), 1.0, trim_db)
               for i, b in enumerate(beats)]
        counted = [(char_count(b.get("text", "")), len(a)) for b, a in zip(beats, raw)]
        chars = sum(c for c, _ in counted if c)
        secs = sum(n for c, n in counted if c) / SR
        rate = chars / secs if secs and chars else 0
        tempo = min(max(float(voice.get("target_cps", 17.0)) / rate, 1.0), float(voice.get("max_tempo", 1.45))) \
            if rate else 1.0
    else:
        tempo = float(tempo_cfg)
    pieces, timeline, t = [np.zeros(int(lead_in * SR), dtype=np.float32)], [], lead_in
    for i, beat in enumerate(beats):
        audio = prepare_beat_audio(rel(beat["audio"]), os.path.join(tmp, f"beat_{i}.wav"), tempo, trim_db)
        d = len(audio) / SR
        if d < 0.15:
            raise SystemExit(f"beat {i + 1} ({beat['audio']}): only {d:.2f}s of sound left after trimming at "
                             f"{trim_db} dB; the file is silent or too quiet")
        pad = tail if i == len(beats) - 1 else gap
        timeline.append({"beat": beat.get("name", f"beat{i + 1}"), "text": spoken_text(beat.get("text", "")),
                         "speech_start": round(t, 3), "speech_end": round(t + d, 3)})
        pieces += [audio, np.zeros(int(pad * SR), dtype=np.float32)]
        t += d + pad
    total = t
    raw_voice = os.path.join(tmp, "voice_raw.wav")
    sf.write(raw_voice, np.concatenate(pieces), SR)
    normalize_loudness(raw_voice, os.path.join(tmp, "voice.wav"), voice.get("loudness", -14))
    total_frames = int(round(total * fps))

    # 2) Shots: each beat's window (from its first frame to the next beat's speech start) is shared by its shots.
    seg_files, shot_log, beat_start_frames, frame_cursor = [], [], [], 0
    for i, beat in enumerate(beats):
        beat_start_frames.append(frame_cursor)
        f1 = total_frames if i + 1 == len(beats) else int(round(timeline[i + 1]["speech_start"] * fps))
        n_frames = max(f1 - frame_cursor, 1)
        shots = beat.get("shots") or []
        alloc = allocate(shots, n_frames, fps, f"beat {i + 1}")
        for j, shot in enumerate(shots):
            fr = alloc[j]
            seg = os.path.join(tmp, f"seg_{len(seg_files):03d}.mp4")
            scfg = dict(cfg, **shot)
            src = rel(shot["src"])
            if not os.path.exists(src):
                raise SystemExit(f"beat {i + 1}: file not found: {shot['src']}")
            if os.path.splitext(src)[1].lower() in STILL_EXT:
                render_still(src, seg, fr, scfg, tmp, len(seg_files))
                kind = "image"
            else:
                render_clip(src, seg, fr, scfg)
                kind = "video"
            got = count_frames(seg)
            if got != fr:
                raise SystemExit(f"shot {shot['src']} (beat {i + 1}): rendered {got} frames, expected {fr}")
            seg_files.append(seg)
            shot_log.append({"beat": timeline[i]["beat"], "src": shot["src"], "kind": kind,
                             "start": round(frame_cursor / fps, 3), "end": round((frame_cursor + fr) / fps, 3),
                             "motion": shot.get("motion"), "ai": bool(shot.get("ai", False)),
                             "in_use": bool(shot.get("in_use", kind == "video"))})
            frame_cursor += fr

    concat_list = os.path.join(tmp, "concat.txt")
    with open(concat_list, "w") as f:
        f.writelines(f"file '{s}'\n" for s in seg_files)
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy",
         os.path.join(tmp, "video.mp4")])

    # 3) Headline window: from 0 to the first cut at or after `min_end` seconds (default 3.5 s).
    hl = cfg["headline"]
    hl_lines = [str(x) for x in hl.get("lines", []) if str(x).strip()]
    cuts = [s["start"] for s in shot_log[1:]]
    if hl.get("end") in (None, "auto"):
        min_end = float(hl.get("min_end", 3.5))
        hl_end = next((c for c in cuts if c >= min_end), total)
    else:
        hl_end = min(float(hl["end"]), total)
    windows = [(0.0, hl_end)] if hl_lines else []
    if hl_lines and hl.get("repeat_in_last_beat"):
        rep_start = beat_start_frames[-1] / fps
        if rep_start > hl_end:
            windows.append((rep_start, total))
        else:  # the windows touch or overlap: one event, or libass stacks two copies of the headline
            windows[0] = (0.0, total)
    ass_path = os.path.join(tmp, "o.ass")
    sizes = write_ass(ass_path, cfg, hl_lines, windows, plan.get("labels", []), font_dir)

    # 4) Final pass: burn text, add the normalised voice.
    shutil.copytree(font_dir, os.path.join(tmp, "fonts"), dirs_exist_ok=True)
    run(["ffmpeg", "-v", "error", "-y", "-i", "video.mp4", "-i", "voice.wav",
         "-filter_complex", "[0:v]ass=o.ass:fontsdir=fonts,format=yuv420p[v]",
         "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p"]
        + BT709 + ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", os.path.abspath(out_mp4)],
        cwd=tmp)

    stem = os.path.splitext(out_mp4)[0]
    info = {"output": out_mp4, "duration": round(probe_duration(out_mp4), 3), "fps": fps, "tempo": round(tempo, 3),
            "width": cfg["width"], "height": cfg["height"], "voice_gap": gap, "headline_sizes": sizes,
            "headline_lines": hl_lines, "headline_windows": windows, "beats": timeline, "shots": shot_log}
    json.dump(info, open(stem + ".timeline.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(stem + ".srt", "w", encoding="utf-8") as f:
        for k, b in enumerate(timeline, 1):
            f.write(f"{k}\n{srt_time(b['speech_start'])} --> {srt_time(b['speech_end'])}\n{b['text']}\n\n")
    if args.keep_temp:
        sys.stderr.write(f"temp files kept in {tmp}\n")
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    print(json.dumps({"output": out_mp4, "duration": info["duration"], "tempo": info["tempo"], "shots": len(shot_log),
                      "headline_until": round(hl_end, 2), "headline_sizes": sizes,
                      "first_cut": cuts[0] if cuts else None}, ensure_ascii=False))


if __name__ == "__main__":
    main()
