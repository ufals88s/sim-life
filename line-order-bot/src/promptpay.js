'use strict';

// สร้าง PromptPay payload ตามมาตรฐาน EMVCo QR (Tag 29 – credit transfer)
// รองรับทั้งเบอร์โทรศัพท์ (10 หลัก) และเลขบัตรประชาชน/เลขประจำตัวผู้เสียภาษี (13 หลัก)

const PROMPTPAY_AID = 'A000000677010111';

function tlv(tag, value) {
  const len = String(value.length).padStart(2, '0');
  return `${tag}${len}${value}`;
}

// CRC-16/CCITT-FALSE (polynomial 0x1021, init 0xFFFF) ตามที่สเปก EMVCo กำหนด
function crc16(input) {
  let crc = 0xffff;
  for (let i = 0; i < input.length; i++) {
    crc ^= input.charCodeAt(i) << 8;
    for (let bit = 0; bit < 8; bit++) {
      crc = crc & 0x8000 ? ((crc << 1) ^ 0x1021) & 0xffff : (crc << 1) & 0xffff;
    }
  }
  return crc.toString(16).toUpperCase().padStart(4, '0');
}

function formatTarget(id) {
  const digits = id.replace(/\D/g, '');
  if (digits.length === 13) {
    return { tag: '02', value: digits }; // เลขบัตรประชาชน / tax id
  }
  // เบอร์โทร: แปลง 08xxxxxxxx -> 00668xxxxxxxx
  const msisdn = `0066${digits.replace(/^0/, '')}`;
  return { tag: '01', value: msisdn };
}

/**
 * @param {string} target เบอร์โทรหรือเลขบัตรประชาชนของร้าน
 * @param {number} amount จำนวนเงิน (บาท) — ระบุแล้ว QR จะล็อกยอดโอน
 * @returns {string} EMVCo payload สำหรับนำไปทำ QR code
 */
function buildPromptPayPayload(target, amount) {
  const { tag, value } = formatTarget(target);
  const merchantInfo = tlv('00', PROMPTPAY_AID) + tlv(tag, value);

  let payload =
    tlv('00', '01') + // payload format indicator
    tlv('01', '12') + // point of initiation: 12 = dynamic (ใช้ครั้งเดียว)
    tlv('29', merchantInfo) +
    tlv('53', '764') + // currency: THB
    (amount != null ? tlv('54', amount.toFixed(2)) : '') +
    tlv('58', 'TH');

  payload += '6304'; // CRC tag + length, คำนวณ CRC รวมส่วนนี้ด้วย
  return payload + crc16(payload);
}

module.exports = { buildPromptPayPayload };
