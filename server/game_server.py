import threading
import time
from core.game_state import GameState
from server.network import start_network_server, send_message, clients, get_message
from core.battle import run_match
from core.shop import show_shop
from utils.logger import log
import random
import sys


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


def game_loop():
    global game_state
    while not game_state.is_game_over():
        game_state.current_round += 1
        log(f"\n=== 第 {game_state.current_round} 大回合 ===", "cyan")

        alive = [p for p in game_state.players if not p.is_eliminated]
        if len(alive) <= 1:
            break

        log(f"存活玩家: {[p.name for p in alive]}", "cyan")
        random.shuffle(alive)
        log(f"随机顺序: {[p.name for p in alive]}", "cyan")
        matches = []
        for i in range(0, len(alive) - 1, 2):
            matches.append((alive[i], alive[i + 1]))
        log(f"配对: {[(p1.name, p2.name) for p1, p2 in matches]}", "yellow")

        players_in_shop = []
        match_threads = []
        
        def run_match_thread(p1_id, p2_id, p1_name, p2_name, result_list, all_players):
            p1 = next(p for p in all_players if p.id == p1_id)
            p2 = next(p for p in all_players if p.id == p2_id)
            p1_copy, p2_copy, is_draw = run_match(p1, p2)
            result = {"p1_id": p1_id, "p2_id": p2_id, "p1_copy": p1_copy, "p2_copy": p2_copy, "is_draw": is_draw}
            result_list.append(result)

        match_results = []
        all_players = list(game_state.players)
        for p1, p2 in matches:
            t = threading.Thread(target=run_match_thread, args=(p1.id, p2.id, p1.name, p2.name, match_results, all_players), daemon=True)
            match_threads.append(t)
            t.start()

        for t in match_threads:
            t.join()

        log(f"DEBUG match_results: {match_results}", "yellow")

        for result in match_results:
            p1_id = result["p1_id"]
            p2_id = result["p2_id"]
            p1_copy = result["p1_copy"]
            p2_copy = result["p2_copy"]
            is_draw = result["is_draw"]
            
            p1 = next(p for p in game_state.players if p.id == p1_id)
            p2 = next(p for p in game_state.players if p.id == p2_id)
            
            log(f"DEBUG 更新血量: {p1.name} {p1.health}->{p1_copy.health}, {p2.name} {p2.health}->{p2_copy.health}", "yellow")
            
            if is_draw:
                log(f"🤝 {p1.name} 与 {p2.name} 平局", "yellow")
                p1.win_streak = 0
                p1.lose_streak = 0
                p2.win_streak = 0
                p2.lose_streak = 0
                p1.health = p1_copy.health
                p2.health = p2_copy.health
                players_in_shop.extend([p1, p2])
            else:
                p1.health = p1_copy.health
                p2.health = p2_copy.health
                winner = p1 if p1.health > p2.health else p2
                loser = p2 if p1.health > p2.health else p1
                winner.win_streak += 1
                loser.lose_streak += 1
                if loser.health <= 0:
                    loser.is_eliminated = True
                    log(f"💀 {loser.name} 被淘汰！", "red")
                players_in_shop.append(winner)
            log(f"⚔️ {p1.name} VS {p2.name} 结束", "green")

        if len(alive) % 2 == 1:
            bye = alive[-1]
            log(f"👋 {bye.name} 本轮轮空，直接进入商店", "yellow")
            players_in_shop.append(bye)

        log(f"DEBUG 进入商店的玩家: {[p.name for p in players_in_shop]}", "yellow")

        def health_fn():
            return [{"name": p.name, "health": p.health, "is_eliminated": p.is_eliminated} for p in alive]

        log(f"DEBUG 所有存活玩家进入商店: {[p.name for p in alive if not p.is_eliminated]}", "yellow")
        
        shop_threads = []
        for p in alive:
            if not p.is_eliminated:
                log(f"DEBUG 启动商店线程 for {p.name}", "yellow")
                t = threading.Thread(target=show_shop, args=(p, health_fn()))
                shop_threads.append(t)
                t.start()

        for t in shop_threads:
            t.join()

        log(f"DEBUG 商店结束，玩家血量: {[(p.name, p.health) for p in game_state.players]}", "yellow")
        
        for player in game_state.players:
            if player.is_eliminated:
                continue
            income = _round_income(player)
            log(f"DEBUG 结算: {player.name} +{income['total']}金币 (基础{income['base']}+连胜{income['streak']}+利息{income['interest']})", "cyan")
            player.gold += income["total"]
            conn = clients.get(player.id)
            if conn:
                from server.network import send_message
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
                    "health_overview": [{"name": p.name, "health": p.health, "is_eliminated": p.is_eliminated} for p in game_state.players]
                })

        alive = [p for p in game_state.players if not p.is_eliminated]
        if len(alive) <= 1:
            break

    winner = next((p for p in game_state.players if not p.is_eliminated), None)
    log(f"\n🏆 游戏结束！最终胜利者是：{winner.name if winner else '未知'} 🎉", "green")

    time.sleep(3)
    sys.exit(0)


def start_server(host_name, max_players=4):
    global game_state
    game_state = GameState()
    game_state.max_players = max_players

    def on_player_join(player, conn):
        log(f"✅ {player.name} 加入游戏 ({len(game_state.players)}/{game_state.max_players})", "green")
        if len(game_state.players) == game_state.max_players:
            log("🎉 所有玩家已就位，开始游戏！", "green")
            threading.Thread(target=game_loop, daemon=False).start()

    start_network_server("0.0.0.0", 5555, game_state, on_player_join)

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        log("\n🛑 服务器主动关闭...", "red")
        sys.exit(0)