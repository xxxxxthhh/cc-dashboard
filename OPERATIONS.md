# CC Dashboard Operations

别自作聪明。先对账，再 build。

## 真相源优先级

1. `portfolio_data.json` — **dashboard 构建真相源**
2. `../memory/portfolio.md` — 人类账本 / 对账依据
3. `../MEMORY.md` / `../shared-memory/portfolio.md` — 辅助理解，不是精确构建源

## 关键规则

- **不要**把缺失 premium 写成 `0`
- 缺失字段宁可保留 `null` / 不动，也别瞎编
- **不要**把“已实现 / 在途 / 本周总收入”混为一谈
- 周收益一律按 **到期周** 归属，不按开仓周；长周期单（如远期 CC）只在它到期那周计入
- 数据不对，优先修 `portfolio_data.json`，不是先改前端展示逻辑
- `portfolio_data.json` 是私有文件，默认不提交 git
- 发布到 GitHub Pages 的是 `index.html`

## 标准流程

```bash
cd cc-dashboard
node validate_portfolio.js
node build.js
git add index.html
git commit -m "Rebuild dashboard"
git push
```

## 本周基准口径（2026-03-09 ~ 2026-03-13，到期周口径）

- 已实现：`$179`
- 在途：`$1,363`
- 本周总收入：`$1,542`

如果你改完跑不出这个结果，先别 push，说明你又把东西改坏了。
