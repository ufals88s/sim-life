# ElevenLabs: เสียงพากย์ไทย ภาพฉาก และวิดีโอ AI (เรียกผ่าน MCP)

ทดสอบจริงเมื่อ 15 ต.ค. 2026 เครื่องมือเป็น deferred tool ต้องโหลดก่อนเรียก (ToolSearch ต้องใช้ชื่อเต็ม)

```
ToolSearch "select:mcp__ElevenLabs__creative_create_flow,mcp__ElevenLabs__creative_list_voices,mcp__ElevenLabs__creative_generate_speech,mcp__ElevenLabs__creative_get_flow_run_status"
```

ถ้าจะทำภาพหรือวิดีโอ AI ให้โหลดเพิ่ม

```
ToolSearch "select:mcp__ElevenLabs__creative_create_asset_upload,mcp__ElevenLabs__creative_finalize_asset_upload,mcp__ElevenLabs__creative_add_flow_node,mcp__ElevenLabs__creative_get_model_schema,mcp__ElevenLabs__creative_run_flow_nodes,mcp__ElevenLabs__creative_update_node,mcp__ElevenLabs__creative_add_flow_asset_node"
```

ทุกการสร้างเสียง ภาพ หรือวิดีโอ **ใช้เครดิตของผู้ใช้**
- ห้ามเรียกซ้ำเพื่อ "ลองใหม่" เพราะจะเสียเครดิตอีกรอบ
- ถ้าผลไม่ดี ให้ถามผู้ใช้ก่อนสร้างใหม่

## ราคาที่วัดได้จริง (15 ต.ค. 2026 ราคาอาจเปลี่ยน ให้ใช้ estimate_only ก่อนงานที่แพง)

| งาน | เครดิตโดยประมาณ |
|---|---|
| เสียงพากย์ `eleven_v4` | ~1.1 ต่อตัวอักษร (ไม่นับเว้นวรรค) สคริปต์ 30 วิ (~500 ตัว) ≈ 550 |
| ภาพฉาก `bytedance-seedream-5-lite` 1 ใบ | ~210 |
| วิดีโอ 5 วิ 9:16 `kling-2.5-turbo` | ~2,100 (ถูกสุด ค่าเริ่มต้น) |
| วิดีโอ 5 วิ 9:16 720p `bytedance-seedance-v2-mini` | ~4,600 |
| วิดีโอ 5 วิ 9:16 720p `bytedance-seedance-v2.5` | ~14,000 |

ตอนแจ้งราคา ให้บอกเป็นเครดิตตามผลประเมิน ถ้าผลประเมินมี `price_cents` ให้บอกเป็นเงินด้วย อย่าแปลงเครดิตเป็นเงินเอง เพราะราคาต่อเครดิตขึ้นกับแพ็กเกจของผู้ใช้

## 0) สร้าง flow เดียวต่อ 1 คลิป

```
creative_create_flow(name="<สินค้า> – Shopee video", context="...")
```

เก็บ `flow_id` ไว้ใช้กับทุกการเรียกหลังจากนี้ ผู้ใช้จะเปิดดูทุกชิ้นได้ใน canvas เดียว

## 1) เลือกเสียง

```
creative_list_voices(languages=["th"], context="...")
```

