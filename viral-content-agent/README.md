# 爆款内容拆解与二创 Agent

> 一个**数据驱动、可复算、带人工确认闸门**的社交媒体爆款内容分析智能体。
> 用真实公开数据对比"爆款"与"普通"内容，沉淀可复用结构模板，并生成原创二创候选——
> **但任何内容进入资产库之前，都必须经过人工确认（Human-in-the-loop）。**

---

## 一、项目简介（对应题目要求）

本项目的设计严格对应题目对"爆款内容拆解与二创 Agent"的四条要求：

| 题目要求 | 本项目的实现 |
| --- | --- |
| **使用真实公开数据进行对比分析** | 第一步只从真实公开接口抓取数据（Hacker News Algolia API、Reddit、V2EX、搜索 API、Jina/Playwright 浏览器通道），并保留抓取快照保证结论可复算；数据缺失时标注"数据不可得"，**绝不编造互动数字**。 |
| **内容生成入库必须包含人工确认** | 第三步结尾是流程唯一的强制暂停点，输出《二创内容确认单》并阻塞等待人工输入；资产库写入前校验 `ApprovalToken`（含内容 sha256 摘要），**代码层面不可绕过**。人工确认开关在配置中不存在（不可关闭）。 |
| **角色设定（数据驱动 / 逻辑严密 / 极具创意）** | `config/prompts.py` 中的 `SYSTEM_PROMPT` 定义了"精通社交媒体算法的内容策略专家"人设与工作准则。 |
| **可部署到 GitHub 的标准项目结构** | 模块化分包（数据获取 / 分析 / 创作 / 人工确认 / 资产库各自独立），配置与代码分离，含 `README`、测试、CI。 |

---

## 二、核心特性

- **真实数据优先，多级降级**：官方公开 API → 浏览器通道 → 搜索工具 → 本地真实快照兜底。断网/无 Key 也能用历史真实快照完整演示。
- **六维可复算拆解**：选题 / Hook / 结构节奏 / 信息密度 / CTA / 互动设计，每维可回溯到原文片段与具体指标。
- **方向感知的归因**：差异归因建议与数据方向严格一致（高表现组更不常含数字时，绝不会建议"加数字"）。
- **解释力自评**：主动评估"文案写法能解释多少真实互动差异"，差异极大而六维接近时明确提示"解释力弱"，**防止过度归因**。
- **Human-in-the-loop 硬闸门**：未经确认 `commit()` 直接抛 `HumanApprovalRequired`；确认后改内容再入库也会被摘要校验拦下。
- **可扩展后端**：资产库支持本地 JSON（默认）/ Notion / 飞书多维表格，通过 `ASSET_BACKEND` 切换。
- **零硬依赖可运行**：未配置 LLM Key 时自动降级为规则引擎，Demo 永远跑得起来。

---

## 三、快速开始

### 1. 环境要求
- Python 3.10+
- 无需任何 API Key 即可用**本地真实抓取快照**跑通完整 Demo

### 2. 安装依赖
```bash
git clone <your-repo-url>
cd viral-content-agent
pip install -r requirements.txt
```

### 3. 一键演示（推荐）
```bash
# 用内置真实抓取快照离线演示（无需联网/Key）
python demo.py --offline

# 或实时抓取真实公开数据（失败自动回落快照）
python demo.py hn:author:pseudolus
```
演示要点：
1. 全程打印**思考过程**与**对比表格**；
2. 走到第三步会出现黄色 `HUMAN-IN-THE-LOOP` 暂停框，提示：
   > 分析已完成。请审核生成的候选内容。输入 '确认' 将内容写入资产库，输入 '修改' 重新调整。
3. 输入 `确认` 才会写入资产库并打印入库日志；输入 `修改` 会按意见重新生成候选。

### 4. 一键运行 Web Demo（可视化网页版）

无需终端交互，打开浏览器即可走完"数据概览 → 拆解分析 → 人工确认 → 资产入库"四步流程，
人工确认闸门与 CLI 版完全一致（仍需勾选审核框、点击"执行入库"才会落库）。

```bash
pip install streamlit
streamlit run app.py
```

> 浏览器会自动打开 `http://localhost:8501`。左侧选择 **📦 内置快照 Demo（无需 Key）**，
> 点击「🚀 开始拆解与生成」即可；走到第三步会显示 3 条候选内容，勾选确认框后「执行入库」按钮才亮起。

