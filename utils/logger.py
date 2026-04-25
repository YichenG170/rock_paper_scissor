def log(message: str, color: str = "white"):
    colors = {
        "green": "\033[92m",
        "yellow": "\033[93m",
        "red": "\033[91m",
        "cyan": "\033[96m",
        "white": "\033[97m"
    }
    reset = "\033[0m"
    print(f"{colors.get(color, '')}{message}{reset}")