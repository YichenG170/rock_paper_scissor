from dataclasses import dataclass, field
from typing import Dict, List

@dataclass
class Player:
    # 必须提供的字段（放在最前面）
    id: str
    name: str
    rps_bag: Dict[str, int]

    # 带默认值的字段
    health: int = 20
    gold: int = 10
    bag_size: int = 7
    attack: int = 3
    interest_rate: float = 0.2
    shop_slots: int = 5
    pending_score_swing: int = 0
    win_streak: int = 0
    lose_streak: int = 0
    rock_streak_cnt: int = 0
    talents: List[dict] = field(default_factory=list)
    items: List[dict] = field(default_factory=list)
    is_eliminated: bool = False

    def __post_init__(self):
        """防止 mutable 默认值问题 + 初始化检查"""
        if not isinstance(self.rps_bag, dict):
            self.rps_bag = dict(self.rps_bag)  # 确保是 dict

    def use_rps(self, choice: str) -> bool:
        """使用一个出拳，返回是否成功"""
        if self.rps_bag.get(choice, 0) > 0:
            self.rps_bag[choice] -= 1
            return True
        return False

    def add_to_bag(self, choice: str, count: int):
        """增加出拳数量"""
        self.rps_bag[choice] = self.rps_bag.get(choice, 0) + count