#!/usr/bin/env python3
"""
decision_engine.py — 决策层：从原始数据生成可操作的交易建议

输出 decision_data.json，供 build.js 注入 dashboard

功能：
1. 80% 止盈追踪
2. 下周最优 CSP 候选排名（含 delta、OTM%、流动性评分）
3. 到期头寸分析 + 到期后行动建议
4. 资金效率评分 + 死钱警告
5. Wheel 循环下一步建议
6. 每周操作计划
"""
import json
import sqlite3
import math
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
IV_DB = SCRIPT_DIR / '..' / 'iv-scanner' / 'data' / 'iv_scanner.db'
SCREENER_JSON = SCRIPT_DIR / '..' / 'iv-scanner' / 'data' / 'screener_results.json'


def load_portfolio():
    """从 portfolio_data.json 读取持仓"""
    pf = SCRIPT_DIR / 'portfolio_data.json'
    if pf.exists():
        with open(pf) as f:
            return json.load(f)
    return None


def get_best_csp_candidates(conn, top_n=10, max_dte=10):
    """从期权链快照中找最优 CSP 候选"""
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

        # 评分逻辑
        # 1. 年化收益基础分
        yield_score = min(ann_yield, 300)  # cap at 300% 避免极端值主导

        # 2. 流动性（OI + volume）
        liquidity_score = min(1.0, math.log10(max(oi, 1)) / 3)
        if vol and vol > 0:
            liquidity_score = min(1.0, liquidity_score + 0.2)

        # 3. OTM 安全边际（5-10% 最佳）
        if otm_pct < 2:
            safety_score = 0.3
        elif otm_pct < 5:
            safety_score = 0.7
        elif otm_pct <= 10:
            safety_score = 1.0
        elif otm_pct <= 15:
            safety_score = 0.7
        else:
            safety_score = 0.4

        # 4. Delta 偏好（-0.20 到 -0.35 最佳）
        delta_score = 0.5
        if delta is not None:
            abs_d = abs(delta)
            if 0.20 <= abs_d <= 0.35:
                delta_score = 1.0
            elif 0.15 <= abs_d <= 0.40:
                delta_score = 0.7
            elif abs_d > 0.45:
                delta_score = 0.3

        score = yield_score * liquidity_score * safety_score * delta_score / 10

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

    # 每个 ticker 保留最优的
    best_per_ticker = {}
    for c in candidates:
        tk = c['ticker']
        if tk not in best_per_ticker or c['score'] > best_per_ticker[tk]['score']:
            best_per_ticker[tk] = c

    result = sorted(best_per_ticker.values(), key=lambda x: -x['score'])
    return result[:top_n]


def get_best_cc_candidates(conn, holdings, max_dte=10):
    """为当前持仓找最优 CC 候选"""
    row = conn.execute(
        "SELECT MAX(date) FROM option_chain_snapshot WHERE dte <= ?",
        (max_dte,)).fetchone()
    if not row or not row[0]:
        return []
    latest_date = row[0]

    candidates = []
    for h_ticker in holdings:
        symbol = f'US.{h_ticker}'
        rows = conn.execute('''
            SELECT dte, strike_price, implied_volatility,
                   bid_price, ask_price, open_interest, volume, stock_price, delta
            FROM option_chain_snapshot
            WHERE date = ? AND symbol = ? AND dte <= ? AND option_type = 'CALL'
                  AND implied_volatility IS NOT NULL
                  AND strike_price > stock_price
                  AND bid_price > 0
            ORDER BY (bid_price / strike_price) DESC
        ''', (latest_date, symbol, max_dte)).fetchall()

        best = None
        for r in rows:
            dte, strike, iv, bid, ask, oi, vol, price, delta = r
            if dte <= 0:
                continue
            mid = (bid + ask) / 2 if ask else bid
            otm_pct = (strike / price - 1) * 100
            ann_yield = (mid / price) * (365 / dte) * 100

            # CC 偏好：slightly OTM (2-8%)，delta 0.20-0.35
            if 2 <= otm_pct <= 8 and oi >= 10:
                if best is None or ann_yield > best['annYield']:
                    best = {
                        'ticker': h_ticker,
                        'strike': strike,
                        'dte': dte,
                        'price': round(price, 2),
                        'otmPct': round(otm_pct, 1),
                        'iv': round(iv * 100, 1),
                        'bid': round(bid, 2),
                        'ask': round(ask, 2),
                        'premium': round(mid * 100),
                        'annYield': round(ann_yield, 1),
                        'delta': round(delta, 3) if delta else None,
                        'oi': oi,
                    }
        if best:
            candidates.append(best)

    return sorted(candidates, key=lambda x: -x['annYield'])


