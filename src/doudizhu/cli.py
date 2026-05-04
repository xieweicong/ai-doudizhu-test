from __future__ import annotations

import argparse
from random import Random
from typing import Any, Sequence

from .ai import built_in_ai_names, create_ai
from .cards import format_cards
from .env import load_dotenv
from .game import DouDizhuGame, GameConfig, Player, run_match


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="doudizhu", description="AI-vs-AI Dou Dizhu CLI")
    subparsers = parser.add_subparsers(dest="command")

    play_parser = subparsers.add_parser("play", help="run one game and print the play log")
    _add_player_args(play_parser)
    play_parser.add_argument("--seed", type=int, default=None)
    play_parser.add_argument("--verbose", action="store_true", help="show initial hands")
    play_parser.add_argument("--show-reasons", action="store_true", help="show AI public reasons")
    play_parser.add_argument("--expose-all-hands", action="store_true", help="let AI views include all hands")

    run_parser = subparsers.add_parser("run", help="run many games and print statistics")
    _add_player_args(run_parser)
    run_parser.add_argument("--rounds", type=int, default=10)
    run_parser.add_argument("--seed", type=int, default=None)
    run_parser.add_argument("--expose-all-hands", action="store_true", help="let AI views include all hands")

    subparsers.add_parser("list-ai", help="list built-in AI names")

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "list-ai":
        print("Built-in AI:")
        for name in built_in_ai_names():
            print(f"  - {name}")
        print("Custom AI: module.path:ClassName or process:your-command")
        return 0
    if args.command == "play":
        players = _make_players(args.players, args.seed)
        return _play_one(args, players)
    if args.command == "run":
        if args.rounds <= 0:
            raise SystemExit("--rounds must be positive")
        players = _make_players(args.players, args.seed)
        return _run_many(args, players)
    raise SystemExit(f"unknown command: {args.command}")


def _add_player_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--players",
        nargs=3,
        default=["greedy", "conservative", "random"],
        metavar=("P0", "P1", "P2"),
        help="three AI specs: local name, deepseek@model, openrouter@model, bedrock@model-id, module:Class, or process:command",
    )


def _make_players(specs: list[str], seed: int | None) -> list[Player]:
    rng = Random(seed)
    players: list[Player] = []
    for seat, spec in enumerate(specs):
        ai_rng = Random(rng.randrange(2**63))
        ai = create_ai(spec, ai_rng)
        name = getattr(ai, "name", spec)
        players.append(Player(seat=seat, name=f"P{seat}:{name}", ai=ai))
    return players


def _play_one(args: argparse.Namespace, players: list[Player]) -> int:
    print("== 对局信息 ==", flush=True)
    for player in players:
        print(f"P{player.seat}: {player.name}", flush=True)
    if args.seed is not None:
        print(f"随机种子: {args.seed}", flush=True)
    print("\n== 实时播报 ==", flush=True)
    game = DouDizhuGame(
        players,
        GameConfig(seed=args.seed, expose_all_hands=args.expose_all_hands),
        event_handler=lambda event, payload: _print_live_event(event, payload, players, args.show_reasons),
    )
    result = game.play()

    if args.verbose:
        print("\n== 发牌复盘 ==")
        for seat, cards in result.initial_hands.items():
            print(f"{players[seat].name}: {format_cards(cards)}")

    print("\n== 叫分结果 ==")
    for bid in result.bids:
        reason = _format_reason(bid.reason, args.show_reasons)
        print(f"{players[bid.player].name}: {bid.bid} 分{reason}")
    print(f"地主: {players[result.landlord].name}")
    print(f"底牌: {format_cards(result.bottom_cards)}")

    print("\n== 出牌记录 ==")
    for play in result.plays:
        print(_format_play_log_line(play, players, args.show_reasons))

    print("\n== 对局结果 ==")
    print(_format_result_summary(result, players))
    print("积分:")
    for seat, points in result.points.items():
        print(f"{players[seat].name}: {points:+d}")
    return 0


