'use strict';

// ตรรกะบทสนทนาทั้งหมดของบอท — โค้ดชุดเดียว ใช้กับทุกร้าน (tenant) ผ่าน config

const line = require('./line');
const store = require('./store');
const { verifySlip } = require('./slipVerify');

const { ORDER_STATUS } = store;

function baht(n) {
  return n.toLocaleString('th-TH', { minimumFractionDigits: 0 });
}

function catalogText(tenant) {
  const lines = tenant.products.map(
    (p) => `${p.code}. ${p.name} — ${baht(p.price)} บาท${p.note ? ` (${p.note})` : ''}`
  );
  return [
    `🛍️ สินค้าของ ${tenant.name}`,
    '',
    ...lines,
    '',
    'สั่งซื้อพิมพ์: สั่ง <รหัส> <จำนวน>',
    'เช่น  สั่ง 1 2',
    'ดูตะกร้าพิมพ์: ตะกร้า | ยืนยันออเดอร์พิมพ์: ยืนยัน',
  ].join('\n');
}

function cartText(tenant, order) {
  if (!order || order.items.length === 0) {
    return 'ตะกร้ายังว่างอยู่ค่ะ 🧺 พิมพ์ "เมนู" เพื่อดูสินค้า';
  }
  const lines = order.items.map(
    (it) => `• ${it.name} x${it.qty} = ${baht(it.price * it.qty)} บาท`
  );
  const itemsTotal = order.items.reduce((s, it) => s + it.price * it.qty, 0);
  const shipping = tenant.shippingFlatRate || 0;
  return [
    '🧺 ตะกร้าของคุณ',
    ...lines,
    `ค่าส่ง ${baht(shipping)} บาท`,
    `รวมทั้งหมด ${baht(itemsTotal + shipping)} บาท`,
    '',
    'พิมพ์ "ยืนยัน" เพื่อสั่งซื้อ หรือ "ล้างตะกร้า" เพื่อเริ่มใหม่',
  ].join('\n');
}

function orderSummaryText(tenant, order) {
  const lines = order.items.map(
    (it) => `• ${it.name} x${it.qty} = ${baht(it.price * it.qty)} บาท`
  );
  return [
    `✅ รับออเดอร์แล้ว! หมายเลข ${order.id}`,
    ...lines,
    `ค่าส่ง ${baht(order.shipping)} บาท`,
    `ยอดชำระ ${baht(order.total)} บาท`,
    '',
    `สแกน QR ด้านล่างเพื่อโอนผ่าน PromptPay (ยอดถูกล็อกไว้แล้ว)`,
    'โอนเสร็จแล้ว ส่งรูปสลิปเข้ามาในแชทนี้ได้เลยค่ะ 🙏',
  ].join('\n');
}

function qrImageUrl(baseUrl, tenantId, orderId) {
  return `${baseUrl}/qr/${encodeURIComponent(tenantId)}/${encodeURIComponent(orderId)}.png`;
}

function matchFaq(tenant, text) {
  for (const faq of tenant.faq || []) {
    if (faq.keywords.some((k) => text.includes(k))) return faq.answer;
  }
  return null;
}

async function notifyOwner(tenant, text) {
  if (!tenant.ownerUserId) return;
  try {
    await line.push(tenant.accessToken, tenant.ownerUserId, [{ type: 'text', text }]);
  } catch (err) {
    console.error(`[${tenant.id}] push to owner failed:`, err.message);
  }
}

// ---------- คำสั่งฝั่งเจ้าของร้าน ----------

