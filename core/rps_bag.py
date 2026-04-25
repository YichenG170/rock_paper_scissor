import random
from typing import Dict

def generate_initial_bag(total_count: int = 7) -> Dict[str, int]:
    """随机生成初始出拳包（总数固定为 total_count）"""
    choices = ["rock", "scissors", "paper"]
    bag = {"rock": 0, "scissors": 0, "paper": 0}
    for _ in range(max(0, int(total_count))):
        c = random.choice(choices)
        bag[c] += 1
    return bag