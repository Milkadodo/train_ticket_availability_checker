"""Recherche SNCF Connect via l'API interne du site, appelée depuis la page (cookies DataDome inclus).

Pas d'API publique : le format peut changer sans préavis. Les requêtes restent volontairement peu
nombreuses (une recherche + la pagination d'une journée) et espacées.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone

from playwright.async_api import Page

from trajets.models import PARIS_TZ, Itineraire, Lieu, Offre, Options, Statut, Trajet
from trajets.navigateur import Navigateur, ProtectionAntiRobot, attendre_fin_verification
from trajets.providers import ErreurFournisseur

SOURCE = "SNCF Connect"
ACCUEIL = "https://www.sncf-connect.com/"
# Clé « publique » envoyée par le front web à son backend ; relue sur la page si elle change.
BFF_KEY_PAR_DEFAUT = "ah1MPO-izehIHD-QZZ9y88n-kku876"
CARTE_AVANTAGE_JEUNE = {"code": "YOUNG_PASS", "label": "Carte Avantage Jeune"}
PAGES_MAX = 8

_FETCH_JS = """async ([chemin, corps, entetes]) => {
  const r = await fetch(chemin, {method: 'POST', headers: entetes, body: JSON.stringify(corps)});
  return {status: r.status, texte: await r.text()};
}"""


class SncfConnect:
    def __init__(self, navigateur: Navigateur):
        self.navigateur = navigateur
        self._page: Page | None = None
        self._bff_key = BFF_KEY_PAR_DEFAUT

    async def reinitialiser(self) -> None:
        self._page = None

    async def chercher_lieux(self, texte: str, attente_verification: float = 20) -> list[Lieu]:
        """Villes et gares correspondant au texte saisi (autocomplétion de SNCF Connect)."""
        page = await self._page_prete(attente_verification)
        reponse = await self._appeler(
            page,
            "/bff/api/v2/autocomplete",
            {"searchTerm": texte, "resultTypes": ["PLACE"], "recentSearchTypes": []},
            {"x-search-usage": "AUTOCOMPLETION"},
        )
        return analyser_autocompletion(reponse)

    async def rechercher(
        self, itineraire: Itineraire, jour: date, options: Options, attente_verification: float = 20
    ) -> list[Trajet]:
        page = await self._page_prete(attente_verification)
        id_recherche = str(uuid.uuid4())
        reponse = await self._appeler(page, "/bff/api/v1/itineraries", self._corps(itineraire, jour, options, id_recherche))
        propositions = _propositions(reponse)
        for _ in range(PAGES_MAX):
            suivant = (reponse.get("longDistance", {}).get("proposals", {}).get("pagination") or {}).get("next")
            if not suivant or suivant.get("changeDay"):
                break
            await asyncio.sleep(random.uniform(0.8, 1.6))
            reponse = await self._appeler(
                page,
                "/bff/api/v1/itineraries/more",
                {
                    "itineraryId": id_recherche,
                    "next": True,
                    "outward": True,
                    "trainExpected": True,
                    "metadataY": {"decisionAction": "NEXT"},
                    "decisionSource": "FORCE",
                },
            )
            nouvelles = _propositions(reponse)
            if not nouvelles:
                break
            propositions += nouvelles
        trajets = {}
        for p in propositions:
            trajet = analyser_proposition(p, itineraire, jour, options)
            if trajet:
                trajets[(trajet.depart, trajet.libelle_train)] = trajet
        return sorted(trajets.values(), key=lambda t: t.depart)

    async def _page_prete(self, attente_verification: float) -> Page:
        if self._page and not self._page.is_closed():
            return self._page
        page = await self.navigateur.nouvelle_page()

        def lire_cle(requete):
            cle = requete.headers.get("x-bff-key")
            if cle:
                self._bff_key = cle

        page.on("request", lire_cle)
        await page.goto(ACCUEIL, wait_until="domcontentloaded")
        if not await attendre_fin_verification(page, attente_verification):
            await page.close()
            raise ProtectionAntiRobot("SNCF Connect demande une vérification anti-robot")
        self._page = page
        return page

    def _corps(self, itineraire: Itineraire, jour: date, options: Options, id_recherche: str) -> dict:
        minuit = datetime.combine(jour, time(0, 0), tzinfo=PARIS_TZ)
        passager = {
            "id": "0",
            "discountCards": [],
            "typology": "ADULT",
            "withoutSeatAssignment": False,
            "hasDisability": False,
            "hasWheelchair": False,
        }
        if options.carte_jeune:
            passager.update(typology="YOUNG", age=options.age, discountCards=[CARTE_AVANTAGE_JEUNE])

        def lieu(l: Lieu) -> dict:
            return {"label": l.nom, "id": l.sncf_id, "codes": [], "geolocation": False}

        return {
            "schedule": {
                "outward": {"date": minuit.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"), "arrivalAt": False}
            },
            "mainJourney": {"origin": lieu(itineraire.origine), "destination": lieu(itineraire.destination)},
            "passengers": [passager],
            "pets": [],
            "itineraryId": id_recherche,
            "forceDisplayResults": True,
            "trainExpected": True,
            "wishBike": False,
            "strictMode": False,
            "directJourney": options.direct_seulement,
            "transporterLabels": [],
            "metadataY": {},
            "userNavigation": ["IS_NOT_BUSINESS"],
        }

    async def _appeler(self, page: Page, chemin: str, corps: dict, entetes_en_plus: dict | None = None) -> dict:
        entetes = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "x-bff-key": self._bff_key,
            "x-client-app-id": "front-web",
            "x-client-channel": "web",
            "x-market-locale": "fr_FR",
            "x-api-env": "production",
            "x-device-class": "desktop",
            "virtual-env-name": "master",
            **(entetes_en_plus or {}),
        }
        resultat = await page.evaluate(_FETCH_JS, [chemin, corps, entetes])
        statut, texte = resultat["status"], resultat["texte"]
        if statut == 403 and "captcha-delivery" in texte:
            self._page = None
            await page.close()
            raise ProtectionAntiRobot("SNCF Connect demande une vérification anti-robot")
        if statut != 200:
            raise ErreurFournisseur(f"SNCF Connect a répondu HTTP {statut} : {texte[:200]}")
        try:
            return json.loads(texte)
        except ValueError as exc:
            raise ErreurFournisseur("Réponse SNCF Connect illisible") from exc


def analyser_autocompletion(reponse: dict) -> list[Lieu]:
    lieux: dict[str, Lieu] = {}
    for section in reponse.get("places") or []:
        for r in section.get("results") or []:
            type_lieu = (r.get("type") or {}).get("placeType")
            if type_lieu not in ("CITY", "STATION") or not r.get("id") or r["id"] in lieux:
                continue
            codes = {c.get("type"): c.get("value") for c in r.get("codes") or []}
            lieux[r["id"]] = Lieu(
                nom=r.get("label", ""),
                sncf_id=r["id"],
                type=type_lieu,
                uic=codes.get("UIC8"),
                region=r.get("description") if isinstance(r.get("description"), str) else None,
            )
    return list(lieux.values())


def _propositions(reponse: dict) -> list[dict]:
    return list(((reponse.get("longDistance") or {}).get("proposals") or {}).get("proposals") or [])


def _segments(p: dict) -> list[dict]:
    """Les tronçons (train, car...) de la frise du trajet."""
    return [
        valeur
        for etape in (p.get("globalTimeline") or {}).get("steps", [])
        for valeur in etape.values()
        if isinstance(valeur, dict) and "transporter" in valeur
    ]


def _nb_correspondances(description: str, segments: list[dict]) -> int:
    if description.lower().startswith("direct"):
        return 0
    if m := re.match(r"(\d+)\s+correspondance", description, re.I):
        return int(m.group(1))
    return max(len(segments) - 1, 0)


def analyser_proposition(p: dict, itineraire: Itineraire, jour: date, options: Options = Options()) -> Trajet | None:
    """Transforme une proposition SNCF Connect en Trajet ; None si elle ne correspond pas aux critères."""
    travel_id = p.get("travelId") or ""
    if not travel_id.startswith(jour.isoformat()):
        return None
    description = p.get("transporterDescription") or ""
    segments = _segments(p)
    correspondances = _nb_correspondances(description, segments)
    if options.direct_seulement and correspondances:
        return None

    descriptions = [(s.get("transporter") or {}).get("description") or "" for s in segments]
    if not descriptions:
        descriptions = [description.removeprefix("Direct ").strip()]
    if not options.tous_trains and not all(re.search(r"TGV|OUIGO", d, re.I) for d in descriptions):
        return None

    if correspondances or len(segments) > 1:
        transporteur = " + ".join(
            f"{d} {_numero((s.get('transporter') or {}).get('number')) or ''}".strip()
            for d, s in zip(descriptions, segments)
        )
        numero = None
    else:
        transporteur = descriptions[0]
        info = (segments[0].get("transporter") or {}) if segments else {}
        numero = _numero(info.get("number")) or _numero(travel_id.split("_", 1)[-1])

    depart = _horaire(jour, (p.get("departure") or {}).get("timeLabel"))
    arrivee = _horaire(jour, (p.get("arrival") or {}).get("timeLabel"))
    if depart is None or arrivee is None:
        return None
    if arrivee < depart:
        arrivee += timedelta(days=1)

    premier, dernier = (segments[0], segments[-1]) if segments else ({}, {})
    gare_depart = (premier.get("departure") or {}).get("stationLabel") or (p.get("departure") or {}).get("originStationLabel", "")
    gare_arrivee = (dernier.get("arrival") or {}).get("stationLabel") or (p.get("arrival") or {}).get("destinationStationLabel", "")

    statut_brut = p.get("status") or {}
    offre, avertissements = _meilleure_offre(p)
    if statut_brut.get("isBookable", True):
        statut = Statut.DISPONIBLE if offre else Statut.INDISPONIBLE
        message = None if offre else "aucun tarif proposé"
    else:
        libelle = statut_brut.get("label") or statut_brut.get("title") or "indisponible"
        if "prochainement" in libelle.lower():
            statut = Statut.PAS_ENCORE_EN_VENTE
        elif "complet" in libelle.lower():
            statut = Statut.COMPLET
        else:
            statut = Statut.INDISPONIBLE
        message = libelle

    return Trajet(
        itineraire=itineraire,
        depart=depart,
        arrivee=arrivee,
        gare_depart=gare_depart,
        gare_arrivee=gare_arrivee,
        transporteur=transporteur,
        numero=numero,
        statut=statut,
        offres=[offre] if offre else [],
        message=message,
        avertissements=avertissements,
        correspondances=correspondances,
    )


def _meilleure_offre(p: dict) -> tuple[Offre | None, list[str]]:
    meilleure, avertissements = None, []
    for cle, classe in (("secondComfortClassOffers", "2de"), ("firstComfortClassOffers", "1re")):
        for o in ((p.get(cle) or {}).get("offers") or []):
            if o.get("type") == "PUSH":
                continue  # suggestion d'achat d'une autre carte, pas un tarif accessible
            prix = _prix(o.get("priceLabel"))
            if prix is None:
                continue
            if meilleure is None or prix < meilleure.prix:
                fares = o.get("travelersFares") or [{}]
                tarif = " + ".join(fares[0].get("subtitles") or []) or o.get("title")
                meilleure = Offre(SOURCE, prix, tarif=tarif, classe=classe)
                avertissements = [
                    m["message"] for m in o.get("messages") or [] if "place" in (m.get("message") or "").lower()
                ]
    return meilleure, avertissements


def _prix(libelle: str | None) -> float | None:
    if not libelle:
        return None
    m = re.search(r"(\d+(?:[   ]\d{3})*(?:,\d{1,2})?)", libelle)
    if not m:
        return None
    return float(re.sub(r"[   ]", "", m.group(1)).replace(",", "."))


def _horaire(jour: date, libelle: str | None) -> datetime | None:
    m = re.fullmatch(r"(\d{1,2})[:h](\d{2})", (libelle or "").strip())
    if not m:
        return None
    return datetime.combine(jour, time(int(m.group(1)), int(m.group(2))), tzinfo=PARIS_TZ)


def _numero(texte: str | None) -> str | None:
    m = re.search(r"\d{3,6}", texte or "")
    return m.group(0) if m else None
