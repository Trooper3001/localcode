// Fancy renderer with glow effects, animations, particles
import { MAZE_LAYOUT, TILE, COLS, ROWS, DIR, GHOST_COLORS } from './data.js';

export class Renderer {
  constructor(ctx) {
    this.ctx = ctx;
    this.particles = [];
    this.eyeTrail = [];
  }

  clear() {
    this.ctx.fillStyle = '#0a0a1a';
    this.ctx.fillRect(0, 0, this.ctx.canvas.width, this.ctx.canvas.height);
  }

  drawMaze(maze) {
    const ctx = this.ctx;
    for (let r = 0; r < ROWS; r++) {
      for (let c = 0; c < COLS; c++) {
        const tile = maze[r][c];
        const x = c * TILE;
        const y = r * TILE;

        if (tile === 1) {
          // Wall with neon glow
          ctx.shadowColor = '#4444ff';
          ctx.shadowBlur = 6;
          ctx.fillStyle = '#1a1a5e';
          ctx.fillRect(x, y, TILE, TILE);
          ctx.strokeStyle = '#4444ff';
          ctx.lineWidth = 2;
          ctx.strokeRect(x + 1, y + 1, TILE - 2, TILE - 2);
          ctx.shadowBlur = 0;
        } else if (tile === 4) {
          // Ghost house door
          ctx.fillStyle = '#ffb8ff';
          ctx.fillRect(x, y + TILE/2 - 2, TILE, 4);
        } else if (tile === 2) {
          // Pellet
          ctx.fillStyle = '#ffcc66';
          ctx.shadowColor = '#ffcc66';
          ctx.shadowBlur = 4;
          ctx.beginPath();
          ctx.arc(x + TILE/2, y + TILE/2, 2.5, 0, Math.PI * 2);
          ctx.fill();
          ctx.shadowBlur = 0;
        } else if (tile === 3) {
          // Power pellet (pulsing)
          const pulse = 0.5 + 0.5 * Math.sin(Date.now() * 0.008);
          const radius = 5 + pulse * 3;
          ctx.fillStyle = '#ffcc66';
          ctx.shadowColor = '#ffcc66';
          ctx.shadowBlur = 10 + pulse * 8;
          ctx.beginPath();
          ctx.arc(x + TILE/2, y + TILE/2, radius, 0, Math.PI * 2);
          ctx.fill();
          ctx.shadowBlur = 0;
        }
      }
    }
  }

