"""Navigateur Chrome piloté par Playwright, avec un profil persistant.

SNCF Connect et OUIGO n'ont pas d'API publique et SNCF Connect est protégé par DataDome :
les recherches passent donc par un vrai navigateur, qui garde ses cookies d'une exécution à l'autre.
Par défaut il tourne en arrière-plan ; si une vérification anti-robot apparaît, on peut le
relancer en fenêtre visible pour que l'utilisateur la fasse lui-même.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from playwright.async_api import BrowserContext, Error as PlaywrightError, Page, async_playwright

MARQUEUR_DATADOME = "captcha-delivery.com"


class ProtectionAntiRobot(Exception):
    """Le site demande une vérification anti-robot (DataDome)."""


class NavigateurIndisponible(Exception):
    """Impossible de démarrer le navigateur ; `profil_occupe` si un autre Chrome utilise déjà le profil."""

    def __init__(self, message: str, profil_occupe: bool = False):
        super().__init__(message)
        self.profil_occupe = profil_occupe


class Navigateur:
    def __init__(self, profil: Path, visible: bool = False):
        self.profil = profil
        self.visible = visible
        self._pw = None
        self._ctx: BrowserContext | None = None
        self._canal: str | None = "chrome"  # Google Chrome installé, sinon Chromium de Playwright
        self._user_agent: str | None = None

    async def __aenter__(self) -> "Navigateur":
        self.profil.mkdir(parents=True, exist_ok=True)
        self._pw = await async_playwright().start()
        try:
            await self._lancer()
        except BaseException:
            await self._pw.stop()
            raise
        return self

    async def __aexit__(self, *exc) -> None:
        if self._ctx:
            await self._ctx.close()
        if self._pw:
            await self._pw.stop()

    async def nouvelle_page(self) -> Page:
        assert self._ctx is not None
        return await self._ctx.new_page()

    async def passer_en_visible(self) -> None:
        if self.visible:
            return
        self.visible = True
        await self._ctx.close()
        await self._lancer()

    async def _lancer(self) -> None:
        try:
            self._ctx = await self._ouvrir_contexte()
        except PlaywrightError as exc:
            if "ProcessSingleton" in str(exc):
                raise NavigateurIndisponible(
                    "Un autre navigateur de trajets utilise déjà son profil (recherche en cours ailleurs, "
                    "ou navigateur resté ouvert après un arrêt brutal).",
                    profil_occupe=True,
                ) from exc
            if self._canal is None or "is not found" not in str(exc):
                raise NavigateurIndisponible(f"Chrome n'a pas pu démarrer : {str(exc).splitlines()[0]}") from exc
            self._canal = None  # Google Chrome absent : Chromium fourni par Playwright
            try:
                self._ctx = await self._ouvrir_contexte()
            except PlaywrightError as exc2:
                raise NavigateurIndisponible(
                    "Ni Google Chrome ni le Chromium de Playwright ne sont installés : installe Google Chrome, "
                    "ou lance « .venv/bin/playwright install chromium »."
                ) from exc2
        if not self.visible and self._user_agent is None:
            # Chrome headless s'annonce « HeadlessChrome » : on reprend l'UA normal du même navigateur.
            page = await self._ctx.new_page()
            ua = await page.evaluate("navigator.userAgent")
            await page.close()
            if "Headless" in ua:
                self._user_agent = ua.replace("HeadlessChrome", "Chrome")
                await self._ctx.close()
                self._ctx = await self._ouvrir_contexte()

    async def _ouvrir_contexte(self) -> BrowserContext:
        options = dict(
            headless=not self.visible,
            locale="fr-FR",
            timezone_id="Europe/Paris",
            viewport={"width": 1280, "height": 860},
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        if self._canal:
            options["channel"] = self._canal
        if not self.visible and self._user_agent:
            options["user_agent"] = self._user_agent
        return await self._pw.chromium.launch_persistent_context(str(self.profil), **options)


def fermer_navigateurs_restes_ouverts(profil: Path) -> None:
    """Ferme les Chrome qui utilisent encore le profil dédié de l'outil (jamais le Chrome personnel)."""
    subprocess.run(["pkill", "-f", "--", f"--user-data-dir={profil}"], capture_output=True, check=False)


async def attendre_fin_verification(page: Page, secondes: float) -> bool:
    """Attend que la page réelle soit affichée. La vérification DataDome se résout souvent seule
    (« device check » puis rechargement) ; sinon c'est un captcha que l'utilisateur doit faire."""
    boucle = asyncio.get_running_loop()
    fin = boucle.time() + secondes
    controles_ok = 0
    while boucle.time() < fin:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
            libre = MARQUEUR_DATADOME not in await page.content()
        except PlaywrightError:
            libre = False  # navigation en cours (rechargement après la vérification)
        controles_ok = controles_ok + 1 if libre else 0
        if controles_ok >= 2:
            return True
        await asyncio.sleep(1)
    return False
