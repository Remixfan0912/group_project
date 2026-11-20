"""Pure Tic-Tac-Toe rules, using positions 1 through 9 in row-major order."""


class Game:
    """A new game starts with X. Invalid moves leave all state unchanged.

    ``board`` is an immutable snapshot of nine cells (None, 'X', or 'O').
    ``play(position)`` accepts integers only and raises ValueError for illegal
    moves. After a terminal move, current_player remains the last mover.
    """

    WINNING_LINES = (
        (0, 1, 2), (3, 4, 5), (6, 7, 8),
        (0, 3, 6), (1, 4, 7), (2, 5, 8),
        (0, 4, 8), (2, 4, 6),
    )

    def __init__(self):
        self._board = [None] * 9
        self._current_player = "X"

    @property
    def board(self):
        return tuple(self._board)

    @property
    def current_player(self):
        return self._current_player

    @property
    def winner(self):
        for a, b, c in self.WINNING_LINES:
            if self._board[a] is not None and self._board[a] == self._board[b] == self._board[c]:
                return self._board[a]
        return None

    @property
    def is_draw(self):
        return self.winner is None and all(cell is not None for cell in self._board)

    @property
    def is_over(self):
        return self.winner is not None or self.is_draw

    @property
    def available_moves(self):
        if self.is_over:
            return ()
        return tuple(i + 1 for i, cell in enumerate(self._board) if cell is None)

    def play(self, position):
        if type(position) is not int or not 1 <= position <= 9:
            raise ValueError("Position must be an integer from 1 to 9.")
        if self.is_over:
            raise ValueError("The game is over. Start a new game.")
        if self._board[position - 1] is not None:
            raise ValueError("That position is already occupied.")
        self._board[position - 1] = self._current_player
        if not self.is_over:
            self._current_player = "O" if self._current_player == "X" else "X"
