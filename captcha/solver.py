from twocaptcha import TwoCaptcha
from config import Config

class CaptchaSolver:
    def __init__(self):
        if not Config.TWOCAPTCHA_API_KEY:
            print("[!] Pas de clé 2Captcha → résolution CAPTCHA désactivée")
            self.solver = None
        else:
            self.solver = TwoCaptcha(Config.TWOCAPTCHA_API_KEY)

    def solve_recaptcha_v2(self, sitekey: str, url: str) -> str | None:
        if not self.solver:
            return None
        try:
            result = self.solver.recaptcha(sitekey=sitekey, url=url)
            return result["code"]
        except Exception as e:
            print(f"[!] Erreur 2Captcha : {e}")
            return None

    def solve_hcaptcha(self, sitekey: str, url: str) -> str | None:
        if not self.solver:
            return None
        try:
            result = self.solver.hcaptcha(sitekey=sitekey, url=url)
            return result["code"]
        except Exception as e:
            print(f"[!] Erreur 2Captcha : {e}")
            return None