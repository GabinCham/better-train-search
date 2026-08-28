import os
import uuid
from playwright.sync_api import sync_playwright
from config import Config
from browser.stealth import apply_stealth

class BrowserManager:
    def __init__(self, proxy: str | None = None, profile_id: str | None = None):
        self.proxy = proxy
        self.profile_id = profile_id or str(uuid.uuid4())[:8]
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

        os.makedirs(Config.PROFILES_DIR, exist_ok=True)
        self.user_data_dir = os.path.join(Config.PROFILES_DIR, self.profile_id)

    def start(self):
        self.playwright = sync_playwright().start()

        launch_args = {
            "channel": "chrome",
            "headless": Config.HEADLESS,
            "slow_mo": Config.SLOW_MO,
            # Playwright ajoute --enable-automation : c’est ce bandeau jaune.
            "ignore_default_args": ["--enable-automation"],
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-popup-blocking",
            ]
        }

        if self.proxy:
            launch_args["proxy"] = {"server": self.proxy}

        # Profil persistant
        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=self.user_data_dir,
            **launch_args,
            viewport={"width": 1440, "height": 900},
            locale="fr-FR",
            timezone_id="Europe/Paris",
            device_scale_factor=1,
            color_scheme="light",
            extra_http_headers={
                "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            },
            java_script_enabled=True,
        )

        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        apply_stealth(self.page)

        return self.page

    def close(self):
        if self.context:
            self.context.close()
        if self.playwright:
            self.playwright.stop()