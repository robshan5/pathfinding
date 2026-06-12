#!/usr/bin/env python3
"""
Pathfinding Visualiser
======================
Visualises 5 pathfinding algorithms on an interactive grid.

Algorithms:  A*, Dijkstra, BFS, DFS, Greedy Best-First

Controls:
  Left-click / drag   — draw walls (selected tool)
  Right-click / drag  — erase
  Tool buttons        — switch between Wall / Start / End / Erase
  Run                 — start the selected algorithm
  Clear Path          — remove explored/path cells, keep walls
  Clear All           — reset everything
  Maze                — generate a random maze

Requirements: Python 3.8+  (tkinter — included with most Python installs)
Run with:     python pathfinding_visualiser.py

Linux: sudo apt install python3-tk   (if tkinter is missing)
"""

import heapq
import math
import threading
import time
import tkinter as tk
from collections import deque
from tkinter import ttk

# ── Grid constants ────────────────────────────────────────────────────────────
CELL      = 22          # pixels per cell
MIN_COLS  = 20
MIN_ROWS  = 15

# ── Colours ───────────────────────────────────────────────────────────────────
BG          = "#070d1a"
GRID_LINE   = "#0b1828"
COL_EMPTY   = "#070d1a"
COL_WALL    = "#ff3a5c"
COL_WALL_DK = "#cc2040"
COL_START   = "#00ff9d"
COL_END     = "#ff3a5c"
COL_EXPLORED= "#0a3060"
COL_FRONTIER= "#00568a"
COL_PATH    = "#ffaa00"
PANEL_BG    = "#0b1525"
TEXT        = "#8aaccc"
TEXT_BRIGHT = "#c8dff0"
ACCENT      = "#00d4ff"
MUTED       = "#2a4060"

# ── Cell states ───────────────────────────────────────────────────────────────
EMPTY    = 0
WALL     = 1
START    = 2
END      = 3
EXPLORED = 4
FRONTIER = 5
PATH     = 6


# ── Helpers ───────────────────────────────────────────────────────────────────

class Cell:
    __slots__ = ("r", "c", "state", "parent", "g", "f")
    def __init__(self, r, c):
        self.r = r; self.c = c
        self.state = EMPTY
        self.parent = None
        self.g = 0; self.f = 0

    def __lt__(self, other):   # for heapq
        return self.f < other.f


def heuristic(a: Cell, b: Cell) -> int:
    return abs(a.r - b.r) + abs(a.c - b.c)


# ── Visualiser ────────────────────────────────────────────────────────────────

