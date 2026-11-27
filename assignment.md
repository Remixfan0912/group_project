# Project Assignment: Pretty Sequence Diagrams Generator

## 1. Project Overview & Goal
本小組（3 人 + 3 AI Agents）負責期末專題七大任務之一的 **Pretty Sequence Diagrams**。
核心目標是建立一個自動化編譯與視覺化管線（Pipeline），將基於 **Structure-Behavior Coalescence (SBC)** 理論的 **修訂版行程代數（Revised Process Algebra）** 與 **受保護交互表（Guarded Interaction Table, GIT）**，轉換為乾淨、美觀、防重疊且完全符合 UML/SysML 標準的 **Sequence Diagrams（循序圖）**。

* **競爭與合併機制**：多個小組正平行開發同一任務，第二輪將進行跨組評比並合併最佳方案。因此我們的產出必須具備極高的語法涵蓋率、視覺美觀度與完整的使用說明文件。
* **協作規範**：所有進度、分支與任務同步必須透過課程開發的 client 軟體（`groupctl` / `person_client`）進行，並妥善分配 AI 用量（避開 5 小時與 7 天 Rate Limit）。

---

## 2. System Architecture (Pipeline)
系統採用類似編譯器的三階段管線設計，透過標準化的中間 JSON 格式解耦前後端：

```text
[Process Algebra String] + [8-Field GIT]
                  │
                  ▼  (Module 1: Parser / AST Builder)
    [Intermediate AST & Lifelines JSON]
                  │
                  ▼  (Module 2: Layout & Pretty Renderer)
    [PlantUML / Mermaid DSL 或客製化 SVG]
                  │
                  ▼
     [High-Quality Sequence Diagram]
```

---

## 3. Input Specifications (輸入規格)

### A. Revised Process Algebra Grammar (修訂版行程代數語法)
解析器必須完整支援以下 BNF 語法規則，不可遺漏循序圖特有的時序與複合片段語意：

* **基礎運算子**：
  * **嚴格順序（Strict Sequencing）**：`>>`、`.`、`strict`（前一動作完全結束，後一動作才能開始）
  * **寬鬆順序（Weak Sequencing）**：`seq`（僅維持同一 Lifeline 上的局部順序，允許不同 Lifeline 的獨立事件在視覺上交錯）
  * **條件分支與平行**：`alt`、`par`
  * **終止與延續**：`0`、`◉`、`C`、`©`
  * **模組引用與事件**：`ref A`、`raise[name]`
* **複合片段（Combined Fragments, `CFtype`）**：
  * 語法格式：`s ::= '(' CFtype ':' expr ')'`
  * 必須支援類型：`neg`、`critical`、`opt[cond]`、`break[cond]`、`assert[cond]`、`ignore[i, ...]`、`consider[i, ...]`、`loop(min, max)[cond]`
* **屬性括號與跨圖相容語法**：
  * 語法格式：`s ::= '(' { '[' attribs ']:' }? expr ')'`
  * 需能安全解析（或優雅降級呈現）來自狀態機或活動圖的屬性，如 `SMDattrib`（`defer`、`invariant`）、`ADattrib`（`swimlanes`、`inlane`、`interrupt`、`catch`、`activityFinal`）、`fork`、`join` 與 `pseudo(...)`。

### B. Guarded Interaction Table (GIT 8 欄位結構)
每個原子交互動作 $i$ 對應 GIT 中的一筆定義：
$$i = (C, \Xi, N, \Gamma, \Lambda, \Theta_{in}, \Theta_{out}, \Pi)$$

* $C$：Guard condition（觸發條件，需顯示為 `[C]`）
* $\Xi$：Caller（呼叫者元件 $\rightarrow$ 對應圖上的來源 Lifeline）
* $N$：Nature（互動性質：`call` 實線箭頭、`return` 虛線返回箭頭，或 `combined`）
* $\Gamma$：Callee（接收者元件 $\rightarrow$ 對應圖上的目標 Lifeline）
* $\Lambda$：Operation（呼叫的方法名稱）
* $\Theta_{in}$ / $\Theta_{out}$：輸入與輸出參數
* $\Pi$：Transition actions / code（附帶動作）

---

## 4. "Pretty" Visual Requirements (美觀與排版標準)
生成的循序圖必須達成以下視覺標準，才能在第二輪評比中勝出：

1. **生命線（Lifelines）最佳化排列**：根據 GIT 的 $\Xi$ 與 $\Gamma$ 自動建立生命線，並依呼叫關係由左至右合理排序，減少箭頭交叉。
2. **動態間距計算（防重疊）**：依據 `[Guard] method(in): out` 標籤長度自動調整相鄰 Lifeline 之間的水平間距，確保文字絕不重疊或截斷。
3. **完整的複合片段框線（Nested Frames）**：正確繪製多層嵌套的 `alt`、`opt`、`par`、`loop`、`critical`、`neg`、`assert`、`break` 方框，包含分區虛線與左上角條件標籤。
4. **激活條（Activation Bars）**：在呼叫與返回期間自動於接收者生命線上繪製執行矩形（Execution Specification）。
5. **嚴格 vs. 寬鬆時序區分**：明確區分 `strict` 區塊與 `seq` 寬鬆順序的視覺呈現。
6. **高質感輸出**：優先採用 `AST` $\rightarrow$ `PlantUML / Mermaid DSL`（搭配客製化美化主題 `skinparam` / `CSS`）輸出高解析度 SVG 與 PNG。

---

## 5. Team Division of Labor (3 人 + 3 AI 分工)

| 角色 | 負責模組 | 核心產出檔案 | 職責說明 |
| :--- | :--- | :--- | :--- |
| **成員 1（翻譯官）** | Parser & AST Builder | `parser.py`、`schema.json` | 實作遞迴下降解析器，將 Process Algebra 字串與 GIT 表格轉換為標準化、嵌套的 JSON 語法樹（AST）。 |
| **成員 2（小畫家）** | Pretty Renderer | `renderer.py`、`theme.puml` | 讀取標準化 JSON，生成具備美化樣式（配色、間距、Activation Bar、Combined Fragments）的繪圖腳本並匯出 SVG/PNG。 |
| **成員 3（品管員）** | Test Suite & Docs | `test_cases/`、`main.py`、`README.md` | 設計多層嵌套與邊界測試案例（Test Cases），串接前後端管線，並撰寫圖文並茂的展示與說明文件。 |

---

## 6. Agent Execution Guidelines (給 AI Agent 的執行守則)
1. **介面契約優先**：在撰寫程式碼前，先確認 `parser.py` 輸出與 `renderer.py` 輸入的 JSON Schema 完全一致。
2. **模組化與零依賴優先**：核心解析邏輯盡量使用 Python 標準函式庫（`re`、`json`、`dataclasses`），降低環境部署門檻。
3. **漸進式開發**：每次對話聚焦於單一模組或特定語法規則的實作與驗證，避免單次生成過長代碼導致上下文混亂或觸發 Token 限制。
