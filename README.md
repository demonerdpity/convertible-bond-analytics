# 可转债比价看板（Vue + Python FastAPI）

基于东方财富可转债比价表数据的独立 Web 应用，支持全市场可转债一次拉取、全量排序、筛选及自定义衍生指标计算。

## 功能特性

- **完整比价字段**：覆盖东方财富可转债比价表全部核心列（转债/正股现价及涨跌幅、转股价、转股价值、转股溢价率、纯债溢价率、回售/强赎触发价、到期赎回价、纯债价值、转股日/上市日/申购日）。
- **新增指标「每百元现价转股市值」**：公式为 `100 ÷ 转债现价 ×（100 ÷ 转股价 × 正股价）`，悬停 `ⓘ` 查看释义，数值 ≥ 100 自动高亮。
- **全量排序与筛选**：突破原网页单页排序限制，所有数值与日期列均支持全市场三态排序（降序 / 升序 / 还原），空值自动沉底；支持代码/简称搜索、过滤未上市新债与折价筛选。
- **稳定数据源（动静结合）**：主源采用东方财富公开数据中心（`datacenter-web.eastmoney.com`，`RPT_BOND_CB_LIST`），1 页即可获取全市场活跃沪深可转债及实时行情；对缺失现价自动使用腾讯批量行情（`qt.gtimg.cn`）补全，纯债价值按剩余票息与到期赎回价本地贴现估算。
- **按需单次拉取与本地缓存**：后端采用 `uv` 独立虚拟环境管理，仅在手动点击按钮时触发拉取，成功后落盘至 `backend/data/latest_bonds.json` 并启用 30 秒冷却防抖，不做自动定时轮询。

## 目录结构

```text
├── backend/                # Python FastAPI 后端（uv 独立虚拟环境）
│   ├── pyproject.toml
│   └── app/
│       ├── main.py
│       ├── models.py
│       └── services/eastmoney.py
└── frontend/               # Vue 3 + Vite 前端
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── App.vue
        ├── components/BondTable.vue
        └── style.css
```

## 启动方式

### 1. 启动后端（uv 虚拟环境）

```powershell
cd backend
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 20001 --reload
```

### 2. 启动前端（Vue 3 + Vite）

```powershell
cd frontend
npm install
npm run dev
```

打开浏览器访问 `http://127.0.0.1:30001`（前端 `30001` 自动将 `/api` 代理到后端 `20001`），页面默认不加载数据，点击 **「获取数据」** 即可发起一次全量请求。

> 生产运行：`cd frontend && npm run build && npm run preview`（默认监听 `30001` 并代理 `/api` 到 `20001`），也可直接访问后端 `20001` 端口。
