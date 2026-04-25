from utils.logger import log
from server.network import send_message, get_message, clients   # ← 补全 clients
from core.rps_bag import generate_initial_bag
import random


def _build_health_overview(p1, p2):
    return [
        {"name": p1.name, "health": p1.health, "is_eliminated": p1.is_eliminated},
        {"name": p2.name, "health": p2.health, "is_eliminated": p2.is_eliminated},
    ]

def _has_available_rps(player):
    return any(player.rps_bag.get(k, 0) > 0 for k in ("rock", "scissors", "paper"))


def _talent_total(player, effect_type):
    total = 0
    for t in player.talents:
        eff = t.get("effect", {})
        if eff.get("type") == effect_type:
            total += int(eff.get("value", 0))
    return total


def _has_talent_effect(player, effect_type):
    return _talent_total(player, effect_type) > 0


def _has_talent_id(player, talent_id):
    return any(t.get("id") == talent_id for t in player.talents)


def _random_valid_choice(player):
    options = [k for k in ("rock", "scissors", "paper") if player.rps_bag.get(k, 0) > 0]
    if not options:
        return None
    return random.choice(options)


def _convert_random_non_rock_to_rock(player):
    non_rock = [k for k in ("scissors", "paper") if player.rps_bag.get(k, 0) > 0]
    if not non_rock:
        return False
    picked = random.choice(non_rock)
    player.rps_bag[picked] -= 1
    player.rps_bag["rock"] = player.rps_bag.get("rock", 0) + 1
    return True

def _convert_random_to_type(player, target_type):
    """把随机一个非目标类型的拳变成目标类型"""
    others = [k for k in ("rock", "scissors", "paper") if k != target_type and player.rps_bag.get(k, 0) > 0]
    if not others:
        return False
    picked = random.choice(others)
    player.rps_bag[picked] -= 1
    player.rps_bag[target_type] = player.rps_bag.get(target_type, 0) + 1
    return True

def _add_random_rps(player, count):
    for _ in range(max(0, int(count))):
        player.add_to_bag(random.choice(["rock", "scissors", "paper"]), 1)


def _gain_gold_in_battle(player, amount):
    if amount <= 0:
        return
    player.gold += amount
    
    if _has_talent_effect(player, "battle_gold_to_scissors"):
        for _ in range(amount):
            player.add_to_bag("scissors", 1)
    
    if _has_talent_effect(player, "battle_gold_to_random_bag"):
        _add_random_rps(player, amount)


def _apply_talent_match_start(player):
    for t in player.talents:
        eff = t.get("effect", {})
        effect_type = eff.get("type")
        value = int(eff.get("value", 0))
        if effect_type == "battle_start_add_bag":
            choice = eff.get("choice")
            if choice in ("rock", "scissors", "paper") and value > 0:
                player.add_to_bag(choice, value)
        elif effect_type == "battle_start_add_random" and value > 0:
            _add_random_rps(player, value)

def _handle_paper_win_effects(winner, loser, match_state):
    if _has_talent_effect(winner, "paper_win_heal"):
        heal = _talent_total(winner, "paper_win_heal")
        winner.health += heal
        log(f"{winner.name} [纸上春风] 回复 {heal} 血量", "green")

    if _has_talent_effect(winner, "paper_over_5_win_bonus"):
        if winner.rps_bag.get("paper", 0) > 5:
            bonus = _talent_total(winner, "paper_over_5_win_bonus")
            match_state["round_bonus"][winner.id] += bonus
            log(f"{winner.name} [纸海狂潮] 额外 +{bonus} 分", "green")


def _handle_scissors_win_effects(winner, loser, match_state):
    # 偷金币
    if _has_talent_effect(winner, "scissors_win_drain_gold"):
        steal = _talent_total(winner, "scissors_win_drain_gold") * 2  # 每个天赋偷2
        stolen = min(steal, max(0, loser.gold))
        loser.gold -= stolen
        _gain_gold_in_battle(winner, stolen)
        log(f"{winner.name} [剪财夺金] 偷取 {stolen} 金币", "yellow")

    # 伤害加成（本场持续）
    if _has_talent_effect(winner, "scissors_win_damage_plus"):
        match_state.setdefault("damage_bonus", {}).setdefault(winner.id, 0)
        match_state["damage_bonus"][winner.id] += _talent_total(winner, "scissors_win_damage_plus")
        log(f"{winner.name} [剪刀手] 本场伤害 +{match_state['damage_bonus'][winner.id]}", "green")


