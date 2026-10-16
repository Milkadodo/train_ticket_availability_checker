"""Point d'entrée : `trajets` ouvre l'application interactive (menus au clavier, aucun argument)."""

from __future__ import annotations

import asyncio
import sys
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

import questionary
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from questionary import Choice
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from trajets.affichage import (
    afficher_comparatif_allers_retours,
    afficher_ouvertures,
    afficher_recapitulatif,
    afficher_recherche,
    regrouper_fermes,
)
from trajets.assistant import RETOUR, SAUTER, derouler, reponse_valide
from trajets.cache import Cache
from trajets.dates import DateInvalide, est_vendredi, format_courte, format_jour, parse_date, parse_liste_dates
from trajets.modes import recherches_allers_retours, recherches_alternance
from trajets.models import PARIS_TZ, Itineraire, Lieu, Options, Recherche
from trajets.navigateur import Navigateur, NavigateurIndisponible, fermer_navigateurs_restes_ouverts
from trajets.providers import ErreurFournisseur
from trajets.rappels import construire_rappels, enregistrer, ouvrir_dans_calendrier
from trajets.recherche import Moteur
from trajets.reglages import DOSSIER_APP, Reglages
from trajets.ventes import charger_fenetres

STYLE = questionary.Style(
    [
        ("qmark", "fg:#e5007d bold"),
        ("question", "bold"),
        ("pointer", "fg:#00a1e0 bold"),
        ("highlighted", "fg:#00a1e0 bold"),
        ("selected", "fg:#00a1e0"),
        ("answer", "fg:#00a1e0 bold"),
        ("instruction", "fg:#8a8a8a italic"),
    ]
)
ANNULE = "↩ Annulé, retour au menu"
CHOIX_RETOUR = "↩ Retour"
SEUIL_JOURNEES = 8  # au-delà, on demande confirmation avant de lancer la recherche
SECONDES_PAR_JOURNEE = 10


def main() -> int:
    console = Console()
    if not sys.stdin.isatty():
        console.print("[red]trajets est interactif : lance-le depuis un terminal.[/]")
        return 2
    try:
        asyncio.run(Application(console).lancer())
    except KeyboardInterrupt:
        console.print("\n[yellow]À bientôt ![/]")
        return 130
    return 0


def aujourd_hui() -> date:
    return datetime.now(PARIS_TZ).date()


