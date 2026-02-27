const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const PASSWORD = '1029';

// Load decision data if available
let DECISION = null;
const decisionPath = path.join(__dirname, 'decision_data.json');
if (fs.existsSync(decisionPath)) {
  DECISION = JSON.parse(fs.readFileSync(decisionPath, 'utf8'));
  console.log('📊 Decision data loaded:', decisionPath);
}

const DATA = {
  updatedAt: "2026-02-28",
  ccPositions: [
    { ticker: "JD", strike: 31, expiry: "2026-03-06", premium: 42, costPerShare: 31.94, sellDate: "2026-02-14", shares: 100 },
    { ticker: "CRCL", strike: 65, expiry: "2026-06-18", premium: 720, costPerShare: 63.60, sellDate: "2026-01-20", shares: 100 },
    { ticker: "NFLX", strike: 81, expiry: "2026-03-06", premium: 120, costPerShare: 80.15, sellDate: "2026-02-13", shares: 100 }
  ],
  cspPositions: [
    { ticker: "COIN", strike: 175, expiry: "2026-03-06", premium: 400, collateral: 17500, sellDate: "2026-02-26" }
  ],
  closedTrades: [
    { ticker: "AVGO", type: "CSP", strike: 310, openDate: "2026-02-24", closeDate: "2026-02-27", premium: 320, assigned: true, note: "被Assign，接100股@$310，权利金$320抵扣" },
    { ticker: "COIN", type: "CSP", strike: 167.5, openDate: "2026-02-25", closeDate: "2026-02-27", premium: 120, assigned: true, note: "被Assign，接100股@$167.5，权利金$120抵扣" },
    { ticker: "LI", type: "CC", strike: 19.5, openDate: "2026-02-14", closeDate: "2026-02-27", premium: 39, assigned: false, note: "到期归零，权利金$39落袋" },
    { ticker: "PDD", type: "CC", strike: 108, openDate: "2026-02-14", closeDate: "2026-02-27", premium: 58, assigned: false, note: "到期归零，权利金$58落袋" },
    { ticker: "ORCL", type: "CSP", strike: 135, openDate: "2026-02-23", closeDate: "2026-02-26", premium: 218, assigned: false, note: "平仓@$0.20，获利$218，91.7%止盈" },
    { ticker: "NET", type: "CSP", strike: 155, openDate: "2026-02-24", closeDate: "2026-02-26", premium: 307, assigned: false, note: "平仓@$0.25，获利$307，92%止盈" },
    { ticker: "CRM", type: "CSP", strike: 185, openDate: "2026-02-25", closeDate: "2026-02-26", premium: 505, assigned: false, note: "平仓@$0.58，获利$505，89.5%止盈" },
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
    { ticker: "COIN", phase: "assigned", detail: "CSP $167.5 被Assign，接100股@$167.5", note: "持有200股，现$174.92，CSP $175 3/6 在持" },
    { ticker: "AVGO", phase: "assigned", detail: "CSP $310 被Assign，接100股@$310", note: "新买入100股，现$319.20，考虑开CC" },
    { ticker: "CRM", phase: "idle", detail: "IV crush 后观察", note: "IV 85%→42%，等回升再操作" },
    { ticker: "ORCL", phase: "idle", detail: "CSP $135 已平仓", note: "获利$218，等下周开新CSP" },
    { ticker: "NET", phase: "idle", detail: "CSP $155 已平仓", note: "获利$307，等下周开新仓" },
    { ticker: "JD", phase: "cc-exit", detail: "CC $31 3/6", note: "清退中，让assign" },
    { ticker: "NFLX", phase: "cc", detail: "CC $81 3/6", note: "保股票为主" },
    { ticker: "CRCL", phase: "cc-locked", detail: "CC $65 6/18", note: "远期锁定" }
  ],
  optChanges: [
    { action: "已完成", cls: "done", detail: "AVGO CSP $310 被Assign，接100股@$310" },
    { action: "已完成", cls: "done", detail: "COIN CSP $167.5 被Assign，接100股@$167.5" },
    { action: "已完成", cls: "done", detail: "LI CC $19.5 到期归零，权利金$39落袋" },
    { action: "已完成", cls: "done", detail: "PDD CC $108 到期归零，权利金$58落袋" },
    { action: "已完成", cls: "done", detail: "ORCL CSP $135 平仓@$0.20，获利$218（91.7%止盈）" },
    { action: "已完成", cls: "done", detail: "COIN CSP $175 3/6 新开@$4.00，权利金$400" },
    { action: "已完成", cls: "done", detail: "NET CSP $155 平仓@$0.25，获利$307（92%止盈）" },
    { action: "已完成", cls: "done", detail: "CRM CSP $185 平仓@$0.58，获利$505（89.5%止盈）" },
    { action: "已完成", cls: "done", detail: "CRM CSP $170 平仓获利$418，滚仓至$185" },
    { action: "已完成", cls: "done", detail: "COIN CSP $157.5 平仓获利$201，滚仓至$167.5" },
    { action: "已完成", cls: "done", detail: "COIN 100股被CC $167.5 assign，回笼$16,920" },
    { action: "已完成", cls: "done", detail: "PDD 100股被CC $104 assign，回笼$10,445" },
    { action: "已完成", cls: "done", detail: "NIO 100股被CC $5 assign，清退完成" },
    { action: "进行中", cls: "active", detail: "COIN CSP $167.5 2/27 接回中（滚仓）" },
    { action: "进行中", cls: "active", detail: "CRM IV crush 后降级观察，等 IV 回升" },
    { action: "进行中", cls: "active", detail: "ORCL 等下周开新 CSP" },
    { action: "进行中", cls: "active", detail: "NET 等下周开新 CSP" },
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

// Inject decision data
if (DECISION) {
  DATA.decision = DECISION;
}

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
