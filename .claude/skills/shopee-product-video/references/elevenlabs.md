# ElevenLabs: เสียงพากย์ไทยและวิดีโอ AI (เรียกผ่าน MCP)

ทดสอบจริงเมื่อ 15 ต.ค. 2026 เครื่องมือทั้งหมดเป็น deferred tool ต้องโหลดก่อนเรียก

```
ToolSearch "select:mcp__ElevenLabs__creative_create_flow,mcp__ElevenLabs__creative_list_voices,mcp__ElevenLabs__creative_generate_speech,mcp__ElevenLabs__creative_get_flow_run_status"
```

ถ้าจะทำวิดีโอ AI ให้โหลดเครื่องมือเหล่านี้เพิ่ม
- `creative_create_asset_upload`, `creative_finalize_asset_upload`
- `creative_add_flow_node`, `creative_get_model_schema`
- `creative_run_flow_nodes`, `creative_update_node`

ทุกการสร้างเสียงหรือวิดีโอ **ใช้เครดิตของผู้ใช้**
- ห้ามเรียกซ้ำเพื่อ "ลองใหม่" เพราะจะเสียเครดิตอีกรอบ
- ถ้าผลออกมาไม่ดี ให้ถามผู้ใช้ก่อนสร้างใหม่

## 0) สร้าง flow เดียวต่อ 1 คลิป

```
creative_create_flow(name="<สินค้า> – Shopee video", context="...")
```

เก็บ `flow_id` ไว้ใช้กับทุกการเรียกหลังจากนี้ ผู้ใช้จะเปิดดูทุกเทคได้ใน canvas เดียว

## 1) เลือกเสียง

```
creative_list_voices(languages=["th"], context="...")
```

- ห้ามใช้ voice_id จากความจำ ต้องเลือกจากผลที่ได้ทุกครั้ง
- ลำดับการเลือก
  1. เสียงที่ผู้ใช้ระบุ
  2. เสียง category `cloned` ถ้าผู้ใช้บอกว่าเป็นเสียงตัวเอง
     - ถามก่อน 1 ครั้งถ้ายังไม่รู้ว่าเป็นเสียงใคร
     - ข้อดี: เป็นตัวตนของครีเอเตอร์เอง
  3. เสียงไทยแนว Social Media / Conversational
     - ตอนทดสอบมีเสียงหญิง "Malee – Cheerful, Bright, Lively" และ "Nueng – Cheerful, Bright, Friendly"
     - และเสียงชาย "Chai – Upbeat, Playful, Punchy" และ "Ekkarat – Relaxed, Cheerful, Casual"
     - ให้ค้นด้วยชื่อหรือคำอธิบายนี้ใน list ใหม่ทุกครั้ง
- เสียงแนว Narration หรือ Advertisement จะช้าและเป็นทางการเกินไปสำหรับคลิปป้ายยา

## 2) สร้างเสียง 1 beat ต่อ 1 ครั้ง

```
creative_generate_speech(
  prompt="[excited] เก็บเส้นผม ฝุ่น ขนสัตว์ได้สะอาดมาก ไม่ต้องดูด ไม่ต้องล้างไม้ม็อบให้วุ่นวายเลยค่ะ",
  model_id="eleven_v4", voice_id="<จาก list>", flow_id="<flow>", generations_count=1, context="...")
```

- **โมเดล**: `eleven_v4` (หรือ `eleven_v3`)
  - `eleven_multilingual_v2`, `flash`, `turbo` ไม่รองรับภาษาไทยเต็มรูปแบบและไม่มีแท็กอารมณ์
- **แท็กอารมณ์**: ใส่ไม่บ่อย
  - `[excited]` ที่ beat แรก, `[warmly]` ที่ beat สุดท้าย
  - แท็กมีผลไปจนกว่าจะเจอแท็กใหม่
  - `build_video.py` ตัดแท็กออกก่อนนับตัวอักษรและก่อนเขียนไฟล์ซับให้เอง
- **ตัวเลข**: เขียนเป็นตัวเลขปกติได้เลย เช่น "470 ml" "3 ชั้น" v4 อ่านเองได้
- **คำอังกฤษ**: เช่น "ทูอินวัน" ให้เขียนเป็นภาษาไทย จะอ่านเป็นธรรมชาติกว่า "2 in 1"
- **generations_count=1 ต่อ beat**: ประหยัดเครดิตเป็น 4 เท่าเมื่อเทียบกับค่าเริ่มต้น 4 เทค
  - ถ้าผู้ใช้อยากได้หลายเทคให้เลือก ให้ส่ง 4 เฉพาะ beat แรก (hook)
- **ส่ง beat ทุก beat ใน flow เดียวกัน** เรียกต่อกันได้เลยโดยไม่ต้องรอ

**ราคาที่วัดได้**: ~1.2 เครดิตต่อตัวอักษร
- ประโยค 76 ตัวอักษร = 90 เครดิต
- สคริปต์ 30 วิ (ราว 550 ตัวอักษร) ≈ 650 เครดิต

**ความเร็วพูด**: เสียง v4 พูดไทยราว 12–14 ตัวอักษรต่อวินาที ช้ากว่าคลิปต้นแบบ (17–19) จึงต้องให้ `build_video.py` เร่งเองด้วย `tempo: "auto"`

## 3) รอผลและดาวน์โหลด

