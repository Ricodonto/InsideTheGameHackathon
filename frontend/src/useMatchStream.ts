import { useCallback, useEffect, useRef, useState } from "react";
import type { Answer, Frame, MatchState, Meta, Overlay, Profile, Status, ViewerData } from "./types";

const MAX_OVERLAYS = 1500;

export interface FrameBuffer {
  prev: Frame | null;
  cur: Frame | null;
  at: number; // performance.now() when cur arrived
}

const emptyViewer = (): ViewerData => ({ overlays: [], answers: [] });

/** One WebSocket per scenario: shared clock, frames and state, plus per-viewer overlays. */
export function useMatchStream(scenario: string, viewers: Profile[], initialSpeed: number) {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [state, setState] = useState<MatchState | null>(null);
  const [frame, setFrame] = useState<Frame | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [views, setViews] = useState<ViewerData[]>([emptyViewer(), emptyViewer()]);
  const [connected, setConnected] = useState(false);
  const frames = useRef<FrameBuffer>({ prev: null, cur: null, at: 0 });
  const ws = useRef<WebSocket | null>(null);
  const viewersRef = useRef(viewers);
  viewersRef.current = viewers;

  const send = useCallback((msg: object) => {
    if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify(msg));
  }, []);

  useEffect(() => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const sock = new WebSocket(`${proto}://${location.host}/ws/match/${scenario}`);
    ws.current = sock;
    setViews([emptyViewer(), emptyViewer()]);
    setState(null);
    frames.current = { prev: null, cur: null, at: 0 };

    sock.onopen = () => {
      setConnected(true);
      sock.send(JSON.stringify({ type: "hello", viewers: viewersRef.current, speed: initialSpeed }));
    };
    sock.onclose = () => setConnected(false);
    sock.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      switch (msg.type) {
        case "meta":
          setMeta(msg as Meta);
          break;
        case "frame": {
          const f: Frame = { t: msg.t, ball: msg.ball, players: msg.players };
          frames.current = { prev: frames.current.cur, cur: f, at: performance.now() };
          setFrame(f);
          break;
        }
        case "state":
          setState(msg.state as MatchState);
          break;
        case "status":
          setStatus(msg as Status);
          break;
        case "overlay":
          setViews((vs) => updateViewer(vs, msg.viewer, (v) => ({
            ...v,
            overlays: [...v.overlays, { ...(msg.overlay as Overlay), receivedAt: performance.now() }].slice(-MAX_OVERLAYS),
          })));
          break;
        case "overlay_text":
          setViews((vs) => updateViewer(vs, msg.viewer, (v) => ({
            ...v,
            overlays: v.overlays.map((o) => (o.id === msg.id ? { ...o, text: msg.text } : o)),
          })));
          break;
        case "history":
          setViews((vs) => updateViewer(vs, msg.viewer, (v) => ({ ...v, overlays: msg.overlays as Overlay[] })));
          break;
        case "answer":
          setViews((vs) => updateViewer(vs, msg.viewer, (v) => ({
            ...v,
            answers: [...v.answers, msg as Answer].slice(-20),
          })));
          break;
      }
    };
    return () => sock.close();
    // initialSpeed is only used for the hello message
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenario]);

  // Push profile changes (mode, language, club, player, split screen) to the server.
  const profileKey = JSON.stringify(viewers);
  useEffect(() => {
    send({ type: "profiles", viewers });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profileKey, send]);

  return { meta, state, frame, frames, status, views, send, connected };
}

function updateViewer(vs: ViewerData[], i: number, fn: (v: ViewerData) => ViewerData): ViewerData[] {
  const next = [...vs];
  next[i] = fn(next[i] ?? emptyViewer());
  return next;
}