async function handleOwnerCommand(tenant, text, replyToken) {
  const approve = text.match(/^อนุมัติ\s+(OD\d+)/i);
  const cancel = text.match(/^ยกเลิก\s+(OD\d+)/i);
  const m = approve || cancel;
  if (!m) return false;

  const orders = store.loadOrders();
  const order = store.findById(orders, tenant.id, m[1].toUpperCase());
  if (!order) {
    await line.reply(tenant.accessToken, replyToken, [
      { type: 'text', text: `ไม่พบออเดอร์ ${m[1]} ของร้านนี้ค่ะ` },
    ]);
    return true;
  }

  if (approve) {
    order.status = ORDER_STATUS.PAID;
    order.paidAt = new Date().toISOString();
  } else {
    order.status = ORDER_STATUS.CANCELLED;
  }
  store.saveOrders(orders);

  await line.reply(tenant.accessToken, replyToken, [
    {
      type: 'text',
      text: approve
        ? `✅ ยืนยันรับเงินออเดอร์ ${order.id} แล้ว แจ้งลูกค้าให้แล้วค่ะ`
        : `🚫 ยกเลิกออเดอร์ ${order.id} แล้ว แจ้งลูกค้าให้แล้วค่ะ`,
    },
  ]);
  await line.push(tenant.accessToken, order.userId, [
    {
      type: 'text',
      text: approve
        ? `ร้าน ${tenant.name} ตรวจสอบยอดโอนของออเดอร์ ${order.id} เรียบร้อยแล้ว ✅ กำลังเตรียมจัดส่งค่ะ ขอบคุณที่อุดหนุนนะคะ 💕`
        : `ขออภัยค่ะ ออเดอร์ ${order.id} ถูกยกเลิก ติดต่อร้านได้ทางแชทนี้เลยค่ะ`,
    },
  ]);
  return true;
}

// ---------- ข้อความจากลูกค้า ----------

async function handleText(tenant, event, baseUrl) {
  const text = event.message.text.trim();
  const userId = event.source.userId;
  const rt = event.replyToken;
  const say = (msgs) => line.reply(tenant.accessToken, rt, msgs);

  // เจ้าของร้านสั่งงานผ่านแชทเดียวกันได้
  if (userId === tenant.ownerUserId && (await handleOwnerCommand(tenant, text, rt))) return;

  if (/^(เมนู|สินค้า|catalog|menu)$/i.test(text)) {
    return say([{ type: 'text', text: catalogText(tenant) }]);
  }

  const orderCmd = text.match(/^สั่ง\s+(\S+)(?:\s+(\d+))?/);
  if (orderCmd) {
    const product = tenant.products.find((p) => String(p.code) === orderCmd[1]);
    if (!product) {
      return say([
        { type: 'text', text: `ไม่พบสินค้ารหัส "${orderCmd[1]}" ค่ะ พิมพ์ "เมนู" เพื่อดูรหัสสินค้า` },
      ]);
    }
    const qty = Math.max(1, parseInt(orderCmd[2] || '1', 10));

    const orders = store.loadOrders();
    let draft = store.findDraft(orders, tenant.id, userId);
    if (!draft) {
      draft = {
        id: store.nextOrderId(orders),
        tenantId: tenant.id,
        userId,
        status: ORDER_STATUS.DRAFT,
        items: [],
        createdAt: new Date().toISOString(),
      };
      orders.push(draft);
    }
    const existing = draft.items.find((it) => it.code === product.code);
    if (existing) existing.qty += qty;
    else draft.items.push({ code: product.code, name: product.name, price: product.price, qty });
    store.saveOrders(orders);

    return say([
      { type: 'text', text: `เพิ่ม ${product.name} x${qty} แล้วค่ะ 🛒\n\n${cartText(tenant, draft)}` },
    ]);
  }

  if (/^ตะกร้า$/i.test(text)) {
    const draft = store.findDraft(store.loadOrders(), tenant.id, userId);
    return say([{ type: 'text', text: cartText(tenant, draft) }]);
  }

  if (/^ล้างตะกร้า$/i.test(text)) {
    const orders = store.loadOrders();
    const draft = store.findDraft(orders, tenant.id, userId);
    if (draft) {
      draft.status = ORDER_STATUS.CANCELLED;
      store.saveOrders(orders);
    }
    return say([{ type: 'text', text: 'ล้างตะกร้าแล้วค่ะ พิมพ์ "เมนู" เพื่อเริ่มใหม่' }]);
  }

  if (/^ยืนยัน$/i.test(text)) {
    const orders = store.loadOrders();
    const draft = store.findDraft(orders, tenant.id, userId);
    if (!draft || draft.items.length === 0) {
      return say([{ type: 'text', text: 'ยังไม่มีสินค้าในตะกร้าค่ะ พิมพ์ "เมนู" เพื่อเลือกสินค้า' }]);
    }

    // โควตา freemium: เกินแพ็กเกจฟรีแล้วยังรับออเดอร์ต่อ แต่แจ้งเจ้าของร้านให้อัปเกรด
    const used = store.confirmedOrdersThisMonth(orders, tenant.id);
    const quota = tenant.monthlyOrderQuota ?? 30;
    if (used >= quota) {
      await notifyOwner(
        tenant,
        `⚠️ ร้านของคุณใช้ครบ ${quota} ออเดอร์ของแพ็กเกจเดือนนี้แล้ว (ออเดอร์ที่ ${used + 1} กำลังเข้ามา) อัปเกรดแพ็กเกจเพื่อใช้งานต่อเนื่องค่ะ`
      );
    }

    const itemsTotal = draft.items.reduce((s, it) => s + it.price * it.qty, 0);
    draft.shipping = tenant.shippingFlatRate || 0;
    draft.total = itemsTotal + draft.shipping;
    draft.status = ORDER_STATUS.AWAITING_PAYMENT;
    draft.confirmedAt = new Date().toISOString();
    store.saveOrders(orders);

    await notifyOwner(
      tenant,
      `🔔 ออเดอร์ใหม่ ${draft.id} ยอด ${baht(draft.total)} บาท (${draft.items.length} รายการ) — รอลูกค้าโอนเงินค่ะ`
    );

    return say([
      { type: 'text', text: orderSummaryText(tenant, draft) },
      {
        type: 'image',
        originalContentUrl: qrImageUrl(baseUrl, tenant.id, draft.id),
        previewImageUrl: qrImageUrl(baseUrl, tenant.id, draft.id),
      },
    ]);
  }

  const faqAnswer = matchFaq(tenant, text);
  if (faqAnswer) {
    return say([{ type: 'text', text: faqAnswer }]);
  }

  return say([
    {
      type: 'text',
      text:
        `สวัสดีค่ะ ยินดีต้อนรับสู่ ${tenant.name} 🙏\n` +
        'พิมพ์ "เมนู" เพื่อดูสินค้า | "ตะกร้า" เพื่อดูออเดอร์\n' +
        'หรือพิมพ์คำถามได้เลย เดี๋ยวแอดมินตัวจริงมาตอบเสริมค่ะ',
    },
  ]);
}

