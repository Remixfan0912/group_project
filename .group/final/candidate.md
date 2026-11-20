# Group Final Report

## Assignment
﻿# 小組專案需求：Tic-Tac-Toe（井字棋）遊戲

## 1. 專案目標
使用 Python 實作一個可執行的 **Tic-Tac-Toe（井字棋）** 雙人／人機對戰遊戲，並具備清晰的模組分工與完整的自動化單元測試（`unittest`）。

## 2. 功能需求
1. **棋盤與遊戲狀態管理**
   - 支援標準 3×3 棋盤，格子編號為 `1`–`9`（或 `(row, col)` 座標，需在介面中清楚提示）。
   - 輪流落子：預設 `X` 先手、`O` 後手。
   - 輸入驗證：不可落子在已有棋子的位置、不可輸入超出範圍或非數字的座標；輸入錯誤時須給出明確提示並讓同一位玩家重新輸入，不得直接崩潰。
2. **勝負與平手判定**
   - 任一方在橫列、直行或兩條對角線連成三子時立即判定勝出並結束該局。
   - 棋盤 9 格全滿且無人連成三子時判定為平手（Draw）。
3. **遊戲流程與介面（CLI）**
   - 清楚印出目前 3×3 棋盤狀態與輪到哪一位玩家。
   - 提供雙人本地對戰（Player vs Player），並可選支援簡易電腦對手（Player vs AI）。
   - 單局結束後顯示最終棋盤與結果（勝者或平手），並詢問是否再玩一局。

## 3. 建議模組結構與分工
- **遊戲核心邏輯（例如 `game.py` / `board.py`）**：棋盤資料結構、合法步數檢查、落子、勝負／平手判定（純邏輯，不綁定 `input()`/`print()`，方便測試）。
- **使用者介面與主程式（例如 `cli.py` / `main.py`）**：顯示棋盤、讀取與驗證玩家輸入、控制遊戲迴圈。
- **測試套件（`tests/`）**：使用 Python 內建 `unittest` 驗證核心邏輯與邊界情況。

## 4. 驗收與測試標準
- 執行 `python -m unittest discover -s tests -v` 必須全數通過，不可有失敗或全部跳過。
- 測試需涵蓋：
  - 初始空棋盤與合法落子
  - 重複落子與非法座標的防呆處理
  - 橫、直、斜線各種勝利條件判定
  - 滿盤平手判定
  - 完整一局流程模擬
- 程式碼需維持整潔、無未使用的暫存檔，且符合本專案協作流程（透過 `PUB` / `REV` / `INT` / `TEST` 審查與整合後再合併至 `main`）。


## Result
完成 assignment.md 所有必做需求：Python 雙人井字棋、1–9 棋盤、X/O 輪流落子、非法輸入重試、勝負和平手判定、最終棋盤、重玩、CLI 與核心分離、使用說明及 17 項 unittest（含完整 CLI 子程序對戰）。以 python main.py 啟動。

## Canonical Commit
649d3a819fdd62ded01b83929db6f9ec8024f863

## Important Changes
- C-P17-35c5ce44fc: Setup Tic-Tac-Toe assignment, agent instructions, and initial tests (P17)
- C-P18-7e5a20a0a2: Implement pure Tic-Tac-Toe game rules and unit tests (P18)
- C-P18-82d03da86a: Complete two-player CLI, replay flow, documentation and end-to-end tests (P18)

## Validation
Automated checks passed. Evidence: E-20261120T083933Z-P18-296d18f506.
- ["C:\\Users\\潘建宏\\OneDrive\\桌面\\115-1\\AIAP\\yunx\\groupctl-ai-collaboration\\.venv\\Scripts\\python.exe", "-m", "unittest", "discover", "-s", "tests", "-v"]
- Review E-20261120T081750Z-P18-d800d51dc1: accept — Agent self-review: inspected core and tests against assignment. All eight win lines, turn preservation on invalid moves, draw precedence and terminal locking are correct; no existing runtime API to conflict with. CLI is explicitly out of scope.
- Review E-20261120T083832Z-P18-b2748c0d37: accept — Agent self-review: inspected CLI, entrypoint, tests, README and config against assignment. Invalid moves preserve turn; terminal board is printed before result; replay constructs fresh Game; EOF and Ctrl+C exit cleanly. No change to core API. AI is optional and documented.

## Known Limitations
選配 Player vs AI 未實作；本版本為本地雙人對戰。
程式審查由實作代理自我審查，尚無獨立隊友審查或人類遊玩紀錄。

## Unincorporated Changes

## Contributors
- P17
- P18