- **在线体验链接**：（待填写，可后续部署到 Streamlit Community Cloud / 自有服务器后填入）
- 演示模式说明：快照模式默认演示 `hn:author:pseudolus` 的真实抓取数据；联网模式会尝试实时抓取，失败自动回退快照。

### 4b. 纯前端静态 Demo（免安装，可直接部署 GitHub Pages）

`index.html` 是一个**零依赖单文件静态页**（HTML5 + Tailwind CDN + 原生 JS），内置模拟快照数据，
**不需要 Python / 不需要后端 / 不需要任何 Key**，双击或托管后即可体验完整的
"新建任务 → 数据概览 → 拆解分析 → 人工确认入库"对话式流程。

```bash
# 本地直接打开
#   双击 index.html，或：
python -m http.server 8000   # 然后访问 http://localhost:8000/index.html
```

部署到 GitHub Pages：
1. 将仓库 push 到 GitHub；
2. 仓库 **Settings → Pages → Source** 选择 `main` 分支根目录（`/root`）；
3. 保存后访问 `https://<your-username>.github.io/<repo>/index.html`。

- **在线体验链接**：（待填写，部署后填入上方 Pages 地址）
- 说明：该静态页为前端演示，数据为模拟快照；**真实抓取与入库逻辑仍以 `app.py` / CLI 为准**。

### 5. 通过 CLI 运行完整工作流
```bash
# 完整跑一遍：真实抓取 → 分析 → 生成 → 人工确认 → 入库
python main.py run --account "hn:author:pseudolus"

# 只跑到人工确认就停下（把确认单交给他人审核）
python main.py run --account "reddit:r/LocalLLaMA" --non-interactive

# 审核完成后续跑入库（'确认 1,3' 表示只入库第 1、3 条）
python main.py resume --session S20260820XXXX --decision "确认 1,3"

# 查看资产库 / 历史会话 / 某会话详情
python main.py assets
python main.py sessions
python main.py show --session S20260820XXXX
```

### 6. 运行测试
```bash
pip install pytest
pytest -q
```

---

## 四、四步工作流

```
INIT → RETRIEVED → ANALYZED → DRAFTED → AWAITING_APPROVAL
                                         ├─ 确认  → APPROVED → LOGGED
                                         ├─ 修改  → DRAFTED（回到生成，最多 N 轮）
                                         └─ 取消  → ABORTED
```

1. **真实数据获取与筛选**（`src/data_retrieval.py`）
   调用真实公开数据通道抓取账号近 30 天内容，按真实互动数据筛出 Top 1–3 条"高表现内容" + 固定随机种子抽样的 2–3 条"普通内容"对照组。
2. **深度拆解与归因**（`src/analyzer.py`）
   六维打分 → 高低对比找关键变量（强因果 / 疑似相关 / 噪声分级）→ 沉淀可复用"爆款内容结构模板"。
3. **二次创作与人工确认**（`src/creator.py` + `src/human_review.py`）
   生成 ≥3 条不同角度的原创候选，输出《二创内容确认单》，**强制暂停等待人工输入**；收到"确认"后才签发确认凭证。
4. **资产入库与记录**（`src/asset_store.py`）
   仅当携带有效人工确认凭证时，才写入内容资产库并打印入库日志（含资产 ID，待后续追踪表现）。

> 详细流程与合规设计见 [`docs/workflow.md`](docs/workflow.md)；模块职责划分见 [`docs/architecture.md`](docs/architecture.md)。

---

## 五、项目结构

