from __future__ import annotations

import json
import threading
import time
import webbrowser
from dataclasses import asdict, is_dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from .cards import format_cards
from .game import DouDizhuGame, GameConfig, GameResult, Player


class EventHub:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._events: list[dict[str, Any]] = []
        self._closed = False

    def publish(self, event: str, payload: dict[str, Any]) -> None:
        with self._condition:
            item = {
                "id": len(self._events) + 1,
                "event": event,
                "payload": _to_jsonable(payload),
            }
            self._events.append(item)
            self._condition.notify_all()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def stream_from(self, last_seen: int = 0):
        next_index = last_seen
        while True:
            with self._condition:
                while next_index >= len(self._events) and not self._closed:
                    self._condition.wait(timeout=15)
                    if next_index >= len(self._events):
                        yield None
                if next_index < len(self._events):
                    item = self._events[next_index]
                    next_index += 1
                    yield item
                    continue
                if self._closed:
                    return


def run_live_table(
    *,
    players: list[Player],
    config: GameConfig,
    host: str,
    port: int,
    show_reasons: bool,
    open_browser: bool,
) -> int:
    hub = EventHub()
    server = _make_server(host, port, hub)
    actual_port = server.server_address[1]
    url = f"http://{host}:{actual_port}/"

    hub.publish(
        "players",
        {
            "players": [
                {
                    "seat": player.seat,
                    "name": player.name,
                    "display_name": display_player_name(player.name),
                }
                for player in players
            ],
            "show_reasons": show_reasons,
            "seed": config.seed,
        },
    )

    server_thread = threading.Thread(target=server.serve_forever, name="doudizhu-live-server", daemon=True)
    server_thread.start()
    print(f"实时牌桌: {url}", flush=True)
    if open_browser:
        webbrowser.open(url)

    result_holder: dict[str, Any] = {}

    def on_event(event: str, payload: dict[str, Any]) -> None:
        hub.publish(event, payload)

    def run_game() -> None:
        try:
            time.sleep(0.5)
            game = DouDizhuGame(players, config, event_handler=on_event)
            result = game.play()
            result_holder["result"] = result
            hub.publish("game_result", {"result": _result_payload(result, players)})
        except Exception as error:
            result_holder["error"] = error
            hub.publish("game_error", {"message": str(error) or type(error).__name__})
        finally:
            time.sleep(2)
            hub.close()
            server.shutdown()

    game_thread = threading.Thread(target=run_game, name="doudizhu-live-game")
    game_thread.start()
    try:
        game_thread.join()
        server_thread.join(timeout=3)
    except KeyboardInterrupt:
        hub.close()
        server.shutdown()
        return 130

    if "error" in result_holder:
        return 1
    return 0


