from core.player import Player
from core.rps_bag import generate_initial_bag
import json
import os

class GameState:
    def __init__(self):
        self.players: list[Player] = []
        self.current_round = 0
        self.max_players = 3

    def add_player(self, player_id: str, name: str):
        bag_size = 7
        bag = generate_initial_bag(bag_size)
        player = Player(
            id=player_id,
            name=name,
            health=20,
            gold=10,
            bag_size=bag_size,
            rps_bag=bag
        )
        self.players.append(player)
        return player

    def get_player_by_id(self, player_id: str):
        for p in self.players:
            if p.id == player_id:
                return p
        return None

    def is_game_over(self):
        alive = [p for p in self.players if not p.is_eliminated]
        return len(alive) <= 1