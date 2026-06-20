// Entry point: input, game loop, wiring
import { DIR, CANVAS_W, CANVAS_H } from './data.js';
import { Game } from './engine.js';
import { Renderer } from './renderer.js';

const canvas = document.getElementById('pacman');
canvas.width = CANVAS_W;
canvas.height = CANVAS_H;

const game = new Game(canvas);
const renderer = new Renderer(canvas.getContext('2d'));

// Input
const keyMap = {
  'ArrowUp': DIR.UP, 'w': DIR.UP, 'W': DIR.UP,
  'ArrowDown': DIR.DOWN, 's': DIR.DOWN, 'S': DIR.DOWN,
  'ArrowLeft': DIR.LEFT, 'a': DIR.LEFT, 'A': DIR.LEFT,
  'ArrowRight': DIR.RIGHT, 'd': DIR.RIGHT, 'D': DIR.RIGHT,
};

document.addEventListener('keydown', (e) => {
  const dir = keyMap[e.key];
  if (dir) {
    e.preventDefault();
    game.pacman.nextDir = dir;
    if (game.state === 'ready') game.state = 'playing';
  }
  // Restart on game over
  if (game.state === 'gameover' && (e.key === 'Enter' || e.key === ' ')) {
    game.reset();
    game.state = 'ready';
    game.readyTimer = 60;
  }
});

// Track pellet eating for particle effects
let lastPelletsEaten = 0;
let lastGhostsEatenFrenzy = 0;

function gameLoop() {
  game.update();

  // Spawn particles on pellet eat
  if (game.pelletsEaten > lastPelletsEaten) {
    const px = game.pacman.x;
    const py = game.pacman.y;
    renderer.addEatParticle(px, py, '#ffcc66');
    lastPelletsEaten = game.pelletsEaten;
  }

  // Spawn particles on ghost eat
  if (game.ghostsEatenFrenzy > lastGhostsEatenFrenzy) {
    for (const g of game.ghosts) {
      if (g.mode === 'eaten') {
        renderer.addGhostEatParticle(g.x, g.y);
        break;
      }
    }
    lastGhostsEatenFrenzy = game.ghostsEatenFrenzy;
  }

  renderer.render(game);
  requestAnimationFrame(gameLoop);
}

// Start
game.state = 'ready';
game.readyTimer = 60;
gameLoop();