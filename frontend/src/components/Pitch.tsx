import { useEffect, useRef } from "react";
import type { FrameBuffer } from "../useMatchStream";
import type { Club } from "../types";

// View box in metres: the 105 x 68 pitch plus a 3 m margin.
export const VIEW = { x0: -3, y0: -3, w: 111, h: 74 };

/** Pitch metres -> percentage position inside the stage (y grows upwards on the pitch). */
export function toPct(x: number, y: number) {
  return { left: ((x - VIEW.x0) / VIEW.w) * 100, top: ((VIEW.y0 + VIEW.h - y) / VIEW.h) * 100 };
}

interface Props {
  frames: React.MutableRefObject<FrameBuffer>;
  home: Club;
  away: Club;
  focusPlayer: string | null;
  favClub: string | null;
}

const FRAME_MS = 100;

export function Pitch({ frames, home, away, focusPlayer, favClub }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const props = useRef({ home, away, focusPlayer, favClub });
  props.current = { home, away, focusPlayer, favClub };

  useEffect(() => {
    const el = canvas.current!;
    const ctx = el.getContext("2d")!;
    let raf = 0;
    const resize = () => {
      const r = el.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      el.width = Math.round(r.width * dpr);
      el.height = Math.round(r.height * dpr);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(el);

    const draw = () => {
      raf = requestAnimationFrame(draw);
      const s = el.width / VIEW.w;
      const X = (x: number) => (x - VIEW.x0) * s;
      const Y = (y: number) => (VIEW.y0 + VIEW.h - y) * s;
      drawPitch(ctx, el.width, el.height, X, Y, s);

      const { prev, cur, at } = frames.current;
      if (!cur) return;
      const a = Math.min(1, (performance.now() - at) / FRAME_MS);
      const prevPos = new Map(prev?.players.map((p) => [p[0], p]) ?? []);
      const { home, away, focusPlayer, favClub } = props.current;
      const clubOf = (pid: string) => (pid.startsWith(home.short + "-") ? home : away);
      const numberOf = (pid: string) => pid.split("-")[1];

      const players = [...cur.players].sort((a, b) => Number(a[0] === focusPlayer) - Number(b[0] === focusPlayer));
      for (const [pid, x1, y1] of players) {
        const p0 = prevPos.get(pid);
        const x = p0 ? p0[1] + (x1 - p0[1]) * a : x1;
        const y = p0 ? p0[2] + (y1 - p0[2]) * a : y1;
        const club = clubOf(pid);
        const focused = pid === focusPlayer;
        const dim = favClub && club.short !== favClub && !focused;
        const r = (focused ? 1.7 : 1.25) * s;
        ctx.globalAlpha = dim ? 0.6 : 1;
        if (focused) {
          ctx.beginPath();
          ctx.arc(X(x), Y(y), r + 0.7 * s, 0, Math.PI * 2);
          ctx.strokeStyle = "#ffb547";
          ctx.lineWidth = 0.35 * s;
          ctx.stroke();
        }
        ctx.beginPath();
        ctx.arc(X(x), Y(y), r, 0, Math.PI * 2);
        ctx.fillStyle = club.primary;
        ctx.fill();
        ctx.lineWidth = 0.25 * s;
        ctx.strokeStyle = club.secondary;
        ctx.stroke();
        ctx.fillStyle = club.secondary;
        ctx.font = `600 ${(focused ? 1.5 : 1.15) * s}px "IBM Plex Mono", monospace`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(numberOf(pid), X(x), Y(y) + 0.05 * s);
      }
      ctx.globalAlpha = 1;

      const bx = prev ? prev.ball[0] + (cur.ball[0] - prev.ball[0]) * a : cur.ball[0];
      const by = prev ? prev.ball[1] + (cur.ball[1] - prev.ball[1]) * a : cur.ball[1];
      ctx.beginPath();
      ctx.arc(X(bx), Y(by), 0.65 * s, 0, Math.PI * 2);
      ctx.fillStyle = "#ffffff";
      ctx.shadowColor = "rgba(0,0,0,0.6)";
      ctx.shadowBlur = 0.8 * s;
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.lineWidth = 0.15 * s;
      ctx.strokeStyle = "#111";
      ctx.stroke();
    };
    draw();
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [frames]);

  return <canvas ref={canvas} className="pitch-canvas" aria-label="Live pitch view" />;
}

function drawPitch(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  X: (x: number) => number,
  Y: (y: number) => number,
  s: number,
) {
  ctx.fillStyle = "#24543a";
  ctx.fillRect(0, 0, w, h);
  const stripes = 14;
  for (let i = 0; i < stripes; i++) {
    if (i % 2) continue;
    ctx.fillStyle = "#2a5f42";
    ctx.fillRect(X((105 / stripes) * i), Y(68), (105 / stripes) * s, 68 * s);
  }
  ctx.strokeStyle = "rgba(255,255,255,0.82)";
  ctx.lineWidth = 0.18 * s;
  const rect = (x: number, y: number, rw: number, rh: number) => ctx.strokeRect(X(x), Y(y + rh), rw * s, rh * s);
  rect(0, 0, 105, 68);
  ctx.beginPath();
  ctx.moveTo(X(52.5), Y(0));
  ctx.lineTo(X(52.5), Y(68));
  ctx.stroke();
  const circle = (x: number, y: number, r: number, a0 = 0, a1 = Math.PI * 2, fill = false) => {
    ctx.beginPath();
    ctx.arc(X(x), Y(y), r * s, a0, a1);
    fill ? ctx.fill() : ctx.stroke();
  };
  circle(52.5, 34, 9.15);
  ctx.fillStyle = "rgba(255,255,255,0.82)";
  circle(52.5, 34, 0.3, 0, Math.PI * 2, true);
  for (const left of [true, false]) {
    const gx = left ? 0 : 105;
    const dir = left ? 1 : -1;
    rect(left ? 0 : 105 - 16.5, 34 - 20.16, 16.5, 40.32);
    rect(left ? 0 : 105 - 5.5, 34 - 9.16, 5.5, 18.32);
    circle(gx + dir * 11, 34, 0.3, 0, Math.PI * 2, true);
    const ang = Math.acos(5.5 / 9.15);
    if (left) circle(11, 34, 9.15, -ang, ang);
    else circle(94, 34, 9.15, Math.PI - ang, Math.PI + ang);
    ctx.strokeRect(left ? X(-2) : X(105), Y(34 + 3.66), 2 * s, 7.32 * s);
  }
}