class PathfindingVisualiser:
    def __init__(self, root):
        self.root = root
        self.root.title("Pathfinding Visualiser")
        self.root.configure(bg=PANEL_BG)
        self.root.resizable(True, True)

        self.cols = MIN_COLS
        self.rows = MIN_ROWS
        self.grid: list[list[Cell]] = []
        self.start_cell: Cell | None = None
        self.end_cell:   Cell | None = None

        self._running     = False
        self._stop_flag   = False
        self._paint_state = None   # what we're currently drawing
        self._tool        = tk.StringVar(value="wall")

        self._build_ui()
        self._init_grid()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Toolbar ──
        bar = tk.Frame(self.root, bg=PANEL_BG, pady=8)
        bar.pack(fill=tk.X)

        tk.Label(bar, text="PATH_VIZ", fg=ACCENT, bg=PANEL_BG,
                 font=("Courier", 12, "bold")).pack(side=tk.LEFT, padx=14)

        self._sep(bar)

        tk.Label(bar, text="ALGORITHM", fg=MUTED, bg=PANEL_BG,
                 font=("Courier", 8)).pack(side=tk.LEFT)
        self.algo_var = tk.StringVar(value="A*")
        ttk.Combobox(bar, textvariable=self.algo_var,
                     values=["A*", "Dijkstra", "BFS", "DFS", "Greedy"],
                     state="readonly", width=12,
                     font=("Courier", 9)).pack(side=tk.LEFT, padx=(4, 0))

        self._sep(bar)

        tk.Label(bar, text="SPEED", fg=MUTED, bg=PANEL_BG,
                 font=("Courier", 8)).pack(side=tk.LEFT)
        self.speed_var = tk.StringVar(value="Normal")
        ttk.Combobox(bar, textvariable=self.speed_var,
                     values=["Slow", "Normal", "Fast", "Instant"],
                     state="readonly", width=8,
                     font=("Courier", 9)).pack(side=tk.LEFT, padx=(4, 0))

        self._sep(bar)

        tk.Label(bar, text="DRAW", fg=MUTED, bg=PANEL_BG,
                 font=("Courier", 8)).pack(side=tk.LEFT)
        for label, val in [("WALL","wall"),("START","start"),("END","end"),("ERASE","erase")]:
            rb = tk.Radiobutton(bar, text=label, variable=self._tool, value=val,
                                bg=PANEL_BG, fg=TEXT, selectcolor="#00d4ff",
                                activebackground=PANEL_BG, activeforeground=ACCENT,
                                font=("Courier", 8), indicatoron=False,
                                relief=tk.FLAT, bd=0, padx=8, pady=4,
                                cursor="hand2")
            rb.pack(side=tk.LEFT, padx=2)

        self._sep(bar)

        for txt, cmd in [("MAZE", self._gen_maze),
                         ("CLEAR PATH", self._clear_path),
                         ("CLEAR ALL",  self._clear_all),
                         ("RUN ▶",     self._start)]:
            tk.Button(bar, text=txt, command=cmd,
                      bg="#0a1828" if txt != "RUN ▶" else ACCENT,
                      fg="#000" if txt == "RUN ▶" else TEXT,
                      relief=tk.FLAT, font=("Courier", 9, "bold"),
                      padx=8, pady=4, cursor="hand2").pack(side=tk.LEFT, padx=3)

        # ── Canvas ──
        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0,
                                cursor="crosshair")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>",       self._on_resize)
        self.canvas.bind("<ButtonPress-1>",   self._on_press)
        self.canvas.bind("<B1-Motion>",       self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", lambda e: setattr(self, "_paint_state", None))
        self.canvas.bind("<ButtonPress-3>",   lambda e: self._apply("erase", e))
        self.canvas.bind("<B3-Motion>",       lambda e: self._apply("erase", e))

        # ── Status bar ──
        sbar = tk.Frame(self.root, bg=PANEL_BG, pady=4)
        sbar.pack(fill=tk.X)
        self.status_var   = tk.StringVar(value="READY")
        self.explored_var = tk.StringVar(value="Explored: 0")
        self.path_var     = tk.StringVar(value="Path: —")
        self.time_var     = tk.StringVar(value="Time: —")
        for var in [self.explored_var, self.path_var, self.time_var]:
            tk.Label(sbar, textvariable=var, fg=MUTED, bg=PANEL_BG,
                     font=("Courier", 8)).pack(side=tk.LEFT, padx=12)
        tk.Label(sbar, textvariable=self.status_var, fg=ACCENT, bg=PANEL_BG,
                 font=("Courier", 8, "bold")).pack(side=tk.RIGHT, padx=12)

    def _sep(self, parent):
        tk.Frame(parent, bg=MUTED, width=1, height=22).pack(
            side=tk.LEFT, padx=10)

    # ── Grid init ─────────────────────────────────────────────────────────────

    def _on_resize(self, event):
        new_cols = max(MIN_COLS, event.width  // CELL)
        new_rows = max(MIN_ROWS, event.height // CELL)
        if new_cols != self.cols or new_rows != self.rows:
            self.cols = new_cols
            self.rows = new_rows
            self._init_grid()
        else:
            self._render()

    def _init_grid(self):
        self.grid = [[Cell(r, c) for c in range(self.cols)]
                     for r in range(self.rows)]
        mid_r = self.rows // 2
        self.start_cell = self.grid[mid_r][int(self.cols * 0.15)]
        self.end_cell   = self.grid[mid_r][int(self.cols * 0.85)]
        self.start_cell.state = START
        self.end_cell.state   = END
        self._update_stats(0, None, None)
        self.status_var.set("READY")
        self._render()

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _render(self):
        c = self.canvas
        c.delete("all")
        W = int(c.winfo_width())
        H = int(c.winfo_height())
        if W < 10 or H < 10:
            return

        # Background
        c.create_rectangle(0, 0, W, H, fill=BG, outline="")

        # Grid lines
        for col in range(0, self.cols + 1):
            x = col * CELL
            c.create_line(x, 0, x, H, fill=GRID_LINE)
        for row in range(0, self.rows + 1):
            y = row * CELL
            c.create_line(0, y, W, y, fill=GRID_LINE)

        # Cells
        for row in self.grid:
            for cell in row:
                self._draw_cell(cell)

    def _draw_cell(self, cell):
        c = self.canvas
        x0 = cell.c * CELL
        y0 = cell.r * CELL
        x1 = x0 + CELL
        y1 = y0 + CELL

        s = cell.state
        if s == EMPTY:
            return
        elif s == WALL:
            c.create_rectangle(x0, y0, x1, y1, fill=COL_WALL, outline="")
            c.create_rectangle(x0+1, y0+1, x1-1, y1-1, fill=COL_WALL_DK, outline="")
        elif s == START:
            c.create_rectangle(x0+2, y0+2, x1-2, y1-2, fill=COL_START, outline="")
            cx, cy = x0 + CELL//2, y0 + CELL//2
            c.create_oval(cx-3, cy-3, cx+3, cy+3, fill="#003322", outline="")
        elif s == END:
            c.create_rectangle(x0+2, y0+2, x1-2, y1-2, fill=COL_END, outline="")
            cx, cy = x0 + CELL//2, y0 + CELL//2
            c.create_oval(cx-3, cy-3, cx+3, cy+3, fill="#330011", outline="")
        elif s == EXPLORED:
            c.create_rectangle(x0+1, y0+1, x1-1, y1-1, fill=COL_EXPLORED, outline="")
        elif s == FRONTIER:
            c.create_rectangle(x0+1, y0+1, x1-1, y1-1, fill=COL_FRONTIER, outline="")
        elif s == PATH:
            c.create_rectangle(x0+3, y0+3, x1-3, y1-3, fill=COL_PATH, outline="")

    def _redraw_cell(self, cell):
        """Redraw a single cell (faster than full render during animation)."""
        x0 = cell.c * CELL; y0 = cell.r * CELL
        x1 = x0 + CELL;     y1 = y0 + CELL
        self.canvas.delete(f"cell_{cell.r}_{cell.c}")
        # Clear cell background
        self.canvas.create_rectangle(x0, y0, x1, y1, fill=BG, outline=GRID_LINE,
                                     tags=f"cell_{cell.r}_{cell.c}")
        s = cell.state
        if s == WALL:
            self.canvas.create_rectangle(x0, y0, x1, y1, fill=COL_WALL, outline="",
                                         tags=f"cell_{cell.r}_{cell.c}")
            self.canvas.create_rectangle(x0+1, y0+1, x1-1, y1-1,
                                         fill=COL_WALL_DK, outline="",
                                         tags=f"cell_{cell.r}_{cell.c}")
        elif s == EXPLORED:
            self.canvas.create_rectangle(x0+1, y0+1, x1-1, y1-1,
                                         fill=COL_EXPLORED, outline="",
                                         tags=f"cell_{cell.r}_{cell.c}")
        elif s == FRONTIER:
            self.canvas.create_rectangle(x0+1, y0+1, x1-1, y1-1,
                                         fill=COL_FRONTIER, outline="",
                                         tags=f"cell_{cell.r}_{cell.c}")
        elif s == PATH:
            self.canvas.create_rectangle(x0+3, y0+3, x1-3, y1-3,
                                         fill=COL_PATH, outline="",
                                         tags=f"cell_{cell.r}_{cell.c}")
        elif s == START:
            self.canvas.create_rectangle(x0+2, y0+2, x1-2, y1-2,
                                         fill=COL_START, outline="",
                                         tags=f"cell_{cell.r}_{cell.c}")
        elif s == END:
            self.canvas.create_rectangle(x0+2, y0+2, x1-2, y1-2,
                                         fill=COL_END, outline="",
                                         tags=f"cell_{cell.r}_{cell.c}")

    # ── Drawing interaction ───────────────────────────────────────────────────

    def _cell_at(self, event):
        c = max(0, min(self.cols - 1, event.x // CELL))
        r = max(0, min(self.rows - 1, event.y // CELL))
        return self.grid[r][c]

    def _on_press(self, event):
        if self._running:
            return
        cell = self._cell_at(event)
        self._paint_state = self._tool.get()
        self._apply(self._paint_state, event, cell)

    def _on_drag(self, event):
        if self._running or self._paint_state is None:
            return
        self._apply(self._paint_state, event)

    def _apply(self, tool, event, cell=None):
        cell = cell or self._cell_at(event)
        if tool == "wall":
            if cell not in (self.start_cell, self.end_cell):
                if cell.state in (EMPTY, EXPLORED, FRONTIER, PATH):
                    cell.state = WALL
                    self._redraw_cell(cell)
        elif tool == "erase":
            if cell not in (self.start_cell, self.end_cell):
                if cell.state != EMPTY:
                    cell.state = EMPTY
                    self._redraw_cell(cell)
        elif tool == "start":
            old = self.start_cell
            old.state = EMPTY; self._redraw_cell(old)
            self.start_cell = cell
            cell.state = START; self._redraw_cell(cell)
        elif tool == "end":
            old = self.end_cell
            old.state = EMPTY; self._redraw_cell(old)
            self.end_cell = cell
            cell.state = END; self._redraw_cell(cell)

    # ── Clear ─────────────────────────────────────────────────────────────────

    def _clear_path(self):
        if self._running:
            return
        for row in self.grid:
            for cell in row:
                if cell.state in (EXPLORED, FRONTIER, PATH):
                    cell.state = EMPTY
                cell.parent = None; cell.g = 0; cell.f = 0
        self._update_stats(0, None, None)
        self.status_var.set("READY")
        self._render()

    def _clear_all(self):
        self._stop_flag = True
        self._running   = False
        self._init_grid()

    # ── Maze generation (recursive division) ──────────────────────────────────

    def _gen_maze(self):
        """Randomised Prim's algorithm — guarantees a perfect maze (always solvable)."""
        if self._running:
            return
        self._clear_all()
        import random

        # Fill everything with walls
        for row in self.grid:
            for cell in row:
                if cell not in (self.start_cell, self.end_cell):
                    cell.state = WALL

        def neighbours2(r, c):
            """Cells exactly 2 steps away (potential passage targets)."""
            for dr, dc in [(-2,0),(2,0),(0,-2),(0,2)]:
                nr, nc = r+dr, c+dc
                if 1 <= nr < self.rows-1 and 1 <= nc < self.cols-1:
                    yield nr, nc

        def carve(r, c):
            """Mark cell as passage."""
            cell = self.grid[r][c]
            if cell not in (self.start_cell, self.end_cell):
                cell.state = EMPTY

        # Start Prim's from the start cell's position, snapped to odd coords
        sr = self.start_cell.r | 1   # nearest odd row
        sc = self.start_cell.c | 1   # nearest odd col
        sr = max(1, min(self.rows-2, sr))
        sc = max(1, min(self.cols-2, sc))
        carve(sr, sc)

        # Frontier: set of walls adjacent to carved cells
        frontier = set()
        for nr, nc in neighbours2(sr, sc):
            frontier.add((nr, nc))

        while frontier:
            # Pick a random frontier cell
            fr, fc = random.choice(list(frontier))
            frontier.discard((fr, fc))

            # Find carved neighbours (2 steps away)
            carved_neighbours = [
                (nr, nc) for nr, nc in neighbours2(fr, fc)
                if self.grid[nr][nc].state in (EMPTY, START, END)
            ]
            if carved_neighbours:
                # Connect to one of them by carving the cell between
                nr, nc = random.choice(carved_neighbours)
                mid_r, mid_c = (fr+nr)//2, (fc+nc)//2
                carve(fr, fc)
                carve(mid_r, mid_c)
                # Add new frontier cells
                for nnr, nnc in neighbours2(fr, fc):
                    if self.grid[nnr][nnc].state == WALL:
                        frontier.add((nnr, nnc))

        # Restore start/end markers (carving may have overwritten them)
        self.start_cell.state = START
        self.end_cell.state   = END

        # Carve the cells immediately around start and end so they're never sealed
        for cell, dr, dc in [(self.start_cell, 0, 1), (self.start_cell, 0, -1),
                              (self.end_cell,   0, 1), (self.end_cell,   0, -1),
                              (self.start_cell, 1, 0), (self.start_cell,-1, 0),
                              (self.end_cell,   1, 0), (self.end_cell,  -1, 0)]:
            nr, nc = cell.r + dr, cell.c + dc
            if 0 <= nr < self.rows and 0 <= nc < self.cols:
                nb = self.grid[nr][nc]
                if nb not in (self.start_cell, self.end_cell):
                    nb.state = EMPTY

        self._render()

    # ── Stats ─────────────────────────────────────────────────────────────────

    def _update_stats(self, explored, path_len, elapsed):
        self.explored_var.set(f"Explored: {explored:,}")
        self.path_var.set(f"Path: {path_len if path_len else '—'}")
        self.time_var.set(f"Time: {elapsed:.1f}ms" if elapsed is not None else "Time: —")

    # ── Neighbours ────────────────────────────────────────────────────────────

    def _neighbours(self, cell: Cell):
        for dr, dc in [(-1,0),(1,0),(0,-1),(0,1)]:
            nr, nc = cell.r + dr, cell.c + dc
            if 0 <= nr < self.rows and 0 <= nc < self.cols:
                nb = self.grid[nr][nc]
                if nb.state != WALL:
                    yield nb

    # ── Algorithm generators ──────────────────────────────────────────────────

    def _astar(self, start, end):
        open_set = [start]
        in_open  = {start}
        closed   = set()
        start.g  = 0
        start.f  = heuristic(start, end)
        while open_set:
            cur = heapq.heappop(open_set)
            in_open.discard(cur)
            if cur is end:
                yield True, cur, set(), closed
                return
            closed.add(cur)
            for nb in self._neighbours(cur):
                if nb in closed:
                    continue
                g = cur.g + 1
                if nb not in in_open or g < nb.g:
                    nb.parent = cur; nb.g = g
                    nb.f = g + heuristic(nb, end)
                    heapq.heappush(open_set, nb)
                    in_open.add(nb)
            yield False, cur, in_open, closed
        yield True, None, set(), closed

    def _dijkstra(self, start, end):
        for row in self.grid:
            for cell in row:
                cell.g = math.inf
        start.g  = 0
        start.f  = 0
        open_set = [start]
        in_open  = {start}
        closed   = set()
        while open_set:
            cur = heapq.heappop(open_set)
            in_open.discard(cur)
            if cur is end:
                yield True, cur, set(), closed
                return
            if cur in closed:
                continue
            closed.add(cur)
            for nb in self._neighbours(cur):
                g = cur.g + 1
                if g < nb.g:
                    nb.g = g; nb.f = g; nb.parent = cur
                    heapq.heappush(open_set, nb)
                    in_open.add(nb)
            yield False, cur, in_open, closed
        yield True, None, set(), closed

    def _bfs(self, start, end):
        queue   = deque([start])
        visited = {start}
        while queue:
            cur = queue.popleft()
            if cur is end:
                yield True, cur, set(queue), visited
                return
            for nb in self._neighbours(cur):
                if nb not in visited:
                    visited.add(nb); nb.parent = cur
                    queue.append(nb)
            yield False, cur, set(queue), visited
        yield True, None, set(), set()

    def _dfs(self, start, end):
        stack   = [start]
        visited = {start}
        while stack:
            cur = stack.pop()
            if cur is end:
                yield True, cur, set(stack), visited
                return
            for nb in self._neighbours(cur):
                if nb not in visited:
                    visited.add(nb); nb.parent = cur
                    stack.append(nb)
            yield False, cur, set(stack), visited
        yield True, None, set(), set()

    def _greedy(self, start, end):
        start.f  = heuristic(start, end)
        open_set = [start]
        in_open  = {start}
        closed   = set()
        while open_set:
            cur = heapq.heappop(open_set)
            in_open.discard(cur)
            if cur is end:
                yield True, cur, set(), closed
                return
            closed.add(cur)
            for nb in self._neighbours(cur):
                if nb not in closed and nb not in in_open:
                    nb.parent = cur; nb.f = heuristic(nb, end)
                    heapq.heappush(open_set, nb)
                    in_open.add(nb)
            yield False, cur, in_open, closed
        yield True, None, set(), closed

    # ── Run ───────────────────────────────────────────────────────────────────

    def _start(self):
        if self._running:
            return
        self._clear_path()
        self._running   = True
        self._stop_flag = False

        algo = self.algo_var.get()
        gens = {"A*": self._astar, "Dijkstra": self._dijkstra,
                "BFS": self._bfs,  "DFS": self._dfs, "Greedy": self._greedy}
        gen = gens[algo](self.start_cell, self.end_cell)

        speed  = self.speed_var.get()
        delays = {"Slow": 30, "Normal": 8, "Fast": 1, "Instant": 0}
        delay  = delays[speed]

        explored_count = [0]
        t0 = [time.perf_counter()]
        self.status_var.set(f"{algo.upper()} RUNNING...")

        def tick():
            if self._stop_flag:
                self._running = False
                return

            batch = 1 if delay > 1 else (30 if delay == 0 else 8)
            for _ in range(batch):
                try:
                    done, cur, frontier, closed = next(gen)
                except StopIteration:
                    self._running = False
                    return

                if done:
                    elapsed = (time.perf_counter() - t0[0]) * 1000
                    if cur:
                        path = []; node = cur
                        while node:
                            path.append(node); node = node.parent
                        path.reverse()
                        for cell in path:
                            if cell not in (self.start_cell, self.end_cell):
                                cell.state = PATH
                        self._render()
                        self._update_stats(explored_count[0], len(path), elapsed)
                        self.status_var.set(f"PATH FOUND — {len(path)} steps")
                    else:
                        self._render()
                        self._update_stats(explored_count[0], None, elapsed)
                        self.status_var.set("NO PATH EXISTS")
                    self._running = False
                    return

                if cur not in (self.start_cell, self.end_cell):
                    cur.state = EXPLORED
                    explored_count[0] += 1
                    self._redraw_cell(cur)

                for nb in frontier:
                    if nb not in (self.start_cell, self.end_cell) and nb.state != EXPLORED:
                        nb.state = FRONTIER
                        self._redraw_cell(nb)

            elapsed = (time.perf_counter() - t0[0]) * 1000
            self._update_stats(explored_count[0], None, elapsed)

            if delay == 0:
                self.root.after_idle(tick)
            else:
                self.root.after(delay, tick)

        self.root.after(10, tick)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()
    root.geometry("1000x640")
    PathfindingVisualiser(root)
    root.mainloop()


if __name__ == "__main__":
    main()
