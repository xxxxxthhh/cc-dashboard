#!/usr/bin/env python3
"""
decision_engine.py — 决策层：从原始数据生成可操作的交易建议

输出 decision_data.json，供 build.js 注入 dashboard

功能：
1. 80% 止盈追踪（需要当前期权价格）
2. 下周最优 CSP 候选排名
3. 到期头寸分析 + 到期后行动建议
4. 资金效率评分
5. Wheel 循环下一步建议
"""
import json
import sqlite3
import math
from datetime import datetime, timedelta, date
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
IV_DB = SCRIPT_DIR / '..' / 'iv-scanner' / 'data' / 'iv_scanner.db'
SCREENER_JSON = SCRIPT_DIR / '..' / 'iv-scanner' / 'data' / 'screener_results.json'


def load_portfolio():
    """从 build.js 的 DATA 中读取持仓（或独立 JSON）"""
    # 先尝试独立 portfolio JSON
    pf = SCRIPT_DIR / 'portfolio_data.json'
    if pf.exists():
        with open(pf) as f:
            return json.load(f)
    return None


def get_best_csp_candidates(conn, top_n=10, max_dte=10):
    """从期权链快照中找最优 CSP 候选"""
    # 找最新采集日期
    row = conn.execute(
        "SELECT MAX(date) FROM option_chain_snapshot WHERE dte <= ?",
        (max_dte,)).fetchone()
    if not row or not row[0]:
        return []
    latest_date = row[0]

    rows = conn.execute('''
        SELECT symbol, dte, strike_price, implied_volatility,
               bid_price, ask_price, open_interest, volume, stock_price,
               delta
        FROM option_chain_snapshot
        WHERE date = ? AND dte <= ? AND option_type = 'PUT'
              AND implied_volatility IS NOT NULL
              AND strike_price < stock_price
              AND bid_price > 0
              AND open_interest >= 20
        ORDER BY date DESC
    ''', (latest_date, max_dte)).fetchall()

    candidates = []
    for r in rows:
        symbol, dte, strike, iv, bid, ask, oi, vol, price, delta = r
        if dte <= 0 or strike <= 0:
            continue
        mid = (bid + ask) / 2 if ask else bid
        otm_pct = (1 - strike / price) * 100
        ann_yield = (mid / strike) * (365 / dte) * 100
        collateral = strike * 100

        # 评分：年化收益 × 流动性权重 × OTM安全边际
        liquidity_score = min(1.0, math.log10(max(oi, 1)) / 3)
        safety_score = min(1.0, otm_pct / 10)  # 5-10% OTM 最佳
        if otm_pct < 2:
            safety_score *= 0.5  # 太贴近 ATM 扣分
        if otm_pct > 15:
            safety_score *= 0.7  # 太远 OTM 权利金低

        score = ann_yield * liquidity_score * (0.5 + safety_score * 0.5)

        ticker = symbol.replace('US.', '')
        candidates.append({
            'ticker': ticker,
            'strike': strike,
            'dte': dte,
            'price': round(price, 2),
            'otmPct': round(otm_pct, 1),
            'iv': round(iv * 100, 1),
            'bid': round(bid, 2),
            'ask': round(ask, 2),
            'mid': round(mid, 2),
            'premium': round(mid * 100),
            'collateral': round(collateral),
            'annYield': round(ann_yield, 1),
            'oi': oi,
            'volume': vol or 0,
            'delta': round(delta, 3) if delta else None,
            'score': round(score, 1),
        })

    # 去重：每个 ticker 只保留最优的一个
    best_per_ticker = {}
    for c in candidates:
        tk = c['ticker']
        # 优先选 5-10% OTM 的
        if tk not in best_per_ticker or c['score'] > best_per_ticker[tk]['score']:
            best_per_ticker[tk] = c

    result = sorted(best_per_ticker.values(), key=lambda x: -x['score'])
    return result[:top_n]


def get_iv_rankings(conn):
    """获取最新 IV 排名"""
    row = conn.execute("SELECT MAX(date) FROM daily_iv").fetchone()
    if not row or not row[0]:
        return []
    latest = row[0]

    rows = conn.execute('''
        SELECT symbol, stock_price, atm_iv, atm_dte
        FROM daily_iv WHERE date = ?
        ORDER BY atm_iv DESC
    ''', (latest,)).fetchall()

    return [{
        'ticker': r[0].replace('US.', ''),
        'price': round(r[1], 2),
        'iv': round(r[2] * 100, 1),
        'dte': r[3],
    } for r in rows]


