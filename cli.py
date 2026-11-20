"""Interactive local two-player Tic-Tac-Toe."""

from game import Game


def render_board(board):
    """Show position numbers in empty cells so players can choose a move."""
    cells = [str(i + 1) if cell is None else cell for i, cell in enumerate(board)]
    return "\n---+---+---\n".join(
        " " + " | ".join(cells[i:i + 3]) + " " for i in (0, 3, 6)
    )


def run(input_fn=None, output_fn=None):
    """Run complete rounds; injectable I/O supports automated flow tests."""
    read = input if input_fn is None else input_fn
    write = print if output_fn is None else output_fn
    write("井字棋 Tic-Tac-Toe：雙人對戰，X 先手。格子由左至右、由上至下編號 1–9。")
    try:
        while True:
            game = Game()
            write(render_board(game.board))
            while not game.is_over:
                raw = read(f"輪到 {game.current_player}，請輸入格子 1–9：")
                try:
                    position = int(raw)
                except ValueError:
                    write("請輸入 1–9 的整數。")
                    continue
                try:
                    game.play(position)
                except ValueError:
                    if not 1 <= position <= 9:
                        write("格子超出範圍，請輸入 1–9。")
                    else:
                        write("該格已有棋子，請選擇空格。")
                    continue
                write(render_board(game.board))
            write(f"{game.winner} 獲勝！" if game.winner else "平手（Draw）！")
            while True:
                answer = read("再玩一局？(y/n)：").strip().lower()
                if answer in ("y", "yes", "是"):
                    break
                if answer in ("n", "no", "否"):
                    write("謝謝遊玩！")
                    return
                write("請輸入 y 或 n。")
    except (EOFError, KeyboardInterrupt):
        write("\n遊戲已結束。")


if __name__ == "__main__":
    run()
