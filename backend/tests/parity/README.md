# Parity Testing

> 防止「同样的输入跑出不一样的结果」回归。

## 两个层级

| 层级 | 文件 | CI 跑吗 | 何时触发漂移检测 |
|---|---|---|---|
| **Phase 级** | `test_score_phase_parity.py` + `fixtures/score_phase_v1.json` | ✅ 每次 push | ScoringAgent prompt/parser 改了、score 排序逻辑变了 |
| **Round 级** | `test_round_replay.py` + `fixtures/golden_round_*.json` | 当 fixture 存在时跑（默认 skip） | QueryPlanAgent → Fetcher → ScoringAgent 整链路任一环节出现跨 phase 漂移 |

Phase 级开箱即用，3 docs + 3 LLM 响应已经手写在 fixture 里。Round 级需要从真实环境跑一次 `record_round.py` 录一份 golden。

---

## Round 级 Bootstrap（一次性操作）

### 前置条件

- docker compose v2 起着完整后端（postgres + redis + backend + worker）
- 至少一个项目跑过一轮真实检索（即 `search_rounds.status = 'awaiting_feedback'` 的某条记录）
- 真实 fetcher API key 配在 `.env` 里（OpenAlex / Crossref 这些不需要 key 也能跑）
- LLM 配置就绪（`llm:config` Redis key 不为空）

### 录制步骤

```bash
# 1. 进入 backend 容器
docker compose exec backend bash

# 2. 在容器内执行（替换 <UUID> 为真实 project_id）
python -m tests.parity.record_round \
    --project-id <UUID> \
    --output tests/parity/fixtures/golden_round_001.json

# 3. 退出容器
exit

# 4. 把生成的 fixture 入库
git add backend/tests/parity/fixtures/golden_round_001.json
git commit -m "test(parity): bootstrap round-level golden 001"
```

录制过程会触发**真实** fetcher 网络请求和**真实** LLM 计费（约一轮的成本，
~$0.05 USD）。生成的 JSON 通常 1-5 MB，可以正常入 git。

### 上线效果

下一次 push 起，CI 的 unit-tests job 会跑 `test_round_replay.py`：
- 安装 fetcher / LLM replay → 跑 `_execute_round_async`
- 断言最终 paper_id 集合 = 录制时的集合
- 漂移时给出 doc-id 级别的 +/- diff

任何一处改动（Fetcher 解析逻辑、ScoringAgent prompt、排序、cutoff、…）
导致 paper 集变化，CI 会立刻红，diff 一目了然。

---

## 接受漂移（intentional behaviour change）

```bash
docker compose exec backend python -m pytest tests/parity/ --update-golden
git diff backend/tests/parity/fixtures/  # 检查变化合理
git commit -m "test(parity): update golden after <X> change"
```

`--update-golden` 是命令行 flag（在 `conftest.py` 里注册）。**漂移本身**写进
git 历史 — 半年后 `git log -p backend/tests/parity/fixtures/` 就是一份天然的
「行为变更日志」。

---

## 未来想加几份 golden 时

`test_round_replay.py` 用 glob 匹配 `golden_round_*.json`，参数化跑每一份。
直接命名 `golden_round_002.json` / `golden_round_patent_heavy.json` 加入即可。

建议覆盖：
- `golden_round_001.json` — 通用学术检索（默认 fetcher 集）
- `golden_round_002_patent.json` — 含 patenthub / lens 等专利源
- `golden_round_003_local_kb.json` — `static_db` 模式只走本地知识库
- `golden_round_004_zero_results.json` — 验证零结果分支不漂移

每加一份就多一道安全网，CI 时间增加微乎其微（fetcher / LLM 都是 replay）。

---

## 故障排查

| 症状 | 原因 | 解决 |
|---|---|---|
| `LLMReplayManager exhausted` | 代码新增了 LLM 调用，replay 不够 | 先看 diff 是不是有意加的，再 `--update-golden` |
| `FetcherReplay exhausted for target=...` | 同上，fetcher 调用增加 | 同上 |
| `paper_ids drifted` 报 +N -M | Fetcher / Scoring 逻辑变了 | 检查 PR 改动，合理就 `--update-golden` |
| `fixture not found` → skipped | 还没 bootstrap | 按上面"Bootstrap"步骤跑一次 |
