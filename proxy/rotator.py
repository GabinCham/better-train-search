import random
from config import Config

class ProxyRotator:
    def __init__(self):
        self.proxies = Config.PROXY_LIST.copy()
        random.shuffle(self.proxies)
        self.index = 0

    def next(self) -> str | None:
        if not self.proxies:
            return None
        proxy = self.proxies[self.index]
        self.index = (self.index + 1) % len(self.proxies)
        return proxy

    def random(self) -> str | None:
        return random.choice(self.proxies) if self.proxies else None