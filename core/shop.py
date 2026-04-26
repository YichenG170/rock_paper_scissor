import json
import random
from utils.logger import log
from server.network import send_to_player, get_message, clients
import time

shop_done_event = None


RARITY_WEIGHTS = {
    "common": 67,
    "rare": 20,
    "epic": 10,
    "legendary": 3,
}
TALENT_SLOT_RATE = 0.33

def load_shop_items():
    with open("data/items.json", encoding="utf-8") as f:
        return json.load(f)["items"]

def load_shop_talents():
    with open("data/talents.json", encoding="utf-8") as f:
        return json.load(f)["talents"]


def _serialize_item(item):
    return {k: v for k, v in item.items() if not str(k).startswith("_")}


def _owned_item_count(player, item_id):
    return sum(1 for i in player.items if i.get("id") == item_id)


def _available_items(player, items):
    owned_ids = {item.get("id") for item in player.items if not item.get("repeatable_purchase", True)}
    return [i for i in items if i.get("id") not in owned_ids]


def _can_buy_item(player, item):
    return True


def _owned_talent_ids(player):
    return {t.get("id") for t in player.talents}


def _can_buy_talent(player, talent):
    return talent.get("id") not in _owned_talent_ids(player)


def _apply_talent_on_buy(player, talent):
    effect = talent.get("effect", {})
    effect_type = effect.get("type")
    value = int(effect.get("value", 0))

    if effect_type == "shop_slots_plus" and value > 0:
        player.shop_slots += value
    elif effect_type == "attack_plus" and value > 0:
        has_battle_tutor = any(t.get("id") == "battle_tutor" for t in player.talents)
        has_brutal_edge = any(t.get("id") == "brutal_edge" for t in player.talents)
        if has_battle_tutor and has_brutal_edge:
            player.attack += 2
        else:
            player.attack += value
    elif effect_type == "interest_rate_plus" and value > 0:
        player.interest_rate += value / 100 if value > 1 else value
    elif effect_type == "bag_size_plus" and value > 0:
        player.bag_size += value
    elif effect_type == "health_plus" and value > 0:
        player.health += value


def _roll_rarity():
    rarity_list = list(RARITY_WEIGHTS.keys())
    weight_list = [RARITY_WEIGHTS[r] for r in rarity_list]
    return random.choices(rarity_list, weights=weight_list, k=1)[0]


def _all_offers(items, talents):
    offers = []
    for item in items:
        offers.append({
            "kind": "item",
            "id": item["id"],
            "name": item["name"],
            "rarity": item.get("rarity", "common"),
            "cost": item["cost"],
            "refresh_each_match": item.get("refresh_each_match", True),
            "repeatable_purchase": item.get("repeatable_purchase", True),
            "description": item.get("description", "")
        })
    for talent in talents:
        offers.append({
            "kind": "talent",
            "id": talent["id"],
            "name": talent["name"],
            "cost": talent["cost"],
            "description": talent.get("description", "")
        })
    return offers


def _roll_item_offer(items, player):
    items = _available_items(player, items)
    if not items:
        return None
    rolled_rarity = _roll_rarity()
    candidates = [i for i in items if i.get("rarity", "common") == rolled_rarity]
    if not candidates:
        candidates = items
    item = random.choice(candidates)
    return {
        "kind": "item",
        "id": item["id"],
        "name": item["name"],
        "rarity": item.get("rarity", "common"),
        "cost": item["cost"],
        "refresh_each_match": item.get("refresh_each_match", True),
        "repeatable_purchase": item.get("repeatable_purchase", True),
        "description": item.get("description", "")
    }


def _roll_talent_offer(talents, player):
    available = [t for t in talents if _can_buy_talent(player, t)]
    if not available:
        return None
    talent = random.choice(available)
    return {
        "kind": "talent",
        "id": talent["id"],
        "name": talent["name"],
        "cost": talent["cost"],
        "description": talent.get("description", "")
    }


