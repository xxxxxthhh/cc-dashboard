#!/usr/bin/env python3
"""
sync_portfolio.py — 从 build.js 提取 DATA 对象，输出 portfolio_data.json

避免 decision_engine.py 依赖硬编码 fallback。
每次更新 build.js 后跑一次即可。
"""
import re
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
BUILD_JS = SCRIPT_DIR / 'build.js'
OUTPUT = SCRIPT_DIR / 'portfolio_data.json'


def extract_data_from_buildjs():
    """从 build.js 中提取 DATA = { ... }; 对象"""
    text = BUILD_JS.read_text()

    # 找到 const DATA = { 到对应的 }; 
    # 用简单的括号匹配
    start = text.find('const DATA = {')
    if start == -1:
        raise ValueError("Cannot find 'const DATA = {' in build.js")

    # 从 { 开始计数括号
    brace_start = text.index('{', start)
    depth = 0
    i = brace_start
    while i < len(text):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                break
        i += 1

    js_obj = text[brace_start:i + 1]

    # JS → JSON 转换：
    # 1. 去掉尾逗号
    js_obj = re.sub(r',(\s*[}\]])', r'\1', js_obj)
    # 2. 给无引号的 key 加引号
    js_obj = re.sub(r'(\s)(\w+)\s*:', r'\1"\2":', js_obj)
    # 3. 处理单引号字符串 → 双引号（简单情况）
    # 不处理，build.js 用的是双引号

    try:
        data = json.loads(js_obj)
    except json.JSONDecodeError as e:
        # fallback: 用 node 执行
        import subprocess
        result = subprocess.run(
            ['node', '-e', f'const DATA = {js_obj}; console.log(JSON.stringify(DATA))'],
            capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            raise ValueError(f"JSON parse failed: {e}\nNode fallback also failed: {result.stderr}")
        data = json.loads(result.stdout)

    return data


def main():
    data = extract_data_from_buildjs()

    # 只保留 decision_engine 需要的字段
    portfolio = {
        'updatedAt': data.get('updatedAt', ''),
        'cash': data.get('cash', 25000),
        'ccPositions': data.get('ccPositions', []),
        'cspPositions': data.get('cspPositions', []),
        'idlePositions': data.get('idlePositions', []),
        'closedTrades': data.get('closedTrades', []),
        'wheelCycles': data.get('wheelCycles', []),
    }

    with open(OUTPUT, 'w') as f:
        json.dump(portfolio, f, indent=2, ensure_ascii=False)

    print(f"✅ Portfolio synced: {OUTPUT}")
    print(f"   CC: {len(portfolio['ccPositions'])} positions")
    print(f"   CSP: {len(portfolio['cspPositions'])} positions")
    print(f"   Idle: {len(portfolio['idlePositions'])} positions")
    print(f"   Closed: {len(portfolio['closedTrades'])} trades")


if __name__ == '__main__':
    main()
