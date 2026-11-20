import subprocess
import sys
import unittest
from pathlib import Path

from cli import render_board, run


class CliTests(unittest.TestCase):
    def run_script(self, answers):
        answers = iter(answers)
        prompts, output = [], []

        def read(prompt):
            prompts.append(prompt)
            try:
                return next(answers)
            except StopIteration:
                raise AssertionError("CLI requested unexpected input") from None

        run(read, output.append)
        return prompts, output

    def test_numbered_board_and_marks(self):
        board = render_board(("X", "O") + (None,) * 7)
        self.assertEqual(board, " X | O | 3 \n---+---+---\n 4 | 5 | 6 \n---+---+---\n 7 | 8 | 9 ")

    def test_complete_win_and_final_board(self):
        prompts, output = self.run_script(["1", "4", "2", "5", "3", "n"])
        self.assertEqual([p[3] for p in prompts[:-1]], list("XOXOX"))
        self.assertIn(" X | X | X ", output[-3])
        self.assertEqual(output[-2:], ["X 獲勝！", "謝謝遊玩！"])

    def test_errors_retry_same_player(self):
        prompts, output = self.run_script(
            ["abc", "1.5", "0", "10", "1", "1", "4", "2", "5", "3", "n"]
        )
        self.assertTrue(all("輪到 X" in p for p in prompts[:5]))
        self.assertTrue(all("輪到 O" in p for p in prompts[5:7]))
        self.assertEqual(output.count("請輸入 1–9 的整數。"), 2)
        self.assertEqual(output.count("格子超出範圍，請輸入 1–9。"), 2)
        self.assertIn("該格已有棋子，請選擇空格。", output)

    def test_draw_then_replay_resets_board_and_first_player(self):
        prompts, output = self.run_script(
            ["1", "2", "3", "5", "4", "6", "8", "7", "9", "maybe", " Y ",
             "1", "4", "2", "5", "3", "no"]
        )
        self.assertIn("平手（Draw）！", output)
        self.assertIn("請輸入 y 或 n。", output)
        self.assertEqual(output.count(render_board((None,) * 9)), 2)
        self.assertIn("輪到 X", prompts[11])
        self.assertIn("X 獲勝！", output)

    def test_eof_and_interrupt_exit_during_move_or_replay(self):
        for exception in (EOFError, KeyboardInterrupt):
            for prefix in ([], ["1", "4", "2", "5", "3"]):
                with self.subTest(exception=exception, prefix=prefix):
                    answers = iter(prefix)
                    output = []

                    def read(prompt):
                        try:
                            return next(answers)
                        except StopIteration:
                            raise exception from None

                    run(read, output.append)
                    self.assertEqual(output[-1], "\n遊戲已結束。")

    def test_main_entrypoint_complete_game(self):
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "main.py"],
            input="1\n4\n2\n5\n3\nn\n", capture_output=True,
            encoding="utf-8", cwd=Path(__file__).resolve().parents[1], timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("X 獲勝！", result.stdout)
        self.assertIn("謝謝遊玩！", result.stdout)


if __name__ == "__main__":
    unittest.main()