def _build_shop_slots(items, talents, slot_count, player):
    if not items and not talents:
        return []

    slots = []
    for _ in range(slot_count):
        offer = None
        if random.random() < TALENT_SLOT_RATE:
            offer = _roll_talent_offer(talents, player)
        if offer is None:
            offer = _roll_item_offer(items, player)
        if offer is None:
            offer = _roll_talent_offer(talents, player)
        if offer is not None:
            slots.append(offer)
    return slots


def _refresh_cost(refresh_count):
    return refresh_count + 2

def show_shop(player, health_overview=None):
    items = load_shop_items()
    talents = load_shop_talents()
    refresh_count = 0
    current_offers = _build_shop_slots(items, talents, player.shop_slots, player)

    log(f"\n=== 🛒 商店阶段 ===\n{player.name} 当前金币: {player.gold}", "yellow")

    while True:
        next_refresh_cost = _refresh_cost(refresh_count)
        send_to_player(player.id, {
            "type": "shop_menu",
            "gold": player.gold,
            "health": player.health,
            "bag_size": player.bag_size,
            "attack": player.attack,
            "interest_rate": player.interest_rate,
            "win_streak": player.win_streak,
            "lose_streak": player.lose_streak,
            "shop_slots": player.shop_slots,
            "refresh_cost": next_refresh_cost,
            "health_overview": health_overview or [],
            "offers": current_offers,
            "bag": player.rps_bag,
            "owned_items": [_serialize_item(i) for i in player.items],
            "owned_talents": player.talents
        })

        while True:
            msg = get_message(player.id)
            if not msg:
                continue
            break
        choice = msg.get("choice")

        if choice == "exit" or choice is None:
            break
        elif choice == "refresh":
            cost = _refresh_cost(refresh_count)
            if player.gold < cost:
                log(f"❌ 金币不足，刷新需要 {cost} 金币", "red")
            else:
                player.gold -= cost
                refresh_count += 1
                current_offers = _build_shop_slots(items, talents, player.shop_slots, player)
                log(f"🔄 已刷新商店，花费 {cost} 金币", "cyan")
        elif choice.startswith("slot_"):
            try:
                slot_idx = int(choice.split("_")[1])
            except Exception:
                slot_idx = -1

            if not (0 <= slot_idx < len(current_offers)):
                log("❌ 槽位无效", "red")
            else:
                picked = current_offers[slot_idx]
                if player.gold < picked["cost"]:
                    log(f"❌ 金币不足，购买 {picked['name']} 需要 {picked['cost']} 金币", "red")
                else:
                    player.gold -= picked["cost"]
                    if picked["kind"] == "item":
                        item = next((i for i in items if i["id"] == picked["id"]), None)
                        if item:
                            if not _can_buy_item(player, item):
                                player.gold += picked["cost"]
                                log(f"❌ {item['name']} 不可重复购买", "red")
                            else:
                                item_instance = dict(item)
                                item_instance["_used_this_match"] = False
                                player.items.append(item_instance)
                                log(f"✅ 购买成功: {item['name']}（已放入道具栏）", "green")
                    else:
                        talent = next((t for t in talents if t["id"] == picked["id"]), None)
                        if talent:
                            if not _can_buy_talent(player, talent):
                                player.gold += picked["cost"]
                                log(f"❌ {talent['name']} 已习得，不可重复购买", "red")
                            else:
                                player.talents.append(dict(talent))
                                _apply_talent_on_buy(player, talent)
                                log(f"✅ 习得天赋: {talent['name']}", "green")
                    # 购买后将该槽位置空并重新补一格，保持固定槽位数。
                    refill = _build_shop_slots(items, talents, 1, player)
                    current_offers[slot_idx] = refill[0] if refill else current_offers[slot_idx]

        send_to_player(player.id, {
            "type": "shop_refresh",
            "gold": player.gold,
            "health": player.health,
            "bag_size": player.bag_size,
            "attack": player.attack,
            "interest_rate": player.interest_rate,
            "win_streak": player.win_streak,
            "lose_streak": player.lose_streak,
            "shop_slots": player.shop_slots,
            "refresh_cost": _refresh_cost(refresh_count),
            "offers": current_offers,
            "health_overview": health_overview or []
        })