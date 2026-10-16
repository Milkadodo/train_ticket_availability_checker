"""Orchestration : pour chaque jour, interroge SNCF Connect et OUIGO puis fusionne les résultats."""

from __future__ import annotations

import asyncio
import json
import random
import time
from datetime import date, datetime
from pathlib import Path
from typing import Awaitable, Callable, TypeVar

from trajets.cache import Cache, trajet_depuis_dict, trajet_vers_dict
from trajets.dates import format_jour
from trajets.gares import GaresOuigo
from trajets.horaires import Horaires, TrainPrevu
from trajets.liens import lien_ouigo, lien_sncf_connect
from trajets.models import PARIS_TZ, Itineraire, Lieu, Options, ResultatJour, Statut, Trajet, TrajetsFermes
from trajets.navigateur import Navigateur, ProtectionAntiRobot
from trajets.providers import ErreurFournisseur
from trajets.providers import ouigo as ouigo_mod
from trajets.providers import sncf_connect as sncf_mod
from trajets.ventes import Fenetre, ouverture_pour

ATTENTE_VERIFICATION_AUTO = 20  # s : le « device check » DataDome se résout souvent seul
ATTENTE_VERIFICATION_MANUELLE = 180  # s : temps laissé pour résoudre un captcha dans la fenêtre
DUREE_VIE_GARES_OUIGO = 7 * 24 * 3600

T = TypeVar("T")


