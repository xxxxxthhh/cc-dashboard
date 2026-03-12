const fs = require('fs');
const path = require('path');

const portfolioPath = path.join(__dirname, 'portfolio_data.json');
if (!fs.existsSync(portfolioPath)) {
  console.error('❌ Missing portfolio_data.json');
  process.exit(1);
}

const data = JSON.parse(fs.readFileSync(portfolioPath, 'utf8'));
const errors = [];
const warnings = [];

const cc = data.ccPositions || [];
const csp = data.cspPositions || [];
const closed = data.closedTrades || [];
const allOpen = [
  ...cc.map(p => ({ ...p, type: 'CC' })),
  ...csp.map(p => ({ ...p, type: 'CSP' })),
];

const toWeekKey = (dateStr) => {
  const d = new Date(dateStr);
  const ws = new Date(d);
  ws.setDate(d.getDate() - d.getDay() + 1);
  return ws.toISOString().slice(0, 10);
};

for (const p of allOpen) {
  if (!p.ticker) errors.push(`Open position missing ticker: ${JSON.stringify(p)}`);
  if (!p.expiry) errors.push(`Open position missing expiry: ${p.ticker || 'UNKNOWN'}`);
  if (typeof p.premium !== 'number') errors.push(`Open position premium is not numeric: ${p.ticker}`);
}

for (const p of allOpen) {
  if (p.sellDate && p.expiry && new Date(p.expiry) <= new Date('2026-03-31') && (!p.premium || p.premium <= 0)) {
    errors.push(`Open near-dated position has zero/invalid premium: ${p.ticker} ${p.type} ${p.strike}`);
  }
}

for (const t of closed) {
  if (!t.ticker) errors.push(`Closed trade missing ticker: ${JSON.stringify(t)}`);
  if (!t.closeDate) errors.push(`Closed trade missing closeDate: ${t.ticker || 'UNKNOWN'}`);
  if (typeof t.premium !== 'number') errors.push(`Closed trade premium is not numeric: ${t.ticker}`);
}

const mustHavePremium = [
  ['ORCL', 'CSP', 135.0, 179],
  ['PDD', 'CC', 105.0, 42],
  ['JD', 'CC', 31.0, 41],
  ['NFLX', 'CC', 81.0, 120],
  ['PDD', 'CSP', 100.0, 115],
  ['NVDA', 'CSP', 175.0, 180],
  ['ORCL', 'CSP', 150.0, 199],
  ['GOOGL', 'CSP', 297.5, 162],
  ['AMD', 'CSP', 185.0, 254],
  ['AVGO', 'CSP', 297.5, 803],
  ['HOOD', 'CSP', 72.0, 107],
  ['COIN', 'CSP', 175.0, 348],
  ['COIN', 'CC', 167.5, 170],
  ['PDD', 'CC', 104.0, 45],
  ['LI', 'CC', 19.5, 39],
  ['PDD', 'CC', 108.0, 58],
];

for (const [ticker, type, strike, premium] of mustHavePremium) {
  const matches = closed.filter(t => t.ticker === ticker && t.type === type && Number(t.strike) === Number(strike));
  if (!matches.length) {
    warnings.push(`Reference trade missing: ${ticker} ${type} ${strike}`);
    continue;
  }
  if (!matches.some(match => match.premium === premium)) {
    errors.push(`Reference trade premium mismatch: ${ticker} ${type} ${strike} => got [${matches.map(m => m.premium).join(', ')}], expected to include ${premium}`);
  }
}

const targetWeek = '2026-03-09';
const openWeek = allOpen
  .filter(p => p.sellDate && toWeekKey(p.sellDate) === targetWeek)
  .reduce((s, p) => s + (p.premium || 0), 0);
const realizedWeek = closed
  .filter(t => t.closeDate && toWeekKey(t.closeDate) === targetWeek)
  .reduce((s, t) => s + ((t.profit < 0) ? t.profit : (t.premium || 0)), 0);
const totalWeek = openWeek + realizedWeek;

if (openWeek !== 0) errors.push(`Week 2026-03-09 ongoing premium mismatch: got ${openWeek}, expected 0`);
if (realizedWeek !== 1542) errors.push(`Week 2026-03-09 realized mismatch: got ${realizedWeek}, expected 1542`);
if (totalWeek !== 1542) errors.push(`Week 2026-03-09 total mismatch: got ${totalWeek}, expected 1542`);

const prevWeek = '2026-03-02';
const prevWeekRealized = closed
  .filter(t => t.closeDate && toWeekKey(t.closeDate) === prevWeek)
  .reduce((s, t) => s + ((t.profit < 0) ? t.profit : (t.premium || 0)), 0);
if (prevWeekRealized !== 1482) errors.push(`Week 2026-03-02 realized mismatch: got ${prevWeekRealized}, expected 1482`);

if (errors.length) {
  console.error('❌ Portfolio validation failed\n');
  for (const err of errors) console.error(`- ${err}`);
  if (warnings.length) {
    console.error('\nWarnings:');
    for (const w of warnings) console.error(`- ${w}`);
  }
  process.exit(1);
}

console.log('✅ Portfolio validation passed');
console.log(`Open premium this week: $${openWeek}`);
console.log(`Realized this week: $${realizedWeek}`);
console.log(`Total this week: $${totalWeek}`);
if (warnings.length) {
  console.log('\nWarnings:');
  for (const w of warnings) console.log(`- ${w}`);
}
