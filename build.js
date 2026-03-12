const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const PASSWORD = '1029';

// Load sensitive portfolio data from local json files (ignored by git)
function loadJsonOrThrow(p, hint) {
  if (!fs.existsSync(p)) {
    console.error(`\n❌ Missing required file: ${p}`);
    if (hint) console.error(hint);
    process.exit(1);
  }
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

const portfolioPath = path.join(__dirname, 'portfolio_data.json');
const DATA = loadJsonOrThrow(
  portfolioPath,
  `\nCreate it locally (do NOT commit). You can generate/sync it via sync_portfolio.py or your pipeline.`
);

try {
  require('./validate_portfolio');
} catch (err) {
  console.error('\n❌ Validation failed before build');
  throw err;
}

function enrichWithLiveQuotes(data) {
  const tickers = Array.from(new Set([
    ...(data.ccPositions || []).map(p => p.ticker),
    ...(data.cspPositions || []).map(p => p.ticker),
  ].filter(Boolean)));

  if (!tickers.length) return;

  try {
    const quoteScript = path.join(__dirname, '..', 'scripts', 'quote.py');
    const raw = execFileSync('python3', [quoteScript, '--json', ...tickers], {
      cwd: __dirname,
      encoding: 'utf8',
      timeout: 20000,
    });
    const quotes = JSON.parse(raw);
    const byTicker = Object.fromEntries(quotes.filter(q => !q.error).map(q => [q.ticker, q]));

    const applyQuote = (p) => {
      const q = byTicker[p.ticker];
      if (!q) return p;
      return {
        ...p,
        currentPrice: q.price,
        prevClose: q.prev_close,
      };
    };

    data.ccPositions = (data.ccPositions || []).map(applyQuote);
    data.cspPositions = (data.cspPositions || []).map(applyQuote);
    data.quoteUpdatedAt = new Date().toISOString();
    console.log('💹 Live quotes loaded for:', Object.keys(byTicker).join(', '));
  } catch (err) {
    console.warn('⚠️ Failed to load live quotes:', err.message);
  }
}

enrichWithLiveQuotes(DATA);

// Optional decision data (alerts/candidates), also sensitive
const decisionPath = path.join(__dirname, 'decision_data.json');
if (fs.existsSync(decisionPath)) {
  DATA.decision = JSON.parse(fs.readFileSync(decisionPath, 'utf8'));
  console.log('📊 Decision data loaded:', decisionPath);
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
