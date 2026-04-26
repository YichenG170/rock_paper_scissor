import socket
import json
from utils.logger import log


def white_panel(title, lines):
    border = "=" * 56
    log(f"\n{border}", "white")
    log(title, "white")
    for line in lines:
        log(line, "white")
    log(border, "white")

def send_message(conn, data):
    """可靠发送（和 server 一致）"""
    try:
        message = json.dumps(data).encode("utf-8")
        header = len(message).to_bytes(4, "big")
        conn.sendall(header + message)
    except Exception as e:
        log(f"发送失败: {e}", "red")

def recv_exact(conn, n):
    """确保收到精确 n 个字节"""
    data = b""
    while len(data) < n:
        chunk = conn.recv(n - len(data))
        if not chunk:
            raise ConnectionError("连接已关闭")
        data += chunk
    return data

def receive_message(conn):
    """可靠接收（和 server 一致）"""
    try:
        length_bytes = recv_exact(conn, 4)
        length = int.from_bytes(length_bytes, "big")
        data_bytes = recv_exact(conn, length)
        data = data_bytes.decode("utf-8")
        return json.loads(data)
    except Exception as e:
        log(f"接收消息失败: {e}", "red")
        return {}


def format_choice(choice):
    mapping = {"rock": "石头", "scissors": "剪刀", "paper": "布", None: "无"}
    return mapping.get(choice, "无")


def bag_text(bag):
    return f"石头({bag.get('rock', 0)}) 剪刀({bag.get('scissors', 0)}) 布({bag.get('paper', 0)})"


def percent_text(rate):
    return f"{int((rate or 0) * 100)}%"


def format_talents(talents):
    if not talents:
        return "无"
    return " / ".join([f"{t.get('name', '未知')}({t.get('description', '')})" for t in talents[:3]])


def player_stat_lines(msg):
    my_talents = msg.get("your_talents", [])
    opp_talents = msg.get("opponent_talents", [])
    lines = [
        f"❤️ 血量: {msg.get('your_health', msg.get('health', 0))}",
        f"💰 金币: {msg.get('your_gold', msg.get('gold', 0))}",
        f"🎒 出拳总数: {msg.get('your_bag_size', msg.get('bag_size', 7))}",
        f"🗡️ 杀伤力: {msg.get('your_attack', msg.get('attack', 2))}",
        f"🏦 利息率: {percent_text(msg.get('your_interest_rate', msg.get('interest_rate', 0.2)))}",
        f"🔥 连胜: {msg.get('your_win_streak', msg.get('win_streak', 0))}",
        f"🧊 连败: {msg.get('your_lose_streak', msg.get('lose_streak', 0))}",
    ]
    if my_talents:
        lines.append(f"✨ 你的天赋: {format_talents(my_talents)}")
    if opp_talents:
        lines.append(f"⚔️ 对手天赋: {format_talents(opp_talents)}")
    return lines


def rarity_tag(rarity):
    mapping = {
        "common": "⚪ 普通",
        "rare": "🔵 稀有",
        "epic": "🟣 史诗",
        "legendary": "🟠 传说",
    }
    return mapping.get((rarity or "").lower(), "⚪ 普通")


def format_item_label(item):
    repeatable = "可重复购" if item.get("repeatable_purchase", True) else "限购1次"
    refresh = "每局刷新" if item.get("refresh_each_match", True) else "不刷新"
    return f"{item.get('name', '未知')} [{rarity_tag(item.get('rarity'))}|{repeatable}|{refresh}]"


def format_talent_label(talent):
    return f"{talent.get('name', '未知')} [✨ 天赋]"


def format_offer_label(offer):
    kind_emoji = "🧰" if offer.get("kind") == "item" else "✨"
    if offer.get("kind") == "talent":
        return f"{kind_emoji} {offer.get('name', '未知')} [天赋]"
    return f"{kind_emoji} {offer.get('name', '未知')} [{rarity_tag(offer.get('rarity'))}]"


def health_board_lines(health_overview):
    if not health_overview:
        return ["🌍 全局血量: 暂无数据"]
    lines = ["🌍 全局血量榜:"]
    for idx, info in enumerate(health_overview, start=1):
        state = "💀 淘汰" if info.get("is_eliminated") else "🟢 存活"
        lines.append(f"  {idx}. {info.get('name', '未知')} - ❤️ {info.get('health', 0)} | {state}")
    return lines


def build_valid_input(bag):
    valid_input = {}
    if bag.get("rock", 0) > 0:
        valid_input["r"] = "rock"
    if bag.get("scissors", 0) > 0:
        valid_input["s"] = "scissors"
    if bag.get("paper", 0) > 0:
        valid_input["p"] = "paper"
    return valid_input


def pick_item_for_battle(items):
    if not items:
        log("当前没有可用道具", "yellow")
        return None

    white_panel(
        "道具栏",
        [f"{i+1}. {format_item_label(item)} - {item.get('description', '无描述')}" for i, item in enumerate(items)]
        + ["0. 取消使用"]
    )
    raw = input("选择要使用的道具编号: ").strip()
    if raw == "0":
        return None
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(items):
            return items[idx]
    except:
        pass
    log("道具输入无效，已取消", "red")
    return None