- ห้ามใช้ voice_id จากความจำ ต้องเลือกจากผลที่ได้ทุกครั้ง
- ผลอาจมีเสียงซ้ำ voice_id เดียวกัน ให้นับเป็นเสียงเดียว
- ลำดับการเลือก
  1. **ผู้ใช้บอกชื่อเสียง** → ใช้เสียงนั้น
  2. **ผู้ใช้บอกแค่ลักษณะ** (เช่น "ผู้หญิงสดใส") → เลือกเสียงไทยแนว Social Media หรือ Conversational ที่ตรงที่สุด
     - ตอนทดสอบมีเสียงหญิง "Malee – Cheerful, Bright, Lively" และ "Nueng – Cheerful, Bright, Friendly"
     - และเสียงชาย "Chai – Upbeat, Playful, Punchy" และ "Ekkarat – Relaxed, Cheerful, Casual"
     - ให้ค้นจากชื่อหรือคำอธิบายใน list ใหม่ทุกครั้ง
  3. **มีเสียง category `cloned`** → ไม่ต้องหยุดถาม ทำงานต่อด้วยเสียงข้อ 2 แล้วบอกตอนส่งงานว่า "ถ้าเสียงโคลน <ชื่อ> เป็นเสียงของคุณ บอกได้ จะพากย์ใหม่ด้วยเสียงนั้น"
- เสียงแนว Narration หรือ Advertisement จะช้าและเป็นทางการเกินไปสำหรับคลิปป้ายยา

## 2) สร้างเสียง 1 beat ต่อ 1 ครั้ง

```
creative_generate_speech(
  prompt="[excited] เก็บเส้นผม ฝุ่น ขนสัตว์ได้สะอาดมาก ไม่ต้องดูด ไม่ต้องล้างไม้ม็อบให้วุ่นวายเลยค่ะ",
  model_id="eleven_v4", voice_id="<จาก list>", flow_id="<flow>", generations_count=1, context="...")
```

- **โมเดล**: `eleven_v4` (หรือ `eleven_v3`)
  - `eleven_multilingual_v2`, `eleven_flash_v2_5`, `eleven_turbo_v2_5` ไม่รองรับภาษาไทยเต็มรูปแบบและไม่มีแท็กอารมณ์
- **แท็กอารมณ์**: ใส่ไม่บ่อย
  - `[excited]` ที่ beat แรก, `[warmly]` ที่ beat สุดท้าย
  - แท็กมีผลจนกว่าจะเจอแท็กใหม่
  - `build_video.py` ตัดแท็กออกก่อนนับตัวอักษรและก่อนเขียนไฟล์ซับให้เอง
- **ตัวเลข**: เขียนเป็นตัวเลขได้ เช่น "470 ml" "3 ชั้น" v4 อ่านเองได้
- **คำอังกฤษ**: เขียนเป็นภาษาไทย เช่น "ทูอินวัน" จะอ่านเป็นธรรมชาติกว่า "2 in 1"
- **generations_count**: ค่าเริ่มต้นของเครื่องมือคือ 4 เทค และ ElevenLabs แนะนำให้คงไว้ เว้นแต่ผู้ใช้ขอจำนวนเอง
  - skill นี้ใช้ 1 เทคต่อ beat เพื่อใช้เครดิตแค่ 1 ใน 4 จึง**ต้องบอกผู้ใช้ในแผนขั้น 4** ว่า "จะสร้างเสียง 1 เทคต่อประโยค (~550 เครดิต) ถ้าอยากได้ 4 เทคไว้เลือก (~2,200 เครดิต) บอกได้"
  - ถ้าสร้างหลายเทค ให้ส่งลิงก์ flow ให้ผู้ใช้ฟังแล้วเลือก ถ้าผู้ใช้ไม่เลือก ให้ใช้ `generations[]` ตัวแรก แล้วดาวน์โหลดเฉพาะเทคนั้น
- **ส่งทุก beat ใน flow เดียวกัน** เรียกต่อกันได้เลยโดยไม่ต้องรอ

**ความเร็วพูด**: v4 พูดไทยราว 12–14 ตัวอักษร/วิ ช้ากว่าคลิปต้นแบบ (17–19) `build_video.py` จะเร่งเองด้วย `tempo: "auto"` (สูงสุด 1.45 เท่า)

## 3) รอผลและดาวน์โหลด

```
creative_get_flow_run_status(flow_id, session_ids=[...])
```

