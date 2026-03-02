#!/usr/bin/env python3
"""sync_portfolio.py — 将 memory/portfolio.md 作为 source of truth，同步生成 cc-dashboard/portfolio_data.json

说明：
- portfolio_data.json / decision_data.json 均在 .gitignore（敏感数据不提交）
- build.js 会读取 portfolio_data.json 并加密注入 index.html

portfolio.md 里信息不全（如 sellDate / cost basis 等），这里生成的 JSON 以“够用、不断”为目标：
- CC/CSP 至少提供 ticker/strike/expiry，供 cc_monitor.py/前端展示
- CSP 尽量带 premium/collateral
- 股票持仓写入 idlePositions（用于前端展示 + 死钱提醒）
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
WORKSPACE = Path.home() / ".openclaw" / "workspace"
MEMORY_DIR = WORKSPACE / "memory"
PORTFOLIO_MD = MEMORY_DIR / "portfolio.md"
OUTPUT = SCRIPT_DIR / "portfolio_data.json"


def _parse_money_to_int(s: str) -> int | None:
    """Parse $ amounts without sign, return integer dollars."""
    if not s:
        return None
    s = s.strip().lower().replace(",", "")
    # ~ $25k / $28k
    m = re.search(r"\$\s*([\d.]+)\s*k", s)
    if m:
        return int(float(m.group(1)) * 1000)
    # $25000
    m = re.search(r"\$\s*([\d.]+)", s)
    if m:
        return int(float(m.group(1)))
    return None


def _parse_signed_money_to_int(s: str) -> int | None:
    """Parse signed money like '+$291' or '-$1,100' into integer dollars."""
    if not s:
        return None
    raw = s.strip().replace(",", "")
    sign = -1 if "-" in raw else 1
    v = _parse_money_to_int(raw)
    if v is None:
        return None
    return sign * v


def _parse_price(s: str) -> float | None:
    if not s:
        return None
    s = s.strip().replace(",", "")
    s = s.replace("$", "")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_int(s: str) -> int | None:
    if not s:
        return None
    s = s.strip().replace(",", "")
    try:
        return int(float(s))
    except ValueError:
        return None


def _parse_expiry(md: str, default_year: int) -> str | None:
    """Accepts '3/6' or '2026-03-06'"""
    if not md:
        return None
    md = md.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", md):
        return md
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})", md)
    if not m:
        return None
    month = int(m.group(1))
    day = int(m.group(2))
    try:
        return datetime(default_year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _extract_updated_at(text: str) -> str:
    # 更新时间：2026-02-28（周五收盘）
    m = re.search(r"更新时间：\s*(\d{4}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)
    return datetime.now().strftime("%Y-%m-%d")


def _extract_cash(text: str) -> int:
    # 现金：~$25k（...）
    m = re.search(r"现金：([^\n]+)", text)
    if m:
        v = _parse_money_to_int(m.group(1))
        if v is not None:
            return v
    return 25000


def _extract_table(text: str, heading: str) -> list[list[str]]:
    """Return rows (list of columns) for the markdown table under a '## {heading}' section."""
    pat = rf"^##\s+{re.escape(heading)}\s*$"
    m = re.search(pat, text, flags=re.MULTILINE)
    if not m:
        return []
    start = m.end()

    # table starts at first line beginning with |
    lines = text[start:].splitlines()
    table_lines: list[str] = []
    in_table = False
    for line in lines:
        if line.strip().startswith("## "):
            break
        if line.strip().startswith("|"):
            in_table = True
            table_lines.append(line)
        else:
            if in_table:
                break

    if len(table_lines) < 3:
        return []

    # Skip header + separator
    body = table_lines[2:]
    rows: list[list[str]] = []
    for line in body:
        parts = [p.strip() for p in line.strip().strip("|").split("|")]
        if all(not p for p in parts):
            continue
        rows.append(parts)
    return rows


def _parse_mmdd_in_text(s: str) -> tuple[int, int] | None:
    """Extract M/D from a string like '✅ 3/2 开仓'"""
    if not s:
        return None
    m = re.search(r"\b(\d{1,2})/(\d{1,2})\b", s)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _parse_premium_from_note(note: str) -> int:
    """Best-effort parse realized premium/profit from Chinese notes."""
    if not note:
        return 0
    note = note.replace(",", "")
    m = re.search(r"获利\s*\$\s*([\d.]+)", note)
    if m:
        return int(float(m.group(1)))
    m = re.search(r"\$\s*([\d.]+)\s*全收", note)
    if m:
        return int(float(m.group(1)))
    m = re.search(r"权利金\s*\$\s*([\d.]+)", note)
    if m:
        return int(float(m.group(1)))
    return 0


def _iter_memory_md_lines():
    """Yield (path, line) from memory/*.md excluding portfolio.md."""
    for p in sorted(MEMORY_DIR.glob("*.md")):
        if p.name == "portfolio.md":
            continue
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                yield p, line
        except Exception:
            continue


def find_cc_entry_credit_from_logs(ticker: str, strike: float, contracts: int) -> int | None:
    """Try to find the *actual* entry credit for a CC from old journal logs.

    We only return a value when we find an explicit open trade record (e.g. '@ $1.20，收 $120').
    No mark-to-market back-solving here.
    """
    strike_s = str(strike).rstrip("0").rstrip(".")
    tk = ticker.upper().strip()

    # Common patterns seen in our logs
    # Example: 卖出 NFLX Mar 6 $81 Call @ $1.20，收 $120
    pat = re.compile(
        rf"卖出\s+{re.escape(tk)}.*?\$?{re.escape(strike_s)}\s*Call.*?@\s*\$?([\d.]+)(?:.*?收\s*\$\s*([\d.]+))?",
        re.IGNORECASE,
    )

    for _p, line in _iter_memory_md_lines():
        if tk not in line:
            continue
        if "call" not in line.lower():
            continue
        if strike_s not in line:
            continue

        m = pat.search(line)
        if not m:
            continue

        price = float(m.group(1)) if m.group(1) else None
        cash = float(m.group(2)) if m.group(2) else None

        if cash is not None and cash > 0:
            return int(round(cash))
        if price is not None and price > 0:
            return int(round(abs(contracts) * price * 100))

    return None


def main():
    if not PORTFOLIO_MD.exists():
        raise SystemExit(f"❌ Missing {PORTFOLIO_MD}")

    text = PORTFOLIO_MD.read_text(encoding="utf-8")
    updated_at = _extract_updated_at(text)
    year = int(updated_at.split("-")[0])
    cash = _extract_cash(text)

    # 股票持仓
    stocks = _extract_table(text, "股票持仓")
    stock_holdings = []
    for r in stocks:
        # | 标的 | 股数 | 现价 | 日涨跌 | P&L | 备注 |
        if len(r) < 3:
            continue
        ticker = r[0]
        shares = _parse_int(r[1]) or 0
        price = _parse_price(r[2])
        note = r[5] if len(r) >= 6 else ""
        stock_holdings.append({
            "ticker": ticker,
            "shares": shares,
            "cost": price or 0,  # 缺 cost basis，用现价占位
            "canCC": shares >= 100,
            "note": note,
        })

    # CC 持仓
    cc_rows = _extract_table(text, "CC 持仓")
    cc_positions = []
    for r in cc_rows:
        # | 标的 | Strike | 到期日 | 张数 | 现价 | P&L | 状态 |
        if len(r) < 4:
            continue
        ticker = r[0]
        strike = _parse_price(r[1])
        expiry = _parse_expiry(r[2], year)
        contracts = _parse_int(r[3])
        if not ticker or strike is None or not expiry or not contracts:
            continue

        # sellDate 可能在“状态”里带着（如果没有就留空，前端会 fallback）
        status = r[6] if len(r) >= 7 else ""
        sd = _parse_mmdd_in_text(status)
        sell_date = datetime(year, sd[0], sd[1]).strftime("%Y-%m-%d") if sd else None

        # 从旧日志中找“真实开仓权利金”（如果找不到就留 0，不瞎推）
        entry_credit = find_cc_entry_credit_from_logs(ticker, strike, contracts) or 0

        cc_positions.append({
            "ticker": ticker,
            "strike": strike,
            "expiry": expiry,
            "contracts": contracts,
            "sellDate": sell_date,
            "premium": entry_credit,
        })

    # CSP 持仓
    csp_rows = _extract_table(text, "CSP 持仓")
    csp_positions = []
    for r in csp_rows:
        # | 标的 | Strike | 到期日 | 张数 | 开仓价 | 权利金 | 状态 |
        if len(r) < 6:
            continue
        ticker = r[0]
        strike = _parse_price(r[1])
        expiry = _parse_expiry(r[2], year)
        contracts = _parse_int(r[3])
        entry = _parse_price(r[4])
        premium = _parse_money_to_int(r[5])
        status = r[6] if len(r) >= 7 else ""
        if not ticker or strike is None or not expiry or not contracts:
            continue

        sd = _parse_mmdd_in_text(status)
        sell_date = datetime(year, sd[0], sd[1]).strftime("%Y-%m-%d") if sd else None

        csp_positions.append({
            "ticker": ticker,
            "strike": strike,
            "expiry": expiry,
            "contracts": contracts,
            "sellDate": sell_date,
            "entryPrice": entry,
            "premium": premium or 0,
            "collateral": int(abs(contracts) * strike * 100),
        })

    # 已清仓记录 -> closedTrades（用于 dashboard 已实现收益）
    closed_rows = _extract_table(text, "已清仓记录")
    closed_trades = []
    for r in closed_rows:
        # | 标的 | 操作 | 日期 | 备注 |
        if len(r) < 3:
            continue
        ticker = r[0]
        action = r[1] if len(r) >= 2 else ""
        dt = r[2] if len(r) >= 3 else ""
        note = r[3] if len(r) >= 4 else ""

        # type + strike
        typ = "CSP" if "CSP" in action else "CC" if "CC" in action else ""
        m = re.search(r"\$\s*([\d.]+)", action)
        strike = float(m.group(1)) if m else None
        close_date = _parse_expiry(dt, year) or updated_at

        assigned = "assign" in action.lower() or "被call" in note or "assign" in note.lower()
        premium = _parse_premium_from_note(note)

        if not ticker or not typ:
            continue
        closed_trades.append({
            "ticker": ticker,
            "type": typ,
            "strike": strike or 0,
            "openDate": close_date,  # unknown; keep UI stable
            "closeDate": close_date,
            "premium": premium,
            "assigned": bool(assigned),
        })

    # wheelCycles: 用当前持仓做一个轻量的状态卡（不追求精确，只求可读）
    wheel_cycles = []
    for p in csp_positions:
        wheel_cycles.append({
            "ticker": p["ticker"],
            "phase": "csp",
            "detail": f"PUT ${p['strike']} · 到期 {p['expiry']}",
            "note": "卖 PUT 收租，接到就转卖 CC",
        })
    for p in cc_positions:
        wheel_cycles.append({
            "ticker": p["ticker"],
            "phase": "cc",
            "detail": f"CALL ${p['strike']} · 到期 {p['expiry']}",
            "note": "卖 CC 收租，被 call 走就转 CSP",
        })

    portfolio = {
        "updatedAt": updated_at,
        "cash": cash,
        "ccPositions": cc_positions,
        "cspPositions": csp_positions,
        "idlePositions": stock_holdings,
        "closedTrades": closed_trades,
        "wheelCycles": wheel_cycles,
    }

    OUTPUT.write_text(json.dumps(portfolio, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"✅ Portfolio synced from {PORTFOLIO_MD} → {OUTPUT}")
    print(f"   CC: {len(cc_positions)} positions")
    print(f"   CSP: {len(csp_positions)} positions")
    print(f"   Stocks: {len(stock_holdings)} holdings")


if __name__ == "__main__":
    main()