```
viral-content-agent/
├── main.py                      # CLI 入口（run / resume / assets / sessions / show）
├── demo.py                      # 一键演示脚本
├── app.py                       # 可视化 Web Demo（Streamlit 单文件，复用 src 逻辑）
├── index.html                   # 纯前端静态 Demo（GitHub Pages 用，零依赖，模拟数据）
├── requirements.txt             # 依赖（核心零硬依赖，可选 requests/playwright/streamlit）
├── pyproject.toml              # pytest 配置（pythonpath 让 config/src 可被导入）
├── .env.example                 # 全部可选项模板（明注"人工确认无开关"）
├── config/
│   ├── settings.py              # 全局配置；零硬依赖 .env 解析器
│   └── prompts.py               # 角色设定 + 各阶段 Prompt + 确认提示语
├── src/
│   ├── models.py                # 领域模型（贯穿全链路，可序列化落盘）
│   ├── data_retrieval.py        # 第一步：真实数据获取与筛选 + 快照
│   ├── analyzer.py              # 第二步：六维打分 + 差异归因 + 模板沉淀
│   ├── creator.py               # 第三步（上）：二次创作（LLM/规则双引擎）
│   ├── human_review.py          # 第三步（下）：人工确认闸门（合规核心）
│   ├── asset_store.py           # 第四步：资产入库（JSON/Notion/飞书）
│   ├── agent.py                 # 工作流状态机编排（可暂停、可续跑）
│   ├── llm_client.py            # OpenAI 兼容 LLM 客户端（无 Key 自动降级）
│   ├── providers/               # 数据源：HN / Reddit / V2EX / 搜索 / 浏览器 / 快照
│   └── utils/                   # text 特征提取 / 终端渲染 / 极简 HTTP
├── data/
│   ├── snapshots/               # 真实抓取快照（含 hn-author-pseudolus.json 供离线 Demo）
│   ├── assets/                  # 内容资产库（gitignored，运行后生成）
│   └── sessions/                # 会话状态机落盘（gitignored）
├── docs/
│   ├── workflow.md              # 工作流与人工确认合规设计
│   ├── architecture.md          # 模块化架构说明
│   └── screenshots/             # 演示截图占位目录（见下方说明）
├── tests/                       # pytest 单元测试 + 端到端管线测试
└── .github/workflows/ci.yml     # GitHub Actions：多版本 Python 跑测试
```

---

## 六、配置（`.env.example`）

复制为 `.env` 后按需填写。**人工确认是流程完整性的一部分，不提供任何开关。**

```ini
# ---- 可选：LLM（不填则自动降级为规则引擎）----
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=
LLM_MODEL=gpt-4o-mini

# ---- 可选：数据获取 ----
TARGET_ACCOUNT=hn:author:pseudolus
LOOKBACK_DAYS=30
FETCH_LIMIT=60

# ---- 可选：资产库后端（json / notion / feishu）----
ASSET_BACKEND=json
# NOTION_TOKEN= / NOTION_DATABASE_ID=
# FEISHU_APP_ID= / FEISHU_APP_SECRET= / FEISHU_BITABLE_APP_TOKEN= / FEISHU_BITABLE_TABLE_ID=
```

账号定位符统一格式：`<platform>:<kind>:<value>`
- `hn:author:pseudolus` — Hacker News 账号主页（免密钥，真实 points/comments）
- `hn:topic:AI agent` — Hacker News 话题流
- `reddit:r/LocalLLaMA` / `v2ex:latest` / `@handle` / `https://...` — 走搜索/浏览器通道

---

## 七、合规设计（为什么可以放心用）

1. **不编造数据**：所有互动数字来自平台真实返回值；接口不提供的指标标为"数据不可得"，不参与计算。
2. **结论可复算**：每次抓取自动存快照（含 provider、时间、source_urls 溯源），分析结论可被任何人用同一份数据复现；快照加载时校验 `provenance`，**拒绝伪造数据入链路**。
3. **人工确认不可绕过**：`ApprovalToken` 内含候选内容 sha256 摘要；`asset_store.commit()` 入库前调用 `HumanReviewGate.assert_approved()` 做最终校验，缺凭证 / 会话不匹配 / 内容被篡改 / 决策非 confirm 一律拒绝写入。
4. **防止过度归因**：主动做"解释力自评"，六维接近但真实互动差异极大时明确提示差异来自选题与时机，而非文案技巧。

---

## 八、演示截图占位符

> 请将以下演示截图放到 `docs/screenshots/` 目录，并按对应文件名命名（文件名已与下方引用一致）。
> 录制/运行 Demo 时按下述四个节点截屏即可。

![Step 1 真实数据获取与样本分组](docs/screenshots/step1-data-retrieval.png)
*图 1：第一步——真实数据获取，样本按真实互动数据分为"高表现/对照组"，并打印数据溯源。*

![Step 2 六维拆解与差异归因](docs/screenshots/step2-analysis.png)
*图 2：第二步——六维拆解对比表 + 差异归因表 + 核心洞察 + 解释力自评 + 模板沉淀。*

![Step 3 人工确认暂停框](docs/screenshots/step3-human-gate.png)
*图 3：第三步——黄色 `HUMAN-IN-THE-LOOP` 暂停框与《二创内容确认单》，等待人工输入。*

![Step 4 资产入库日志](docs/screenshots/step4-asset-logged.png)
*图 4：第四步——人工确认后内容入库，打印资产 ID 与入库日志。*

> 占位说明文件见 [`docs/screenshots/README.md`](docs/screenshots/README.md)。

---

## 九、许可证

MIT License —— 可自由用于学习、研究与二次开发。
