from utils.logger import log
from server.network import send_message, get_message, clients   # ← 补全 clients
from core.rps_bag import generate_initial_bag
import random


def _add_summary(match_state, text):
    match_state["round_summary"].append(text)
    log(text, "cyan")


def _broadcast_to_observers(exclude_ids, msg_data):
    for cid, conn in clients.items():
        if cid not in exclude_ids:
            send_message(cid, msg_data)


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

def _has_talent_effect_any(effect_type, player1=None, player2=None):
    return (_talent_total(player1, effect_type) > 0 if player1 else False) or \
           (_talent_total(player2, effect_type) > 0 if player2 else False)


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

def _convert_random_to_type(player, target_type, match_state=None):
    """把随机一个非目标类型的拳变成目标类型"""
    others = [k for k in ("rock", "scissors", "paper") if k != target_type and player.rps_bag.get(k, 0) > 0]
    if not others:
        return False
    picked = random.choice(others)
    player.rps_bag[picked] -= 1
    player.rps_bag[target_type] = player.rps_bag.get(target_type, 0) + 1
    
    if match_state is not None:
        match_state["change_rps_count"][player.id] += 1
        if _has_talent_effect(player, "on_change_rps_gain_gold_by_paper"):
            gold = player.rps_bag.get("paper", 0)
            player.gold += gold / 2
            log(f"{player.name} [印钞机] 根据布数量获得 {gold} 金币", "cyan")
    
    if target_type == "paper" and _has_talent_effect(player, "paper_transform_bonus"):
        bonus = _talent_total(player, "paper_transform_bonus")
        player.rps_bag["paper"] += bonus
        log(f"[一生二] 额外获得 {bonus} 个布", "cyan")
    return True

def _add_random_rps(player, count):
    for _ in range(max(0, int(count))):
        player.add_to_bag(random.choice(["rock", "scissors", "paper"]), 1)

def _remove_random_rps(player):
    """随机移除一个出拳"""
    available = [k for k in ("rock", "scissors", "paper") if player.rps_bag.get(k, 0) > 0]
    if not available:
        return False
    picked = random.choice(available)
    player.rps_bag[picked] -= 1
    return True


def _gain_gold_in_battle(player, amount):
    if amount <= 0:
        return
    player.gold += amount
    
    if _has_talent_effect(player, "battle_gold_to_scissors"):
        for _ in range(amount):
            player.add_to_bag("scissors", 1)
    
    if _has_talent_effect(player, "battle_gold_to_random_bag"):
        _add_random_rps(player, 1)


def _apply_talent_match_start(player, match_state=None):
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
        elif effect_type == "on_set_health_20_damage_double":
            player.health = 10
            if match_state:
                match_state["damage_multiplier"][player.id] = 2
        elif effect_type == "on_set_health_1_gain_gold":
            player.health = 1

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

    if _has_talent_effect(winner, "on_paper_win_random_rock_scissors"):
        import random
        choice = random.choice(["rock", "scissors"])
        winner.rps_bag[choice] = winner.rps_bag.get(choice, 0) + 1
        log(f"{winner.name} [偷天换日] 获得随机 {choice}", "cyan")


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

    # 输掉布的人触发：第一次使用布失败回血
    if _has_talent_effect(loser, "on_first_paper_lose_heal") and not match_state.get("first_paper_lose_used", {}).get(loser.id, False):
        match_state["first_paper_lose_used"][loser.id] = True
        loser.health += 1
        log(f"{loser.name} [垂死挣扎] 第一次布失败回复1点血量", "green")

    # 剪刀失败时：七伤拳自己扣血
    if _has_talent_effect(loser, "on_scissors_win_drain_health_same"):
        loser.health -= 1
        log(f"{loser.name} [七伤拳] 剪刀失败自己减少1血量", "red")


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
    player.rock_streak_cnt = 0


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

    if _has_talent_effect(player, "on_use_item_lose_gold"):
        lose = _talent_total(player, "on_use_item_lose_gold")
        player.gold = max(0, player.gold - lose)
        log(f"{player.name} [采购回扣] 使用道具失去{lose}金币", "red")

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
    item_used_2,
    match_state
):
    health_overview = _build_health_overview(p1, p2)
    round_summary = match_state.get("round_summary", [])
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
        "health_overview": health_overview,
        "round_summary": round_summary
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
        "health_overview": health_overview,
        "round_summary": round_summary
    })

    _broadcast_to_observers(
        [p1.id, p2.id],
        {
            "type": "observer_round",
            "p1": p1.name, "p2": p2.name,
            "choice1": choice1, "choice2": choice2,
            "round_winner": round_winner_name,
            "round_no": round_no,
            "score1": score1, "score2": score2,
            "round_summary": round_summary
        }
    )


