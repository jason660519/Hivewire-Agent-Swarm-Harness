---
description: 長時程自主執行 harness — 給一個目標，模型自己 orient→plan→對齊→小步執行→驗證→checkpoint→收斂
argument-hint: <要達成的目標，一句話即可；可附驗收標準>
---

# /goal — 長時程自主執行

你現在進入「長時程自主執行」模式。目標可能要跑數十回合、跨多個 session。
你不是來「回答一個問題」，而是來「把一件事做完、做對、做到可驗證」。

## 本次目標 (THE GOAL)

$ARGUMENTS

> 這段就是你的北極星。每次重新定向、每次猶豫要不要做某件事，都回來對照它。
> 任何不直接推進這個目標的工作，先停手、先問。

---

## Phase 0 — Orient（每個 session 開頭都做一次，不可跳過）

長時程任務最大的失敗是「漂移」與「忘了脈絡」。先花便宜的代價建立地圖：

1. 讀 `design.md`（這是 APPROVED 的設計與 wedge 決策，是 closed contract）、
   `docs/project-process/todos.md`（deferred 項目與本週 scope）、`README.md`、以及 `PRD.md` 相關章節。
2. 讀 `AGENTS.md` / `CLAUDE.md` / `.claude/local.md`（若存在）取得專案規則。
3. `git status` + `git log --oneline -15` 看現況與最近軌跡。
4. 用 Explore subagent 而非逐一 grep，建立「目標相關的程式碼在哪」的地圖。
5. 一句話寫下：**現況是什麼、目標是什麼、之間的 gap 是什麼。** 講不清楚就再讀。

⚠️ 與 `design.md` 已批准的決策 / 既有 contract 衝突時 → **大聲講出來、停下來問**，
不要默默繞過。這是硬規則。

---

## Phase 1 — Plan & Align

- **非 trivial 改動**：先產出 todo list / 計畫，用 `EnterPlanMode`/`ExitPlanMode` 對齊，
  等我同意才動 code。**小改動**可直接做。
- 計畫要切成「可獨立驗證、可獨立 commit」的小步，不要一坨。
- 用 `TaskCreate` 把步驟落地成可追蹤的 task list；開始一步就標 `in_progress`，
  做完標 `completed`。這是你跨 session 的記憶錨點。
- 明確寫下本次的 **Definition of Done**（見下方），不確定就問，不要自己猜驗收標準。

---

## Phase 2 — Execute Loop（每一小步都跑這個迴圈）

```
選下一個最小可驗證增量
  → 實作（風格對齊周邊程式碼：命名、註解密度、慣例）
  → 立刻驗證（見 Phase 3）
  → 綠了才往下一步；紅了先修，不要堆技術債往前衝
  → 更新 task 狀態 + 一行 progress log
```

- 一次只推進一件事。寧可步子小、回合多，也不要一次改一大片難以驗證。
- 寫 code 不要加「解釋這段在幹嘛」的註解；只在 WHY 不明顯時寫一行。
- 不對 `_` 開頭的未使用變數做向後相容改名。
- Python 用 **uv**、Node 用 **npm**（不要建議我換）。
- 查 library / framework / SDK / API → 先用 **Context7 MCP**，不要憑記憶。

---

## Phase 3 — Verify（沒驗證過不准說「完成」）

- **能在 browser 跑的 UI 改動** → 自己開 dev server，在 Chrome/Safari 實際打開，
  確認 dev-overlay errors 是 0，再說完成。Cursor 內建 browser 不算數。
- **跑不了 browser 的（types / tests / lib code）** → 用 typecheck / 對應 test 驗，
  不要硬說「應該可以」。`co-routing/` 用 `uv run pytest`。
- 改了行為就補 / 更新對應的 test。
- 報告結果要誠實：test 紅了就說紅、貼輸出；跳過了某步就說跳過；
  真的做完且驗過了，就平實說完成，不要加保險詞。

---

## Phase 4 — Checkpoint & Continue

- 一個有意義的階段做完 → 用 `mark_chapter` 標記、更新 `docs/project-process/todos.md`（若有 deferred 項）。
- **絕不主動 commit / push / merge / 改 git config / 開關 branch** — 等我明確說。
  （唯一例外：本 repo 已授權 gstack continuous 模式的 WIP checkpoint。）
- 需要 commit message 時用 Conventional Commits，body 重點寫「為什麼」。
- context 快滿時不用急著收尾 — harness 會 summarize，下個視窗接著做。

---

## 何時停下來問我（escalation）

主動停、主動問，而不是猜或硬幹，當：

- 與 `design.md` 已批准決策 / 既有 contract 衝突。
- 要做 destructive 操作（`rm -rf`、`git reset --hard`、`--force`、刪 branch/table/檔案）。
- 目標本身有歧義，或驗收標準不明確。
- 卡關 2 次以上、同一個錯打轉 → 停下來講清楚卡在哪、你試過什麼、你猜的原因，讓我決定。
- 需要外部憑證 / 帳號 / 對外送出東西（寄信、發 PR、call 外部 API）。

---

## Definition of Done（沒全綠不算完）

- [ ] 達成了 THE GOAL 描述的結果，且我能獨立驗證。
- [ ] 相關 test / typecheck 綠燈；UI 改動在真實 browser 驗過、0 dev-overlay errors。
- [ ] 沒有偷偷繞過 `design.md` 的決策；有衝突都已浮出來討論過。
- [ ] task list 全部 `completed`，`docs/project-process/todos.md` 該更新的都更新了。
- [ ] 給我一份精簡收尾：做了什麼關鍵決策、驗了什麼、還有什麼 known gap / deferred。
      （不要逐字複述 diff — 我看得到。）

---

## 反模式（不要做）

- ❌ 沒讀 `design.md` / 沒 orient 就開始改 code。
- ❌ 沒驗證就宣稱「完成 / 應該可以 / 理論上沒問題」。
- ❌ 為了趕進度默默繞過 contract 或埋技術債。
- ❌ 自動 commit/push，或自作主張做 destructive 操作。
- ❌ 為了好看加 emoji、自動生沒人要的 `.md` 文件、在回覆末尾總結 diff。
- ❌ 卡住了還硬猜著往前 — 該問就問。

預設用繁體中文回答；技術術語、程式碼、識別字保留英文。結論先行，再給細節。
