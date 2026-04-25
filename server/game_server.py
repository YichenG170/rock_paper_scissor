from core.game_state import GameState
from server.network import start_network_server, send_message, clients, get_message
from core.battle import run_match
from core.shop import show_shop
from utils.logger import log
import threading
import random
import time
import sys

game_state = None


def _build_health_overview(players):
    return [
        {"name": p.name, "health": p.health, "is_eliminated": p.is_eliminated}
        for p in players
    ]


def _send_state_update(player, players, phase):
    conn = clients.get(player.id)
    if not conn:
        return
    send_message(conn, {
        "type": "state_update",
        "phase": phase,
        "your_health": player.health,
        "your_gold": player.gold,
        "your_bag_size": player.bag_size,
        "your_attack": player.attack,
        "your_interest_rate": player.interest_rate,
        "your_win_streak": player.win_streak,
        "your_lose_streak": player.lose_streak,
        "health_overview": _build_health_overview(players)
    })


def _round_income(player):
    base_income = 5
    streak_bonus = 2 if max(player.win_streak, player.lose_streak) >= 2 else 0
    interest_income = min(5, int(player.gold * player.interest_rate))
    total_income = base_income + streak_bonus + interest_income
    return {
        "base": base_income,
        "streak": streak_bonus,
        "interest": interest_income,
        "total": total_income,
    }


def _has_talent_effect(player, effect_type):
    for t in player.talents:
        effect = t.get("effect", {})
        if effect.get("type") == effect_type:
            return True
    return False

def start_server(host_name):
    global game_state
    game_state = GameState()

    def on_player_join(player, conn):
        log(f"✅ {player.name} 加入游戏 ({len(game_state.players)}/{game_state.max_players})", "green")
        if len(game_state.players) == game_state.max_players:
            log("🎉 所有玩家已就位，开始游戏！", "green")
            threading.Thread(target=game_loop, daemon=False).start()   # ← 关键：改成 daemon=False

    start_network_server("0.0.0.0", 5555, game_state, on_player_join)

    # 保持主线程存活，防止提前退出
    try:
        while True:
            time.sleep(0.5)   # 每0.5秒检查一次，响应 Ctrl+C
    except KeyboardInterrupt:
        log("\n🛑 服务器主动关闭...", "red")
        sys.exit(0)

def game_loop():
    global game_state
    while not game_state.is_game_over():
        game_state.current_round += 1
        log(f"\n=== 第 {game_state.current_round} 大回合 ===", "cyan")

        alive = [p for p in game_state.players if not p.is_eliminated]
        if len(alive) <= 1:
            break

        random.shuffle(alive)
        matches = []
        for i in range(0, len(alive) - 1, 2):
            matches.append((alive[i], alive[i + 1]))

        if len(alive) % 2 == 1:
            bye = alive[-1]
            log(f"👋 {bye.name} 本轮轮空，直接进入商店", "yellow")

        for p1, p2 in matches:
            winner, loser, is_draw = run_match(p1, p2)

            if is_draw:
                log(f"🤝 {p1.name} 与 {p2.name} 平局，双方不掉血", "yellow")
                p1.win_streak = 0
                p1.lose_streak = 0
                p2.win_streak = 0
                p2.lose_streak = 0
            else:
                damage = winner.attack
                if _has_talent_effect(winner, "double_damage_on_win"):
                    damage *= 2
                loser.health -= damage
                winner.win_streak += 1
                winner.lose_streak = 0
                loser.lose_streak += 1
                loser.win_streak = 0
                if loser.health <= 0:
                    loser.is_eliminated = True
                    log(f"💀 {loser.name} 被淘汰！", "red")

            _send_state_update(p1, game_state.players, "post_match")
            _send_state_update(p2, game_state.players, "post_match")

        # 回合经济结算：基础金币 + 连胜/连败奖励 + 利息（取整，封顶 5）
        for player in alive:
            if player.is_eliminated:
                continue
            income = _round_income(player)
            player.gold += income["total"]
            conn = clients.get(player.id)
            if conn:
                send_message(conn, {
                    "type": "state_update",
                    "phase": "round_income",
                    "your_health": player.health,
                    "your_gold": player.gold,
                    "your_bag_size": player.bag_size,
                    "your_attack": player.attack,
                    "your_interest_rate": player.interest_rate,
                    "your_win_streak": player.win_streak,
                    "your_lose_streak": player.lose_streak,
                    "income": income,
                    "health_overview": _build_health_overview(game_state.players)
                })

        # 商店阶段
        log("\n=== 商店阶段 ===", "yellow")
        for player in alive:
            if not player.is_eliminated:
                show_shop(player, _build_health_overview(game_state.players))

    winner = next((p for p in game_state.players if not p.is_eliminated), None)
    log(f"\n🏆 游戏结束！最终胜利者是：{winner.name if winner else '未知'} 🎉", "green")
    
    # 游戏结束后自动退出
    time.sleep(3)
    sys.exit(0)