class Moteur:
    def __init__(
        self,
        navigateur: Navigateur,
        fenetres: list[Fenetre],
        cache: Cache,
        fichier_gares_ouigo: Path,
        demander_fenetre_visible: Callable[[], Awaitable[bool]],
        dossier_horaires: Path | None = None,
        annoncer: Callable[[str], None] = lambda message: None,
    ):
        self.navigateur = navigateur
        self.fenetres = fenetres
        self.cache = cache
        self.fichier_gares_ouigo = fichier_gares_ouigo
        self.demander_fenetre_visible = demander_fenetre_visible
        self.sncf = sncf_mod.SncfConnect(navigateur)
        self.ouigo = ouigo_mod.Ouigo(navigateur)
        self.sncf_bloque = False
        self._gares_ouigo: GaresOuigo | None = None
        self.dossier_horaires = dossier_horaires
        self.annoncer = annoncer
        self._horaires: Horaires | None = None
        self._horaires_charges = False

    # --- SNCF Connect --------------------------------------------------------------------------

    async def _via_sncf(self, action: Callable[[float], Awaitable[T]]) -> T:
        """Exécute un appel SNCF Connect ; en cas de vérification anti-robot, propose la fenêtre
        visible (où l'utilisateur peut résoudre un captcha) puis réessaie une fois."""
        for _ in range(2):
            if self.sncf_bloque:
                break
            attente = ATTENTE_VERIFICATION_MANUELLE if self.navigateur.visible else ATTENTE_VERIFICATION_AUTO
            try:
                return await action(attente)
            except ProtectionAntiRobot:
                if not self.navigateur.visible:
                    if not await self.demander_fenetre_visible():
                        break
                    await self.navigateur.passer_en_visible()
                await self.sncf.reinitialiser()
        self.sncf_bloque = True
        raise ErreurFournisseur("vérification anti-robot demandée par SNCF Connect : réessaie plus tard")

    async def chercher_lieux(self, texte: str) -> list[Lieu]:
        return await self._via_sncf(lambda attente: self.sncf.chercher_lieux(texte, attente))

    # --- Recherche d'une journée ----------------------------------------------------------------

    async def rechercher_jour(self, itineraire: Itineraire, jour: date, options: Options) -> ResultatJour:
        res = ResultatJour(itineraire, jour)
        trajets_sncf = trajets_ouigo = None
        if options.sncf:
            res.liens[sncf_mod.SOURCE] = lien_sncf_connect(itineraire, jour)
        itineraire_ouigo = await self._itineraire_ouigo(itineraire, options, res) if options.ouigo else None
        if itineraire_ouigo:
            res.liens[ouigo_mod.SOURCE] = lien_ouigo(itineraire_ouigo, jour)
        if options.sncf:
            trajets_sncf = await self._sncf(itineraire, jour, options, res)
        resultat_ouigo = await self._ouigo(itineraire_ouigo, jour, options, res) if itineraire_ouigo else None
        if resultat_ouigo:
            for t in resultat_ouigo.trajets:
                t.itineraire = itineraire
        res.trajets = fusionner(trajets_sncf or [], resultat_ouigo.trajets if resultat_ouigo else [])
        if options.horaires_officiels and (horaires := await self._horaires_officiels()) and horaires.couvre(jour):
            self._ajouter_trains_absents(res, horaires.trains(itineraire, jour), options, resultat_ouigo)
        self._ventes_fermees(res, trajets_sncf, resultat_ouigo)
        return res

    async def _sncf(self, itineraire: Itineraire, jour: date, options: Options, res: ResultatJour) -> list[Trajet] | None:
        cle = (
            f"sncf|{itineraire.origine.sncf_id}|{itineraire.destination.sncf_id}|{jour}|{options.age}|"
            f"{options.carte_jeune}|{options.tous_trains}|{options.direct_seulement}"
        )
        if (en_cache := self.cache.lire(cle)) is not None:
            return [trajet_depuis_dict(d, itineraire) for d in en_cache["trajets"]]
        try:
            trajets = await self._via_sncf(lambda attente: self.sncf.rechercher(itineraire, jour, options, attente))
        except ErreurFournisseur as exc:
            res.erreurs[sncf_mod.SOURCE] = str(exc)
            return None
        self.cache.ecrire(cle, {"trajets": [trajet_vers_dict(t) for t in trajets]})
        await asyncio.sleep(random.uniform(1.0, 2.0))  # reste discret entre deux journées
        return trajets

    async def _ouigo(self, itineraire: Itineraire, jour: date, options: Options, res: ResultatJour) -> ouigo_mod.ResultatOuigo | None:
        cle = f"ouigo2|{itineraire.origine.ouigo}|{itineraire.destination.ouigo}|{jour}|{options.direct_seulement}"
        if (en_cache := self.cache.lire(cle)) is not None:
            return ouigo_mod.ResultatOuigo(
                etat=en_cache["etat"],
                trajets=[trajet_depuis_dict(d, itineraire) for d in en_cache["trajets"]],
                prochain_depart=_date_ou_rien(en_cache["prochain_depart"]),
                en_vente_jusqu_au=_date_ou_rien(en_cache["en_vente_jusqu_au"]),
                alerte_possible=en_cache["alerte_possible"],
            )
        try:
            resultat = await self.ouigo.rechercher(itineraire, jour, options.direct_seulement)
        except ErreurFournisseur as exc:
            res.erreurs[ouigo_mod.SOURCE] = str(exc)
            return None
        self.cache.ecrire(
            cle,
            {
                "etat": resultat.etat,
                "trajets": [trajet_vers_dict(t) for t in resultat.trajets],
                "prochain_depart": resultat.prochain_depart.isoformat() if resultat.prochain_depart else None,
                "en_vente_jusqu_au": resultat.en_vente_jusqu_au.isoformat() if resultat.en_vente_jusqu_au else None,
                "alerte_possible": resultat.alerte_possible,
            },
        )
        return resultat

    # --- Gares OUIGO ----------------------------------------------------------------------------

    async def _itineraire_ouigo(self, itineraire: Itineraire, options: Options, res: ResultatJour) -> Itineraire | None:
        """L'itinéraire avec ses codes OUIGO, ou None (avec une explication) si OUIGO ne le dessert pas."""
        o, d = itineraire.origine, itineraire.destination
        if o.ouigo and d.ouigo:
            return itineraire
        try:
            gares = await self._gares()
        except ErreurFournisseur as exc:
            res.erreurs[ouigo_mod.SOURCE] = f"liste des gares indisponible ({exc})"
            return None
        code_o, code_d = gares.code_pour(o), gares.code_pour(d)
        manquant = next((l.nom for l, c in ((o, code_o), (d, code_d)) if not c), None)
        if manquant:
            res.infos.append(f"OUIGO ne dessert pas {manquant}.")
            return None
        if options.direct_seulement and not gares.relies(code_o, code_d):
            res.infos.append(f"Pas de OUIGO direct entre {gares.nom(code_o)} et {gares.nom(code_d)}.")
            return None
        return Itineraire(o.avec_ouigo(code_o), d.avec_ouigo(code_d))

    async def _gares(self) -> GaresOuigo:
        if self._gares_ouigo is None:
            fichier = self.fichier_gares_ouigo
            if fichier.exists() and time.time() - fichier.stat().st_mtime < DUREE_VIE_GARES_OUIGO:
                gares = json.loads(fichier.read_text(encoding="utf-8"))
            else:
                gares = await self.ouigo.charger_gares()
                fichier.parent.mkdir(parents=True, exist_ok=True)
                fichier.write_text(json.dumps(gares, ensure_ascii=False), encoding="utf-8")
            self._gares_ouigo = GaresOuigo(gares)
        return self._gares_ouigo

    # --- Horaires officiels : trains prévus mais absents de la vente -----------------------------

    async def _horaires_officiels(self) -> Horaires | None:
        if not self._horaires_charges and self.dossier_horaires:
            self.annoncer("Vérification des horaires officiels SNCF…")
            self._horaires = await asyncio.to_thread(Horaires.charger, self.dossier_horaires)
            self._horaires_charges = True
        return self._horaires

    def _ajouter_trains_absents(
        self, res: ResultatJour, prevus: list[TrainPrevu], options: Options, ouigo: ouigo_mod.ResultatOuigo | None
    ) -> None:
        """Un TGV INOUI / OUIGO prévu aux horaires officiels mais proposé par aucun site est en général
        complet (OUIGO retire de la vente ses trains complets), ou pas encore en vente."""
        types = ({"TGV INOUI", "OUIGO"} if options.sncf else set()) | ({"OUIGO"} if options.ouigo else set())
        numeros = {n for t in res.trajets for n in _numeros(t)}
        horaires = {(t.depart, t.arrivee) for t in res.trajets}
        ajoutes = []
        for p in prevus:
            if p.transporteur not in types or p.numero in numeros or (p.depart, p.arrivee) in horaires:
                continue
            en_vente = self._ventes_ouvertes(p.transporteur, res, ouigo)
            ajoutes.append(
                Trajet(
                    itineraire=res.itineraire,
                    depart=p.depart,
                    arrivee=p.arrivee,
                    gare_depart=p.gare_depart,
                    gare_arrivee=p.gare_arrivee,
                    transporteur=p.transporteur,
                    numero=p.numero,
                    statut=Statut.COMPLET if en_vente else Statut.PAS_ENCORE_EN_VENTE,
                    message="complet (n'est plus en vente)" if en_vente else "pas encore en vente",
                    theorique=True,
                )
            )
            numeros.add(p.numero)
            horaires.add((p.depart, p.arrivee))
        if ajoutes:
            res.trajets = sorted(res.trajets + ajoutes, key=lambda t: t.depart)
        if any(t.statut is Statut.COMPLET for t in ajoutes):
            res.infos.append(
                "Les trains marqués « n'est plus en vente » circulent d'après les horaires officiels SNCF, "
                "mais aucun site ne les vend : ils sont en général complets."
            )

    def _ventes_ouvertes(self, transporteur: str, res: ResultatJour, ouigo: ouigo_mod.ResultatOuigo | None) -> bool:
        if transporteur == "OUIGO":
            if ouigo is not None:
                return ouigo.etat != ouigo_mod.HORS_VENTE
            return not self._ouverture_future("OUIGO", res.jour)
        if any(t.statut is Statut.PAS_ENCORE_EN_VENTE and not t.est_ouigo for t in res.trajets):
            return False
        return not self._ouverture_future("TGV INOUI", res.jour)

    # --- Ouverture des ventes -------------------------------------------------------------------

    def _ventes_fermees(
        self, res: ResultatJour, trajets_sncf: list[Trajet] | None, ouigo: ouigo_mod.ResultatOuigo | None
    ) -> None:
        """Repère les trajets pas encore en vente et y associe la date d'ouverture des ventes.
        OUIGO le dit explicitement ; SNCF Connect marque les trains « En vente prochainement »."""
        transporteurs = {
            "OUIGO" if t.est_ouigo else "TGV INOUI" for t in res.trajets if t.statut is Statut.PAS_ENCORE_EN_VENTE
        }
        precisions: dict[str, list[str]] = {}
        # Journée entière absente de SNCF Connect alors que les ventes ne sont pas encore ouvertes.
        if trajets_sncf is not None and not trajets_sncf and self._ouverture_future("TGV INOUI", res.jour):
            transporteurs.add("TGV INOUI")
        if ouigo and ouigo.etat == ouigo_mod.HORS_VENTE:
            transporteurs.add("OUIGO")
            precisions["OUIGO"] = []
            if ouigo.en_vente_jusqu_au:
                precisions["OUIGO"].append(f"OUIGO vend pour l'instant jusqu'au {format_jour(ouigo.en_vente_jusqu_au)}")
            if ouigo.alerte_possible:
                precisions["OUIGO"].append("alerte e-mail d'ouverture possible sur la page OUIGO")
        elif ouigo and ouigo.etat == ouigo_mod.AUCUN_TRAIN:
            complets = any(t.theorique and t.est_ouigo and t.statut is Statut.COMPLET for t in res.trajets)
            debut = "OUIGO ne vend plus aucun train ce jour-là (complet)" if complets else "Aucun OUIGO ce jour-là"
            suite = f" — prochain OUIGO en vente le {format_jour(ouigo.prochain_depart)}" if ouigo.prochain_depart else ""
            res.infos.append(f"{debut}{suite}.")
        elif ouigo and not ouigo.trajets:
            res.infos.append("Aucun OUIGO direct ce jour-là (seulement avec correspondance).")
        elif ouigo and all(t.statut is Statut.COMPLET for t in ouigo.trajets):
            res.infos.append("Tous les OUIGO de ce jour sont complets.")
        for transporteur in sorted(transporteurs):
            ouverture = ouverture_pour(transporteur, res.jour, self.fenetres)
            lien = res.liens.get(ouigo_mod.SOURCE if transporteur == "OUIGO" else sncf_mod.SOURCE)
            res.fermes.append(
                TrajetsFermes(res.itineraire, res.jour, transporteur, ouverture, lien, precisions.get(transporteur, []))
            )

    def _ouverture_future(self, transporteur: str, jour: date) -> bool:
        return ouverture_pour(transporteur, jour, self.fenetres).date_ouverture > datetime.now(PARIS_TZ)