  drawPacman(pacman, state, deathTimer) {
    const ctx = this.ctx;
    const x = pacman.x;
    const y = pacman.y;
    const angle = this.getAngle(pacman.dir);
    const mouth = pacman.mouthAngle;

    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(angle);

    if (state === 'dying') {
      const progress = 1 - deathTimer / 90;
      const mouthOpen = progress * Math.PI;
      ctx.fillStyle = '#ffff00';
      ctx.shadowColor = '#ffff00';
      ctx.shadowBlur = 15;
      ctx.beginPath();
      ctx.arc(0, 0, TILE/2 - 2, mouthOpen, Math.PI * 2 - mouthOpen);
      ctx.lineTo(0, 0);
      ctx.fill();
    } else {
      // Body with glow
      ctx.fillStyle = '#ffff00';
      ctx.shadowColor = '#ffff00';
      ctx.shadowBlur = 12;
      ctx.beginPath();
      ctx.arc(0, 0, TILE/2 - 1, mouth, Math.PI * 2 - mouth);
      ctx.lineTo(0, 0);
      ctx.closePath();
      ctx.fill();

      // Eye
      ctx.shadowBlur = 0;
      ctx.fillStyle = '#111';
      ctx.beginPath();
      ctx.arc(3, -TILE/4, 2, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.shadowBlur = 0;
    ctx.restore();
  }

  drawGhost(ghost, frameCount) {
    const ctx = this.ctx;
    const x = ghost.x;
    const y = ghost.y;
    const r = TILE / 2 - 1;

    if (ghost.mode === 'eaten') {
      // Just eyes
      this.drawGhostEyes(ctx, x, y, ghost.dir, frameCount);
      return;
    }

    let color = ghost.color;
    if (ghost.mode === 'frightened') {
      // Flash white near end
      if (this.frightenedTimer < 120 && Math.floor(frameCount / 10) % 2 === 0) {
        color = '#ffffff';
      } else {
        color = '#2222ff';
      }
    }

    ctx.save();
    ctx.shadowColor = color;
    ctx.shadowBlur = 10;

    // Ghost body
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(x, y - 2, r, Math.PI, 0, false);
    ctx.lineTo(x + r, y + r);

    // Wavy bottom
    const wave = Math.sin(frameCount * 0.2) * 2;
    const segments = 3;
    const segW = (r * 2) / segments;
    for (let i = segments; i > 0; i--) {
      const sx = x + r - (segments - i) * segW;
      const sy = y + r + ((i % 2 === 0) ? wave : -wave);
      const cp = sx - segW / 2;
      ctx.quadraticCurveTo(cp, sy, sx - segW, y + r);
    }
    ctx.closePath();
    ctx.fill();
    ctx.shadowBlur = 0;

    // Eyes
    if (ghost.mode === 'frightened') {
      // Scared eyes
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.arc(x - 4, y - 4, 2.5, 0, Math.PI * 2);
      ctx.arc(x + 4, y - 4, 2.5, 0, Math.PI * 2);
      ctx.fill();
      // Wavy mouth
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x - 5, y + 4);
      for (let i = 0; i < 5; i++) {
        ctx.lineTo(x - 5 + i * 2.5, y + 4 + (i % 2 === 0 ? 0 : -2));
      }
      ctx.stroke();
    } else {
      this.drawGhostEyes(ctx, x, y, ghost.dir, frameCount);
    }

    ctx.restore();
  }

  drawGhostEyes(ctx, x, y, dir, frameCount) {
    // White of eyes
    ctx.fillStyle = '#ffffff';
    ctx.beginPath();
    ctx.ellipse(x - 4, y - 3, 4, 5, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.ellipse(x + 4, y - 3, 4, 5, 0, 0, Math.PI * 2);
    ctx.fill();

    // Pupils - look in movement direction
    const px = dir.x * 2;
    const py = dir.y * 2;
    ctx.fillStyle = '#2200aa';
    ctx.beginPath();
    ctx.arc(x - 4 + px, y - 3 + py, 2, 0, Math.PI * 2);
    ctx.arc(x + 4 + px, y - 3 + py, 2, 0, Math.PI * 2);
    ctx.fill();
  }

  getAngle(dir) {
    if (dir === DIR.RIGHT) return 0;
    if (dir === DIR.DOWN) return Math.PI / 2;
    if (dir === DIR.LEFT) return Math.PI;
    if (dir === DIR.UP) return -Math.PI / 2;
    return 0;
  }

  addEatParticle(x, y, color) {
    for (let i = 0; i < 8; i++) {
      const angle = Math.random() * Math.PI * 2;
      const speed = 1 + Math.random() * 2;
      this.particles.push({
        x, y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        life: 30,
        maxLife: 30,
        color,
        size: 2 + Math.random() * 2,
      });
    }
  }

  addGhostEatParticle(x, y) {
    for (let i = 0; i < 20; i++) {
      const angle = Math.random() * Math.PI * 2;
      const speed = 2 + Math.random() * 3;
      this.particles.push({
        x, y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        life: 45,
        maxLife: 45,
        color: '#ffffff',
        size: 2 + Math.random() * 3,
      });
    }
  }

  updateAndDrawParticles() {
    const ctx = this.ctx;
    for (let i = this.particles.length - 1; i >= 0; i--) {
      const p = this.particles[i];
      p.x += p.vx;
      p.y += p.vy;
      p.vx *= 0.96;
      p.vy *= 0.96;
      p.life--;

      if (p.life <= 0) {
        this.particles.splice(i, 1);
        continue;
      }

      const alpha = p.life / p.maxLife;
      ctx.globalAlpha = alpha;
      ctx.fillStyle = p.color;
      ctx.shadowColor = p.color;
      ctx.shadowBlur = 6;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.size * alpha, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    ctx.shadowBlur = 0;
  }

  drawUI(game) {
    const ctx = this.ctx;
    ctx.shadowBlur = 0;

    // Score
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 18px "Courier New", monospace';
    ctx.textAlign = 'left';
    ctx.fillText(`SCORE: ${game.score}`, 10, -8);

    // Level
    ctx.textAlign = 'center';
    ctx.fillText(`LEVEL ${game.level}`, ctx.canvas.width / 2, -8);

    // Lives
    ctx.textAlign = 'right';
    for (let i = 0; i < game.lives; i++) {
      const lx = ctx.canvas.width - 20 - i * 24;
      ctx.fillStyle = '#ffff00';
      ctx.beginPath();
      ctx.arc(lx, -14, 7, 0.3, Math.PI * 2 - 0.3);
      ctx.lineTo(lx, -14);
      ctx.fill();
    }

    // High score
    const highScore = parseInt(localStorage.getItem('pacman_highscore') || '0');
    if (game.score > highScore) localStorage.setItem('pacman_highscore', game.score);
    const hs = Math.max(highScore, game.score);
    ctx.fillStyle = '#ffcc66';
    ctx.font = '12px "Courier New", monospace';
    ctx.textAlign = 'left';
    ctx.fillText(`HI: ${hs}`, 10, ctx.canvas.height + 16);
  }

  drawOverlay(text, sub) {
    const ctx = this.ctx;
    ctx.fillStyle = 'rgba(0,0,0,0.6)';
    ctx.fillRect(0, ctx.canvas.height * 0.3, ctx.canvas.width, ctx.canvas.height * 0.4);

    ctx.fillStyle = '#ffff00';
    ctx.shadowColor = '#ffff00';
    ctx.shadowBlur = 20;
    ctx.font = 'bold 36px "Courier New", monospace';
    ctx.textAlign = 'center';
    ctx.fillText(text, ctx.canvas.width / 2, ctx.canvas.height / 2);

    if (sub) {
      ctx.shadowBlur = 0;
      ctx.fillStyle = '#ffffff';
      ctx.font = '16px "Courier New", monospace';
      ctx.fillText(sub, ctx.canvas.width / 2, ctx.canvas.height / 2 + 35);
    }
    ctx.shadowBlur = 0;
  }

  render(game) {
    this.frightenedTimer = game.frightenedTimer;
    this.clear();
    this.drawMaze(game.maze);

    // Draw ghosts
    for (const g of game.ghosts) {
      this.drawGhost(g, game.frameCount);
    }

    // Draw Pac-Man
    this.drawPacman(game.pacman, game.state, game.deathTimer);

    // Particles
    this.updateAndDrawParticles();

    // UI
    this.drawUI(game);

    // Overlays
    if (game.state === 'ready') {
      this.drawOverlay('READY!', 'Press any key to start');
    } else if (game.state === 'gameover') {
      this.drawOverlay('GAME OVER', `Final Score: ${game.score}`);
    } else if (game.state === 'win') {
      this.drawOverlay('LEVEL CLEAR!', `Score: ${game.score}`);
    }
  }
}