class Application:
    def __init__(self, console: Console):
        self.console = console
        self.reglages = Reglages.charger()
        self.fenetres = charger_fenetres(DOSSIER_APP / "ouvertures_ventes.json")
        self.statut = console.status("")
        self._navigateur: Navigateur | None = None
        self._moteur: Moteur | None = None

    # --- Boucle principale ----------------------------------------------------------------------

    async def lancer(self) -> None:
        self.console.print(
            Panel(
                Text.assemble(
                    ("🚄 Trajets", "bold magenta"),
                    " — billets TGV INOUI et OUIGO au meilleur prix\n",
                    ("↑↓ choisir · Entrée valider · Échap étape précédente · Ctrl+C menu principal", "dim"),
                ),
                expand=False,
            )
        )
        try:
            while True:
                choix = await self._choisir(
                    "Que veux-tu faire ?",
                    [
                        Choice("🎓  Mode alternance — Paris ⇄ Nancy, autour de tes fins de période", "alternance"),
                        Choice("🧭  Trajet libre — aller simple, aller-retour ou plusieurs A/R, villes au choix", "libre"),
                        Choice("⚙️   Réglages", "reglages"),
                        Choice("🚪  Quitter", "quitter"),
                    ],
                    retour=False,
                )
                if choix in (None, "quitter"):
                    break
                actions = {"alternance": self.mode_alternance, "libre": self.mode_libre, "reglages": self.menu_reglages}
                await actions[choix]()
                self.console.print()
        finally:
            await self._fermer_navigateur()
        self.console.print("[dim]À bientôt ![/]")

    # --- Mode alternance ------------------------------------------------------------------------

    async def mode_alternance(self) -> None:
        r, auj = self.reglages, aujourd_hui()
        etat = {
            "ecole": r.fins_a_venir(r.fins_ecole, auj),
            "entreprise": r.fins_a_venir(r.fins_entreprise, auj),
            "jours": "flex" if r.flex else tuple(r.jours_weekend),
            "avant": r.flex_avant,
            "apres": r.flex_apres,
        }

        async def ecole():
            return _ranger(etat, "ecole", await self._saisir_dates(
                "Vendredis de fin d'école (→ trajet Nancy → Paris)", etat["ecole"]
            ))

        async def entreprise():
            return _ranger(etat, "entreprise", await self._saisir_dates(
                "Vendredis de fin d'entreprise (→ trajet Paris → Nancy)", etat["entreprise"],
                obligatoire=not etat["ecole"], message_obligatoire="Indique au moins une date (ici ou à l'étape précédente)",
            ))

        async def jours():
            return _ranger(etat, "jours", await self._choisir(
                "Jours à chercher",
                [
                    Choice("Samedi et dimanche", (5, 6)),
                    Choice("Samedi seulement", (5,)),
                    Choice("Dimanche seulement", (6,)),
                    Choice(f"Flex : X jours avant et Y jours après la date (dernier choix : −{etat['avant']} / +{etat['apres']})", "flex"),
                ],
                defaut=etat["jours"],
            ))

        async def avant():
            if etat["jours"] != "flex":
                return SAUTER
            return _ranger(etat, "avant", await self._saisir_nombre(
                "Combien de jours AVANT la date ?", etat["avant"], "(0 = à partir de la date de fin, 1 = dès la veille…)"
            ))

        async def apres():
            if etat["jours"] != "flex":
                return SAUTER
            return _ranger(etat, "apres", await self._saisir_nombre(
                "Combien de jours APRÈS la date ?", etat["apres"], "(2 = jusqu'au dimanche pour un vendredi)"
            ))

        async def confirmation():
            r.flex = etat["jours"] == "flex"
            if r.flex:
                r.flex_avant, r.flex_apres = etat["avant"], etat["apres"]
            else:
                r.jours_weekend = sorted(etat["jours"])
            etat["recherches"], etat["passees"] = recherches_alternance(etat["ecole"], etat["entreprise"], r.choix_jours(), auj)
            return await self._confirmer_volume(etat["recherches"])

        if not await derouler([ecole, entreprise, jours, avant, apres, confirmation]):
            return
        r.fins_ecole = [d.isoformat() for d in etat["ecole"]]
        r.fins_entreprise = [d.isoformat() for d in etat["entreprise"]]
        r.enregistrer()

        if not r.flex:
            for d in etat["ecole"] + etat["entreprise"]:
                if not est_vendredi(d):
                    self.console.print(f"[yellow]⚠ Le {format_jour(d)} n'est pas un vendredi : je cherche le week-end qui suit.[/]")
        for d in etat["passees"]:
            self.console.print(f"[dim]Les jours à chercher autour du {format_jour(d)} sont déjà passés : ignoré.[/]")
        if etat["recherches"]:
            titre = "Récapitulatif — meilleur prix par période" if r.flex else "Récapitulatif — meilleur prix par week-end"
            await self._executer(etat["recherches"], r.options(direct_seulement=True), titre)

    # --- Trajet libre ---------------------------------------------------------------------------

    async def mode_libre(self) -> None:
        r, auj = self.reglages, aujourd_hui()
        etat = {
            "type": "simple",
            "origine": r.lieu("derniere_origine"),
            "destination": r.lieu("derniere_destination"),
            "allers": [],
            "retours": [],
            "flex": r.libre_flex,
            "avant": r.libre_flex_avant,
            "apres": r.libre_flex_apres,
            "direct": r.direct_seulement,
        }

        async def type_trajet():
            return _ranger(etat, "type", await self._choisir(
                "Type de trajet",
                [
                    Choice("Aller simple", "simple"),
                    Choice("Aller-retour", "ar"),
                    Choice("Plusieurs allers-retours (plusieurs dates d'aller et de retour)", "plusieurs"),
                ],
                defaut=etat["type"],
            ))

        async def origine():
            return _ranger(etat, "origine", await self._choisir_lieu("Ville ou gare de départ", etat["origine"]))

        async def destination():
            return _ranger(etat, "destination", await self._choisir_lieu(
                "Ville ou gare d'arrivée", etat["destination"], exclure=etat["origine"]
            ))

        async def allers():
            if etat["type"] == "plusieurs":
                return _ranger(etat, "allers", await self._saisir_dates(
                    "Dates d'aller", etat["allers"], obligatoire=True, minimum=auj,
                    aide="(séparées par des espaces, ex. 07/11 13/11 20/11)",
                ))
            aller = await self._saisir_date("Date de l'aller", defaut=etat["allers"][0] if etat["allers"] else None)
            return _ranger(etat, "allers", [aller] if reponse_valide(aller) else aller)

        async def retours():
            if etat["type"] == "simple":
                etat["retours"] = []
                return SAUTER
            if etat["type"] == "plusieurs":
                return _ranger(etat, "retours", await self._saisir_dates(
                    "Dates de retour", etat["retours"], minimum=auj,
                    aide="(séparées par des espaces — chaque aller est associé au premier retour qui suit)",
                ))
            precedent = etat["retours"][0] if etat["retours"] and etat["retours"][0] >= etat["allers"][0] else None
            retour = await self._saisir_date("Date du retour", minimum=etat["allers"][0], defaut=precedent)
            return _ranger(etat, "retours", [retour] if reponse_valide(retour) else retour)

        async def flex():
            return _ranger(etat, "flex", await self._choisir(
                "Dates",
                [
                    Choice("Dates exactes", False),
                    Choice(f"Flex : X jours avant et Y jours après chaque date (dernier choix : −{etat['avant']} / +{etat['apres']})", True),
                ],
                defaut=etat["flex"],
            ))

        async def avant():
            if not etat["flex"]:
                return SAUTER
            return _ranger(etat, "avant", await self._saisir_nombre("Combien de jours AVANT chaque date ?", etat["avant"], "(0 = pas de jour avant)"))

        async def apres():
            if not etat["flex"]:
                return SAUTER
            return _ranger(etat, "apres", await self._saisir_nombre("Combien de jours APRÈS chaque date ?", etat["apres"], "(0 = pas de jour après)"))

        async def direct():
            return _ranger(etat, "direct", await self._choisir(
                "Quels trajets ?",
                [Choice("Directs uniquement", True), Choice("Avec correspondances aussi", False)],
                defaut=etat["direct"],
            ))

        async def confirmation():
            plage = (etat["avant"], etat["apres"]) if etat["flex"] else None
            itineraire = Itineraire(etat["origine"], etat["destination"])
            etat["recherches"] = recherches_allers_retours(itineraire, etat["allers"], etat["retours"], plage, auj)
            if etat["type"] == "plusieurs":
                self._annoncer_allers_retours(etat["recherches"])
            return await self._confirmer_volume(etat["recherches"])

        etapes = [type_trajet, origine, destination, allers, retours, flex, avant, apres, direct, confirmation]
        if not await derouler(etapes):
            return
        r.derniere_origine, r.derniere_destination = etat["origine"].vers_dict(), etat["destination"].vers_dict()
        r.direct_seulement, r.libre_flex = etat["direct"], etat["flex"]
        if etat["flex"]:
            r.libre_flex_avant, r.libre_flex_apres = etat["avant"], etat["apres"]
        r.enregistrer()

        recherches = etat["recherches"]
        if not recherches:
            self.console.print("[yellow]Toutes les dates sont déjà passées.[/]")
            return
        comparatif = any(rech.sens == "retour" for rech in recherches) and any(rech.sens == "aller" for rech in recherches)
        await self._executer(recherches, r.options(), "Récapitulatif", comparatif=comparatif)

    def _annoncer_allers_retours(self, recherches: list[Recherche]) -> None:
        groupes: dict[str, list[Recherche]] = {}
        for rech in recherches:
            groupes.setdefault(rech.groupe or "", []).append(rech)
        self.console.print("[bold]Allers-retours comparés :[/]")
        for groupe, liste in groupes.items():
            self.console.print(f"  • {groupe} : " + " → ".join(rech.etiquette for rech in liste))

    # --- Saisies réutilisables ------------------------------------------------------------------

    async def _choisir_lieu(self, message: str, precedent: Lieu | None, exclure: Lieu | None = None):
        """Texte libre, puis choix dans la liste de SNCF Connect (« ↩ Retour » ramène à la saisie)."""
        if precedent and exclure and precedent.sncf_id == exclure.sncf_id:
            precedent = None
        defaut = precedent.nom if precedent else ""
        while True:
            texte = await self._texte(message, defaut, None, lambda t: len(t.strip()) >= 2 or "Tape au moins 2 lettres")
            if not reponse_valide(texte):
                return texte
            texte = texte.strip()
            if precedent and texte == precedent.nom:
                return precedent
            try:
                moteur = await self._moteur_pret()
                with self._attente(f"Recherche des gares « {texte} »…"):
                    lieux = await moteur.chercher_lieux(texte)
            except NavigateurIndisponible as exc:
                self.console.print(f"[red]{exc}[/]")
                return None
            except ErreurFournisseur as exc:
                self.console.print(f"[red]SNCF Connect : {exc}[/]")
                return None
            lieux = [l for l in lieux if not exclure or l.sncf_id != exclure.sncf_id]
            if not lieux:
                self.console.print(f"[yellow]Aucune ville ni gare trouvée pour « {texte} ».[/]")
                defaut = texte
                continue
            choix = await self._choisir("Laquelle ?", [Choice(_libelle_lieu(l), l) for l in lieux[:10]])
            if choix is None:
                return None
            if choix is not RETOUR:
                return choix
            defaut = texte  # retour à la saisie, texte conservé

    async def _saisir_dates(
        self,
        message: str,
        deja: list[date],
        obligatoire: bool = False,
        minimum: date | None = None,
        aide: str = "(séparés par des espaces, ex. 18/12/2026 22/01 — vide si aucun)",
        message_obligatoire: str = "Indique au moins une date",
    ):
        def valider(texte: str):
            try:
                dates = parse_liste_dates(texte, aujourd_hui())
            except DateInvalide as exc:
                return str(exc)
            if obligatoire and not dates:
                return message_obligatoire
            if minimum and any(d < minimum for d in dates):
                return f"Les dates doivent être à partir du {format_jour(minimum)}"
            return True

        texte = await self._texte(message, " ".join(format_courte(d) for d in deja), aide, valider)
        return parse_liste_dates(texte, aujourd_hui()) if reponse_valide(texte) else texte

    async def _saisir_date(self, message: str, minimum: date | None = None, defaut: date | None = None):
        minimum = minimum or aujourd_hui()

        def valider(texte: str):
            try:
                d = parse_date(texte, aujourd_hui())
            except DateInvalide as exc:
                return str(exc)
            return True if d >= minimum else f"Choisis une date à partir du {format_jour(minimum)}"

        texte = await self._texte(message, format_courte(defaut) if defaut else "", "(JJ/MM/AAAA, JJ/MM, demain…)", valider)
        return parse_date(texte, aujourd_hui()) if reponse_valide(texte) else texte

    async def _saisir_nombre(self, message: str, defaut: int, aide: str, maximum: int = 7):
        texte = await self._texte(
            message, str(defaut), aide, lambda t: (t.strip().isdigit() and int(t) <= maximum) or f"Un nombre entre 0 et {maximum}"
        )
        return int(texte) if reponse_valide(texte) else texte

    async def _confirmer_volume(self, recherches: list[Recherche]):
        """Beaucoup de jours = longue recherche et risque de blocage anti-robot : on demande confirmation."""
        nb_jours = len({(r.itineraire.label, j) for r in recherches for j in r.jours})
        if nb_jours <= SEUIL_JOURNEES:
            return True
        minutes = max(1, round(nb_jours * SECONDES_PAR_JOURNEE / 60))
        self.console.print(
            f"[yellow]{nb_jours} journées à chercher : compte environ {minutes} min. Beaucoup de recherches d'affilée "
            "peuvent déclencher la vérification anti-robot de SNCF Connect.[/]"
        )
        return await self._choisir("Lancer la recherche ?", [Choice("Oui, lancer", True)])

    # --- Réglages -------------------------------------------------------------------------------

    async def menu_reglages(self) -> None:
        while True:
            r = self.reglages
            sources = ", ".join(s for s, actif in (("SNCF Connect", r.sncf), ("OUIGO", r.ouigo)) if actif)
            choix = await self._choisir(
                "Réglages",
                [
                    Choice(f"Âge : {r.age} ans", "age"),
                    Choice(f"Carte de réduction : {'Carte Avantage Jeune' if r.carte_jeune else 'aucune'}", "carte"),
                    Choice(f"Sites consultés : {sources}", "sources"),
                    Choice(f"Trains : {'tous (TER, Intercités…)' if r.tous_trains else 'TGV INOUI et OUIGO seulement'}", "trains"),
                    Choice(f"Trains complets (horaires officiels SNCF) : {'détectés' if r.horaires_officiels else 'ignorés'}", "horaires"),
                    Choice(f"Fenêtre du navigateur : {'visible' if r.fenetre_visible else 'cachée'}", "fenetre"),
                    Choice(f"Dossier des rappels : {r.dossier_rappels}", "dossier"),
                    Choice("Vider le cache des recherches", "cache"),
                ],
            )
            if not reponse_valide(choix):
                return
            await self._modifier_reglage(choix)
            r.enregistrer()

    async def _modifier_reglage(self, cle: str) -> None:
        r = self.reglages
        if cle == "age":
            age = await self._texte(
                "Ton âge", str(r.age), None, lambda t: (t.isdigit() and 4 <= int(t) <= 99) or "Un nombre entre 4 et 99"
            )
            if reponse_valide(age):
                r.age = int(age)
                if r.carte_jeune and not 12 <= r.age <= 27:
                    self.console.print("[yellow]La Carte Avantage Jeune est réservée aux 12-27 ans.[/]")
        elif cle == "carte":
            carte = await self._choisir(
                "Carte de réduction",
                [Choice("Carte Avantage Jeune (12-27 ans)", True), Choice("Aucune carte", False)],
                defaut=r.carte_jeune,
            )
            if reponse_valide(carte):
                r.carte_jeune = carte
        elif cle == "sources":
            sources = await self._choisir(
                "Sites à consulter",
                [
                    Choice("SNCF Connect et OUIGO", (True, True)),
                    Choice("SNCF Connect seulement", (True, False)),
                    Choice("OUIGO seulement", (False, True)),
                ],
                defaut=(r.sncf, r.ouigo),
            )
            if reponse_valide(sources):
                r.sncf, r.ouigo = sources
        elif cle == "trains":
            tous = await self._choisir(
                "Trains à afficher",
                [Choice("TGV INOUI et OUIGO seulement", False), Choice("Tous les trains (TER, Intercités…)", True)],
                defaut=r.tous_trains,
            )
            if reponse_valide(tous):
                r.tous_trains = tous
        elif cle == "horaires":
            actif = await self._choisir(
                "Trains complets",
                [
                    Choice("Les détecter avec les horaires officiels SNCF (recommandé, ≈ 5 Mo téléchargés par jour d'utilisation)", True),
                    Choice("Ne pas les chercher", False),
                ],
                defaut=r.horaires_officiels,
            )
            if reponse_valide(actif):
                r.horaires_officiels = actif
        elif cle == "fenetre":
            visible = await self._choisir(
                "Fenêtre du navigateur",
                [
                    Choice("Cachée (recommandé)", False),
                    Choice("Visible (utile si SNCF Connect demande souvent une vérification)", True),
                ],
                defaut=r.fenetre_visible,
            )
            if reponse_valide(visible) and visible != r.fenetre_visible:
                r.fenetre_visible = visible
                await self._fermer_navigateur()  # relancé dans le bon mode à la prochaine recherche
        elif cle == "dossier":
            dossier = await self._poser(
                questionary.path(
                    "Dossier des rappels", default=r.dossier_rappels, only_directories=True,
                    instruction="(Échap : retour)", style=STYLE,
                )
            )
            if reponse_valide(dossier) and dossier:
                r.dossier_rappels = str(Path(dossier).expanduser())
        elif cle == "cache":
            if await self._choisir("Vider le cache des recherches ?", [Choice("Oui, vider", True)]) is True:
                for fichier in (DOSSIER_APP / "cache.json", DOSSIER_APP / "ouigo_gares.json", DOSSIER_APP / "horaires" / "index.json"):
                    fichier.unlink(missing_ok=True)
                await self._fermer_navigateur()
                self.console.print("[green]✓ Cache vidé.[/]")

    # --- Recherche et résultats -----------------------------------------------------------------

    async def _executer(self, recherches: list[Recherche], options: Options, titre_recap: str, comparatif: bool = False) -> None:
        self.console.print(f"[dim]{_resume_options(options)} — modifiable dans Réglages[/]")
        try:
            moteur = await self._moteur_pret()
        except NavigateurIndisponible as exc:
            self.console.print(f"[red]{exc}[/]")
            return
        with self._attente("Recherche en cours…"):
            for recherche in recherches:
                for jour in recherche.jours:
                    self.statut.update(f"Recherche {recherche.itineraire.label} du {format_jour(jour)}…")
                    recherche.resultats.append(await moteur.rechercher_jour(recherche.itineraire, jour, options))
        for recherche in recherches:
            afficher_recherche(self.console, recherche)
        if comparatif:
            afficher_comparatif_allers_retours(self.console, recherches)
        else:
            afficher_recapitulatif(self.console, recherches, titre_recap)
        await self._proposer_rappels([res for r in recherches for res in r.resultats])

    async def _proposer_rappels(self, resultats) -> None:
        groupes = regrouper_fermes([f for r in resultats for f in r.fermes])
        if not groupes:
            return
        afficher_ouvertures(self.console, groupes)
        maintenant = datetime.now(PARIS_TZ)
        a_venir = [g for g in groupes if g[0].ouverture.date_ouverture > maintenant]
        if len(a_venir) < len(groupes):
            self.console.print("[dim]Certaines dates d'ouverture estimées sont déjà passées : les billets devraient "
                               "arriver d'un jour à l'autre, vérifie régulièrement.[/]")
        if not a_venir or not await self._oui_non("Créer un rappel iCalendar pour ces ouvertures de ventes ?"):
            return
        fichier = enregistrer(construire_rappels(a_venir), Path(self.reglages.dossier_rappels))
        self.console.print(f"[green]✓ Rappel enregistré :[/] {fichier}", soft_wrap=True)
        if await self._oui_non("L'ajouter maintenant à ton calendrier ?"):
            if ouvrir_dans_calendrier(fichier):
                self.console.print("[green]✓ Ouvert dans ton application de calendrier.[/]")
            else:
                self.console.print("[yellow]Impossible de l'ouvrir automatiquement : double-clique sur le fichier .ics.[/]")

    # --- Navigateur -----------------------------------------------------------------------------

    async def _moteur_pret(self) -> Moteur:
        if self._moteur is None:
            profil = DOSSIER_APP / "navigateur"
            navigateur = Navigateur(profil, visible=self.reglages.fenetre_visible)
            try:
                with self._attente("Démarrage du navigateur…"):
                    await navigateur.__aenter__()
            except NavigateurIndisponible as exc:
                if not exc.profil_occupe:
                    raise
                self.console.print(f"[yellow]{exc}[/]")
                if not await self._oui_non("Fermer ce navigateur et continuer ?"):
                    raise
                fermer_navigateurs_restes_ouverts(profil)
                await asyncio.sleep(2)
                navigateur = Navigateur(profil, visible=self.reglages.fenetre_visible)
                with self._attente("Démarrage du navigateur…"):
                    await navigateur.__aenter__()
            self._navigateur = navigateur
            self._moteur = Moteur(
                navigateur,
                self.fenetres,
                Cache(DOSSIER_APP / "cache.json"),
                DOSSIER_APP / "ouigo_gares.json",
                self._demander_fenetre_visible,
                dossier_horaires=DOSSIER_APP / "horaires",
                annoncer=self.statut.update,
            )
        self._moteur.sncf_bloque = False  # nouvelle chance à chaque recherche
        return self._moteur

    async def _fermer_navigateur(self) -> None:
        if self._navigateur:
            await self._navigateur.__aexit__(None, None, None)
        self._navigateur = self._moteur = None

    async def _demander_fenetre_visible(self) -> bool:
        self.statut.stop()
        self.console.print(
            "\n[yellow]SNCF Connect demande une vérification anti-robot.[/] Je peux ouvrir une fenêtre Chrome : "
            "si un captcha s'affiche, résous-le toi-même, la recherche reprendra toute seule (3 min max)."
        )
        accepte = await self._oui_non("Ouvrir la fenêtre ?")
        self.statut.update("En attente de la vérification dans la fenêtre Chrome…")
        self.statut.start()
        return accepte

    # --- Petits outils d'interface --------------------------------------------------------------

    @contextmanager
    def _attente(self, message: str):
        self.statut.update(message)
        self.statut.start()
        try:
            yield
        finally:
            self.statut.stop()

    async def _poser(self, question: questionary.Question, retour: bool = True):
        """Pose la question. Renvoie None si l'utilisateur annule (Ctrl+C), RETOUR s'il appuie sur Échap."""
        if retour:
            touches = KeyBindings()

            @touches.add("escape", eager=True)
            def _revenir(event):
                event.app.exit(result=RETOUR)

            application = question.application
            application.key_bindings = merge_key_bindings([b for b in (application.key_bindings, touches) if b])
            application.ttimeoutlen = 0.1  # Échap réagit tout de suite
        return await question.ask_async(kbi_msg=ANNULE)

    async def _texte(self, message: str, defaut: str, aide: str | None, valider):
        aide = f"{aide[:-1]} · Échap : retour)" if aide else "(Échap : retour)"
        return await self._poser(questionary.text(message, default=defaut, instruction=aide, validate=valider, style=STYLE))

    async def _choisir(self, message: str, choix: list[Choice], defaut=None, retour: bool = True):
        """Menu au clavier ; avec `retour`, un choix « ↩ Retour » (ou Échap) renvoie RETOUR."""
        if retour:
            choix = [*choix, Choice(CHOIX_RETOUR, RETOUR)]
        initial = next((c for c in choix if defaut is not None and c.value == defaut), None)
        return await self._poser(
            questionary.select(message, choices=choix, default=initial, instruction="(↑↓ puis Entrée)", style=STYLE),
            retour=retour,
        )

    async def _oui_non(self, message: str, defaut: bool = True) -> bool:
        reponse = await self._choisir(message, [Choice("Oui", True), Choice("Non", False)], defaut=defaut, retour=False)
        return reponse is True


def _ranger(etat: dict, cle: str, valeur):
    """Mémorise une réponse valide dans l'état de l'assistant et la renvoie telle quelle."""
    if reponse_valide(valeur):
        etat[cle] = valeur
    return valeur


def _libelle_lieu(lieu: Lieu) -> str:
    genre = "ville, toutes les gares" if lieu.type == "CITY" else "gare"
    return f"{lieu.nom} ({genre}{', ' + lieu.region if lieu.region else ''})"


def _resume_options(options: Options) -> str:
    morceaux = [
        f"{options.age} ans",
        "Carte Avantage Jeune" if options.carte_jeune else "sans carte",
        "tous les trains" if options.tous_trains else "TGV INOUI / OUIGO",
        "directs uniquement" if options.direct_seulement else "avec correspondances",
        " + ".join(s for s, actif in (("SNCF Connect", options.sncf), ("OUIGO", options.ouigo)) if actif),
    ]
    return "Critères : " + " · ".join(morceaux)
