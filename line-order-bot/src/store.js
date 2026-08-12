'use strict';

// เก็บข้อมูลเป็นไฟล์ JSON เพื่อให้ MVP รันได้ทันทีโดยไม่ต้องตั้งฐานข้อมูล
// โครงสร้างถูกออกแบบให้ย้ายไป PostgreSQL/SQLite ได้ตรงๆ (ทุกตารางมี tenantId)

const fs = require('fs');
const path = require('path');

const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, '..', 'data');

function ensureDataDir() {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  fs.mkdirSync(path.join(DATA_DIR, 'slips'), { recursive: true });
}

function readJson(name, fallback) {
  try {
    return JSON.parse(fs.readFileSync(path.join(DATA_DIR, name), 'utf8'));
  } catch {
    return fallback;
  }
}

function writeJson(name, value) {
  ensureDataDir();
  const file = path.join(DATA_DIR, name);
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(value, null, 2));
  fs.renameSync(tmp, file);
}

// ---------- tenants (ร้านค้า) ----------

function loadTenants() {
  const tenants = readJson('tenants.json', null);
  if (!tenants) {
    throw new Error(
      'ไม่พบ data/tenants.json — คัดลอกจาก data/tenants.example.json แล้วใส่ค่าจริงของร้าน'
    );
  }
  return tenants;
}

function getTenant(tenantId) {
  return loadTenants().find((t) => t.id === tenantId) || null;
}

// ---------- orders ----------

const ORDER_STATUS = {
  DRAFT: 'draft', // กำลังเลือกสินค้า (ตะกร้า)
  AWAITING_PAYMENT: 'awaiting_payment', // ยืนยันแล้ว รอโอน
  AWAITING_VERIFY: 'awaiting_verify', // ส่งสลิปแล้ว รอตรวจ
  PAID: 'paid',
  CANCELLED: 'cancelled',
};

function loadOrders() {
  return readJson('orders.json', []);
}

function saveOrders(orders) {
  writeJson('orders.json', orders);
}

function nextOrderId(orders) {
  const n = orders.length + 1;
  return `OD${String(n).padStart(5, '0')}`;
}

function findDraft(orders, tenantId, userId) {
  return orders.find(
    (o) => o.tenantId === tenantId && o.userId === userId && o.status === ORDER_STATUS.DRAFT
  );
}

function findAwaiting(orders, tenantId, userId) {
  return orders.find(
    (o) =>
      o.tenantId === tenantId &&
      o.userId === userId &&
      o.status === ORDER_STATUS.AWAITING_PAYMENT
  );
}

function findById(orders, tenantId, orderId) {
  return orders.find((o) => o.tenantId === tenantId && o.id === orderId);
}

/** นับออเดอร์ที่ยืนยันแล้วของร้านในเดือนปัจจุบัน — ใช้คุมโควตา freemium */
function confirmedOrdersThisMonth(orders, tenantId) {
  const now = new Date();
  const monthKey = `${now.getUTCFullYear()}-${now.getUTCMonth()}`;
  return orders.filter((o) => {
    if (o.tenantId !== tenantId || !o.confirmedAt) return false;
    const d = new Date(o.confirmedAt);
    return `${d.getUTCFullYear()}-${d.getUTCMonth()}` === monthKey;
  }).length;
}

function saveSlip(orderId, buffer) {
  ensureDataDir();
  const file = path.join(DATA_DIR, 'slips', `${orderId}-${Date.now()}.jpg`);
  fs.writeFileSync(file, buffer);
  return file;
}

module.exports = {
  ORDER_STATUS,
  loadTenants,
  getTenant,
  loadOrders,
  saveOrders,
  nextOrderId,
  findDraft,
  findAwaiting,
  findById,
  confirmedOrdersThisMonth,
  saveSlip,
};
