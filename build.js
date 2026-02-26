const crypto = require('crypto');
const fs = require('fs');

const PASSWORD = '1029';

const DATA = {
  updatedAt: "2026-02-26",
  ccPositions: [
    { ticker: "PDD", strike: 108, expiry: "2026-02-27", premium: 58, costPerShare: 107.66, sellDate: "2026-02-14", shares: 100 },
    { ticker: "JD", strike: 31, expiry: "2026-03-06", premium: 42, costPerShare: 31.94, sellDate: "2026-02-14", shares: 100 },
    { ticker: "LI", strike: 19.5, expiry: "2026-02-27", premium: 39, costPerShare: 23.01, sellDate: "2026-02-14", shares: 100 },
    { ticker: "CRCL", strike: 65, expiry: "2026-06-18", premium: 720, costPerShare: 63.60, sellDate: "2026-01-20", shares: 100 },
    { ticker: "NFLX", strike: 81, expiry: "2026-03-06", premium: 120, costPerShare: 80.15, sellDate: "2026-02-13", shares: 100 }
  ],
  cspPositions: [
    { ticker: "CRM", strike: 185, expiry: "2026-02-27", premium: 565, collateral: 18500, sellDate: "2026-02-25" },
    { ticker: "COIN", strike: 167.5, expiry: "2026-02-27", premium: 120, collateral: 16750, sellDate: "2026-02-25" },
    { ticker: "ORCL", strike: 135, expiry: "2026-02-27", premium: 240, collateral: 13500, sellDate: "2026-02-23" },
    { ticker: "NET", strike: 155, expiry: "2026-02-27", premium: 334, collateral: 15500, sellDate: "2026-02-24" },
    { ticker: "AVGO", strike: 310, expiry: "2026-02-27", premium: 320, collateral: 31000, sellDate: "2026-02-24" }
  ],
  closedTrades: [
    { ticker: "CRM", type: "CSP", strike: 170, openDate: "2026-02-23", closeDate: "2026-02-25", premium: 418, assigned: false, note: "平仓获利$418，滚仓至$185" },
    { ticker: "COIN", type: "CSP", strike: 157.5, openDate: "2026-02-23", closeDate: "2026-02-25", premium: 201, assigned: false, note: "平仓获利$201，滚仓至$167.5" },
    { ticker: "COIN", type: "CC", strike: 167.5, openDate: "2026-02-19", closeDate: "2026-02-20", premium: 170, assigned: true, note: "被Assign，100股call走" },
    { ticker: "PDD", type: "CC", strike: 104, openDate: "2026-02-14", closeDate: "2026-02-20", premium: 45, assigned: true, note: "被Assign，100股call走" },
    { ticker: "NIO", type: "CC", strike: 5, openDate: "2026-02-14", closeDate: "2026-02-20", premium: 8, assigned: true, note: "被Assign，清退完成" },
    { ticker: "PDD", type: "CC", strike: 112, openDate: "2026-02-13", closeDate: "2026-02-17", premium: 70.52, assigned: false, note: "买回平仓@$0.05" },
    { ticker: "PDD", type: "CC", strike: 110, openDate: "2026-01-30", closeDate: "2026-02-07", premium: 168.85, assigned: false, note: "到期归零" },
    { ticker: "JD", type: "CC", strike: 32, openDate: "2026-01-24", closeDate: "2026-01-31", premium: 21.27, assigned: false, note: "到期归零" },
    { ticker: "NIO", type: "CC", strike: 6, openDate: "2026-01-24", closeDate: "2026-01-31", premium: 12.96, assigned: false, note: "到期归零" }
  ],
  idlePositions: [
    { ticker: "NEOV", shares: 100, cost: 4.41, canCC: true, note: "低价股，CC权利金极低" },
    { ticker: "COPX", shares: 60, cost: 84.24, canCC: false, note: "不足100股" },
    { ticker: "CRM", shares: 20, cost: 184.65, canCC: false, note: "不足100股，CSP接回中" },
    { ticker: "AMD", shares: 20, cost: 214.35, canCC: false, note: "不足100股" },
    { ticker: "PYPL", shares: 20, cost: 42.95, canCC: false, note: "不足100股" },
    { ticker: "AMZN", shares: 10, cost: 205.37, canCC: false, note: "不足100股" }
  ],
  wheelCycles: [
    { ticker: "COIN", phase: "csp", detail: "CSP $167.5 2/27", note: "滚仓提strike，接回中" },
    { ticker: "CRM", phase: "csp", detail: "CSP $185 2/27", note: "滚仓提strike，建仓中" },
    { ticker: "ORCL", phase: "csp", detail: "CSP $135 2/27", note: "新标的，Sell Put建仓" },
    { ticker: "NET", phase: "csp", detail: "CSP $155 2/27", note: "新标的，Sell Put建仓" },
    { ticker: "AVGO", phase: "csp", detail: "CSP $310 2/27", note: "新标的，Sell Put建仓" },
    { ticker: "PDD", phase: "cc", detail: "CC $108 2/27", note: "100股持有中" },
    { ticker: "JD", phase: "cc-exit", detail: "CC $31 3/6", note: "清退中，让assign" },
    { ticker: "LI", phase: "cc-exit", detail: "CC $19.5 2/27", note: "清退中，让assign" },
    { ticker: "NFLX", phase: "cc", detail: "CC $81 3/6", note: "保股票为主" },
    { ticker: "CRCL", phase: "cc-locked", detail: "CC $65 6/18", note: "远期锁定" }
  ],
  optChanges: [
    { action: "已完成", cls: "done", detail: "CRM CSP $170 平仓获利$418，滚仓至$185" },
    { action: "已完成", cls: "done", detail: "COIN CSP $157.5 平仓获利$201，滚仓至$167.5" },
    { action: "已完成", cls: "done", detail: "COIN 100股被CC $167.5 assign，回笼$16,920" },
    { action: "已完成", cls: "done", detail: "PDD 100股被CC $104 assign，回笼$10,445" },
    { action: "已完成", cls: "done", detail: "NIO 100股被CC $5 assign，清退完成" },
    { action: "进行中", cls: "active", detail: "COIN CSP $167.5 2/27 接回中（滚仓）" },
    { action: "进行中", cls: "active", detail: "CRM CSP $185 2/27 建仓中（滚仓）" },
    { action: "进行中", cls: "active", detail: "ORCL CSP $135 2/27 新加入Wheel池" },
    { action: "进行中", cls: "active", detail: "NET CSP $155 2/27 新加入Wheel池" },
    { action: "进行中", cls: "active", detail: "AVGO CSP $310 2/27 新加入Wheel池" },
    { action: "待执行", cls: "pending", detail: "NEOV 100股 清仓 (~$441)" },
    { action: "待执行", cls: "pending", detail: "PYPL 20股 清仓 (~$859)" }
  ],
  optEstimates: [
    { ticker: "COIN", shares: 100, contracts: 1, monthlyPremium: 800, cost: 16194 },
    { ticker: "PDD", shares: 100, contracts: 1, monthlyPremium: 60, cost: 10766 },
    { ticker: "CRCL", shares: 100, contracts: 1, monthlyPremium: 200, cost: 6360 },
    { ticker: "NFLX", shares: 100, contracts: 1, monthlyPremium: 150, cost: 8015 },
    { ticker: "CRM", shares: 100, contracts: 1, monthlyPremium: 500, cost: 17000 },
    { ticker: "ORCL", shares: 100, contracts: 1, monthlyPremium: 300, cost: 13500 },
    { ticker: "NET", shares: 100, contracts: 1, monthlyPremium: 600, cost: 15500 },
    { ticker: "AVGO", shares: 100, contracts: 1, monthlyPremium: 1200, cost: 31000 }
  ]
};

// Encrypt
function encrypt(data, password) {
  const salt = crypto.randomBytes(16);
  const iv = crypto.randomBytes(12);
  const key = crypto.pbkdf2Sync(password, salt, 100000, 32, 'sha256');
  const cipher = crypto.createCipheriv('aes-256-gcm', key, iv);
  const json = JSON.stringify(data);
  let encrypted = cipher.update(json, 'utf8');
  const final = cipher.final();
  encrypted = Buffer.concat([encrypted, final]);
  const tag = cipher.getAuthTag();
  return {
    salt: salt.toString('base64'),
    iv: iv.toString('base64'),
    tag: tag.toString('base64'),
    data: encrypted.toString('base64')
  };
}

const ENC = encrypt(DATA, PASSWORD);

// Read template and inject
const template = fs.readFileSync(__dirname + '/template.html', 'utf8');
const output = template.replace('__ENCRYPTED_DATA__', JSON.stringify(ENC));
fs.writeFileSync(__dirname + '/index.html', output);
console.log('✅ Dashboard built successfully');
console.log('Data size:', JSON.stringify(DATA).length, 'bytes');
console.log('Encrypted size:', ENC.data.length, 'chars');
