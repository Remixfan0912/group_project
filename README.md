# 井字棋 Tic-Tac-Toe

使用 Python 3.10 以上版本，無第三方套件需求。

## 執行

```sh
python main.py
```

也可以執行 `python -m cli`。Windows 若使用 Python Launcher，將 `python` 改為 `py`。

兩位玩家共用終端機，X 先手，O 後手。輸入 1–9 選擇格子：

```text
 1 | 2 | 3
---+---+---
 4 | 5 | 6
---+---+---
 7 | 8 | 9
```

連成橫、直或對角線的三子即獲勝；滿盤無勝者則平手。
無效輸入或重複落子會提示並讓同一位玩家重試。
每局結束輸入 `y` 再玩、`n` 離開；Ctrl+C 或輸入結束（EOF）也可離開。
本版本提供本地雙人對戰；選配的 AI 對手未實作。

## 測試

```sh
python -m unittest discover -s tests -v
```

測試涵蓋核心狀態、雙方八種勝利線、平手、非法落子、完整 CLI 對戰、
輸入重試、重玩及程式進入點。

## 模組

- `game.py`：純遊戲規則。`Game.play(position)` 接受 1–9 整數；非法落子拋出
  `ValueError` 且不改變狀態。`board` 是九格不可變快照，空格為 `None`。
- `cli.py`：棋盤顯示、輸入處理及重玩流程。
- `main.py`：啟動程式。
- `tests/`：Python `unittest` 測試。

正式需求見 [assignment.md](assignment.md)，協作流程見 [AGENT_COLLABORATION.md](AGENT_COLLABORATION.md)。