// ---------- รูปภาพ (สลิปโอนเงิน) ----------

async function handleImage(tenant, event) {
  const userId = event.source.userId;
  const rt = event.replyToken;
  const orders = store.loadOrders();
  const order = store.findAwaiting(orders, tenant.id, userId);

  if (!order) {
    return line.reply(tenant.accessToken, rt, [
      { type: 'text', text: 'ได้รับรูปแล้วค่ะ 📷 ถ้าต้องการสั่งซื้อ พิมพ์ "เมนู" ได้เลยค่ะ' },
    ]);
  }

  const slip = await line.getMessageContent(tenant.accessToken, event.message.id);
  const slipFile = store.saveSlip(order.id, slip);
  order.slipFile = slipFile;

  const result = await verifySlip(tenant, slip, order);
  if (result.verified) {
    order.status = ORDER_STATUS.PAID;
    order.paidAt = new Date().toISOString();
    store.saveOrders(orders);
    await notifyOwner(tenant, `💰 ออเดอร์ ${order.id} ตรวจสลิปผ่านอัตโนมัติ ยอด ${baht(order.total)} บาท`);
    return line.reply(tenant.accessToken, rt, [
      { type: 'text', text: `ตรวจสอบยอดโอนเรียบร้อยค่ะ ✅ ออเดอร์ ${order.id} กำลังเตรียมจัดส่ง ขอบคุณที่อุดหนุนนะคะ 💕` },
    ]);
  }

  order.status = ORDER_STATUS.AWAITING_VERIFY;
  store.saveOrders(orders);
  await notifyOwner(
    tenant,
    `📩 ลูกค้าส่งสลิปออเดอร์ ${order.id} ยอด ${baht(order.total)} บาท แล้ว\nตรวจสอบแล้วพิมพ์: อนุมัติ ${order.id}\nหรือ: ยกเลิก ${order.id}`
  );
  return line.reply(tenant.accessToken, rt, [
    { type: 'text', text: `ได้รับสลิปแล้วค่ะ 🙏 กำลังตรวจสอบยอดโอนของออเดอร์ ${order.id} เดี๋ยวแจ้งผลทางแชทนี้นะคะ` },
  ]);
}

async function handleEvent(tenant, event, baseUrl) {
  if (event.type !== 'message') return;
  if (event.message.type === 'text') return handleText(tenant, event, baseUrl);
  if (event.message.type === 'image') return handleImage(tenant, event);
}

module.exports = { handleEvent };