def _handle_consecutive_choice(player, last_choice, current_choice):
    if last_choice == current_choice and last_choice is not None:
        if _has_talent_effect(player, "consecutive_same_choice_gold"):
            _gain_gold_in_battle(player, 1)
            log(f"{player.name} [连招赏金] 连续相同出拳 +1 金币", "cyan")


def _consume_item(player, item_id):
    for item in player.items:
        if item.get("id") == item_id and not item.get("_used_this_match", False):
            item["_used_this_match"] = True
            return item
    return None


def _reset_item_for_new_match(player):
    for item in player.items:
        if item.get("refresh_each_match", True):
            item["_used_this_match"] = False


def _available_items_for_match(player):
    return [
        {k: v for k, v in item.items() if not str(k).startswith("_")}
        for item in player.items
        if not item.get("_used_this_match", False)
    ]


def _rarity_cn(rarity):
    mapping = {
        "common": "普通",
        "rare": "稀有",
        "epic": "史诗",
        "legendary": "传说",
    }
    return mapping.get((rarity or "").lower(), "普通")


def _apply_battle_item(player, opponent, item_id, match_state):
    if not item_id:
        return None

    item = _consume_item(player, item_id)
    if not item:
        return None

    effect = item.get("effect", {})
    effect_type = effect.get("type")
    value = int(effect.get("value", 0))
    choice = effect.get("choice")

    if effect_type == "add_bag" and choice in ("rock", "scissors", "paper") and value > 0:
        player.add_to_bag(choice, value)
    elif effect_type == "add_random_bag" and value > 0:
        for _ in range(value):
            player.add_to_bag(random.choice(["rock", "scissors", "paper"]), 1)
    elif effect_type == "score_bonus" and value > 0:
        match_state["round_bonus"][player.id] += value
    elif effect_type == "heal" and value > 0:
        player.health += value
    elif effect_type == "gain_gold" and value > 0:
        _gain_gold_in_battle(player, value)
    elif effect_type == "drain_gold" and value > 0:
        stolen = min(value, max(0, opponent.gold))
        opponent.gold -= stolen
        _gain_gold_in_battle(player, stolen)
    elif effect_type == "reroll_bag":
        player.rps_bag = generate_initial_bag(player.bag_size)
    elif effect_type == "reroll_opponent_bag":
        opponent.rps_bag = generate_initial_bag(opponent.bag_size)
    elif effect_type == "reduce_opponent_score_bonus" and value > 0:
        match_state["round_bonus"][opponent.id] = max(0, match_state["round_bonus"][opponent.id] - value)
    elif effect_type == "boost_max_bag" and value > 0:
        key = max(player.rps_bag, key=lambda k: player.rps_bag.get(k, 0))
        player.add_to_bag(key, value)
    elif effect_type == "next_match_score_swing" and value > 0:
        player.pending_score_swing += value

    return f"{item.get('name', '未知')}[{_rarity_cn(item.get('rarity'))}]"


def _send_round_result(
    p1,
    p2,
    choice1,
    choice2,
    score1,
    score2,
    round_winner_name,
    round_no,
    max_rounds,
    item_used_1,
    item_used_2
):
    health_overview = _build_health_overview(p1, p2)
    send_message(clients[p1.id], {
        "type": "round_result",
        "your_choice": choice1,
        "opponent_choice": choice2,
        "round_winner": round_winner_name,
        "round_no": round_no,
        "max_rounds": max_rounds,
        "score_you": score1,
        "score_opponent": score2,
        "item_used_you": item_used_1,
        "item_used_opponent": item_used_2,
        "your_health": p1.health,
        "opponent_health": p2.health,
        "your_gold": p1.gold,
        "your_bag_size": p1.bag_size,
        "your_attack": p1.attack,
        "your_interest_rate": p1.interest_rate,
        "your_win_streak": p1.win_streak,
        "your_lose_streak": p1.lose_streak,
        "health_overview": health_overview
    })
    send_message(clients[p2.id], {
        "type": "round_result",
        "your_choice": choice2,
        "opponent_choice": choice1,
        "round_winner": round_winner_name,
        "round_no": round_no,
        "max_rounds": max_rounds,
        "score_you": score2,
        "score_opponent": score1,
        "item_used_you": item_used_2,
        "item_used_opponent": item_used_1,
        "your_health": p2.health,
        "opponent_health": p1.health,
        "your_gold": p2.gold,
        "your_bag_size": p2.bag_size,
        "your_attack": p2.attack,
        "your_interest_rate": p2.interest_rate,
        "your_win_streak": p2.win_streak,
        "your_lose_streak": p2.lose_streak,
        "health_overview": health_overview
    })


