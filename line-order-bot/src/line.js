'use strict';

const crypto = require('crypto');

const API_BASE = 'https://api.line.me/v2/bot';
const DATA_BASE = 'https://api-data.line.me/v2/bot';

/**
 * ตรวจลายเซ็น webhook ตามคู่มือ LINE Messaging API
 * @param {string} channelSecret
 * @param {Buffer} rawBody
 * @param {string} signature ค่าจาก header x-line-signature
 */
function verifySignature(channelSecret, rawBody, signature) {
  if (!signature) return false;
  const expected = crypto
    .createHmac('sha256', channelSecret)
    .update(rawBody)
    .digest('base64');
  try {
    return crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(signature));
  } catch {
    return false;
  }
}

async function lineFetch(accessToken, url, options = {}) {
  const res = await fetch(url, {
    ...options,
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
      ...options.headers,
    },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`LINE API ${res.status}: ${body}`);
  }
  return res;
}

// ใช้ reply เป็นหลักเพราะฟรีไม่จำกัดโควตา — push ใช้เฉพาะแจ้งเตือนเจ้าของร้าน
async function reply(accessToken, replyToken, messages) {
  await lineFetch(accessToken, `${API_BASE}/message/reply`, {
    method: 'POST',
    body: JSON.stringify({ replyToken, messages }),
  });
}

async function push(accessToken, to, messages) {
  await lineFetch(accessToken, `${API_BASE}/message/push`, {
    method: 'POST',
    body: JSON.stringify({ to, messages }),
  });
}

/** ดาวน์โหลดไฟล์แนบ (รูปสลิป) จาก LINE */
async function getMessageContent(accessToken, messageId) {
  const res = await lineFetch(accessToken, `${DATA_BASE}/message/${messageId}/content`, {
    headers: { 'Content-Type': undefined },
  });
  return Buffer.from(await res.arrayBuffer());
}

module.exports = { verifySignature, reply, push, getMessageContent };
