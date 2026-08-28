import random
import time
import numpy as np
from playwright.sync_api import Page

def human_delay(min_ms=300, max_ms=1200):
    time.sleep(random.uniform(min_ms, max_ms) / 1000)

def human_mouse_move(page: Page, x: int, y: int):
    """Déplacement de souris avec courbe de Bézier simplifiée"""
    current = page.evaluate("() => ({ x: window.mouseX || 0, y: window.mouseY || 0 })")
    start_x, start_y = current.get("x", 0), current.get("y", 0)

    steps = random.randint(15, 30)
    for i in range(steps):
        t = i / steps
        # Courbe simple
        ctrl_x = (start_x + x) / 2 + random.randint(-50, 50)
        ctrl_y = (start_y + y) / 2 + random.randint(-40, 40)

        curr_x = (1-t)**2 * start_x + 2*(1-t)*t * ctrl_x + t**2 * x
        curr_y = (1-t)**2 * start_y + 2*(1-t)*t * ctrl_y + t**2 * y

        page.mouse.move(curr_x, curr_y)
        time.sleep(random.uniform(0.008, 0.025))

    page.evaluate(f"() => {{ window.mouseX = {x}; window.mouseY = {y}; }}")

def human_scroll(page: Page, distance: int = None):
    if distance is None:
        distance = random.randint(300, 900)
    
    steps = random.randint(8, 15)
    for _ in range(steps):
        page.mouse.wheel(0, distance // steps + random.randint(-20, 20))
        time.sleep(random.uniform(0.05, 0.15))

def human_type(page: Page, selector: str, text: str):
    page.click(selector)
    human_delay(200, 500)
    for char in text:
        page.keyboard.type(char, delay=random.randint(60, 180))
        if random.random() < 0.08:
            time.sleep(random.uniform(0.2, 0.5))