def _send_match_result(winner, loser, score1, score2, is_draw=False):
    health_overview = _build_health_overview(winner, loser)
    if is_draw:
        send_message(clients[winner.id], {
            "type": "match_result",
            "result": "draw",
            "winner": None,
            "loser": None,
            "score_you": score1,
            "score_opponent": score2,
            "your_health": winner.health,
            "opponent_health": loser.health,
            "your_gold": winner.gold,
            "your_bag_size": winner.bag_size,
            "your_attack": winner.attack,
            "your_interest_rate": winner.interest_rate,
            "your_win_streak": winner.win_streak,
            "your_lose_streak": winner.lose_streak,
            "health_overview": health_overview
        })
        send_message(clients[loser.id], {
            "type": "match_result",
            "result": "draw",
            "winner": None,
            "loser": None,
            "score_you": score2,
            "score_opponent": score1,
            "your_health": loser.health,
            "opponent_health": winner.health,
            "your_gold": loser.gold,
            "your_bag_size": loser.bag_size,
            "your_attack": loser.attack,
            "your_interest_rate": loser.interest_rate,
            "your_win_streak": loser.win_streak,
            "your_lose_streak": loser.lose_streak,
            "health_overview": health_overview
        })
        return

    send_message(clients[winner.id], {
        "type": "match_result",
        "result": "win",
        "winner": winner.name,
        "loser": loser.name,
        "score_you": max(score1, score2),
        "score_opponent": min(score1, score2),
        "your_health": winner.health,
        "opponent_health": loser.health,
        "your_gold": winner.gold,
        "your_bag_size": winner.bag_size,
        "your_attack": winner.attack,
        "your_interest_rate": winner.interest_rate,
        "your_win_streak": winner.win_streak,
        "your_lose_streak": winner.lose_streak,
        "health_overview": health_overview
    })
    send_message(clients[loser.id], {
        "type": "match_result",
        "result": "lose",
        "winner": winner.name,
        "loser": loser.name,
        "score_you": min(score1, score2),
        "score_opponent": max(score1, score2),
        "your_health": loser.health,
        "opponent_health": winner.health,
        "your_gold": loser.gold,
        "your_bag_size": loser.bag_size,
        "your_attack": loser.attack,
        "your_interest_rate": loser.interest_rate,
        "your_win_streak": loser.win_streak,
        "your_lose_streak": loser.lose_streak,
        "health_overview": health_overview
    })