- เรียกซ้ำโดยเว้นช่วงตามค่า `poll_after_seconds` จนได้ `all_completed: true` หรือ `has_failures: true`
  - ถ้า failure ให้บอกผู้ใช้ว่า beat หรือชิ้นไหนล้มเหลว และถามก่อนสร้างใหม่
- **ลิงก์ไฟล์เต็มคือ `media[].master_url`** (หรือ `generations[].content_url`)
  - สำหรับภาพและวิดีโอ `media[].url` เป็นแค่ไฟล์ตัวอย่างขนาดเล็ก (`preview_content.*`)
  - ลิงก์อยู่บน storage.googleapis.com และ**หมดอายุใน 2 ชั่วโมง**

```bash
curl -sS -L -o video-jobs/<job>/vo/01.mp3 "<master_url>"
```

หมายเหตุเครือข่าย: ในสภาพแวดล้อมคลาวด์ที่ทดสอบ ดาวน์โหลดจาก storage.googleapis.com ได้ แต่ api.us.elevenlabs.io ถูกบล็อก จึงต้องใช้ลิงก์ storage เสมอ

## 4) อัปโหลดภาพเข้า flow

1. ขอที่อัปโหลด
   ```
   creative_create_asset_upload(name, mime_type="<image/jpeg | image/png | image/webp ตรงกับไฟล์จริง>", file_size=<ไบต์จริงจาก stat -c %s>)
   ```
   ได้ `asset_id` และ `upload_url`
2. อัปโหลดไฟล์ โดย Content-Type ต้องตรงกับ mime_type ข้างบน และต้องได้ HTTP 200
   ```bash
   curl -sS -X PUT -H "Content-Type: <mime_type>" --data-binary @<ไฟล์> "<upload_url>"
   ```
3. วางภาพลงใน flow
   ```
   creative_finalize_asset_upload(asset_id, flow_id)
   ```
   ได้ `node_id` ของภาพ ขนาดไฟล์ที่รายงานกลับอาจต่างจากที่อัปโหลด เพราะ server แปลงไฟล์เอง ไม่ใช่ปัญหา

## 5) ภาพฉากและวิดีโอ AI (ขอราคาประเมิน → ผู้ใช้ยืนยัน → สร้าง)

### 5.1 ภาพฉากสินค้าในบ้านจริง (แนะนำเมื่อมีแค่ภาพพื้นขาว)

ถ้าใช้ภาพพื้นขาวเป็นเฟรมเริ่ม วิดีโอจะยังเป็นพื้นขาว และวินาทีแรกนิ่งเป็นภาพสินค้า ให้สร้างภาพฉากก่อน

```
creative_add_flow_node(flow_id, node_type="image-generation", model_id="bytedance-seedream-5-lite",
  connect_from=["<node_id ภาพสินค้า>"], model_parameters={"aspect_ratio": "9:16"},
  prompt="Keep the product exactly as in the reference image. Place it on <a black granite kitchen counter next to
  a stainless wok / a white vanity desk / a light wood floor> in a bright Thai home, natural window light,
  realistic phone photo, empty space at the top third, no text, no logo, no people.")
```

ขอราคาก่อนด้วย `creative_run_flow_nodes(flow_id, node_ids=[...], generations_count=1, estimate_only=true)`
- **ต้องใส่ `generations_count=1`** ไม่งั้นจะได้ 4 ใบและเสียเครดิต 4 เท่า

ผู้ใช้ยืนยันแล้วค่อยสร้างจริง จากนั้นดาวน์โหลด `master_url` แล้วตรวจด้วยตา
- รูปทรง สี และชิ้นส่วนของสินค้าต้องตรงกับภาพจริง ถ้าไม่ตรง **ห้ามใช้** เพราะจะเป็นการโชว์สินค้าผิดจากของจริง
- ภาพฉากใช้เป็นช็อตนิ่งได้ (ใส่ `ai: true`) และใช้เป็นเฟรมเริ่มของวิดีโอได้
- ถ้าสร้างหลายใบ node วิดีโอรับได้ใบเดียว ต้องปักใบที่เลือกด้วย `creative_add_flow_asset_node` (ใส่ generation_id ของใบนั้น) แล้วต่อเข้า node วิดีโอ

