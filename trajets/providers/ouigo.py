"""Recherche sur ventes.ouigo.com : on ouvre le lien profond de recherche dans le navigateur et on
lit la réponse que le site récupère lui-même (horaires + prix), sans appeler son API à sa place.

Pour chaque jour, OUIGO dit explicitement s'il y a des trains (chacun complet ou non), si les billets
ne sont pas encore en vente (« OUT_OF_SALES »), ou s'il n'y a aucun OUIGO (avec le prochain départ).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime

from playwright.async_api import Response

from trajets.liens import lien_ouigo
from trajets.models import Itineraire, Offre, Statut, Trajet
from trajets.navigateur import Navigateur
from trajets.providers import ErreurFournisseur

SOURCE = "OUIGO"
ACCUEIL = "https://ventes.ouigo.com/fr-FR"
DELAI_MAX = 35  # secondes
DELAI_CALENDRIER = 3  # secondes laissées au calendrier des prix après la recherche

TRAINS = "trains"
HORS_VENTE = "hors vente"
AUCUN_TRAIN = "aucun train"


@dataclass
class ResultatOuigo:
    etat: str  # TRAINS, HORS_VENTE ou AUCUN_TRAIN
    trajets: list[Trajet] = field(default_factory=list)
    prochain_depart: date | None = None  # si aucun train ce jour-là
    en_vente_jusqu_au: date | None = None  # dernier jour actuellement en vente, si hors vente
    alerte_possible: bool = False  # OUIGO propose une alerte e-mail d'ouverture des ventes


class Ouigo:
    def __init__(self, navigateur: Navigateur):
        self.navigateur = navigateur

    async def charger_gares(self) -> list[dict]:
        """Liste des gares OUIGO, lue au chargement du site de vente."""
        gares, _ = await self._capturer(ACCUEIL, lambda r: "/api/Data/GetStations" in r.url and "NotServed" not in r.url)
        return gares

    async def rechercher(self, itineraire: Itineraire, jour: date, direct_seulement: bool = True) -> ResultatOuigo:
        lien = lien_ouigo(itineraire, jour)
        if lien is None:
            raise ErreurFournisseur("pas de gare OUIGO pour ce trajet")
        donnees, calendriers = await self._capturer(
            lien,
            lambda r: "/api/Sale/journeysearch" in r.url
            and r.request.method == "POST"
            and (r.request.post_data_json or {}).get("outbound_date") == jour.isoformat(),
            filtre_annexe=lambda r: "/api/Calendar/prices" in r.url and r.status == 200,
            attendre_annexes=lambda d: analyser_etat(d)[0] == HORS_VENTE,
        )
        etat, prochain, alerte = analyser_etat(donnees)
        return ResultatOuigo(
            etat=etat,
            trajets=analyser_recherche(donnees, itineraire, direct_seulement),
            prochain_depart=prochain,
            en_vente_jusqu_au=dernier_jour_en_vente(calendriers, jour) if etat == HORS_VENTE else None,
            alerte_possible=alerte,
        )

    async def _capturer(self, url: str, filtre, filtre_annexe=None, attendre_annexes=lambda donnees: False):
        """Ouvre une page ; renvoie le JSON de la première réponse qui passe `filtre`, et ceux des
        réponses qui passent `filtre_annexe` (attendues quelques secondes si `attendre_annexes`)."""
        page = await self.navigateur.nouvelle_page()
        capture: dict = {}
        annexes: list = []
        termine = asyncio.Event()

        async def sur_reponse(reponse: Response) -> None:
            try:
                if filtre_annexe and filtre_annexe(reponse):
                    annexes.append(await reponse.json())
                    return
                if termine.is_set() or not filtre(reponse):
                    return
                capture["statut"] = reponse.status
                capture["donnees"] = await reponse.json() if reponse.ok else None
            except Exception as exc:  # noqa: BLE001 - on remonte l'erreur proprement plus bas
                if termine.is_set() or (filtre_annexe and filtre_annexe(reponse)):
                    return  # une annexe illisible n'empêche pas la recherche
                capture["erreur"] = str(exc)
            termine.set()

        page.on("response", sur_reponse)
        try:
            await page.goto(url, wait_until="domcontentloaded")
            try:
                await asyncio.wait_for(termine.wait(), DELAI_MAX)
            except asyncio.TimeoutError as exc:
                raise ErreurFournisseur("OUIGO n'a pas répondu (délai dépassé)") from exc
            if capture.get("donnees") is not None and attendre_annexes(capture["donnees"]):
                for _ in range(DELAI_CALENDRIER * 4):
                    if len(annexes) >= 2:  # le calendrier autour du jour, puis celui du mois
                        break
                    await asyncio.sleep(0.25)
        finally:
            await page.close()
        if "erreur" in capture:
            raise ErreurFournisseur(f"Réponse OUIGO illisible : {capture['erreur']}")
        if capture.get("donnees") is None:
            raise ErreurFournisseur(f"OUIGO a répondu HTTP {capture.get('statut')}")
        return capture["donnees"], annexes


def analyser_etat(donnees: dict) -> tuple[str, date | None, bool]:
    """(état du jour, prochain départ, alerte e-mail possible)."""
    if donnees.get("outbound"):
        return TRAINS, None, False
    blocs = {b.get("name") for b in donnees.get("blocs_cms_outbound") or []}
    inscription = donnees.get("registration_sales_opening_outbound") or {}
    if "OUT_OF_SALES" in blocs or inscription:
        return HORS_VENTE, None, bool(inscription.get("can_register"))
    prochain = (donnees.get("next_departure_outbound") or {}).get("date")
    return AUCUN_TRAIN, date.fromisoformat(prochain) if prochain else None, False


def dernier_jour_en_vente(calendriers: list, jour: date) -> date | None:
    """Dans les calendriers de prix OUIGO, le dernier jour avant `jour` qui a un prix."""
    dates = [
        date.fromisoformat(item["date"])
        for calendrier in calendriers
        if isinstance(calendrier, list)
        for item in calendrier
        if item.get("price") is not None and item.get("date")
    ]
    avant = [d for d in dates if d < jour]
    return max(avant) if avant else None


def analyser_recherche(donnees: dict, itineraire: Itineraire, direct_seulement: bool = True) -> list[Trajet]:
    trajets = []
    for service in donnees.get("outbound") or []:
        segments = service.get("segments") or []
        if not segments or (direct_seulement and len(segments) != 1):
            continue
        depart = datetime.fromisoformat(service["departure_station"]["departure_timestamp"])
        arrivee = datetime.fromisoformat(service["arrival_station"]["arrival_timestamp"])
        prix = service.get("price")
        complet = bool(service.get("full"))
        if complet:
            statut, message = Statut.COMPLET, "complet"
        elif prix is None:
            statut, message = Statut.INDISPONIBLE, "pas de tarif"
        else:
            statut, message = Statut.DISPONIBLE, None
        if len(segments) == 1:
            type_service = segments[0].get("service_type") or {}
            transporteur = "OUIGO" if type_service.get("code", "OUIGO") == "OUIGO" else type_service.get("name", "OUIGO")
            numero = segments[0].get("service_name")
        else:
            transporteur = " + ".join(f"OUIGO {s.get('service_name', '')}".strip() for s in segments)
            numero = None
        trajets.append(
            Trajet(
                itineraire=itineraire,
                depart=depart,
                arrivee=arrivee,
                gare_depart=service["departure_station"].get("name", ""),
                gare_arrivee=service["arrival_station"].get("name", ""),
                transporteur=transporteur,
                numero=numero,
                statut=statut,
                offres=[Offre(SOURCE, prix, tarif="OUIGO Essentiel", classe="2de")] if prix is not None and not complet else [],
                message=message,
                correspondances=len(segments) - 1,
            )
        )
    return sorted(trajets, key=lambda t: t.depart)