def analyze_expiring_positions(positions, today_str):
    """分析即将到期的头寸"""
    today = datetime.strptime(today_str, '%Y-%m-%d').date()
    alerts = []

    for p in positions:
        expiry = datetime.strptime(p['expiry'], '%Y-%m-%d').date()
        dte = (expiry - today).days

        if dte > 7:
            continue

        alert = {
            'ticker': p['ticker'],
            'type': p.get('type', 'CC'),
            'strike': p['strike'],
            'expiry': p['expiry'],
            'dte': dte,
            'premium': p.get('premium', 0),
        }

        if dte <= 0:
            alert['status'] = 'expired'
            alert['action'] = '已到期，检查是否被 assign'
            alert['urgency'] = 'high'
        elif dte <= 2:
            alert['status'] = 'imminent'
            alert['action'] = '即将到期，准备下一步操作'
            alert['urgency'] = 'high'
        else:
            alert['status'] = 'approaching'
            alert['action'] = f'{dte}天后到期，关注股价走势'
            alert['urgency'] = 'medium'

        alerts.append(alert)

    return sorted(alerts, key=lambda x: x['dte'])


def calc_capital_efficiency(cc_positions, csp_positions, idle_positions, cash=25000):
    """计算资金效率"""
    cc_capital = sum(p.get('costPerShare', 0) * p.get('shares', 100) for p in cc_positions)
    cc_premium_ann = 0
    for p in cc_positions:
        sell = p.get('sellDate', '')
        exp = p.get('expiry', '')
        if sell and exp:
            try:
                d = (datetime.strptime(exp, '%Y-%m-%d') - datetime.strptime(sell, '%Y-%m-%d')).days
                if d > 0:
                    cc_premium_ann += p.get('premium', 0) * (365 / d)
            except:
                pass

    csp_capital = sum(p.get('collateral', 0) for p in csp_positions)
    csp_premium_ann = 0
    for p in csp_positions:
        sell = p.get('sellDate', '')
        exp = p.get('expiry', '')
        if sell and exp:
            try:
                d = (datetime.strptime(exp, '%Y-%m-%d') - datetime.strptime(sell, '%Y-%m-%d')).days
                if d > 0:
                    csp_premium_ann += p.get('premium', 0) * (365 / d)
            except:
                pass

    idle_capital = sum(p.get('shares', 0) * p.get('cost', 0) for p in idle_positions)

    total_deployed = cc_capital + csp_capital
    total_capital = total_deployed + idle_capital + cash
    utilization = (total_deployed / total_capital * 100) if total_capital > 0 else 0

    working_yield = (cc_premium_ann + csp_premium_ann) / total_deployed * 100 if total_deployed > 0 else 0
    total_yield = (cc_premium_ann + csp_premium_ann) / total_capital * 100 if total_capital > 0 else 0

    idle_drag = total_yield - working_yield * (total_deployed / total_capital) if total_capital > 0 else 0

    return {
        'totalCapital': round(total_capital),
        'deployedCapital': round(total_deployed),
        'idleCapital': round(idle_capital),
        'cash': cash,
        'utilization': round(utilization, 1),
        'workingYield': round(working_yield, 1),
        'totalYield': round(total_yield, 1),
        'ccAnnualPremium': round(cc_premium_ann),
        'cspAnnualPremium': round(csp_premium_ann),
        'totalAnnualPremium': round(cc_premium_ann + csp_premium_ann),
        'deadMoney': round(idle_capital),
        'deadMoneyPct': round(idle_capital / total_capital * 100, 1) if total_capital > 0 else 0,
    }


def generate_weekly_plan(expiring_alerts, csp_candidates, iv_rankings, capital_eff):
    """生成每周操作建议"""
    plan = []

    # 1. 到期头寸处理
    for a in expiring_alerts:
        if a['dte'] <= 3:
            plan.append({
                'priority': 1,
                'category': 'expiry',
                'action': f"{a['ticker']} {a['type']} ${a['strike']} {a['expiry']} — {a['action']}",
                'urgency': a['urgency'],
            })

    # 2. 释放保证金后的最优部署
    freed_capital = sum(a.get('premium', 0) for a in expiring_alerts if a['dte'] <= 3)
    if csp_candidates:
        top3 = csp_candidates[:3]
        for c in top3:
            plan.append({
                'priority': 2,
                'category': 'opportunity',
                'action': f"CSP {c['ticker']} ${c['strike']} {c['dte']}DTE — 年化 {c['annYield']}%, OTM {c['otmPct']}%, 权利金 ${c['premium']}",
                'urgency': 'medium',
            })

    # 3. 死钱提醒
    if capital_eff['deadMoneyPct'] > 10:
        plan.append({
            'priority': 3,
            'category': 'efficiency',
            'action': f"闲置资金 ${capital_eff['deadMoney']:,}（{capital_eff['deadMoneyPct']}%）— 考虑补仓或清掉",
            'urgency': 'low',
        })

    return sorted(plan, key=lambda x: x['priority'])


