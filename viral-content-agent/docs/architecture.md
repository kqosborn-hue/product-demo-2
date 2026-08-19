# 模块化架构说明

本项目刻意把"数据分析 / 内容生成 / 人工确认 / 资产入库"拆成相互独立的模块，
每个模块只通过明确的接口通信，便于单独测试、替换与扩展。

---

## 一、分层与依赖方向

```
                  main.py / demo.py  (CLI 入口)
                          │
                          ▼
                   src/agent.py  (状态机编排：run / resume)
        ┌─────────┬─────────┬──────────┬──────────┐
        ▼         ▼         ▼          ▼          ▼
  data_retrieval  analyzer  creator  human_review  asset_store
        │            │         │          │            │
        └────┬───────┴────┬────┴──────────┴────────────┘
             ▼            ▼
        providers/    utils/ (text / console / http)
             │
             ▼
        models.py  (贯穿全链路的领域模型，全部可序列化)
             │
             ▼
        config/ (settings.py 配置 / prompts.py 角色与 Prompt)
```

依赖原则：**上层调用下层，下层不反向依赖上层**；所有跨步骤的中间态都落在
`models.py` 的领域对象上，并可 `to_dict()` 序列化进 `data/sessions/`，这是
"可暂停、可续跑"状态机的基础。

---

## 二、模块职责

### `config/`
- **settings.py**：全局配置。内置极简 `.env` 解析器（未装 python-dotenv 也能跑），
  所有敏感信息只从环境变量读取，不硬编码。`require_human_approval` 为常量 `True`。
- **prompts.py**：集中所有 Prompt——`SYSTEM_PROMPT`（角色设定）、六维拆解 /
  差异归因 / 模板沉淀 / 二次创作 / 修改 Prompt，以及人工确认提示语 `CONFIRM_HINT`
  与接受词集合 `CONFIRM_ACCEPT/REVISE/ABORT`。

### `src/models.py`
领域模型：`Metrics`（互动数据，缺失标 `None`）、`Post`、`Dataset`、
`DimensionScore`、`PostAnalysis`、`VariableDiff`、`ViralTemplate`、
`AnalysisResult`、`Draft`、`ApprovalToken`、`Session`（状态机）+ `Stage` 常量。
所有模型支持 `to_dict() / from_dict()` 往返，保证可落盘、可续跑。

### `src/data_retrieval.py` + `src/providers/`
- **DataRetriever**：入口 `retrieve()`，完成解析→通道选择→时间窗→分类→存快照。
- **providers/**：`base.py`（账号解析 `parse_account` + `AccountRef` + 抽象接口）、
  `hackernews.py`、`community.py`（Reddit/V2EX）、`search_api.py`
  （Serper/Tavily/博查）、`browser.py`（Jina Reader/Playwright）、
  `snapshot.py`（本地真实快照，校验 `provenance` 防伪造）。
  注册表 `LIVE_PROVIDERS` 按优先级串行尝试，逐层降级。

### `src/analyzer.py`
- **ScoreEngine**：六维打分（纯规则、可复算）。
- **ContentAnalyzer**：`analyze()` 串联 拆解 → 差异归因（`diff`，方向感知的
  `_actionable`）→ 核心洞察 → **解释力自评**（`_explanatory_power`）→ 模板沉淀
  （`distill`）。LLM 仅做增强，失败自动回落规则引擎，不影响可复算结论。

### `src/creator.py`
- **ContentCreator**：`create()` 生成 ≥3 条不同角度原创候选。优先 LLM，不足时
  规则引擎补齐；生成后用六维引擎反向自评打分（`_self_check`，生成即自检）。

### `src/human_review.py`（合规核心）
- **HumanReviewGate**：`render_confirmation_sheet()` 输出确认单；
  `wait_for_decision()` 阻塞等待人工输入；`_parse_selection()` 支持"确认 1,3"；
  `assert_approved()` 入库前最终闸门校验（缺凭证/非 confirm/会话不匹配/摘要不符 →
  抛 `HumanApprovalRequired`）。

### `src/asset_store.py`
- **BaseAssetStore.commit()**：写入前强制 `assert_approved()`；按确认选中的候选入库。
- 三种后端：`JsonAssetStore`（默认）/ `NotionAssetStore` / `FeishuAssetStore`，
  由 `get_asset_store(settings)` 按 `ASSET_BACKEND` 切换。

### `src/llm_client.py`
- **LLMClient**：OpenAI 兼容 `/chat/completions`；`available` 在缺 Key 时为 `False`，
  analyzer / creator 自动降级规则引擎。`parse_json_loose()` 容忍模型输出脏数据。

### `src/utils/`
- **text.py**：文本特征提取（Hook/CTA 分类、信息密度、结构识别、CJK 宽度对齐），
  是"可解释归因"的事实基础。
- **console.py**：终端渲染（思考过程、CJK 对齐表格、黄色人工确认警示框、进度条）。
- **http.py**：极简 HTTP 客户端（requests 优先，urllib 兜底）。

---

## 三、扩展指引

- **新增数据源**：在 `src/providers/` 继承 `BaseProvider` 实现 `fetch()`，
  加入 `LIVE_PROVIDERS` 注册表即可，无需改动编排层。
- **新增资产后端**：继承 `BaseAssetStore` 实现 `_persist()`，注册进
  `get_asset_store()` 的字典，并设置 `ASSET_BACKEND`。
- **调整归因维度**：修改 `analyzer.py` 的 `VARIABLE_SPECS` 与 `ScoreEngine`
  各维度打分函数，规则保持纯函数、可复算。
- **接入更强 LLM**：在 `.env` 配置 `LLM_BASE_URL` / `LLM_API_KEY`，
  分析/创作会自动启用 LLM 增强。
