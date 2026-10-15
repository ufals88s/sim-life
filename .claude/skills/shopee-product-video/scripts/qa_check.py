#!/usr/bin/env python3
"""Check a built video against the Tier A rules of the shopee-viral-clip formula.

Reads the video and the <name>.timeline.json that build_video.py wrote next to it, measures the final
audio with ffmpeg, and prints a Thai pass/warn/fail table. Exit code 1 when any check fails.

Usage:
  python3 qa_check.py final.mp4 [--timeline final.timeline.json] [--json qa.json]
"""
import argparse
import json
import os
import re
import subprocess
import sys


def ff(args):
    return subprocess.run(["ffmpeg", "-hide_banner", "-nostats"] + args, capture_output=True, text=True).stderr


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,width,height,avg_frame_rate:format=duration",
                        "-of", "json", path], capture_output=True, text=True)
    return json.loads(r.stdout)


def silences(path, noise_db=-40, min_d=0.3):
    out = ff(["-i", path, "-vn", "-af", f"silencedetect=n={noise_db}dB:d={min_d}", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", out)]
    return list(zip(starts, ends + [None] * (len(starts) - len(ends))))


def variety(shots, total):
    """Camera-setup variety, measured the same way as the four 20k+ view clips.

    Returns (number of setups, the most-used setup and its share of screen time, share of screen time that re-shows
    something already shown: the same still again, even re-cropped, or an overlapping part of the same video).
    """
    per_setup, shown, reused = {}, {}, 0.0
    for s in shots:
        d = s["end"] - s["start"]
        key = s.get("setup") or s["src"]
        per_setup[key] = per_setup.get(key, 0.0) + d
        seen = shown.setdefault(s["src"], [])
        if s["kind"] == "image":
            reused += d if seen else 0.0
            seen.append((0.0, float("inf")))
        elif s.get("src_in") is not None:  # timelines from older builds lack in/out points: no reuse check
            a, b = s["src_in"], s["src_out"]
            if b > a:
                cover, end = 0.0, a
                for x, y in sorted(seen):  # overlap of [a, b] with the union of what was shown before
                    lo, hi = max(x, end), min(y, b)
                    if hi > lo:
                        cover, end = cover + hi - lo, hi
                reused += d * cover / (b - a)
            seen.append((a, b))
    top = max(per_setup, key=per_setup.get)
    return len(per_setup), top, per_setup[top] / max(total, 1e-6), reused / max(total, 1e-6)


def loudness(path):
    m = re.findall(r"I:\s+(-?[0-9.]+) LUFS", ff(["-i", path, "-vn", "-af", "ebur128", "-f", "null", "-"]))
    return float(m[-1]) if m else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--timeline")
    ap.add_argument("--json")
    a = ap.parse_args()
    tl_path = a.timeline or os.path.splitext(a.video)[0] + ".timeline.json"
    tl = json.load(open(tl_path, encoding="utf-8"))
    info = probe(a.video)
    dur = float(info["format"]["duration"])
    vstreams = [s for s in info["streams"] if s["codec_type"] == "video"]
    w, h = (vstreams[0]["width"], vstreams[0]["height"]) if vstreams else (0, 0)
    num, _, den = (vstreams[0].get("avg_frame_rate", "0/1") if vstreams else "0/1").partition("/")
    fps = float(num) / float(den) if float(den or 0) else 0.0
    shots, beats = tl["shots"], tl["beats"]
    rows = []

    def add(code, rule, status, detail):
        rows.append({"code": code, "rule": rule, "status": status, "detail": detail})

    first = shots[0]
    if first["kind"] == "video" and first.get("in_use", True):  # a static AI opening still needs a visual check
        add("A1", "เฟรมแรกคือสินค้ากำลังใช้งาน", "pass", f"ช็อตแรกเป็นวิดีโอ ({first['src']})"
            + (" ที่สร้างด้วย AI: ต้องติดป้าย AI ตอนโพสต์" if first.get("ai") else ""))
    elif first["kind"] == "video":
        add("A1", "เฟรมแรกคือสินค้ากำลังใช้งาน", "warn", "ช็อตแรกเป็นวิดีโอ แต่ไม่ได้ระบุว่าสินค้ากำลังใช้งาน")
    else:
        add("A1", "เฟรมแรกคือสินค้ากำลังใช้งาน", "warn",
            "ช็อตแรกเป็นภาพนิ่งใส่การเคลื่อนกล้อง ยังไม่ถึงเกณฑ์ 'กำลังใช้งาน' ถ้ามีคลิปจริงหรือวิดีโอ AI ให้ใช้เป็นช็อตแรก")

    cuts = [s["start"] for s in shots[1:]]
    fc = cuts[0] if cuts else dur
    add("A2", "มีภาพใหม่ภายใน 2 วิ (ช้าสุด ~4 วิ)", "pass" if fc <= 2.0 else ("warn" if fc <= 4.0 else "fail"),
        f"ตัดภาพครั้งแรกที่ {fc:.2f} วิ")

    fs = beats[0]["speech_start"]
    add("A3", "เริ่มพูดภายใน 0.3 วิ", "pass" if fs <= 0.3 else "fail", f"คำแรกที่ {fs:.2f} วิ")

    win = tl.get("headline_windows") or []
    has_text = any(str(x).strip() for x in tl.get("headline_lines", []))
    if has_text and win and win[0][0] <= 0.05 and win[0][1] - win[0][0] >= 3.0:
        add("A4", "ข้อความหัวคลิปตั้งแต่เฟรมแรก ค้าง ≥3 วิ", "pass",
            f"ขึ้นจอ {win[0][0]:.1f}–{win[0][1]:.1f} วิ: {' / '.join(tl.get('headline_lines', []))}")
    else:
        add("A4", "ข้อความหัวคลิปตั้งแต่เฟรมแรก ค้าง ≥3 วิ", "fail", f"ช่วงข้อความ: {win}")

    speech_end = beats[-1]["speech_end"]
    inner = [(s, e) for s, e in silences(a.video) if s < speech_end - 0.05 and s > beats[0]["speech_start"]]
    longest = max([((e or speech_end) - s) for s, e in inner], default=0.0)
    add("A5", "ไม่มีช่วงเงียบเกิน ~0.5 วิ", "pass" if longest <= 0.5 else "fail",
        f"ช่วงเงียบยาวสุดระหว่างพูด {longest:.2f} วิ (นับเฉพาะช่วงที่ยาวกว่า 0.3 วิ)")

    early_stills = sum(min(s["end"], 5.0) - s["start"] for s in shots if s["kind"] == "image" and s["start"] < 5.0)
    still_share = sum(s["end"] - s["start"] for s in shots if s["kind"] == "image") / max(dur, 1e-6)
    status = "pass" if early_stills <= 1.0 and still_share <= 0.2 else "warn"
    add("A6", "ฟุตเทจจริง ไม่ใช่สไลด์ภาพนิ่ง (Shopee: ภาพนิ่ง ≤20%)", status,
        f"ภาพนิ่งใน 5 วิแรก {early_stills:.1f} วิ, ภาพนิ่งทั้งคลิป {still_share * 100:.0f}%"
        + (" (ภาพนิ่งที่ใส่การเคลื่อนกล้องเยอะ เสี่ยงถูกมองว่าเป็นสไลด์ และไม่เข้า Original Creator)" if status == "warn" else ""))

    n_setups, top, top_share, reused = variety(shots, dur)
    every = dur / n_setups
    ok = every <= 4.0 and top_share <= 0.30 and reused <= 0.15
    add("angles", "มุมกล้องหลากหลาย (มุมใหม่ทุก ≤4 วิ, มุมเดียว ≤30%, ภาพซ้ำ ≤15%)", "pass" if ok else "warn",
        f"{n_setups} มุม ใน {dur:.0f} วิ (มุมใหม่ทุก {every:.1f} วิ), มุมที่ใช้มากสุด {top_share * 100:.0f}% ({top}), "
        f"ภาพที่โชว์ซ้ำ {reused * 100:.0f}%"
        + ("" if ok else " / คลิปต้นแบบ: มุมใหม่ทุก 2.5–2.9 วิ (3 ใน 4 คลิป ช้าสุด 6.1), มุมเดียวไม่เกิน 30%, "
           "ภาพซ้ำไม่เกิน 12% ให้เพิ่มมุมตาม references/shot-list.md"))

    if 20 <= dur <= 45:
        st = "pass"
    elif 15 <= dur <= 60:
        st = "warn"
    else:
        st = "fail"
    add("A7", "ยาว 15–60 วิ (แนะนำ 20–45)", st, f"{dur:.1f} วิ, ขนาด {w}x{h}" + ("" if (w, h) == (1080, 1920) else " (ควรเป็น 1080x1920)"))

    voiced = [b for b in beats if b["text"].strip()]  # beats without text cannot be measured
    chars = sum(len(re.sub(r"\s", "", b["text"])) for b in voiced)
    talk = sum(b["speech_end"] - b["speech_start"] for b in voiced)
    cps = chars / talk if talk else 0
    add("rate", "ความเร็วพูด 16–19 ตัวอักษร/วิ", "pass" if 16 <= cps <= 19.5 else "warn",
        f"{cps:.1f} ตัวอักษร/วิ (tempo {tl.get('tempo')})" if chars else "ไม่มีข้อความใน plan จึงวัดไม่ได้")

    planned = shots[-1]["end"]
    ok_sync = dur + 0.05 >= speech_end and abs(dur - planned) <= 0.1
    ok_fmt = (w, h) == (1080, 1920) and abs(fps - 30) < 0.01
    add("sync", "วิดีโอครบตามแผน / 1080x1920 30fps", "fail" if not ok_sync else ("pass" if ok_fmt else "warn"),
        f"ยาว {dur:.2f} วิ (ตามแผน {planned:.2f}), เสียงพูดจบที่ {speech_end:.2f} วิ, {w}x{h} @ {fps:.2f} fps"
        + ("" if ok_sync else " (คลิปสั้นกว่าเสียงพากย์: เสียงท้ายคลิปถูกตัด)"))

    lu = loudness(a.video)
    add("loud", "ความดังราว −14 LUFS", "pass" if lu is not None and -16 <= lu <= -12 else "warn", f"{lu} LUFS")

    ai_video = any(s.get("ai") for s in shots)
    add("label", "ติดป้ายเนื้อหา AI", "warn",
        "เสียงพากย์สร้างด้วย ElevenLabs" + (" และมีช็อตวิดีโอ/ภาพ AI" if ai_video else "")
        + ": ต้องเปิดป้าย AI ตอนโพสต์ตามกฎ Shopee")
    add("A8", "ทุกคำกล่าวอ้างจริง + ชื่อหมวดก่อน 12 วิ + สินค้าเดียว", "manual",
        "สคริปต์นี้วัดจากไฟล์ไม่ได้: ตรวจสคริปต์เองว่าทุกข้อมีป้ายที่มา ([ภาพ]/[ผู้ใช้]/[หน้าร้าน]/[เว็บ])")

    icon = {"pass": "✅", "warn": "⚠️", "fail": "❌", "manual": "👀"}
    print("| ข้อ | เกณฑ์ | ผล | รายละเอียด |\n|---|---|---|---|")
    for r in rows:
        print(f"| {r['code']} | {r['rule']} | {icon[r['status']]} | {r['detail']} |")
    if a.json:
        json.dump(rows, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    sys.exit(1 if any(r["status"] == "fail" for r in rows) else 0)


if __name__ == "__main__":
    main()