### 5.2 วิดีโอจากภาพ

1. **เฟรมเริ่มต้องเป็น 9:16**
   - ภาพฉากจาก 5.1 เป็น 9:16 อยู่แล้ว
   - ถ้าใช้ภาพอื่น ให้ทำด้วย `python3 <skill-dir>/scripts/build_video.py --frame input/<ภาพ> media/start_9x16.jpg` แล้วอัปโหลดตามหัวข้อ 4
2. **เช็กพารามิเตอร์ของโมเดลก่อน**: `creative_get_model_schema(node_type="video-generation", model_id=...)`
   - `kling-2.5-turbo` รับ `start_frame` และ `end_frame` พารามิเตอร์คือ `aspect_ratio`, `duration_secs` (5 หรือ 10), `negative_prompt`, `cfg_scale` (ค่าเริ่มต้น 0.5)
   - Seedance รับ `reference_images` เพิ่ม และมี `resolution`, `generate_audio`
3. **เพิ่ม node** (ยังไม่สร้าง)
   ```
   creative_add_flow_node(flow_id, node_type="video-generation", model_id="kling-2.5-turbo",
     prompt="<แม่แบบข้างล่าง>", connect_from=["<node_id เฟรมเริ่ม>"],
     model_parameters={"aspect_ratio": "9:16", "duration_secs": 5, "negative_prompt": "distortion, deformation, text, watermark, logo, extra fingers"})
   ```
   - ถ้าเป็น Seedance ให้ใช้ `{"aspect_ratio":"9:16","resolution":"720p","duration_secs":5,"generate_audio":false}`
4. **ขอราคาประเมิน** ด้วย `creative_run_flow_nodes(..., estimate_only=true)` แจ้งผู้ใช้ แล้ว**รอยืนยัน**
5. **สร้างจริง** แล้วรอผล 1–3 นาที ระหว่างรอให้ทำเสียงพากย์ไปก่อน จากนั้นดาวน์โหลด `master_url` เข้า `media/`
6. **ตรวจด้วยตา**: ดึงภาพ 1 เฟรมต่อวินาทีแล้วดู
   - สินค้าต้องไม่ผิดรูป และไม่มีมือหรือนิ้วผิดปกติ
   - การกระทำต้องทำได้จริง เช่น ไม่กดนิ้วลงบนฝาครอบ
   - หาวินาทีที่เริ่มขยับ (วินาทีแรกมักนิ่ง) แล้วใส่เป็น `start` ใน plan
   - ถ้าใช้ไม่ได้ให้บอกผู้ใช้ อย่าสร้างซ้ำเอง

**แม่แบบ prompt วิดีโอ** (เขียนภาษาอังกฤษ 1 คลิป = 1 การกระทำ)

```
Close-up handheld phone footage in a bright Thai home <kitchen/bedroom/vanity>: a hand <one concrete action that is
physically possible from the start frame and clearly visible on camera, e.g. tilts the bottle and pours a thin golden
stream of oil into a stainless wok>. Natural window light, realistic. Keep the product exactly as in the start frame,
no deformation, no text, no logos.
```

- บอกการเคลื่อนไหว อย่าบรรยายหน้าตาสินค้าซ้ำ
- เลือกการกระทำที่ตาเห็นชัด การเทหรือการเติมเห็นชัด แต่ละอองสเปรย์แทบมองไม่เห็น
- ถ้าเฟรมเริ่มมีฝาครอบปิดอยู่ อย่าสั่งให้กดหัวพ่น
- ไม่ต้องให้วิดีโอมีเสียง เพราะเสียงพากย์ทำแยก
