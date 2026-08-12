'use strict';

// จุดต่อระบบตรวจสลิปอัตโนมัติ
//
// อย่าใช้ OCR อ่านรูปสลิปเพื่อ "อนุมัติอัตโนมัติ" เด็ดขาด — สลิปปลอมทำง่ายมาก
// ให้ตรวจกับผู้ให้บริการที่เช็คธุรกรรมจริงกับธนาคาร เช่น SlipOK, Slip2Go
// หรือ API ของธนาคารโดยตรง แล้วเทียบ 3 อย่าง: ยอดเงิน, บัญชีปลายทาง, เวลาโอน
//
// MVP นี้ตั้งค่าเริ่มต้นเป็น "ให้เจ้าของร้านกดอนุมัติเอง" ซึ่งปลอดภัยและ
// เพียงพอสำหรับร้านเล็ก เมื่อพร้อมค่อยเสียบ API ตรงนี้ที่เดียว ทุกร้านได้ใช้ทันที

/**
 * @param {object} tenant ร้านค้า (อ่าน API key ของผู้ให้บริการจาก tenant.slipApiKey)
 * @param {Buffer} slipImage รูปสลิปจากลูกค้า
 * @param {object} order ออเดอร์ที่รอชำระ (ใช้ order.total เทียบยอด)
 * @returns {Promise<{verified: boolean, reason: string}>}
 */
async function verifySlip(tenant, slipImage, order) {
  if (!tenant.slipApiKey) {
    return { verified: false, reason: 'manual' }; // ไม่ได้ตั้ง API — รอเจ้าของร้านอนุมัติ
  }

  // ตัวอย่างโครงเรียก SlipOK (ปรับตาม endpoint จริงของผู้ให้บริการที่เลือกใช้):
  //
  // const form = new FormData();
  // form.append('files', new Blob([slipImage]), 'slip.jpg');
  // form.append('amount', String(order.total));
  // const res = await fetch('https://api.slipok.com/api/line/apikey/<branchId>', {
  //   method: 'POST',
  //   headers: { 'x-authorization': tenant.slipApiKey },
  //   body: form,
  // });
  // const data = await res.json();
  // return { verified: data.success === true, reason: data.message || '' };

  return { verified: false, reason: 'manual' };
}

module.exports = { verifySlip };
