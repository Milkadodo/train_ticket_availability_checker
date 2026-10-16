"""Dates d'ouverture des ventes : calendrier connu + estimation selon le rythme habituel SNCF.

Rythme observé (2026) :
- voyages de début juillet à la mi-décembre  -> ouverture le 2e mercredi de mars ;
- voyages des fêtes (mi-décembre -> 6 janvier) -> ouverture le dernier mercredi de septembre ;
- voyages de janvier à début juillet :
    TGV INOUI -> 2e jeudi de novembre de l'année précédente,
    OUIGO     -> dernier mercredi de septembre de l'année précédente (avec les fêtes).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from importlib import resources
from pathlib import Path

from trajets.models import PARIS_TZ, OuvertureVentes

HEURE_OUVERTURE = time(6, 0)
SOURCE_ESTIMATION = "estimation d'après le rythme habituel des ouvertures SNCF"


@dataclass(frozen=True)
class Fenetre:
    transporteur: str
    voyages_du: date
    voyages_au: date
    ouverture: datetime
    source: str | None


def normaliser_transporteur(nom: str) -> str:
    return "OUIGO" if "OUIGO" in nom.upper() else "TGV INOUI"


def charger_fenetres(fichier_utilisateur: Path | None = None) -> list[Fenetre]:
    """Fenêtres du fichier utilisateur (prioritaires) puis celles fournies avec l'outil."""
    contenus = []
    if fichier_utilisateur and fichier_utilisateur.exists():
        contenus.append(json.loads(fichier_utilisateur.read_text(encoding="utf-8")))
    contenus.append(json.loads(resources.files("trajets.data").joinpath("ouvertures_ventes.json").read_text("utf-8")))
    fenetres = []
    for contenu in contenus:
        for item in contenu.get("ouvertures", []):
            fenetres.append(
                Fenetre(
                    transporteur=normaliser_transporteur(item["transporteur"]),
                    voyages_du=date.fromisoformat(item["voyages_du"]),
                    voyages_au=date.fromisoformat(item["voyages_au"]),
                    ouverture=datetime.fromisoformat(item["ouverture"]).replace(tzinfo=PARIS_TZ),
                    source=item.get("source"),
                )
            )
    return fenetres


def ouverture_pour(transporteur: str, jour: date, fenetres: list[Fenetre]) -> OuvertureVentes:
    transporteur = normaliser_transporteur(transporteur)
    for f in fenetres:
        if f.transporteur == transporteur and f.voyages_du <= jour <= f.voyages_au:
            return OuvertureVentes(transporteur, f.ouverture, estimee=False, source=f.source)
    return OuvertureVentes(transporteur, estimer_ouverture(transporteur, jour), estimee=True, source=SOURCE_ESTIMATION)


def estimer_ouverture(transporteur: str, jour: date) -> datetime:
    transporteur = normaliser_transporteur(transporteur)
    a = jour.year
    if _premier_samedi_juillet(a) <= jour < _changement_de_service(a):
        d = _nieme_jour(a, 3, 2, n=2)  # 2e mercredi de mars
    elif jour >= _changement_de_service(a):
        d = _dernier_jour(a, 9, 2)  # dernier mercredi de septembre
    elif transporteur == "OUIGO" or jour <= date(a, 1, 6):
        d = _dernier_jour(a - 1, 9, 2)
    else:
        d = _nieme_jour(a - 1, 11, 3, n=2)  # 2e jeudi de novembre
    return datetime.combine(d, HEURE_OUVERTURE, tzinfo=PARIS_TZ)


def _nieme_jour(annee: int, mois: int, jour_semaine: int, n: int) -> date:
    d = date(annee, mois, 1)
    d += timedelta(days=(jour_semaine - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _dernier_jour(annee: int, mois: int, jour_semaine: int) -> date:
    fin = date(annee + (mois == 12), mois % 12 + 1, 1) - timedelta(days=1)
    return fin - timedelta(days=(fin.weekday() - jour_semaine) % 7)


def _premier_samedi_juillet(annee: int) -> date:
    return _nieme_jour(annee, 7, 5, n=1)


def _changement_de_service(annee: int) -> date:
    """Le service annuel ferroviaire change le 2e dimanche de décembre."""
    return _nieme_jour(annee, 12, 6, n=2)
