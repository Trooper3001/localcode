// Core game engine: movement, collision, pellets, scoring
import { MAZE_LAYOUT, TILE, COLS, ROWS, DIR, PACMAN_SPEED, GHOST_SPEED, FRIGHTENED_SPEED, FRIGHTENED_DURATION, SCORE_PELLET, SCORE_POWER, SCORE_GHOST, GHOST_HOUSE_EXIT_FRAME } from './data.js';

export class Game {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.reset();
  }

  reset() {
    this.maze = MAZE_LAYOUT.map(r => [...r]);
    this.score = 0;
    this.lives = 3;
    this.level = 1;
    this.state = 'ready'; // ready, playing, dying, gameover, win
    this.frameCount = 0;
    this.totalPellets = 0;
    this.pelletsEaten = 0;
    this.ghostsEatenFrenzy = 0;
    this.frightenedTimer = 0;
    this.deathTimer = 0;
    this.readyTimer = 0;
    this.ghostExitTimer = 0;
    this.ghostsExited = 0;

    // Count pellets
    for (let r = 0; r < ROWS; r++)
      for (let c = 0; c < COLS; c++)
        if (this.maze[r][c] === 2 || this.maze[r][c] === 3)
          this.totalPellets++;

    this.initEntities();
  }

  initEntities() {
    // Pac-Man starts at (10, 16) heading left
    this.pacman = {
      x: 10 * TILE + TILE / 2,
      y: 16 * TILE + TILE / 2,
      dir: DIR.LEFT,
      nextDir: DIR.LEFT,
      mouthAngle: 0,
      mouthDir: 1,
    };

    // Ghosts
    this.ghosts = [
      { name: 'blinky', x: 10 * TILE + TILE/2, y: 8 * TILE + TILE/2, dir: DIR.LEFT, color: '#FF0000', mode: 'scatter', inHouse: false, exitTimer: 0 },
      { name: 'pinky',  x: 10 * TILE + TILE/2, y: 10 * TILE + TILE/2, dir: DIR.UP, color: '#FFB8FF', mode: 'scatter', inHouse: true, exitTimer: GHOST_HOUSE_EXIT_FRAME },
      { name: 'inky',   x: 8 * TILE + TILE/2, y: 10 * TILE + TILE/2, dir: DIR.UP, color: '#00FFFF', mode: 'scatter', inHouse: true, exitTimer: GHOST_HOUSE_EXIT_FRAME * 2 },
      { name: 'clyde',  x: 12 * TILE + TILE/2, y: 10 * TILE + TILE/2, dir: DIR.UP, color: '#FFB852', mode: 'scatter', inHouse: true, exitTimer: GHOST_HOUSE_EXIT_FRAME * 3 },
    ];

    this.ghostsExited = 0;
    this.ghostExitTimer = 0;
  }

  resetPositions() {
    this.pacman.x = 10 * TILE + TILE / 2;
    this.pacman.y = 16 * TILE + TILE / 2;
    this.pacman.dir = DIR.LEFT;
    this.pacman.nextDir = DIR.LEFT;
    this.initEntities();
    this.ghosts = this.ghosts || [];
    // Re-init ghosts
    this.initEntities();
  }

  tileAt(px, py) {
    const c = Math.floor(px / TILE);
    const r = Math.floor(py / TILE);
    if (r < 0 || r >= ROWS || c < 0 || c >= COLS) return 1;
    return this.maze[r][c];
  }

  canMoveTo(px, py, isGhost) {
    // Check all 4 corners of the entity
    const half = TILE / 2 - 1;
    const corners = [
      [px - half, py - half],
      [px + half, py - half],
      [px - half, py + half],
      [px + half, py + half],
    ];
    for (const [cx, cy] of corners) {
      const t = this.tileAt(cx, cy);
      if (t === 1) return false;
      if (t === 4 && !isGhost) return false;
    }
    return true;
  }

  isCentered(px, py) {
    return Math.abs(px % TILE - TILE / 2) < 2 && Math.abs(py % TILE - TILE / 2) < 2;
  }

  snapToCenter(px, py) {
    const c = Math.floor(px / TILE);
    const r = Math.floor(py / TILE);
    return { x: c * TILE + TILE / 2, y: r * TILE + TILE / 2 };
  }

  // Tunnel wrapping
  wrapX(x) {
    if (x < -TILE / 2) return (COLS - 0.5) * TILE;
    if (x > (COLS - 0.5) * TILE) return -TILE / 2;
    return x;
  }

  updatePacman() {
    const p = this.pacman;

    // Animate mouth
    p.mouthAngle += 0.15 * p.mouthDir;
    if (p.mouthAngle > 0.8) p.mouthDir = -1;
    if (p.mouthAngle < 0.05) p.mouthDir = 1;

    // Try next direction first
    if (p.nextDir !== p.dir) {
      const nx = p.x + p.nextDir.x * PACMAN_SPEED;
      const ny = p.y + p.nextDir.y * PACMAN_SPEED;
      if (this.isCentered(p.x, p.y) && this.canMoveTo(nx, ny, false)) {
        const snap = this.snapToCenter(p.x, p.y);
        p.x = snap.x;
        p.y = snap.y;
        p.dir = p.nextDir;
      }
    }

    // Move in current direction
    const nx = p.x + p.dir.x * PACMAN_SPEED;
    const ny = p.y + p.dir.y * PACMAN_SPEED;

    if (this.canMoveTo(nx, ny, false)) {
      p.x = nx;
      p.y = ny;
    } else if (this.isCentered(p.x, p.y)) {
      const snap = this.snapToCenter(p.x, p.y);
      p.x = snap.x;
      p.y = snap.y;
    }

    p.x = this.wrapX(p.x);

    // Eat pellets
    const col = Math.floor(p.x / TILE);
    const row = Math.floor(p.y / TILE);
    if (row >= 0 && row < ROWS && col >= 0 && col < COLS) {
      const tile = this.maze[row][col];
      if (tile === 2) {
        this.maze[row][col] = 0;
        this.score += SCORE_PELLET;
        this.pelletsEaten++;
      } else if (tile === 3) {
        this.maze[row][col] = 0;
        this.score += SCORE_POWER;
        this.pelletsEaten++;
        this.frightenedTimer = FRIGHTENED_DURATION;
        this.ghostsEatenFrenzy = 0;
        // Reverse all ghosts not in house
        for (const g of this.ghosts) {
          if (!g.inHouse && g.mode !== 'eaten') {
            g.dir = { x: -g.dir.x, y: -g.dir.y };
          }
        }
      }
    }

    // Check win
    if (this.pelletsEaten >= this.totalPellets) {
      this.state = 'win';
      this.readyTimer = 120;
    }
  }

  updateGhosts() {
    if (this.frightenedTimer > 0) {
      this.frightenedTimer--;
      if (this.frightenedTimer === 0) {
        for (const g of this.ghosts) {
          if (g.mode === 'frightened') g.mode = 'chase';
        }
      }
    }

    for (const g of this.ghosts) {
      if (g.inHouse) {
        g.exitTimer--;
        if (g.exitTimer <= 0) {
          g.inHouse = false;
          g.x = 10 * TILE + TILE / 2;
          g.y = 8 * TILE + TILE / 2;
          g.dir = DIR.LEFT;
          this.ghostsExited++;
        } else {
          // Bob up and down in house
          g.y += Math.sin(this.frameCount * 0.1) * 0.5;
        }
        continue;
      }

      const speed = g.mode === 'frightened' ? FRIGHTENED_SPEED : (g.mode === 'eaten' ? 4 : GHOST_SPEED);

      // At center of tile, choose next direction
      if (this.isCentered(g.x, g.y)) {
        const snap = this.snapToCenter(g.x, g.y);
        g.x = snap.x;
        g.y = snap.y;

        // If eaten and reached ghost house, revive
        if (g.mode === 'eaten' && this.tileAt(g.x, g.y) === 4) {
          g.mode = this.frightenedTimer > 0 ? 'frightened' : 'chase';
          g.inHouse = true;
          g.exitTimer = 60;
          continue;
        }

        const possible = this.getValidDirections(g);
        if (possible.length > 0) {
          if (g.mode === 'frightened') {
            // Random direction
            g.dir = possible[Math.floor(Math.random() * possible.length)];
          } else if (g.mode === 'eaten') {
            // Head toward ghost house
            g.dir = this.getDirectionToTarget(g, 10 * TILE + TILE/2, 9 * TILE + TILE/2, possible);
          } else {
            // Chase or scatter
            const target = this.getGhostTarget(g);
            g.dir = this.getDirectionToTarget(g, target.x, target.y, possible);
          }
        }
      }

      const nx = g.x + g.dir.x * speed;
      const ny = g.y + g.dir.y * speed;
      if (this.canMoveTo(nx, ny, true)) {
        g.x = nx;
        g.y = ny;
      }
      g.x = this.wrapX(g.x);
    }
  }

  getValidDirections(ghost) {
    const dirs = [DIR.UP, DIR.DOWN, DIR.LEFT, DIR.RIGHT];
    const opposite = { x: -ghost.dir.x, y: -ghost.dir.y };
    const valid = [];
    for (const d of dirs) {
      // Can't reverse
      if (d.x === opposite.x && d.y === opposite.y) continue;
      const nx = ghost.x + d.x * TILE;
      const ny = ghost.y + d.y * TILE;
      if (this.canMoveTo(nx, ny, true)) {
        valid.push(d);
      }
    }
    return valid;
  }

  getDirectionToTarget(ghost, tx, ty, possible) {
    let best = possible[0];
    let bestDist = Infinity;
    for (const d of possible) {
      const nx = ghost.x + d.x * TILE;
      const ny = ghost.y + d.y * TILE;
      const dist = (nx - tx) ** 2 + (ny - ty) ** 2;
      if (dist < bestDist) {
        bestDist = dist;
        best = d;
      }
    }
    return best;
  }

  getGhostTarget(ghost) {
    const px = this.pacman.x;
    const py = this.pacman.y;
    const pc = Math.floor(px / TILE);
    const pr = Math.floor(py / TILE);

    if (ghost.mode === 'scatter') {
      // Corners
      switch (ghost.name) {
        case 'blinky': return { x: (COLS-2) * TILE, y: TILE };
        case 'pinky': return { x: TILE, y: TILE };
        case 'inky': return { x: (COLS-2) * TILE, y: (ROWS-2) * TILE };
        case 'clyde': return { x: TILE, y: (ROWS-2) * TILE };
      }
    }

    // Chase mode targets
    switch (ghost.name) {
      case 'blinky': // Directly targets Pac-Man
        return { x: px, y: py };
      case 'pinky': // 4 tiles ahead of Pac-Man
        return { x: pc * TILE + this.pacman.dir.x * 4 * TILE, y: pr * TILE + this.pacman.dir.y * 4 * TILE };
      case 'inky': { // Complex: uses Blinky's position
        const blinky = this.ghosts[0];
        const ax = pc * TILE + this.pacman.dir.x * 2 * TILE;
        const ay = pr * TILE + this.pacman.dir.y * 2 * TILE;
        return { x: 2 * ax - blinky.x, y: 2 * ay - blinky.y };
      }
      case 'clyde': { // Chase if far, scatter if close
        const dist = (ghost.x - px) ** 2 + (ghost.y - py) ** 2;
        if (dist > (8 * TILE) ** 2) return { x: px, y: py };
        return { x: TILE, y: (ROWS-2) * TILE };
      }
    }
    return { x: px, y: py };
  }

  checkCollisions() {
    const px = this.pacman.x;
    const py = this.pacman.y;

    for (const g of this.ghosts) {
      if (g.inHouse) continue;
      const dist = Math.hypot(g.x - px, g.y - py);
      if (dist < TILE * 0.8) {
        if (g.mode === 'frightened') {
          g.mode = 'eaten';
          this.ghostsEatenFrenzy++;
          this.score += SCORE_GHOST * Math.pow(2, this.ghostsEatenFrenzy - 1);
        } else if (g.mode !== 'eaten') {
          this.state = 'dying';
          this.deathTimer = 90;
          return;
        }
      }
    }
  }

  update() {
    this.frameCount++;

    if (this.state === 'ready') {
      this.readyTimer--;
      if (this.readyTimer <= 0) this.state = 'playing';
      return;
    }

    if (this.state === 'dying') {
      this.deathTimer--;
      if (this.deathTimer <= 0) {
        this.lives--;
        if (this.lives <= 0) {
          this.state = 'gameover';
        } else {
          this.resetPositions();
          this.state = 'ready';
          this.readyTimer = 90;
        }
      }
      return;
    }

    if (this.state === 'win') {
      this.readyTimer--;
      if (this.readyTimer <= 0) {
        this.level++;
        this.maze = MAZE_LAYOUT.map(r => [...r]);
        this.totalPellets = 0;
        this.pelletsEaten = 0;
        for (let r = 0; r < ROWS; r++)
          for (let c = 0; c < COLS; c++)
            if (this.maze[r][c] === 2 || this.maze[r][c] === 3)
              this.totalPellets++;
        this.resetPositions();
        this.state = 'ready';
        this.readyTimer = 90;
      }
      return;
    }

    if (this.state !== 'playing') return;

    // Mode switching: scatter/chase cycles
    const cycleTime = this.frameCount % 1800; // 30s total cycle
    if (cycleTime < 420) {
      // Scatter
      for (const g of this.ghosts) {
        if (g.mode !== 'frightened' && g.mode !== 'eaten') g.mode = 'scatter';
      }
    } else if (cycleTime < 1020) {
      // Chase
      for (const g of this.ghosts) {
        if (g.mode !== 'frightened' && g.mode !== 'eaten') g.mode = 'chase';
      }
    } else if (cycleTime < 1200) {
      for (const g of this.ghosts) {
        if (g.mode !== 'frightened' && g.mode !== 'eaten') g.mode = 'scatter';
      }
    } else {
      for (const g of this.ghosts) {
        if (g.mode !== 'frightened' && g.mode !== 'eaten') g.mode = 'chase';
      }
    }

    this.updatePacman();
    this.updateGhosts();
    this.checkCollisions();
  }
}