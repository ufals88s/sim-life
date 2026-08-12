'use strict';

const express = require('express');
const QRCode = require('qrcode');

const line = require('./line');
const store = require('./store');
const flow = require('./flow');
const { buildPromptPayPayload } = require('./promptpay');

const PORT = process.env.PORT || 3000;
// URL สาธารณะของเซิร์ฟเวอร์ (ต้องเป็น https เพราะ LINE โหลดรูป QR จากที่นี่)
const BASE_URL = (process.env.BASE_URL || `http://localhost:${PORT}`).replace(/\/$/, '');

const app = express();

// เก็บ raw body ไว้ตรวจลายเซ็น webhook
app.use(
  express.json({
    verify: (req, _res, buf) => {
      req.rawBody = buf;
    },
  })
);

app.get('/healthz', (_req, res) => res.json({ ok: true }));

// webhook แยกตามร้าน: ตั้งค่าใน LINE Developers เป็น {BASE_URL}/webhook/<tenantId>
app.post('/webhook/:tenantId', async (req, res) => {
  const tenant = store.getTenant(req.params.tenantId);
  if (!tenant) return res.sendStatus(404);

  if (!line.verifySignature(tenant.channelSecret, req.rawBody, req.get('x-line-signature'))) {
    return res.sendStatus(401);
  }

  // ตอบ 200 ทันทีตามข้อกำหนดของ LINE แล้วค่อยประมวลผลต่อ
  res.sendStatus(200);

  for (const event of req.body.events || []) {
    try {
      await flow.handleEvent(tenant, event, BASE_URL);
    } catch (err) {
      console.error(`[${tenant.id}] event error:`, err);
    }
  }
});

// รูป QR PromptPay ของออเดอร์ — LINE ดึงรูปจาก endpoint นี้ไปแสดงในแชท
app.get('/qr/:tenantId/:orderId.png', async (req, res) => {
  const tenant = store.getTenant(req.params.tenantId);
  if (!tenant) return res.sendStatus(404);

  const order = store.findById(store.loadOrders(), tenant.id, req.params.orderId);
  if (!order || !order.total) return res.sendStatus(404);

  const payload = buildPromptPayPayload(tenant.promptpayId, order.total);
  const png = await QRCode.toBuffer(payload, { type: 'png', width: 512, margin: 2 });
  res.set('Content-Type', 'image/png').send(png);
});

app.listen(PORT, () => {
  const tenants = store.loadTenants();
  console.log(`line-order-bot listening on :${PORT}`);
  console.log(`base url: ${BASE_URL}`);
  for (const t of tenants) {
    console.log(`  tenant "${t.id}" (${t.name}) -> ${BASE_URL}/webhook/${t.id}`);
  }
});