def get_iv_rankings(conn):
    """获取最新 IV 排名"""
    row = conn.execute("SELECT MAX(date) FROM daily_iv").fetchone()
    if not row or not row[0]:
        return []
    latest = row[0]

    # 也拉前一天的数据算 IV 变化
    prev_row = conn.execute(
        "SELECT MAX(date) FROM daily_iv WHERE date < ?", (latest,)).fetchone()
    prev_date = prev_row[0] if prev_row else None

    rows = conn.execute('''
        SELECT symbol, stock_price, atm_iv, atm_dte
        FROM daily_iv WHERE date = ?
        ORDER BY atm_iv DESC
    ''', (latest,)).fetchall()

    prev_ivs = {}
    if prev_date:
        prev_rows = conn.execute(
            'SELECT symbol, atm_iv FROM daily_iv WHERE date = ?',
            (prev_date,)).fetchall()
        prev_ivs = {r[0]: r[1] for r in prev_rows}

    result = []
    for r in rows:
        sym = r[0]
        iv = r[2]
        prev_iv = prev_ivs.get(sym)
        iv_change = round((iv - prev_iv) * 100, 1) if prev_iv else None
        result.append({
            'ticker': sym.replace('US.', ''),
            'price': round(r[1], 2),
            'iv': round(iv * 100, 1),
            'dte': r[3],
            'ivChange': iv_change,
        })
    return result


def check_profit_targets(conn, positions, today_str):
    """检查持仓是否达到 80% 止盈线
    
    用期权链快照中的 bid/ask 估算当前期权价值
    """
    alerts = []
    row = conn.execute("SELECT MAX(date) FROM option_chain_snapshot").fetchone()
    if not row or not row[0]:
        return alerts
    latest_date = row[0]

    for p in positions:
        ticker = p['ticker']
        symbol = f'US.{ticker}'
        strike = p['strike']
        expiry = p['expiry']
        entry_premium = p.get('premium', 0)
        pos_type = p.get('type', 'CC')

        if entry_premium <= 0:
            continue

        # 找匹配的期权合约当前价格
        opt_type = 'CALL' if pos_type == 'CC' else 'PUT'
        row = conn.execute('''
            SELECT bid_price, ask_price, implied_volatility, delta, stock_price
            FROM option_chain_snapshot
            WHERE symbol = ? AND date = ? AND option_type = ?
                  AND ABS(strike_price - ?) < 0.5
            ORDER BY ABS(dte - ?) LIMIT 1
        ''', (symbol, latest_date, opt_type, strike,
              max(1, (datetime.strptime(expiry, '%Y-%m-%d') -
                       datetime.strptime(today_str, '%Y-%m-%d')).days)
              )).fetchone()

        if not row:
            continue

        bid, ask = row[0] or 0, row[1] or 0
        current_mid = (bid + ask) / 2 if ask else bid
        if current_mid <= 0:
            continue

        # 权利金是总额（如 $570），期权价格是每股（如 $5.70）
        entry_per_share = entry_premium / 100
        profit_pct = (entry_per_share - current_mid) / entry_per_share * 100

        alert = {
            'ticker': ticker,
            'type': pos_type,
            'strike': strike,
            'expiry': expiry,
            'entryPremium': entry_premium,
            'currentValue': round(current_mid * 100),
            'profitPct': round(profit_pct, 1),
            'currentPrice': round(row[4], 2) if row[4] else None,
        }

        if profit_pct >= 80:
            alert['signal'] = 'take_profit'
            alert['message'] = f'🎯 达到 {profit_pct:.0f}% 止盈线！考虑平仓翻台'
        elif profit_pct >= 60:
            alert['signal'] = 'approaching'
            alert['message'] = f'接近止盈（{profit_pct:.0f}%），继续持有'
        elif profit_pct < 0:
            alert['signal'] = 'underwater'
            loss_multiple = abs(profit_pct) / 100
            if loss_multiple >= 1.5:
                alert['message'] = f'⚠️ 亏损 {abs(profit_pct):.0f}%（{loss_multiple:.1f}x），评估止损'
            else:
                alert['message'] = f'浮亏 {abs(profit_pct):.0f}%，继续观察'
        else:
            alert['signal'] = 'holding'
            alert['message'] = f'盈利 {profit_pct:.0f}%，继续持有'

        alerts.append(alert)

    return sorted(alerts, key=lambda x: -x['profitPct'])