def show_profile_detail(
    bag,
    owned_items,
    owned_talents,
    health=None,
    health_overview=None,
    gold=None,
    attack=2,
    interest_rate=0.2,
    win_streak=0,
    lose_streak=0
):
    lines = []
    if health is not None:
        lines.append(f"❤️ 我的血量: {health}")
    if gold is not None:
        lines.append(f"💰 我的金币: {gold}")
    lines.append(f"🗡️ 我的杀伤力: {attack}")
    lines.append(f"🏦 我的利息率: {percent_text(interest_rate)}")
    lines.append(f"🔥 连胜: {win_streak} | 🧊 连败: {lose_streak}")
    lines.extend(health_board_lines(health_overview or []))
    lines.extend(["", f"🎒 出拳包: {bag_text(bag)}", "", "🧰 已拥有道具:"])
    if owned_items:
        for i, item in enumerate(owned_items):
            lines.append(f"- {i+1}. {format_item_label(item)} | {item.get('description', '无描述')}")
    else:
        lines.append("- 暂无")

    lines.append("")
    lines.append("✨ 已习得天赋:")
    if owned_talents:
        for i, talent in enumerate(owned_talents):
            lines.append(f"- {i+1}. {format_talent_label(talent)} | {talent.get('description', '无描述')}")
    else:
        lines.append("- 暂无")

    white_panel("角色详情", lines)