def _make_server(host: str, port: int, hub: EventHub) -> ThreadingHTTPServer:
    class LiveHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/":
                self._send_html()
                return
            if path == "/events":
                self._send_events()
                return
            if path == "/health":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")
                return
            self.send_error(404)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_html(self) -> None:
            body = LIVE_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_events(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            last_seen = int(self.headers.get("Last-Event-ID", "0") or 0)
            try:
                for item in hub.stream_from(last_seen):
                    if item is None:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        continue
                    data = json.dumps(item["payload"], ensure_ascii=False)
                    chunk = f"id: {item['id']}\nevent: {item['event']}\ndata: {data}\n\n".encode("utf-8")
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return

    return ThreadingHTTPServer((host, port), LiveHandler)


def _result_payload(result: GameResult, players: list[Player]) -> dict[str, Any]:
    return {
        "winner": result.winner,
        "winnerName": players[result.winner].name,
        "winnerSide": "地主" if result.winner_side == "landlord" else "农民",
        "landlord": result.landlord,
        "landlordName": players[result.landlord].name,
        "farmers": list(result.farmers),
        "farmerNames": [players[seat].name for seat in result.farmers],
        "bid": result.bid,
        "multiplier": result.multiplier,
        "spring": {"spring": "春天", "anti-spring": "反春", None: "无"}[result.spring],
        "turns": result.turns,
        "bottomCards": list(result.bottom_cards),
        "bottomText": format_cards(result.bottom_cards),
        "points": result.points,
    }


def display_player_name(name: str, max_length: int = 28) -> str:
    if len(name) <= max_length:
        return name
    keep = max(4, (max_length - 3) // 2)
    tail = max_length - 3 - keep
    return f"{name[:keep]}...{name[-tail:]}"


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value


LIVE_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI 斗地主直播桌</title>
  <style>
    :root {
      --felt: #1f6b4b;
      --felt-dark: #114431;
      --ink: #18211d;
      --muted: #6a756d;
      --paper: #fffaf0;
      --gold: #e6b85c;
      --red: #b72d2d;
      --blue: #2f5d9f;
      --line: rgba(24, 33, 29, 0.16);
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      font-family: "Songti SC", "Noto Serif CJK SC", "Source Han Serif SC", Georgia, serif;
      background:
        radial-gradient(circle at 18% 12%, rgba(230, 184, 92, 0.24), transparent 28%),
        radial-gradient(circle at 82% 18%, rgba(47, 93, 159, 0.18), transparent 26%),
        linear-gradient(135deg, #123728 0%, #1e6548 45%, #0d3024 100%);
    }

    .app {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 340px;
      gap: 18px;
      height: 100vh;
      padding: 18px;
      overflow: hidden;
    }

    .table {
      position: relative;
      height: calc(100vh - 36px);
      min-height: 680px;
      border: 2px solid rgba(255, 250, 240, 0.22);
      border-radius: 18px;
      overflow: hidden;
      background:
        repeating-linear-gradient(45deg, rgba(255,255,255,0.025) 0 8px, transparent 8px 16px),
        radial-gradient(circle at 50% 45%, #2d8a62, var(--felt) 48%, var(--felt-dark) 100%);
      box-shadow: 0 30px 80px rgba(0, 0, 0, 0.35), inset 0 0 80px rgba(0, 0, 0, 0.18);
    }

    .topbar {
      position: absolute;
      inset: 14px 14px auto 14px;
      display: flex;
      justify-content: space-between;
      gap: 12px;
      color: var(--paper);
      z-index: 3;
    }

    .badge {
      border: 1px solid rgba(255, 250, 240, 0.24);
      border-radius: 999px;
      padding: 7px 12px;
      background: rgba(10, 30, 22, 0.4);
      backdrop-filter: blur(8px);
      font-size: 13px;
    }

    .center {
      position: absolute;
      left: 50%;
      top: 46%;
      transform: translate(-50%, -50%);
      width: min(560px, 62vw);
      min-height: 200px;
      display: grid;
      place-items: center;
      color: var(--paper);
      text-align: center;
    }

    .last-play {
      min-height: 112px;
      width: 100%;
      border: 1px solid rgba(255, 250, 240, 0.22);
      border-radius: 14px;
      padding: 16px;
      background: rgba(13, 48, 36, 0.48);
      backdrop-filter: blur(10px);
    }

    .last-title {
      color: rgba(255, 250, 240, 0.72);
      font-size: 14px;
      margin-bottom: 12px;
    }

    .last-cards {
      display: flex;
      justify-content: center;
      flex-wrap: wrap;
      gap: 7px;
      min-height: 64px;
    }

    .player {
      position: absolute;
      width: 36%;
      min-width: 260px;
      color: var(--paper);
    }

    .player[data-seat="0"] { left: 50%; bottom: 22px; transform: translateX(-50%); }
    .player[data-seat="1"] { left: 22px; top: 50%; transform: translateY(-43%); }
    .player[data-seat="2"] { right: 22px; top: 50%; transform: translateY(-43%); }

    .player-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 8px;
      padding: 8px 10px;
      border-radius: 10px;
      background: rgba(9, 34, 25, 0.46);
      border: 1px solid rgba(255, 250, 240, 0.16);
    }

    .name {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-weight: 700;
      font-size: 14px;
      min-width: 0;
    }

    .role {
      display: inline-flex;
      align-items: center;
      height: 24px;
      padding: 0 8px;
      border-radius: 999px;
      background: rgba(230, 184, 92, 0.16);
      color: #ffd98a;
      font-size: 12px;
      white-space: nowrap;
    }

    .hand {
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
      min-height: 78px;
      align-items: flex-start;
    }

    .card {
      width: 44px;
      height: 62px;
      display: grid;
      place-items: center;
      border-radius: 7px;
      background: linear-gradient(160deg, #fffdf6, #f4e7c8);
      color: var(--ink);
      border: 1px solid rgba(24, 33, 29, 0.18);
      box-shadow: 0 8px 16px rgba(0,0,0,0.2);
      font-weight: 800;
      font-size: 15px;
      animation: dealIn 360ms ease both;
    }

    .card.red { color: var(--red); }
    .card.joker { color: var(--blue); font-size: 12px; }
    .card.played { animation: playPop 460ms cubic-bezier(.2,.8,.2,1) both; }

    .thinking .player-head {
      outline: 2px solid rgba(255, 217, 138, 0.78);
      box-shadow: 0 0 0 5px rgba(230, 184, 92, 0.12);
    }

    .side {
      height: calc(100vh - 36px);
      min-height: 680px;
      border-radius: 18px;
      background: rgba(255, 250, 240, 0.94);
      box-shadow: 0 24px 70px rgba(0,0,0,0.28);
      overflow: hidden;
      display: grid;
      grid-template-rows: auto auto auto minmax(0, 1fr);
    }

    .panel {
      padding: 16px;
      border-bottom: 1px solid var(--line);
      min-width: 0;
    }

    h1 {
      margin: 0;
      font-size: 22px;
      line-height: 1.2;
      letter-spacing: 0;
    }

    .status {
      margin-top: 8px;
      color: var(--muted);
      font-size: 13px;
    }

    .score-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin-top: 12px;
    }

    .score {
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff7e4;
    }

    .score b {
      display: block;
      font-size: 13px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .score span {
      display: block;
      margin-top: 4px;
      color: var(--muted);
      font-size: 12px;
    }

    .log {
      min-height: 0;
      overflow-y: auto;
      overflow-x: hidden;
      padding: 12px 14px 16px;
      scrollbar-width: thin;
      scrollbar-color: rgba(106,117,109,0.55) transparent;
    }

    .log::-webkit-scrollbar { width: 8px; }
    .log::-webkit-scrollbar-track { background: transparent; }
    .log::-webkit-scrollbar-thumb {
      background: rgba(106,117,109,0.42);
      border-radius: 999px;
    }

    .log-tools {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 10px 14px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 250, 240, 0.78);
      min-width: 0;
    }

    .log-tools span {
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .tool-button {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 6px 9px;
      background: #fff7e4;
      color: var(--ink);
      font: inherit;
      font-size: 12px;
      cursor: pointer;
      white-space: nowrap;
    }

    .tool-button:hover {
      background: #fff1cf;
    }

    .log-item {
      border-left: 3px solid #d5a84e;
      padding: 8px 0 8px 10px;
      margin-bottom: 6px;
      background: linear-gradient(90deg, rgba(230,184,92,0.13), transparent);
      font-size: 12px;
      line-height: 1.36;
      animation: logIn 220ms ease both;
    }

    .log-item small {
      display: block;
      color: var(--muted);
      margin-top: 3px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    @keyframes dealIn {
      from { opacity: 0; transform: translateY(12px) rotate(-3deg); }
      to { opacity: 1; transform: translateY(0) rotate(0); }
    }

    @keyframes playPop {
      from { opacity: 0; transform: translateY(24px) scale(0.92); }
      to { opacity: 1; transform: translateY(0) scale(1); }
    }

    @keyframes logIn {
      from { opacity: 0; transform: translateX(8px); }
      to { opacity: 1; transform: translateX(0); }
    }

    @media (max-width: 980px) {
      .app { grid-template-columns: 1fr; }
      .app { height: auto; overflow: auto; }
      .table { min-height: 720px; }
      .side { height: 520px; min-height: 520px; }
      .player { width: 44%; min-width: 220px; }
      .card { width: 38px; height: 54px; font-size: 13px; }
    }
  </style>
</head>
<body>
  <main class="app">
    <section class="table">
      <div class="topbar">
        <div class="badge" id="roundInfo">等待开局</div>
        <div class="badge" id="connection">连接中</div>
      </div>
      <div class="center">
        <div class="last-play">
          <div class="last-title" id="lastTitle">牌桌正在等待第一手牌</div>
          <div class="last-cards" id="lastCards"></div>
        </div>
      </div>
      <div class="player" data-seat="0">
        <div class="player-head"><div class="name" id="name0">P0</div><div class="role" id="role0">待定</div></div>
        <div class="hand" id="hand0"></div>
      </div>
      <div class="player" data-seat="1">
        <div class="player-head"><div class="name" id="name1">P1</div><div class="role" id="role1">待定</div></div>
        <div class="hand" id="hand1"></div>
      </div>
      <div class="player" data-seat="2">
        <div class="player-head"><div class="name" id="name2">P2</div><div class="role" id="role2">待定</div></div>
        <div class="hand" id="hand2"></div>
      </div>
    </section>
    <aside class="side">
      <div class="panel">
        <h1>AI 斗地主直播桌</h1>
        <div class="status" id="status">正在连接牌局事件</div>
      </div>
      <div class="panel">
        <div class="status">底牌</div>
        <div class="last-cards" id="bottomCards"></div>
        <div class="score-grid" id="scoreGrid"></div>
      </div>
      <div class="log-tools">
        <span id="logCount">事件记录 0 条</span>
        <button class="tool-button" id="followButton" type="button" title="切换是否自动滚动到最新事件">跟随最新</button>
      </div>
      <div class="log" id="log"></div>
    </aside>
  </main>
  <script>
    const state = {
      players: [],
      hands: {0: [], 1: [], 2: []},
      landlord: null,
      showReasons: false,
      followLog: true,
      logCount: 0,
    };

    const rankText = card => ({BJ: "小王", RJ: "大王"}[card] || card);
    const isRed = card => ["3","5","7","9","J","K","2"].includes(card);
    const roleName = (seat) => state.landlord === null ? "待定" : (Number(seat) === Number(state.landlord) ? "地主" : "农民");

    function cardEl(card, extra = "") {
      const div = document.createElement("div");
      div.className = `card ${isRed(card) ? "red" : ""} ${card === "BJ" || card === "RJ" ? "joker" : ""} ${extra}`;
      div.textContent = rankText(card);
      return div;
    }

    function renderHand(seat) {
      const box = document.getElementById(`hand${seat}`);
      box.innerHTML = "";
      (state.hands[seat] || []).forEach((card, index) => {
        const el = cardEl(card);
        el.style.animationDelay = `${Math.min(index * 18, 320)}ms`;
        box.appendChild(el);
      });
      document.getElementById(`role${seat}`).textContent = `${roleName(seat)} · ${(state.hands[seat] || []).length} 张`;
    }

    function renderAllHands() {
      [0, 1, 2].forEach(renderHand);
    }

    function setThinking(seat) {
      document.querySelectorAll(".player").forEach(el => el.classList.remove("thinking"));
      const target = document.querySelector(`.player[data-seat="${seat}"]`);
      if (target) target.classList.add("thinking");
    }

    function renderCards(targetId, cards, played = false) {
      const box = document.getElementById(targetId);
      box.innerHTML = "";
      (cards || []).forEach((card, index) => {
        const el = cardEl(card, played ? "played" : "");
        el.style.animationDelay = `${index * 45}ms`;
        box.appendChild(el);
      });
    }

    function addLog(text, detail = "") {
      const log = document.getElementById("log");
      const shouldStick = state.followLog || log.scrollTop < 12;
      const item = document.createElement("div");
      item.className = "log-item";
      item.innerHTML = `${escapeHtml(text)}${detail ? `<small>${escapeHtml(detail)}</small>` : ""}`;
      log.prepend(item);
      state.logCount += 1;
      document.getElementById("logCount").textContent = `事件记录 ${state.logCount} 条`;
      if (shouldStick) {
        log.scrollTo({ top: 0, behavior: "smooth" });
      }
    }

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, char => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      }[char]));
    }

    function playerName(seat) {
      return state.players[seat]?.display_name || `P${seat}`;
    }

    function fullPlayerName(seat) {
      return state.players[seat]?.name || `P${seat}`;
    }

    function reasonText(reason) {
      if (!state.showReasons || !reason) return "";
      return `理由：${reason}`;
    }

    function removeCards(hand, cards) {
      const next = [...hand];
      for (const card of cards) {
        const index = next.indexOf(card);
        if (index !== -1) next.splice(index, 1);
      }
      return next;
    }

    const source = new EventSource("/events");
    const logBox = document.getElementById("log");
    const followButton = document.getElementById("followButton");
    logBox.addEventListener("scroll", () => {
      state.followLog = logBox.scrollTop < 16;
      followButton.textContent = state.followLog ? "跟随最新" : "查看历史中";
    });
    followButton.addEventListener("click", () => {
      state.followLog = true;
      logBox.scrollTo({ top: 0, behavior: "smooth" });
      followButton.textContent = "跟随最新";
    });
    source.onopen = () => document.getElementById("connection").textContent = "实时连接中";
    source.onerror = () => document.getElementById("connection").textContent = "连接已结束";

    source.addEventListener("players", (event) => {
      const data = JSON.parse(event.data);
      state.players = data.players;
      state.showReasons = data.show_reasons;
      data.players.forEach(p => {
        const el = document.getElementById(`name${p.seat}`);
        el.textContent = p.display_name || p.name;
        el.title = p.name;
      });
      document.getElementById("roundInfo").textContent = data.seed === null ? "随机牌局" : `种子 ${data.seed}`;
    });

    source.addEventListener("initial_deal", (event) => {
      const data = JSON.parse(event.data);
      state.hands = data.hands;
      state.landlord = null;
      renderAllHands();
      renderCards("bottomCards", data.bottom_cards);
      renderCards("lastCards", []);
      document.getElementById("lastTitle").textContent = "新一局发牌完成，等待叫分";
      addLog("发牌完成", `三家各 17 张，底牌 ${data.bottom_cards.map(rankText).join(" ")}`);
    });

    source.addEventListener("bid_thinking", (event) => {
      const data = JSON.parse(event.data);
      setThinking(data.player);
      document.getElementById("status").textContent = `${playerName(data.player)} 正在叫分`;
      addLog(`${playerName(data.player)} 正在叫分`, `${fullPlayerName(data.player)} · ${handSummary(data.hand)}`);
    });

    source.addEventListener("bid_result", (event) => {
      const data = JSON.parse(event.data).record;
      addLog(`${playerName(data.player)} 叫 ${data.bid} 分`, reasonText(data.reason));
    });

    source.addEventListener("landlord_selected", (event) => {
      const data = JSON.parse(event.data);
      state.landlord = data.landlord;
      state.hands[data.landlord] = [...state.hands[data.landlord], ...data.bottom_cards].sort(compareCards);
      renderAllHands();
      renderCards("bottomCards", data.bottom_cards);
      document.getElementById("status").textContent = `${playerName(data.landlord)} 成为地主`;
      addLog(`地主确定：${playerName(data.landlord)}`, `叫分 ${data.bid}，底牌 ${data.bottom_cards.map(rankText).join(" ")}`);
    });

    source.addEventListener("redeal", (event) => {
      const data = JSON.parse(event.data);
      addLog("三家都不叫，重新发牌", `第 ${data.redeals} 次重发`);
    });

    source.addEventListener("play_thinking", (event) => {
      const data = JSON.parse(event.data);
      setThinking(data.player);
      document.getElementById("status").textContent = `${playerName(data.player)} 正在思考第 ${data.turn} 手`;
      addLog(`${playerName(data.player)} 正在思考`, `${fullPlayerName(data.player)} · ${handSummary(data.hand)}；合法动作 ${data.legal_count} 个`);
    });

    source.addEventListener("play_result", (event) => {
      const data = JSON.parse(event.data).record;
      const cards = data.cards || [];
      if (cards.length) {
        state.hands[data.player] = removeCards(state.hands[data.player] || [], cards);
        renderHand(data.player);
      }
      const cardText = cards.map(rankText).join(" ");
      const title = cards.length ? `${playerName(data.player)} 出 ${data.combo}${cardText ? ` ${cardText}` : ""}` : `${playerName(data.player)} 过`;
      document.getElementById("lastTitle").textContent = title;
      renderCards("lastCards", cards, true);
      const details = [
        data.invalid_reason ? `裁判修正：${data.invalid_reason}` : "",
        reasonText(data.reason),
      ].filter(Boolean).join("；");
      addLog(`${title}，剩余 ${data.remaining} 张`, details);
    });

    source.addEventListener("game_result", (event) => {
      const data = JSON.parse(event.data).result;
      document.querySelectorAll(".player").forEach(el => el.classList.remove("thinking"));
      document.getElementById("status").textContent = `对局结束：${data.winnerName} 获胜`;
      const grid = document.getElementById("scoreGrid");
      grid.innerHTML = "";
      Object.entries(data.points).forEach(([seat, point]) => {
        const div = document.createElement("div");
        div.className = "score";
        div.innerHTML = `<b>${playerName(seat)}</b><span>${point > 0 ? "+" : ""}${point} 分</span>`;
        grid.appendChild(div);
      });
      addLog(`对局结束：${data.winnerName} 获胜`, `阵营：${data.winnerSide}；倍率 ${data.multiplier}；${data.spring}`);
    });

    source.addEventListener("game_error", (event) => {
      const data = JSON.parse(event.data);
      document.getElementById("status").textContent = `对局异常：${data.message}`;
      addLog("对局异常", data.message);
    });

    function compareCards(a, b) {
      const order = ["3","4","5","6","7","8","9","10","J","Q","K","A","2","BJ","RJ"];
      return order.indexOf(a) - order.indexOf(b);
    }

    function handSummary(hand) {
      const text = (hand || []).map(rankText).join(" ");
      return `手牌 ${hand.length} 张：${text}`;
    }
  </script>
</body>
</html>"""