def analyze_expiring_positions(positions, today_str):
    """分析即将到期的头寸 + 到期后行动建议"""
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
            alert['action'] = '已到期 — 检查 assign 结果'
            alert['urgency'] = 'high'
            if p.get('type') == 'CSP':
                alert['nextStep'] = f'如被 assign → 立刻 Sell CC；如 OTM 到期 → 继续 Sell Put'
            else:
                alert['nextStep'] = f'如被 assign → Sell Put 接回（或清退）；如 OTM 到期 → 继续 Sell CC'
        elif dte <= 2:
            alert['status'] = 'imminent'
            alert['action'] = f'{dte}天后到期 — 准备下一步'
            alert['urgency'] = 'high'
            alert['nextStep'] = '盘中关注股价 vs strike，准备到期后操作'
        else:
            alert['status'] = 'approaching'
            alert['action'] = f'{dte}天后到期'
            alert['urgency'] = 'medium'
            alert['nextStep'] = '继续持有，关注 80% 止盈机会'

        alerts.append(alert)

    return sorted(alerts, key=lambda x: x['dte'])


def calc_capital_efficiency(cc_positions, csp_positions, idle_positions, cash=25000):
    """计算资金效率"""
    cc_capital = sum(p.get('costPerShare', 0) * p.get('shares', 100) for p in cc_positions)
    cc_premium_ann = 0
    for p in cc_positions:
        sell, exp = p.get('sellDate', ''), p.get('expiry', '')
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
        sell, exp = p.get('sellDate', ''), p.get('expiry', '')
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

    # 死钱明细
    dead_money_items = []
    for p in idle_positions:
        if not p.get('canCC', False) and p.get('shares', 0) < 100:
            dead_money_items.append({
                'ticker': p['ticker'],
                'shares': p['shares'],
                'value': round(p['shares'] * p.get('cost', 0)),
                'reason': f"不足100股（{p['shares']}股），开不了CC",
            })

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
        'deadMoneyItems': dead_money_items,
    }


def generate_weekly_plan(expiring, csp_candidates, cc_candidates, profit_alerts, capital_eff):
    """生成每周操作建议，按优先级排序"""
    plan = []

    # P0: 80% 止盈触发
    for a in profit_alerts:
        if a['signal'] == 'take_profit':
            plan.append({
                'priority': 0,
                'category': 'profit',
                'action': f"🎯 {a['ticker']} {a['type']} ${a['strike']} 盈利 {a['profitPct']:.0f}% — 平仓翻台！",
                'urgency': 'high',
            })

    # P0: 严重亏损警告
    for a in profit_alerts:
        if a['signal'] == 'underwater' and a['profitPct'] < -150:
            plan.append({
                'priority': 0,
                'category': 'risk',
                'action': f"⚠️ {a['ticker']} {a['type']} ${a['strike']} 亏损 {abs(a['profitPct']):.0f}% — 评估止损",
                'urgency': 'high',
            })

    # P1: 到期头寸处理
    for a in expiring:
        if a['dte'] <= 3:
            plan.append({
                'priority': 1,
                'category': 'expiry',
                'action': f"⏰ {a['ticker']} {a['type']} ${a['strike']} {a['expiry']} — {a['action']}",
                'detail': a.get('nextStep', ''),
                'urgency': a['urgency'],
            })

    # P2: 最优 CSP 开仓机会
    if csp_candidates:
        for c in csp_candidates[:3]:
            plan.append({
                'priority': 2,
                'category': 'opportunity',
                'action': f"💰 CSP {c['ticker']} ${c['strike']} {c['dte']}DTE — 年化 {c['annYield']}%, 权利金 ${c['premium']}",
                'urgency': 'medium',
            })

    # P2: CC 开仓机会（持仓没覆盖的）
    for c in cc_candidates:
        plan.append({
            'priority': 2,
            'category': 'opportunity',
            'action': f"📈 CC {c['ticker']} ${c['strike']} {c['dte']}DTE — 年化 {c['annYield']}%, 权利金 ${c['premium']}",
            'urgency': 'medium',
        })

    # P3: 死钱提醒
    for item in capital_eff.get('deadMoneyItems', []):
        plan.append({
            'priority': 3,
            'category': 'efficiency',
            'action': f"💤 {item['ticker']} {item['shares']}股 (${item['value']}) — {item['reason']}",
            'urgency': 'low',
        })

    return sorted(plan, key=lambda x: x['priority'])