def run_match(p1, p2):
    # 每次进入新对战都重置出拳包，避免上一场消耗永久生效。
    p1.rps_bag = generate_initial_bag(p1.bag_size)
    p2.rps_bag = generate_initial_bag(p2.bag_size)
    _reset_item_for_new_match(p1)
    _reset_item_for_new_match(p2)
    _apply_talent_match_start(p1)
    _apply_talent_match_start(p2)

    score1 = 0
    score2 = 0
    rounds_played = 0
    max_rounds = 5
    match_state = {
        "round_bonus": {p1.id: 0, p2.id: 0},
        "score_swing": {p1.id: p1.pending_score_swing, p2.id: p2.pending_score_swing},
        "last_rock_trigger": {p1.id: False, p2.id: False},
        "damage_bonus": {p1.id: 0, p2.id: 0},   # 新增
        "last_choice": {p1.id: None, p2.id: None}  # 用于连招
    }
    p1.pending_score_swing = 0
    p2.pending_score_swing = 0
    log(f"\n=== {p1.name} VS {p2.name} 开始 ===", "cyan")

    while score1 < 3 and score2 < 3 and rounds_played < max_rounds:
        health_overview = _build_health_overview(p1, p2)
        send_message(clients[p1.id], {
            "type": "choose_rps",
            "bag": p1.rps_bag,
            "opponent": p2.name,
            "items": _available_items_for_match(p1),
            "round_no": rounds_played + 1,
            "max_rounds": max_rounds,
            "your_health": p1.health,
            "opponent_health": p2.health,
            "your_gold": p1.gold,
            "your_bag_size": p1.bag_size,
            "your_attack": p1.attack,
            "your_interest_rate": p1.interest_rate,
            "your_win_streak": p1.win_streak,
            "your_lose_streak": p1.lose_streak,
            "health_overview": health_overview
        })
        send_message(clients[p2.id], {
            "type": "choose_rps",
            "bag": p2.rps_bag,
            "opponent": p1.name,
            "items": _available_items_for_match(p2),
            "round_no": rounds_played + 1,
            "max_rounds": max_rounds,
            "your_health": p2.health,
            "opponent_health": p1.health,
            "your_gold": p2.gold,
            "your_bag_size": p2.bag_size,
            "your_attack": p2.attack,
            "your_interest_rate": p2.interest_rate,
            "your_win_streak": p2.win_streak,
            "your_lose_streak": p2.lose_streak,
            "health_overview": health_overview
        })

        msg1 = get_message(p1.id)
        msg2 = get_message(p2.id)

        item_used_1 = _apply_battle_item(p1, p2, msg1.get("use_item"), match_state)
        item_used_2 = _apply_battle_item(p2, p1, msg2.get("use_item"), match_state)
        choice1 = msg1.get("choice")
        choice2 = msg2.get("choice")

        if rounds_played == 0 and _has_talent_id(p1, "berserker_oath"):
            choice1 = _random_valid_choice(p1)
        if rounds_played == 0 and _has_talent_id(p2, "berserker_oath"):
            choice2 = _random_valid_choice(p2)

        if not p1.use_rps(choice1):
            log(f"{p1.name} 出拳无效！", "red")
            choice1 = None
        if not p2.use_rps(choice2):
            log(f"{p2.name} 出拳无效！", "red")
            choice2 = None

        if choice1 == "rock" and _has_talent_effect(p1, "on_play_rock_convert_opponent_to_rock"):
            _convert_random_non_rock_to_rock(p2)
        if choice2 == "rock" and _has_talent_effect(p2, "on_play_rock_convert_opponent_to_rock"):
            _convert_random_non_rock_to_rock(p1)

        if choice1 == "rock" and p1.rps_bag.get("rock", 0) == 0 and _has_talent_effect(p1, "on_last_rock_convert_to_rock"):
            match_state["last_rock_trigger"][p1.id] = True
        if choice2 == "rock" and p2.rps_bag.get("rock", 0) == 0 and _has_talent_effect(p2, "on_last_rock_convert_to_rock"):
            match_state["last_rock_trigger"][p2.id] = True

        if choice1 == "scissors" and _has_talent_effect(p1, "on_play_scissors_convert_opp_to_paper"):
            _convert_random_to_type(p2, "paper")
        if choice2 == "scissors" and _has_talent_effect(p2, "on_play_scissors_convert_opp_to_paper"):
            _convert_random_to_type(p1, "paper")

        if choice1 == "paper" and _has_talent_effect(p1, "on_play_paper_reroll_all"):
            p1.rps_bag = generate_initial_bag(p1.bag_size)
            log(f"{p1.name} 全部出拳随机重置", "magenta")
        if choice2 == "paper" and _has_talent_effect(p2, "on_play_paper_reroll_all"):
            p2.rps_bag = generate_initial_bag(p2.bag_size)
            log(f"{p2.name} 全部出拳随机重置", "magenta")

        rounds_played += 1

        if choice1 == choice2 and choice1 is not None:
            _handle_consecutive_choice(p1, match_state["last_choice"][p1.id], choice1)
            _handle_consecutive_choice(p2, match_state["last_choice"][p2.id], choice2)
            match_state["last_choice"][p1.id] = choice1
            match_state["last_choice"][p2.id] = choice2
            
            log("平局！双方出拳相同", "yellow")
            _send_round_result(
                p1, p2, choice1, choice2, score1, score2, None,
                rounds_played, max_rounds, item_used_1, item_used_2
            )
            if match_state["last_rock_trigger"][p1.id]:
                _convert_random_non_rock_to_rock(p1)
                match_state["last_rock_trigger"][p1.id] = False
            if match_state["last_rock_trigger"][p2.id]:
                _convert_random_non_rock_to_rock(p2)
                match_state["last_rock_trigger"][p2.id] = False
            continue

        win_map = {("rock", "scissors"): True, ("scissors", "paper"): True, ("paper", "rock"): True}
        if choice1 and choice2 and (choice1, choice2) in win_map:
            _handle_consecutive_choice(p1, match_state["last_choice"][p1.id], choice1)
            match_state["last_choice"][p1.id] = choice1
            match_state["last_choice"][p2.id] = choice2

            gain = 1 + match_state["round_bonus"][p1.id]
            if choice1 == "rock":
                gain += _talent_total(p1, "rock_win_score_bonus")
            if match_state["score_swing"][p1.id] > 0:
                gain += match_state["score_swing"][p1.id]
            score1 += gain
            if choice1 == "paper":
                _handle_paper_win_effects(p1, p2, match_state)
            if choice1 == "scissors":
                _handle_scissors_win_effects(p1, p2, match_state)
            match_state["round_bonus"][p1.id] = 0
            if match_state["score_swing"][p1.id] > 0:
                match_state["score_swing"][p1.id] = 0
            if match_state["score_swing"][p2.id] > 0:
                score2 = max(0, score2 - match_state["score_swing"][p2.id])
                match_state["score_swing"][p2.id] = 0
            log(f"{p1.name} 获胜本小局！({score1}:{score2})", "green")
            _send_round_result(
                p1, p2, choice1, choice2, score1, score2, p1.name,
                rounds_played, max_rounds, item_used_1, item_used_2
            )
        elif choice1 and choice2:
            _handle_consecutive_choice(p2, match_state["last_choice"][p2.id], choice2)
            match_state["last_choice"][p1.id] = choice1
            match_state["last_choice"][p2.id] = choice2

            gain = 1 + match_state["round_bonus"][p2.id]
            if choice2 == "rock":
                gain += _talent_total(p2, "rock_win_score_bonus")
            if match_state["score_swing"][p2.id] > 0:
                gain += match_state["score_swing"][p2.id]
            score2 += gain
            if choice2 == "paper":
                _handle_paper_win_effects(p2, p1, match_state)
            if choice2 == "scissors":
                _handle_scissors_win_effects(p2, p1, match_state)
            match_state["round_bonus"][p2.id] = 0
            if match_state["score_swing"][p2.id] > 0:
                match_state["score_swing"][p2.id] = 0
            if match_state["score_swing"][p1.id] > 0:
                score1 = max(0, score1 - match_state["score_swing"][p1.id])
                match_state["score_swing"][p1.id] = 0
            log(f"{p2.name} 获胜本小局！({score1}:{score2})", "green")
            _send_round_result(
                p1, p2, choice1, choice2, score1, score2, p2.name,
                rounds_played, max_rounds, item_used_1, item_used_2
            )
        else:
            log("本小局因无效出拳跳过", "yellow")
            _send_round_result(
                p1, p2, choice1, choice2, score1, score2, None,
                rounds_played, max_rounds, item_used_1, item_used_2
            )

        if match_state["last_rock_trigger"][p1.id]:
            _convert_random_non_rock_to_rock(p1)
            match_state["last_rock_trigger"][p1.id] = False
        if match_state["last_rock_trigger"][p2.id]:
            _convert_random_non_rock_to_rock(p2)
            match_state["last_rock_trigger"][p2.id] = False

        if choice1 and choice2 and (choice1, choice2) not in win_map and choice1 != choice2:
            if _has_talent_effect(p1, "on_lose_if_has_paper_gain") and p1.rps_bag.get("paper", 0) > 0:
                p1.add_to_bag("paper", 1)
                log(f"{p1.name} 【再来一次】获得 1 个布", "cyan")
            if _has_talent_effect(p2, "on_lose_if_has_paper_gain") and p2.rps_bag.get("paper", 0) > 0:
                p2.add_to_bag("paper", 1)
                log(f"{p2.name} 【再来一次】获得 1 个布", "cyan")

    if score1 >= 3:
        winner, loser = p1, p2
        log(f"\n🎉 {winner.name} 赢得本场对战！", "green")
        _send_match_result(winner, loser, score1, score2)

    elif score2 >= 3:
        winner, loser = p2, p1
        log(f"\n🎉 {winner.name} 赢得本场对战！", "green")
        _send_match_result(winner, loser, score1, score2)

    elif score1 > score2:
        winner, loser = p1, p2
        log(f"\n⏱️ 5回合结束，{winner.name} 以比分优势获胜！", "green")
        _send_match_result(winner, loser, score1, score2)

    elif score2 > score1:
        winner, loser = p2, p1
        log(f"\n⏱️ 5回合结束，{winner.name} 以比分优势获胜！", "green")
        _send_match_result(winner, loser, score1, score2)
    
    else:
        log("\n⏱️ 5回合结束，双方平局，本场不掉血", "yellow")
        _send_match_result(p1, p2, score1, score2, is_draw=True)
        p1.gold += 1
        p2.gold += 1
        return p1, p2, True
    
    damage = winner.attack
    if _has_talent_effect(winner, "double_damage_on_win"):
        damage *= 2

    damage += match_state["damage_bonus"].get(winner.id, 0)

    if _has_talent_effect(winner, "scissors_count_damage_bonus"):
        scissors_count = winner.rps_bag.get("scissors", 0)
        extra = (scissors_count // 2) * _talent_total(winner, "scissors_count_damage_bonus")
        damage += extra
        log(f"{winner.name} 【物尽其用】额外伤害 +{extra}（{scissors_count}剪刀）", "red")

    loser.health -= damage

    p1.gold += 5
    p2.gold += 5

    return winner, loser, False