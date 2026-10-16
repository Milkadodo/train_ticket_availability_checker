"""Petit cache disque des recherches : relancer l'outil dans les minutes qui suivent ne re-sollicite
pas les sites (et limite le risque de blocage anti-robot)."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from trajets.models import Itineraire, Offre, Statut, Trajet

DUREE_VIE = 20 * 60  # secondes


class Cache:
    def __init__(self, fichier: Path, actif: bool = True):
        self.fichier = fichier
        self.actif = actif
        self._donnees: dict = {}
        if actif and fichier.exists():
            try:
                self._donnees = json.loads(fichier.read_text(encoding="utf-8"))
            except ValueError:
                self._donnees = {}

    def lire(self, cle: str) -> dict | None:
        if not self.actif:
            return None
        entree = self._donnees.get(cle)
        if not entree or time.time() - entree["t"] > DUREE_VIE:
            return None
        return entree["valeur"]

    def ecrire(self, cle: str, valeur: dict) -> None:
        maintenant = time.time()
        self._donnees = {k: v for k, v in self._donnees.items() if maintenant - v["t"] <= DUREE_VIE}
        self._donnees[cle] = {"t": maintenant, "valeur": valeur}
        if self.actif:
            self.fichier.parent.mkdir(parents=True, exist_ok=True)
            self.fichier.write_text(json.dumps(self._donnees, ensure_ascii=False), encoding="utf-8")


def trajet_vers_dict(t: Trajet) -> dict:
    return {
        "depart": t.depart.isoformat(),
        "arrivee": t.arrivee.isoformat(),
        "gare_depart": t.gare_depart,
        "gare_arrivee": t.gare_arrivee,
        "transporteur": t.transporteur,
        "numero": t.numero,
        "statut": t.statut.value,
        "offres": [vars(o) for o in t.offres],
        "message": t.message,
        "avertissements": t.avertissements,
        "correspondances": t.correspondances,
    }


def trajet_depuis_dict(d: dict, itineraire: Itineraire) -> Trajet:
    return Trajet(
        itineraire=itineraire,
        depart=datetime.fromisoformat(d["depart"]),
        arrivee=datetime.fromisoformat(d["arrivee"]),
        gare_depart=d["gare_depart"],
        gare_arrivee=d["gare_arrivee"],
        transporteur=d["transporteur"],
        numero=d["numero"],
        statut=Statut(d["statut"]),
        offres=[Offre(**o) for o in d["offres"]],
        message=d["message"],
        avertissements=list(d["avertissements"]),
        correspondances=d.get("correspondances", 0),
    )
