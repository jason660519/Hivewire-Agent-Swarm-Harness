# Hivewire File Naming and Archiving Standards

> **Created Date**: 2026-06-23
> **Created By**: Claude (Opus 4.8)
> **Version**: 1.0
> **Document Type**: Governance
> **Status**: Adopted

---

## English Version

### 1. Adoption

Hivewire **adopts the Company AI App File Naming and Archiving Standards**
(canonical source: `Project-Manager/docs/file-naming-standards.md`, v1.9). That
document is the source of truth for naming rules, role-based `docs/` folders, and
the archiving policy. This file records only what is **Hivewire-specific**: which
folders are instantiated, one extension the company standard does not cover, and
intentional local deviations.

Hivewire was not in the original alignment scope (Project Manager / SayDo); this
file is the explicit decision to align it.

### 2. Local folder map (instantiated on demand)

The company standard defines seven role folders. Hivewire is small, so we create
a role folder only when it has a real occupant — not the full empty tree.

```text
docs/
├── assets/           # Binary presentation assets (screenshots, diagrams)  (public)
├── product/          # Product strategy / moat thesis                      (public here, see §4)
├── project-process/  # Backlog, progress, hand-off notes                   (internal)
└── file-naming-standards.md   # this governance doc (docs root, per company §5)
```

Engineering contracts that are tightly coupled to code stay next to that code:
`co-routing/docs/` (e.g. `vendor-integration.md`). This matches the company
standard's allowance for implementation-contract subfolders.

### 3. Asset convention (extension to the company standard)

The company standard governs `.md` documents only and is silent on binary
assets. Hivewire's rule:

- All non-document presentation binaries (PNG, SVG, GIF, diagram sources) live
  under **`docs/assets/`**, never in the repo root and never in `docs/` root.
- Filenames are English **kebab-case** (`console-overview.png`,
  `fork-diff.png`), consistent with the document naming rule.
- README and doc images reference them by repo-relative path
  (`docs/assets/...`).

### 4. Local deviations (per company principle #5)

1. **Role folders on demand.** We do not pre-create empty `guides/`,
   `engineering/`, `design/`, `architecture/`, `archive/`. Add them when a real
   document needs them.
2. **`docs/product/` is public here.** The company default marks `product/`
   internal. Hivewire deliberately publishes its moat thesis
   (`benchmark-moat.md`); genuinely sensitive strategy stays in the gitignored
   `private/` directory and is never tracked.
3. **Root non-`.md` files.** Launcher and installer shell scripts
   (`*.sh`, `*.command`) stay at the repo root because they are user-facing entry
   points. The company root rule (§8) governs Markdown only.
4. **Generated / private data is gitignored, not archived.** Benchmark output
   (`co-routing/benchmark/results.jsonl`, `runs/`, `logs/`, `profiles.yaml`) and
   strategy PDFs are local-only; the archiving policy applies to tracked docs
   with historical value, not to generated data.

### 5. Quality gate

Hivewire has no `npm run docs:check`. Before merging a docs change, manually
confirm: English kebab-case filenames, no new doc in repo root or `docs/` root,
assets under `docs/assets/`, and all incoming links updated.

---

## 中文版本

### 1. 採用

Hivewire **採用公司 AI App 檔案命名與歸檔標準**(正本:
`Project-Manager/docs/file-naming-standards.md`,v1.9)。該文件是命名規則、
role-based `docs/` 資料夾、歸檔流程的 single source of truth。本文件只記錄
**Hivewire 特有**的部分:實際開了哪些資料夾、公司標準沒涵蓋的一項擴充、以及
刻意的本地偏離。

Hivewire 原本不在公司標準的 alignment scope(Project Manager / SayDo);本文件
就是「明確決定把它對齊」的紀錄。

### 2. 本地資料夾對應(按需建立)

公司標準定義七個 role 資料夾。Hivewire 還小,**有真正住戶才開**對應資料夾,不
預先鋪整棵空樹。

```text
docs/
├── assets/           # 二進位展示資產(截圖、圖表)              (public)
├── product/          # 產品策略 / moat thesis                     (此處 public,見 §4)
├── project-process/  # backlog、進度、handoff                     (internal)
└── file-naming-standards.md   # 本治理文件(docs root,依公司標準 §5)
```

與程式碼強耦合的工程 contract 放在程式旁:`co-routing/docs/`(例如
`vendor-integration.md`),符合公司標準對 implementation-contract 子資料夾的
允許。

### 3. 資產慣例(對公司標準的擴充)

公司標準只規範 `.md` 文件,沒講二進位資產。Hivewire 規則:

- 所有非文件的展示二進位(PNG、SVG、GIF、圖表原始檔)一律放
  **`docs/assets/`**,不可放 repo root,也不可放 `docs/` root。
- 檔名用英文 **kebab-case**(`console-overview.png`、`fork-diff.png`),與文件
  命名規則一致。
- README 與文件用 repo 相對路徑引用(`docs/assets/...`)。

### 4. 本地偏離(依公司原則 #5)

1. **role 資料夾按需建立。** 不預建空的 `guides/`、`engineering/`、`design/`、
   `architecture/`、`archive/`,有真文件再開。
2. **此處 `docs/product/` 是 public。** 公司預設把 `product/` 標 internal;
   Hivewire 刻意公開它的 moat thesis(`benchmark-moat.md`),真正敏感的策略放在
   gitignored 的 `private/`,永不進 git。
3. **root 的非 `.md` 檔。** launcher / installer shell scripts(`*.sh`、
   `*.command`)留在 repo root,因為它們是使用者入口;公司 root 規則(§8)只管
   Markdown。
4. **generated / private 資料是 gitignored,不是歸檔。** Benchmark 產物
   (`co-routing/benchmark/results.jsonl`、`runs/`、`logs/`、`profiles.yaml`)與
   策略 PDF 都只在本地;歸檔規則只適用「有歷史價值的 tracked 文件」,不適用
   generated data。

### 5. 品質檢查

Hivewire 沒有 `npm run docs:check`。Docs change 合併前,人工確認:英文
kebab-case 檔名、沒有新文件落在 repo root 或 `docs/` root、資產都在
`docs/assets/`、所有 incoming link 都更新了。