def _date_ou_rien(texte: str | None) -> date | None:
    return date.fromisoformat(texte) if texte else None


def regrouper_rames_jumelees(trajets: list[Trajet]) -> list[Trajet]:
    """Deux rames accouplées (mêmes horaires, deux numéros) deviennent une seule ligne, au meilleur prix."""
    groupes: dict = {}
    for t in trajets:
        if t.correspondances:
            groupes[(t.depart, t.arrivee, t.transporteur, id(t))] = [t]
            continue
        groupes.setdefault((t.depart, t.arrivee, t.transporteur, t.gare_arrivee), []).append(t)
    resultat = []
    for groupe in groupes.values():
        garde = min(groupe, key=lambda t: (t.meilleur_prix is None, t.meilleur_prix or 0))
        numeros = sorted({n for t in groupe for n in _numeros(t)}, key=lambda n: (len(n), n))
        garde.numero = "/".join(numeros) or garde.numero
        resultat.append(garde)
    return sorted(resultat, key=lambda t: t.depart)


def fusionner(trajets_sncf: list[Trajet], trajets_ouigo: list[Trajet]) -> list[Trajet]:
    """Un OUIGO vendu aussi sur SNCF Connect n'apparaît qu'une fois, avec les deux prix."""
    trajets = regrouper_rames_jumelees(trajets_sncf)
    for t in trajets_ouigo:
        existant = next((e for e in trajets if _meme_train(e, t)), None)
        if existant is None:
            trajets.append(t)
            continue
        existant.offres += t.offres
        if existant.statut is not Statut.DISPONIBLE and t.statut is Statut.DISPONIBLE:
            existant.statut, existant.message = Statut.DISPONIBLE, None
    return sorted(trajets, key=lambda t: t.depart)


def _meme_train(a: Trajet, b: Trajet) -> bool:
    if a.correspondances or b.correspondances:
        return (a.depart, a.arrivee, a.correspondances) == (b.depart, b.arrivee, b.correspondances) and a.est_ouigo and b.est_ouigo
    return bool(_numeros(a) & _numeros(b)) and (a.depart == b.depart or a.arrivee == b.arrivee)


def _numeros(t: Trajet) -> set[str]:
    return set(filter(None, (t.numero or "").split("/")))