def _print_live_event(
    event: str,
    payload: dict[str, Any],
    players: list[Player],
    show_reasons: bool,
) -> None:
    if event == "initial_deal":
        print("[发牌] 三家起手牌如下:", flush=True)
        for seat in range(3):
            hand = payload["hands"][seat]
            print(f"  {players[seat].name}（{len(hand)} 张）: {format_cards(hand)}", flush=True)
        print(f"  底牌候选（{len(payload['bottom_cards'])} 张）: {format_cards(payload['bottom_cards'])}", flush=True)
        return
    if event == "bid_thinking":
        player = players[payload["player"]].name
        print(
            f"[叫分] {player} 思考中，可选={payload['valid_bids']}，当前最高={payload['highest_bid']}",
            flush=True,
        )
        return
    if event == "bid_result":
        record = payload["record"]
        player = players[record.player].name
        reason = _format_reason(record.reason, show_reasons)
        print(f"[叫分] {player} 叫 {record.bid} 分{reason}", flush=True)
        return
    if event == "landlord_selected":
        landlord = players[payload["landlord"]].name
        bottom = format_cards(payload["bottom_cards"])
        print(f"[定地主] 地主={landlord}，叫分={payload['bid']}，底牌={bottom}", flush=True)
        return
    if event == "redeal":
        print(f"[重发] 三家都不叫，本局重新发牌，第 {payload['redeals']} 次", flush=True)
        return
    if event == "play_thinking":
        player = players[payload["player"]].name
        tail = f"，目标={payload['last_combo']}" if payload["last_combo"] else "，目标=-"
        print(
            f"[第 {payload['turn']:03d} 手] {player} 思考中，合法动作={payload['legal_count']} "
            f"，可过={_yes_no(payload['can_pass'])}{tail}",
            flush=True,
        )
        return
    if event == "play_result":
        record = payload["record"]
        print(_format_play_log_line(record, players, show_reasons, live=True), flush=True)
        return


def _run_many(args: argparse.Namespace, players: list[Player]) -> int:
    report = run_match(
        players,
        rounds=args.rounds,
        seed=args.seed,
        expose_all_hands=args.expose_all_hands,
    )
    print(f"总局数: {report['rounds']}")
    print(f"随机种子: {report['seed']}")
    side_wins = report["side_wins"]
    print(
        "阵营胜场: "
        f"地主={side_wins.get('landlord', 0)}，"
        f"农民={side_wins.get('farmers', 0)}"
    )
    print()
    header = (
        f"{'座位':<4} {'AI':<34} {'胜场':>9} {'胜率':>7} "
        f"{'地主局':>8} {'地主胜率':>10} {'农民局':>8} {'农民胜率':>10} {'积分':>8}"
    )
    print(header)
    print("-" * len(header))
    for seat in sorted(report["stats"]):
        row = report["stats"][seat]
        games = row["games"]
        landlord_games = row["landlord_games"]
        farmer_games = row["farmer_games"]
        print(
            f"{row['seat']:<4} {row['name']:<34} "
            f"{row['wins']:>7}/{games:<3} {_pct(row['wins'], games):>7} "
            f"{landlord_games:>8} {_pct(row['landlord_wins'], landlord_games):>10} "
            f"{farmer_games:>8} {_pct(row['farmer_wins'], farmer_games):>10} "
            f"{row['points']:>8}"
        )
    return 0


def _pct(value: int, total: int) -> str:
    if total == 0:
        return "-"
    return f"{value / total * 100:5.1f}%"


def _format_play_log_line(play, players: list[Player], show_reasons: bool, live: bool = False) -> str:
    prefix = f"[第 {play.turn:03d} 手] " if live else f"{play.turn:03d} "
    role = _role_label(play.role)
    action = "过" if play.is_pass else f"出 {play.combo} {format_cards(play.cards)}"
    invalid = f" [裁判修正: {play.invalid_reason}]" if play.invalid_reason else ""
    reason = _format_reason(play.reason, show_reasons)
    return f"{prefix}{players[play.player].name}（{role}）{action}，剩余 {play.remaining} 张{invalid}{reason}"


def _format_result_summary(result, players: list[Player]) -> str:
    winner = players[result.winner].name
    landlord = players[result.landlord].name
    farmers = "、".join(players[seat].name for seat in result.farmers)
    spring = _spring_label(result.spring)
    return (
        f"胜方: {winner}（{_winner_side_label(result.winner_side)}）\n"
        f"地主: {landlord}\n"
        f"农民: {farmers}\n"
        f"叫分: {result.bid}\n"
        f"倍率: {result.multiplier}\n"
        f"春天: {spring}\n"
        f"总手数: {result.turns}\n"
        f"底牌: {format_cards(result.bottom_cards)}"
    )


def _role_label(role: str) -> str:
    return {"landlord": "地主", "farmer": "农民"}.get(role, role)


def _winner_side_label(side: str) -> str:
    return {"landlord": "地主", "farmers": "农民"}.get(side, side)


def _spring_label(value: str | None) -> str:
    return {
        None: "无",
        "spring": "春天",
        "anti-spring": "反春",
    }[value]


def _format_reason(reason: str, show_reasons: bool) -> str:
    if not show_reasons or not reason:
        return ""
    compact = reason.strip().replace("\n", " ")
    if len(compact) > 100:
        compact = compact[:97] + "..."
    return f"  理由: {compact}"


def _yes_no(value: bool) -> str:
    return "是" if value else "否"


if __name__ == "__main__":
    raise SystemExit(main())
