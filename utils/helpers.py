import random
import time

def random_delay(min_sec: float = 0.5, max_sec: float = 2.0):
    time.sleep(random.uniform(min_sec, max_sec))

def chance(percent: float) -> bool:
    """Retourne True avec une certaine probabilité (ex: chance(30) = 30% de chance)"""
    return random.random() * 100 < percent