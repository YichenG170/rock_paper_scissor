import os
from server.game_server import start_server
from client.game_client import start_client

if __name__ == "__main__":
    print("=== RPS Battlegrounds ===\n")
    print("1. 创建服务器（房主）")
    print("2. 加入游戏（客人）")
    mode = input("请选择 (1/2): ").strip()

    name = input("请输入你的玩家名称: ").strip() or "玩家"

    if mode == "1":
        while True:
            try:
                max_players = int(input("请输入玩家数量 (2-8): ").strip())
                if 2 <= max_players <= 8:
                    break
                print("请输入2-8之间的数字")
            except ValueError:
                print("请输入有效数字")
        start_server(name, max_players)
    elif mode == "2":
        ip = input("请输入房主IP地址 (直接回车 = 本机测试): ").strip() or "127.0.0.1"
        start_client(name, ip)
    else:
        print("输入错误，程序退出")