```
creative_get_flow_run_status(flow_id, session_ids=[...])
```

- เรียกซ้ำโดยเว้นช่วงตามค่า `poll_after_seconds` (ปกติ 3 วิ) จนได้ `all_completed: true`
- ลิงก์ไฟล์อยู่ที่ `media[].url` (หรือ `generations[].content_url`) เป็นลิงก์ storage.googleapis.com ที่ **หมดอายุใน 2 ชั่วโมง**

```bash
curl -sS -L -o video-jobs/<job>/vo/01.mp3 "<url>"
```

หมายเหตุเรื่องเครือข่าย
- ในสภาพแวดล้อมคลาวด์ที่ทดสอบ ดาวน์โหลดจาก storage.googleapis.com ได้
- แต่ api.us.elevenlabs.io ถูกบล็อก จึงต้องใช้ลิงก์ storage เสมอ

## 4) วิดีโอ AI จากภาพสินค้า (ต้องขอราคาประเมินและให้ผู้ใช้ยืนยันก่อน)

1. **อัปโหลดภาพสินค้า**
   ```
   creative_create_asset_upload(name, mime_type="image/jpeg", file_size=<ไบต์จริง>)
   ```
   ได้ `asset_id` และ `upload_url` จากนั้นอัปโหลดไฟล์ด้วยคำสั่งนี้
   ```bash
   curl -sS -X PUT -H "Content-Type: image/jpeg" --data-binary @input/product.jpg "<upload_url>"
   ```
   ต้องได้ HTTP 200
   ```
   creative_finalize_asset_upload(asset_id, flow_id)
   ```
   ได้ `node_id` ของภาพ
2. **เช็กพารามิเตอร์ของโมเดลก่อน**: `creative_get_model_schema(node_type="video-generation", model_id=...)` เพราะแต่ละโมเดลใช้ชื่อพารามิเตอร์ต่างกัน
3. **เพิ่ม node วิดีโอ** (ยังไม่สร้าง)
   ```
   creative_add_flow_node(flow_id, node_type="video-generation", model_id="kling-2.5-turbo",
     prompt="<ดูแม่แบบข้างล่าง>", connect_from=["<node_id ภาพ>"],
     model_parameters={"aspect_ratio": "9:16", "duration_secs": 5, "negative_prompt": "distortion, deformation, text, watermark, logo"})
   ```
   - ภาพจะเสียบเข้า `start_frame` ให้อัตโนมัติ
   - ถ้าเป็น Seedance ให้ใส่ `{"aspect_ratio":"9:16","resolution":"720p","duration_secs":5,"generate_audio":false}`
4. **ขอราคาประเมิน**: `creative_run_flow_nodes(flow_id, node_ids=[...], estimate_only=true)` แล้วแจ้งผู้ใช้ทั้งเครดิตและเงิน (USD) **รอให้ผู้ใช้ยืนยันก่อน**
5. **สร้างจริง**: เรียก `creative_run_flow_nodes` แบบไม่ใส่ estimate_only แล้วรอผล ใช้เวลาราว 1–3 นาที จากนั้นดาวน์โหลด mp4 เข้า `media/`
6. **ตรวจด้วยตา**: ดึงภาพ 4–6 เฟรม แล้วเช็กว่าสินค้าไม่ผิดรูป ไม่มีตัวหนังสือแปลกๆ และไม่มีมือ 6 นิ้ว ถ้าเสีย ให้บอกผู้ใช้ อย่าสร้างซ้ำเอง

**ราคาประเมินคลิป 5 วิ แนวตั้ง 9:16** (15 ต.ค. 2026 อาจเปลี่ยน ให้ขอราคาประเมินทุกครั้ง)

| โมเดล | เครดิต | USD | ใช้เมื่อ |
|---|---|---|---|
| `kling-2.5-turbo` | ~2,100 | ~$0.39 | ค่าเริ่มต้น ถูกสุด รับแค่ start_frame |
| `bytedance-seedance-v2-mini` (720p) | ~4,600 | ~$0.83 | ภาพสมจริงกว่า |
| `bytedance-seedance-v2.5` (720p) | ~14,000 | ~$2.55 | งานสำคัญ การเทหรือการจับของต้องสมจริง |

**แม่แบบ prompt** (เขียนเป็นภาษาอังกฤษจะได้ผลดีกว่า และ 1 คลิปให้มี 1 การกระทำ)

```
Close-up handheld phone footage in a bright Thai home <kitchen/bedroom/vanity>: a hand <one concrete action
with the product, e.g. presses the pump and oil sprays into a stainless wok>. Natural window light, realistic.
Keep the product exactly as in the reference image, no deformation, no text, no logos.
```

- บอกการเคลื่อนไหว อย่าบรรยายหน้าตาสินค้าซ้ำ
- ถ้าภาพสินค้าเป็นภาพพื้นขาว (packshot) คลิปจะเริ่มจากพื้นขาว ทางเลือกคือสร้างภาพฉากในบ้านก่อนด้วย node `image-generation` (เช่น `bytedance-seedream-5-pro` พร้อมภาพอ้างอิง) แล้วใช้ภาพฉากนั้นเป็น start_frame
  - วิธีนี้เพิ่มเครดิตภาพอีก 1 ใบ ให้ขอราคาประเมินด้วย
- ไม่ต้องให้วิดีโอมีเสียง เพราะเสียงพากย์ทำแยก
