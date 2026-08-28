def apply_stealth(page):
    """Correctifs minimaux qui ne remplacent pas les API natives de Chrome."""
    page.add_init_script("""
        Object.defineProperty(Navigator.prototype, 'webdriver', {
            get: () => undefined,
            configurable: true
        });
    """)