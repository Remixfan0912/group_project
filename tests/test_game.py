import itertools
import unittest

from game import Game


class GameTests(unittest.TestCase):
    def play_game(self, moves):
        game = Game()
        for move in moves:
            game.play(move)
        return game

    def test_initial_state(self):
        game = Game()
        self.assertEqual(game.board, (None,) * 9)
        self.assertEqual(game.current_player, "X")
        self.assertEqual(game.available_moves, tuple(range(1, 10)))
        self.assertIsNone(game.winner)
        self.assertFalse(game.is_draw)
        self.assertFalse(game.is_over)

    def test_legal_moves_alternate_and_snapshot_is_immutable(self):
        game = Game()
        snapshot = game.board
        game.play(1)
        self.assertEqual(game.current_player, "O")
        game.play(9)
        self.assertEqual(game.board[0], "X")
        self.assertEqual(game.board[8], "O")
        self.assertEqual(game.current_player, "X")
        self.assertEqual(snapshot, (None,) * 9)
        self.assertEqual(game.available_moves, tuple(range(2, 9)))

    def test_invalid_positions_preserve_state_and_turn(self):
        for position in (-1, 0, 10, 1.0, "1", "abc", None, True, False):
            with self.subTest(position=position):
                game = self.play_game([5])
                before = game.board
                with self.assertRaisesRegex(ValueError, "integer from 1 to 9"):
                    game.play(position)
                self.assertEqual(game.board, before)
                self.assertEqual(game.current_player, "O")

    def test_occupied_position_can_be_retried(self):
        game = self.play_game([5])
        with self.assertRaisesRegex(ValueError, "occupied"):
            game.play(5)
        self.assertEqual(game.current_player, "O")
        game.play(1)
        self.assertEqual(game.board[0], "O")

    def test_every_winning_line_for_both_players(self):
        lines = ((1, 2, 3), (4, 5, 6), (7, 8, 9),
                 (1, 4, 7), (2, 5, 8), (3, 6, 9),
                 (1, 5, 9), (3, 5, 7))
        for line in lines:
            others = [p for p in range(1, 10) if p not in line]
            for player in ("X", "O"):
                with self.subTest(line=line, player=player):
                    if player == "X":
                        moves = [line[0], others[0], line[1], others[1], line[2]]
                    else:
                        # Choose X's three filler cells without completing a line.
                        fillers = next(c for c in itertools.combinations(others, 3)
                                       if not any(set(w).issubset(c) for w in lines))
                        moves = [fillers[0], line[0], fillers[1], line[1], fillers[2], line[2]]
                    game = self.play_game(moves)
                    self.assertEqual(game.winner, player)
                    self.assertTrue(game.is_over)
                    self.assertFalse(game.is_draw)
                    self.assertEqual(game.current_player, player)
                    self.assertEqual(game.available_moves, ())

    def test_full_game_draw(self):
        game = self.play_game([1, 2, 3, 5, 4, 6, 8, 7, 9])
        self.assertIsNone(game.winner)
        self.assertTrue(game.is_draw)
        self.assertTrue(game.is_over)
        self.assertEqual(game.available_moves, ())

    def test_ninth_move_win_is_not_draw(self):
        game = self.play_game([1, 2, 5, 3, 6, 4, 7, 8, 9])
        self.assertEqual(game.winner, "X")
        self.assertFalse(game.is_draw)

    def test_no_moves_after_win_or_draw(self):
        for moves, position in (([1, 4, 2, 5, 3], 9),
                                ([1, 2, 3, 5, 4, 6, 8, 7, 9], 1)):
            game = self.play_game(moves)
            before = game.board
            with self.assertRaisesRegex(ValueError, "game is over"):
                game.play(position)
            self.assertEqual(game.board, before)

    def test_new_game_has_independent_state(self):
        first = self.play_game([1, 4, 2, 5, 3])
        second = Game()
        self.assertTrue(first.is_over)
        self.assertEqual(second.board, (None,) * 9)
        self.assertEqual(second.current_player, "X")


if __name__ == "__main__":
    unittest.main()