def _handle_match_end(winner, loser, score1, score2, match_state):
    loser_score = min(score1, score2)
    if _has_talent_effect(loser, "on_set_health_1_gain_gold"):
        gold = max(0, 20 - loser.health) * 3
        loser.gold += gold
        log(f"{loser.name} [置之死地] 血量设1，获得{gold}金币", "cyan")
    if _has_talent_effect(winner, "on_zero_score_lose_gold") and loser_score == 0:
        loser.gold = max(0, loser.gold - 15)
        log(f"{winner.name} [乘人之危] 对手0分失败，夺取15金币", "yellow")


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
    p1.rps_bag = generate_initial_bag(p1.bag_size)
    p2.rps_bag = generate_initial_bag(p2.bag_size)
    _reset_item_for_new_match(p1)
    _reset_item_for_new_match(p2)

    if _has_talent_effect(p1, "battle_start_rock_double"):
        p1.rps_bag["rock"] = p1.rps_bag.get("rock", 0) * 2
        log(f"{p1.name} [山] 石头数量翻倍！", "cyan")
    if _has_talent_effect(p2, "battle_start_rock_double"):
        p2.rps_bag["rock"] = p2.rps_bag.get("rock", 0) * 2
        log(f"{p2.name} [山] 石头数量翻倍！", "cyan")

    if _has_talent_effect(p1, "all_to_rock") or _has_talent_effect(p2, "all_to_rock"):
        for player in (p1, p2):
            total = sum(player.rps_bag.values())
            player.rps_bag = {"rock": total, "scissors": 0, "paper": 0}
        log("[疯！狂！原！石！人！] 双方全部变成石头！", "magenta")

    match_state = {
        "round_bonus": {p1.id: 0, p2.id: 0},
        "score_swing": {p1.id: p1.pending_score_swing, p2.id: p2.pending_score_swing},
        "last_rock_trigger": {p1.id: False, p2.id: False},
        "damage_bonus": {p1.id: 0, p2.id: 0},
        "last_choice": {p1.id: None, p2.id: None},
        "change_rps_count": {p1.id: 0, p2.id: 0},
        "first_paper_lose_used": {p1.id: False, p2.id: False},
        "first_to_score": {p1.id: None, p2.id: None},
        "damage_multiplier": {p1.id: 1, p2.id: 1},
        "round_summary": []
    }
    _apply_talent_match_start(p1, match_state)
    _apply_talent_match_start(p2, match_state)

    if _has_talent_effect(p1, "on_start_convert_rock_scissors_if_more_health") and p1.health > p2.health:
        for _ in range(p1.rps_bag.get("rock", 0) + p1.rps_bag.get("scissors", 0)):
            _convert_random_to_type(p1, random.choice(["rock", "scissors", "paper"]))
        p1.rps_bag["rock"] = 0
        p1.rps_bag["scissors"] = 0
        log(f"{p1.name} [以多欺少] 血量优势，随机变换石头和剪刀", "cyan")
    if _has_talent_effect(p2, "on_start_convert_rock_scissors_if_more_health") and p2.health > p1.health:
        for _ in range(p2.rps_bag.get("rock", 0) + p2.rps_bag.get("scissors", 0)):
            _convert_random_to_type(p2, random.choice(["rock", "scissors", "paper"]))
        p2.rps_bag["rock"] = 0
        p2.rps_bag["scissors"] = 0
        log(f"{p2.name} [以多欺少] 血量优势，随机变换石头和剪刀", "cyan")

    score1 = 0
    score2 = 0
    rounds_played = 0
    max_rounds = 5
    p1.pending_score_swing = 0
    p2.pending_score_swing = 0
    log(f"\n=== {p1.name} VS {p2.name} 开始 ===", "cyan")
    _broadcast_to_observers(
        [p1.id, p2.id],
        {"type": "match_start", "p1": p1.name, "p2": p2.name}
    )

    while score1 < 3 and score2 < 3 and rounds_played < max_rounds:
        match_state["round_summary"] = []
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
        if item_used_1:
            _add_summary(match_state, f"【{p1.name}】使用道具 {item_used_1}")
        if item_used_2:
            _add_summary(match_state, f"【{p2.name}】使用道具 {item_used_2}")
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

        if choice1 == "rock" and _has_talent_effect(p1, "rock_streak_bonus"):
            p1.rock_streak_cnt += 1
            if p1.rock_streak_cnt >= 5:
                score1 += 3
                p1.gold += 30
                p1.rock_streak_cnt = 0
                log(f"{p1.name} [一根筋] 连续5次石头，获得3分与30金币！({score1}:{score2})", "cyan")
        if choice1 is not None and choice1 != "rock" and _has_talent_effect(p1, "rock_streak_bonus"):
            p1.rock_streak_cnt = 0
        if choice2 == "rock" and _has_talent_effect(p2, "rock_streak_bonus"):
            p2.rock_streak_cnt += 1
            if p2.rock_streak_cnt >= 5:
                score2 += 3
                p2.gold += 30
                p2.rock_streak_cnt = 0
                log(f"{p2.name} [一根筋] 连续5次石头，获得3分与30金币！({score1}:{score2})", "cyan")
        if choice2 is not None and choice2 != "rock" and _has_talent_effect(p2, "rock_streak_bonus"):
            p2.rock_streak_cnt = 0

        if choice1 == "rock" and _has_talent_effect(p1, "on_play_rock_convert_opponent_to_rock"):
            _convert_random_non_rock_to_rock(p2)
        if choice2 == "rock" and _has_talent_effect(p2, "on_play_rock_convert_opponent_to_rock"):
            _convert_random_non_rock_to_rock(p1)

        if choice1 == "rock" and p1.rps_bag.get("rock", 0) == 0 and _has_talent_effect(p1, "on_last_rock_convert_to_rock"):
            match_state["last_rock_trigger"][p1.id] = True
        if choice2 == "rock" and p2.rps_bag.get("rock", 0) == 0 and _has_talent_effect(p2, "on_last_rock_convert_to_rock"):
            match_state["last_rock_trigger"][p2.id] = True

        if choice1 == "scissors" and _has_talent_effect(p1, "on_play_scissors_convert_opp_to_paper"):
            _convert_random_to_type(p2, "paper", match_state)
        if choice2 == "scissors" and _has_talent_effect(p2, "on_play_scissors_convert_opp_to_paper"):
            _convert_random_to_type(p1, "paper", match_state)

        if choice1 == "scissors" and _has_talent_effect(p1, "on_scissors_opp_bag_greater_than_rounds"):
            opp_rps_total = sum(p2.rps_bag.values())
            remaining_rounds = max_rounds - rounds_played
            if opp_rps_total > remaining_rounds:
                _remove_random_rps(p2)
                log(f"{p1.name} [趁人之危] 对手出拳多于剩余轮数，随机失去一个出拳", "cyan")
        if choice2 == "scissors" and _has_talent_effect(p2, "on_scissors_opp_bag_greater_than_rounds"):
            opp_rps_total = sum(p1.rps_bag.values())
            remaining_rounds = max_rounds - rounds_played
            if opp_rps_total > remaining_rounds:
                _remove_random_rps(p1)
                log(f"{p2.name} [趁人之危] 对手出拳多于剩余轮数，随机失去一个出拳", "cyan")

        if choice1 == "paper" and _has_talent_effect(p1, "on_play_paper_reroll_all"):
            p1.rps_bag = generate_initial_bag(p1.bag_size)
            _add_summary(match_state, f"【{p1.name}】全部出拳随机重置")
        if choice2 == "paper" and _has_talent_effect(p2, "on_play_paper_reroll_all"):
            p2.rps_bag = generate_initial_bag(p2.bag_size)
            _add_summary(match_state, f"【{p2.name}】全部出拳随机重置")

        if _has_talent_effect(p1, "on_change_rps_health_bonus_malus"):
            last_c1 = match_state["last_choice"].get(p1.id)
            if choice1 != last_c1 and choice1 is not None:
                p1.health += 1
                _add_summary(match_state, f"【{p1.name}】变换出拳+1血")
            elif choice1 == last_c1 and choice1 is not None:
                p1.health -= 2
                _add_summary(match_state, f"【{p1.name}】相同出拳-2血")
        if _has_talent_effect(p2, "on_change_rps_health_bonus_malus"):
            last_c2 = match_state["last_choice"].get(p2.id)
            if choice2 != last_c2 and choice2 is not None:
                p2.health += 1
                _add_summary(match_state, f"【{p2.name}】变换出拳+1血")
            elif choice2 == last_c2 and choice2 is not None:
                p2.health -= 2
                _add_summary(match_state, f"【{p2.name}】相同出拳-2血")

        rounds_played += 1

        if choice1 == choice2 and choice1 is not None:
            rock_vs_rock_tie = choice1 == "rock" and (
                _has_talent_effect(p1, "rock_vs_rock_score") or 
                _has_talent_effect(p2, "rock_vs_rock_score")
            )
            if rock_vs_rock_tie:
                p1_rock = p1.rps_bag.get("rock", 0)
                p2_rock = p2.rps_bag.get("rock", 0)
                if p1_rock != p2_rock:
                    winner = p1 if p1_rock > p2_rock else p2
                    if winner is p1:
                        score1 += 1
                        log(f"{p1.name} [掰手腕] 石头更多，获得1分！({score1}:{score2})", "cyan")
                    else:
                        score2 += 1
                        log(f"{p2.name} [掰手腕] 石头更多，获得1分！({score1}:{score2})", "cyan")
                    _send_round_result(
                        p1, p2, choice1, choice2, score1, score2, winner.name,
                        rounds_played, max_rounds, item_used_1, item_used_2, match_state
                    )
                    rounds_played += 1
                    continue
            
            _handle_consecutive_choice(p1, match_state["last_choice"][p1.id], choice1)
            _handle_consecutive_choice(p2, match_state["last_choice"][p2.id], choice2)
            match_state["last_choice"][p1.id] = choice1
            match_state["last_choice"][p2.id] = choice2
            
            log("平局！双方出拳相同", "yellow")
            _send_round_result(
                p1, p2, choice1, choice2, score1, score2, None,
                rounds_played, max_rounds, item_used_1, item_used_2, match_state
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
            if score1 >= 2 and match_state["first_to_score"].get("used") is None:
                match_state["first_to_score"]["used"] = True
                match_state["first_to_score"]["player"] = p1.id
                if _has_talent_effect_any("on_first_score_convert_all_same", p1, p2):
                    new_type = random.choice(["rock", "scissors", "paper"])
                    total = sum(p1.rps_bag.values())
                    p1.rps_bag = {new_type: total, "rock": 0, "scissors": 0, "paper": 0}
                    _add_summary(match_state, f"【{p1.name}】首个达到2分，所有出拳变成{new_type}")
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
                rounds_played, max_rounds, item_used_1, item_used_2, match_state
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
            if score2 >= 2 and match_state["first_to_score"].get("used") is None:
                match_state["first_to_score"]["used"] = True
                match_state["first_to_score"]["player"] = p2.id
                if _has_talent_effect_any("on_first_score_convert_all_same", p1, p2):
                    new_type = random.choice(["rock", "scissors", "paper"])
                    total = sum(p2.rps_bag.values())
                    p2.rps_bag = {new_type: total, "rock": 0, "scissors": 0, "paper": 0}
                    _add_summary(match_state, f"【{p2.name}】首个达到2分，所有出拳变成{new_type}")
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
                rounds_played, max_rounds, item_used_1, item_used_2, match_state
            )
        else:
            log("本小局因无效出拳跳过", "yellow")
            _send_round_result(
                p1, p2, choice1, choice2, score1, score2, None,
                rounds_played, max_rounds, item_used_1, item_used_2, match_state
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
        _handle_match_end(winner, loser, score1, score2, match_state)
        _send_match_result(winner, loser, score1, score2)
        _broadcast_to_observers(
            [p1.id, p2.id],
            {"type": "match_end", "p1": p1.name, "p2": p2.name, "winner": winner.name, "score": f"{score1}:{score2}"}
        )
        return p1, p2, False

    elif score2 >= 3:
        winner, loser = p2, p1
        log(f"\n🎉 {winner.name} 赢得本场对战！", "green")
        _handle_match_end(winner, loser, score1, score2, match_state)
        _send_match_result(winner, loser, score1, score2)
        _broadcast_to_observers(
            [p1.id, p2.id],
            {"type": "match_end", "p1": p1.name, "p2": p2.name, "winner": winner.name, "score": f"{score1}:{score2}"}
        )
        return p1, p2, False

    elif score1 > score2:
        winner, loser = p1, p2
        log(f"\n⏱️ 5回合结束，{winner.name} 以比分优势获胜！", "green")
        _handle_match_end(winner, loser, score1, score2, match_state)
        _send_match_result(winner, loser, score1, score2)
        _broadcast_to_observers(
            [p1.id, p2.id],
            {"type": "match_end", "p1": p1.name, "p2": p2.name, "winner": winner.name, "score": f"{score1}:{score2}"}
        )
        return p1, p2, False
    
    elif score2 > score1:
        winner, loser = p2, p1
        log(f"\n⏱️ 5回合结束，{winner.name} 以比分优势获胜！", "green")
        _handle_match_end(winner, loser, score1, score2, match_state)
        _send_match_result(winner, loser, score1, score2)
        _broadcast_to_observers(
            [p1.id, p2.id],
            {"type": "match_end", "p1": p1.name, "p2": p2.name, "winner": winner.name, "score": f"{score1}:{score2}"}
        )
        return p1, p2, False
    
    else:
        log("\n⏱️ 5回合结束，双方平局，本场不掉血", "yellow")
        _handle_match_end(p1, p1, score1, score2, match_state)
        _handle_match_end(p2, p2, score2, score1, match_state)
        _send_match_result(p1, p2, score1, score2, is_draw=True)
        _broadcast_to_observers(
            [p1.id, p2.id],
            {"type": "match_end", "p1": p1.name, "p2": p2.name, "winner": "平局", "score": f"{score1}:{score2}"}
        )
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

    if _has_talent_effect(winner, "on_damage_extra_by_change_rps_quarter"):
        change_count = match_state.get("change_rps_count", {}).get(winner.id, 0)
        extra = min(change_count // 4, 5)
        if extra > 0:
            damage += extra
            log(f"{winner.name} [伤口撒盐] 变换出拳额外伤害 +{extra}", "red")

    if damage > 0:
        if _has_talent_effect(loser, "on_health_loss_gain_scissors_gold"):
            loser.rps_bag["scissors"] = loser.rps_bag.get("scissors", 0) + 1
            loser.gold += 2
            log(f"{loser.name} [绝境逢生] 血量减少，获得1个剪刀和2金币", "cyan")
        if _has_talent_effect(winner, "on_scissors_win_drain_health_same"):
            loser.health -= 1
            log(f"{winner.name} [七伤拳] 对手减少1血量", "red")
        if _has_talent_effect(winner, "on_first_scissors_win_swap_health_by_gold"):
            first_used_key = f"first_scissors_win_{winner.id}"
            if not match_state.get(first_used_key, False) and winner.gold >= 50:
                match_state[first_used_key] = True
                winner.gold -= 50
                p1.health, p2.health = p2.health, p1.health
                log(f"{winner.name} [破釜沉舟] 消耗50金币互换血量!", "magenta")
        if _has_talent_effect(winner, "on_scissors_win_chance_2damage"):
            if random.random() < 0.1:
                loser.health -= 2
                match_state["round_bonus"][loser.id] += 1
                log(f"{winner.name} [致命剪刀] 10%概率减少2血并使对手减1分!", "red")

    loser.health -= damage

    if _has_talent_effect(loser, "on_set_health_20_damage_double"):
        mult = match_state.get("damage_multiplier", {}).get(loser.id, 1)
        extra_damage = damage * (mult - 1)
        if extra_damage > 0:
            loser.health -= extra_damage
            log(f"{loser.name} [背水一战] 伤害翻倍额外扣血！{extra_damage}", "red")

    p1.gold += 5
    p2.gold += 5

    return winner, loser, False