def start_client(name, server_ip):
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect((server_ip, 5555))
    log("✅ 已连接到服务器", "green")

    # 发送名字
    send_message(client, {"name": name})

    while True:
        msg = receive_message(client)
        if not msg:
            log("与服务器断开连接", "red")
            break

        if msg["type"] == "choose_rps":
            round_no = msg.get("round_no", 1)
            max_rounds = msg.get("max_rounds", 5)
            bag = dict(msg.get("bag", {}))
            items = list(msg.get("items", []))
            my_health = msg.get("your_health", 0)
            health_overview = msg.get("health_overview", [])

            white_panel(
                f"⚔️ 对战中 · 第 {round_no}/{max_rounds} 小局",
                player_stat_lines(msg) + [
                    f"🎯 对手: {msg['opponent']}",
                    f"🎒 你的出拳包: {bag_text(bag)}",
                    f"🧰 你的道具数: {len(items)}"
                ] + health_board_lines(health_overview)
            )

            used_item_id = None
            while True:
                valid_input = build_valid_input(bag)
                if not valid_input:
                    log("⚠️ 你当前没有可用出拳，本小局将自动跳过", "yellow")
                    send_message(client, {"choice": "none", "use_item": used_item_id})
                    break

                allowed_prompt = " / ".join([f"{k}={format_choice(v)}" for k, v in valid_input.items()])
                choice = input(f"选择出拳 ({allowed_prompt}，i=使用道具): ").strip().lower()

                if choice == "i":
                    selected_item = pick_item_for_battle(items)
                    if not selected_item:
                        continue
                    used_item_id = selected_item.get("id")
                    log(
                        f"已选择使用道具: {format_item_label(selected_item)}",
                        "cyan"
                    )

                    # 一局仅允许声明使用一次道具，避免重复选择。
                    for idx, item in enumerate(items):
                        if item.get("id") == used_item_id:
                            items.pop(idx)
                            break
                    continue

                if choice in valid_input:
                    full_choice = valid_input[choice]
                    send_message(client, {"choice": full_choice, "use_item": used_item_id})
                    break
                else:
                    log("输入错误：你只能选择当前有数量的出拳", "red")

        elif msg["type"] == "round_result":
            your_choice = format_choice(msg.get("your_choice"))
            opponent_choice = format_choice(msg.get("opponent_choice"))
            round_winner = msg.get("round_winner")
            score_you = msg.get("score_you", 0)
            score_opponent = msg.get("score_opponent", 0)
            round_no = msg.get("round_no", "?")
            max_rounds = msg.get("max_rounds", "?")
            item_you = msg.get("item_used_you")
            item_op = msg.get("item_used_opponent")
            your_health = msg.get("your_health", 0)
            opponent_health = msg.get("opponent_health", 0)
            health_overview = msg.get("health_overview", [])
            round_summary = msg.get("round_summary", [])
            item_line = ""
            if item_you or item_op:
                item_line = f" | 你用道具: {item_you or '无'} / 对手用道具: {item_op or '无'}"

            if round_winner:
                white_panel(
                    f"📣 第 {round_no}/{max_rounds} 小局结果",
                    player_stat_lines(msg) + [
                        f"你出: {your_choice} | 对手出: {opponent_choice}",
                        f"胜者: {round_winner}",
                        f"比分: {score_you}:{score_opponent}",
                        f"血量: 你 ❤️ {your_health} / 对手 ❤️ {opponent_health}",
                        f"道具信息: 你 {item_you or '无'} / 对手 {item_op or '无'}{item_line and ''}",
                    ] + (["--- 本轮事件 ---"] + round_summary if round_summary else []) +
                    health_board_lines(health_overview)
                )
            else:
                white_panel(
                    f"📣 第 {round_no}/{max_rounds} 小局结果",
                    player_stat_lines(msg) + [
                        f"你出: {your_choice} | 对手出: {opponent_choice}",
                        "结果: 平局/无效",
                        f"比分: {score_you}:{score_opponent}",
                        f"血量: 你 ❤️ {your_health} / 对手 ❤️ {opponent_health}",
                        f"道具信息: 你 {item_you or '无'} / 对手 {item_op or '无'}{item_line and ''}",
                    ] + (["--- 本轮事件 ---"] + round_summary if round_summary else []) +
                    health_board_lines(health_overview)
                )

        elif msg["type"] == "match_result":
            health_overview = msg.get("health_overview", [])
            your_health = msg.get("your_health", 0)
            if msg.get("result") == "win":
                white_panel(
                    "🏆 本场对战结果",
                    player_stat_lines(msg) + [
                        f"结果: 胜利，击败 {msg.get('loser', '对手')}",
                        f"比分: {msg.get('score_you', 0)}:{msg.get('score_opponent', 0)}",
                        f"当前血量: ❤️ {your_health}",
                    ] + health_board_lines(health_overview)
                )
            elif msg.get("result") == "draw":
                white_panel(
                    "🤝 本场对战结果",
                    player_stat_lines(msg) + [
                        "结果: 平局，双方不掉血",
                        f"比分: {msg.get('score_you', 0)}:{msg.get('score_opponent', 0)}",
                        f"当前血量: ❤️ {your_health}",
                    ] + health_board_lines(health_overview)
                )
            else:
                white_panel(
                    "💥 本场对战结果",
                    player_stat_lines(msg) + [
                        f"结果: 失利，败给 {msg.get('winner', '对手')}",
                        f"比分: {msg.get('score_you', 0)}:{msg.get('score_opponent', 0)}",
                        f"当前血量: ❤️ {your_health}",
                    ] + health_board_lines(health_overview)
                )

        elif msg["type"] == "state_update":
            income = msg.get("income")
            income_lines = []
            if income:
                income_lines = [
                    "",
                    "💸 回合收益结算:",
                    f"  基础 +{income.get('base', 0)}",
                    f"  连胜/连败 +{income.get('streak', 0)}",
                    f"  利息 +{income.get('interest', 0)}",
                    f"  合计 +{income.get('total', 0)}",
                ]
            white_panel(
                f"📡 状态同步 · {msg.get('phase', 'unknown')}",
                player_stat_lines(msg) + income_lines + health_board_lines(msg.get("health_overview", []))
            )

        elif msg["type"] == "shop_menu":
            while True:
                offers = msg.get("offers", [])
                lines = player_stat_lines(msg) + [""]
                lines += [f"🧾 商店槽位: {msg.get('shop_slots', 4)}", f"🔄 刷新费用: {msg.get('refresh_cost', 1)} 金币"]
                lines += [""] + health_board_lines(msg.get("health_overview", [])) + ["", "🛍️ 当前可购买槽位:"]
                for i, offer in enumerate(offers):
                    lines.append(
                        f"{i+1}. {format_offer_label(offer)} - {offer.get('cost', 0)}金币 | {offer.get('description', '')}"
                    )
                lines.append("")
                lines.append("输入 v 查看你的 bag/道具/天赋详情")
                lines.append("输入 r 刷新商店（费用递增）")
                lines.append("输入 0 退出商店")
                white_panel("🛒 商店阶段", lines)

                choice = input("输入编号购买 (v=查看详情, r=刷新, 0=退出): ").strip().lower()
                if choice == "v":
                    show_profile_detail(
                        msg.get("bag", {}),
                        msg.get("owned_items", []),
                        msg.get("owned_talents", []),
                        health=msg.get("health", 0),
                        health_overview=msg.get("health_overview", []),
                        gold=msg.get("gold", 0),
                        attack=msg.get("attack", 2),
                        interest_rate=msg.get("interest_rate", 0.2),
                        win_streak=msg.get("win_streak", 0),
                        lose_streak=msg.get("lose_streak", 0)
                    )
                    continue

                if choice == "r":
                    send_message(client, {"choice": "refresh"})
                    break

                if choice == "0":
                    send_message(client, {"choice": "exit"})
                    break

                try:
                    idx = int(choice) - 1
                    offers = msg.get("offers", [])
                    if 0 <= idx < len(offers):
                        send_message(client, {"choice": f"slot_{idx}"})
                    else:
                        raise ValueError("invalid index")
                    break
                except:
                    log("输入错误，请重新选择", "red")

        elif msg["type"] == "shop_refresh":
            white_panel(
                "🔄 商店状态更新",
                player_stat_lines(msg)
                + [
                    f"🧾 商店槽位: {msg.get('shop_slots', 4)}",
                    f"🔄 下次刷新费用: {msg.get('refresh_cost', 1)} 金币",
                ]
                + health_board_lines(msg.get("health_overview", []))
            )