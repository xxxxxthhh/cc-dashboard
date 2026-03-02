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
PORTFOLIO_MD = WORKSPACE / "memory" / "portfolio.md"
OUTPUT = SCRIPT_DIR / "portfolio_data.json"


def _parse_money_to_int(s: str) -> int | None:
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
    # Find section
    pat = rf"^##\s+{re.escape(heading)}\s*$"
    m = re.search(pat, text, flags=re.MULTILINE)
    if not m:
        return []
    start = m.end()

    # table starts at first line beginning with |
    lines = text[start:].splitlines()
    table_lines = []
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
    rows = []
    for line in body:
        parts = [p.strip() for p in line.strip().strip("|").split("|")]
        if all(not p for p in parts):
            continue
        rows.append(parts)
    return rows


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
        stock_holdings.append({
            "ticker": ticker,
            "shares": shares,
            "cost": price or 0,  # 缺 cost basis，用现价占位
            "canCC": shares >= 100,
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
        cc_positions.append({
            "ticker": ticker,
            "strike": strike,
            "expiry": expiry,
            "contracts": contracts,
            # 下面字段可能缺失，decision_engine 会自动跳过止盈追踪
            "premium": 0,
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
        premium = _parse_money_to_int(r[5])
        if not ticker or strike is None or not expiry or not contracts:
            continue
        csp_positions.append({
            "ticker": ticker,
            "strike": strike,
            "expiry": expiry,
            "contracts": contracts,
            "premium": premium or 0,
            "collateral": int(abs(contracts) * strike * 100),
        })

    portfolio = {
        "updatedAt": updated_at,
        "cash": cash,
        "ccPositions": cc_positions,
        "cspPositions": csp_positions,
        "idlePositions": stock_holdings,
        "closedTrades": [],
        "wheelCycles": [],
    }

    OUTPUT.write_text(json.dumps(portfolio, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"✅ Portfolio synced from {PORTFOLIO_MD} → {OUTPUT}")
    print(f"   CC: {len(cc_positions)} positions")
    print(f"   CSP: {len(csp_positions)} positions")
    print(f"   Stocks: {len(stock_holdings)} holdings")


if __name__ == "__main__":
    main()