def main():
    # 加载持仓数据
    pf = load_portfolio()
    if not pf:
        # 从 build.js 硬编码的数据手动构造（fallback）
        print("⚠️  No portfolio_data.json found, using build.js defaults")
        pf = {
            'updatedAt': '2026-02-24',
            'cash': 25000,
            'ccPositions': [
                {"ticker":"PDD","strike":108,"expiry":"2026-02-27","premium":58,"costPerShare":107.66,"sellDate":"2026-02-14","shares":100},
                {"ticker":"JD","strike":31,"expiry":"2026-03-06","premium":42,"costPerShare":31.94,"sellDate":"2026-02-14","shares":100},
                {"ticker":"LI","strike":19.5,"expiry":"2026-02-27","premium":39,"costPerShare":23.01,"sellDate":"2026-02-14","shares":100},
                {"ticker":"CRCL","strike":65,"expiry":"2026-06-18","premium":720,"costPerShare":63.60,"sellDate":"2026-01-20","shares":100},
                {"ticker":"NFLX","strike":81,"expiry":"2026-03-06","premium":120,"costPerShare":80.15,"sellDate":"2026-02-13","shares":100},
            ],
            'cspPositions': [
                {"ticker":"CRM","strike":170,"expiry":"2026-02-27","premium":570,"collateral":17000,"sellDate":"2026-02-23"},
                {"ticker":"COIN","strike":157.5,"expiry":"2026-02-27","premium":240,"collateral":15750,"sellDate":"2026-02-23"},
                {"ticker":"ORCL","strike":135,"expiry":"2026-02-27","premium":240,"collateral":13500,"sellDate":"2026-02-23"},
                {"ticker":"NET","strike":155,"expiry":"2026-02-27","premium":334,"collateral":15500,"sellDate":"2026-02-24"},
                {"ticker":"AVGO","strike":310,"expiry":"2026-02-27","premium":320,"collateral":31000,"sellDate":"2026-02-24"},
            ],
            'idlePositions': [
                {"ticker":"NEOV","shares":100,"cost":4.41,"canCC":True},
                {"ticker":"COPX","shares":60,"cost":84.24,"canCC":False},
                {"ticker":"CRM","shares":20,"cost":184.65,"canCC":False},
                {"ticker":"AMD","shares":20,"cost":214.35,"canCC":False},
                {"ticker":"PYPL","shares":20,"cost":42.95,"canCC":False},
                {"ticker":"AMZN","shares":10,"cost":205.37,"canCC":False},
            ],
        }

    today = pf.get('updatedAt', datetime.now().strftime('%Y-%m-%d'))

    # 连接 IV 数据库
    conn = None
    csp_candidates = []
    iv_rankings = []
    if IV_DB.exists():
        conn = sqlite3.connect(str(IV_DB))
        csp_candidates = get_best_csp_candidates(conn, top_n=10, max_dte=10)
        iv_rankings = get_iv_rankings(conn)

    # 分析到期头寸
    all_positions = []
    for p in pf.get('ccPositions', []):
        all_positions.append({**p, 'type': 'CC'})
    for p in pf.get('cspPositions', []):
        all_positions.append({**p, 'type': 'CSP'})
    expiring = analyze_expiring_positions(all_positions, today)

    # 资金效率
    capital_eff = calc_capital_efficiency(
        pf.get('ccPositions', []),
        pf.get('cspPositions', []),
        pf.get('idlePositions', []),
        pf.get('cash', 25000))

    # 每周操作建议
    weekly_plan = generate_weekly_plan(expiring, csp_candidates, iv_rankings, capital_eff)

    # 输出
    decision = {
        'generatedAt': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'portfolioDate': today,
        'expiringAlerts': expiring,
        'cspCandidates': csp_candidates,
        'ivRankings': iv_rankings,
        'capitalEfficiency': capital_eff,
        'weeklyPlan': weekly_plan,
    }

    out_path = SCRIPT_DIR / 'decision_data.json'
    with open(out_path, 'w') as f:
        json.dump(decision, f, indent=2, ensure_ascii=False)

    print(f"✅ Decision data generated: {out_path}")
    print(f"   到期提醒: {len(expiring)} 个")
    print(f"   CSP 候选: {len(csp_candidates)} 个")
    print(f"   资金利用率: {capital_eff['utilization']}%")
    print(f"   操作建议: {len(weekly_plan)} 条")

    if conn:
        conn.close()

    return decision


if __name__ == '__main__':
    main()