def cleanup_db(conn):
    """清理旧数据，控制数据库大小"""
    # 保留 90 天 daily_iv
    conn.execute("DELETE FROM daily_iv WHERE date < date('now', '-90 days')")
    # 保留 30 天 option_chain_snapshot（最大的表）
    conn.execute("DELETE FROM option_chain_snapshot WHERE date < date('now', '-30 days')")
    conn.commit()

    # 检查是否需要 VACUUM（每月一次就够）
    row = conn.execute("SELECT COUNT(*) FROM option_chain_snapshot").fetchone()
    if row and row[0] < 5000:
        conn.execute("VACUUM")

    return True


def main():
    pf = load_portfolio()
    if not pf:
        print("⚠️  No portfolio_data.json, run sync_portfolio.py first")
        print("   Falling back to build.js extraction...")
        import subprocess
        subprocess.run(['python3', str(SCRIPT_DIR / 'sync_portfolio.py')], check=True)
        pf = load_portfolio()
        if not pf:
            print("❌ Cannot load portfolio data")
            return

    today = pf.get('updatedAt', datetime.now().strftime('%Y-%m-%d'))

    # 连接 IV 数据库
    conn = None
    csp_candidates = []
    cc_candidates = []
    iv_rankings = []
    profit_alerts = []

    if IV_DB.exists():
        conn = sqlite3.connect(str(IV_DB))
        csp_candidates = get_best_csp_candidates(conn, top_n=10, max_dte=10)
        iv_rankings = get_iv_rankings(conn)

        # CC 候选：找持仓中没有 CC 覆盖的标的
        cc_tickers_covered = {p['ticker'] for p in pf.get('ccPositions', [])}
        # 持仓中满 100 股但没 CC 的
        idle_can_cc = [p['ticker'] for p in pf.get('idlePositions', [])
                       if p.get('canCC') and p['ticker'] not in cc_tickers_covered]
        if idle_can_cc:
            cc_candidates = get_best_cc_candidates(conn, idle_can_cc, max_dte=10)

        # 80% 止盈追踪
        all_active = []
        for p in pf.get('ccPositions', []):
            all_active.append({**p, 'type': 'CC'})
        for p in pf.get('cspPositions', []):
            all_active.append({**p, 'type': 'CSP'})
        profit_alerts = check_profit_targets(conn, all_active, today)

        # 清理旧数据
        cleanup_db(conn)

    # 到期分析
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
    weekly_plan = generate_weekly_plan(
        expiring, csp_candidates, cc_candidates, profit_alerts, capital_eff)

    # 输出
    decision = {
        'generatedAt': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'portfolioDate': today,
        'expiringAlerts': expiring,
        'profitAlerts': profit_alerts,
        'cspCandidates': csp_candidates,
        'ccCandidates': cc_candidates,
        'ivRankings': iv_rankings,
        'capitalEfficiency': capital_eff,
        'weeklyPlan': weekly_plan,
    }

    out_path = SCRIPT_DIR / 'decision_data.json'
    with open(out_path, 'w') as f:
        json.dump(decision, f, indent=2, ensure_ascii=False)

    print(f"✅ Decision data generated: {out_path}")
    print(f"   到期提醒: {len(expiring)} 个")
    print(f"   止盈追踪: {len(profit_alerts)} 个" +
          (f" (🎯 {sum(1 for a in profit_alerts if a['signal']=='take_profit')} 达标)" if profit_alerts else ""))
    print(f"   CSP 候选: {len(csp_candidates)} 个")
    print(f"   CC 候选: {len(cc_candidates)} 个")
    print(f"   资金利用率: {capital_eff['utilization']}%")
    print(f"   操作建议: {len(weekly_plan)} 条")

    if conn:
        conn.close()

    return decision


if __name__ == '__main__':
    main()
