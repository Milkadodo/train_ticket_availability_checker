"""Horaires théoriques officiels SNCF (données ouvertes GTFS, transport.data.gouv.fr).

Les sites de vente n'affichent pas toujours un train complet (OUIGO le retire purement et simplement).
En comparant la vente aux horaires officiels, on sait quels TGV INOUI / OUIGO circulent vraiment un jour donné.
L'export (≈ 5,5 Mo) est téléchargé au plus une fois par jour, puis réduit à un petit index.
"""

from __future__ import annotations

import csv
import io
import json
import time
import urllib.request
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from trajets.models import PARIS_TZ, Itineraire, Lieu, gare_du_lieu

URL_GTFS = "https://eu.ftp.opendatasoft.com/sncf/plandata/Export_OpenData_SNCF_GTFS_NewTripId.zip"
DUREE_VIE = 24 * 3600
VERSION_INDEX = 2
# Préfixe des points d'arrêt GTFS -> transporteur affiché
TRANSPORTEURS = {"StopPoint:OCETGV INOUI-": "TGV INOUI", "StopPoint:OCEOUIGO-": "OUIGO"}


@dataclass(frozen=True)
class TrainPrevu:
    numero: str
    transporteur: str
    depart: datetime
    arrivee: datetime
    gare_depart: str
    gare_arrivee: str


class Horaires:
    def __init__(self, index: dict):
        self.debut = datetime.strptime(index["debut"], "%Y%m%d").date()
        self.fin = datetime.strptime(index["fin"], "%Y%m%d").date()
        self.gares: dict[str, str] = index["gares"]
        self._jours = {service: set(dates) for service, dates in index["services"].items()}
        self._trains = index["trains"]

    @classmethod
    def charger(cls, dossier: Path, telecharger=None) -> "Horaires | None":
        """Index à jour (moins d'un jour), sinon téléchargé et reconstruit ; l'ancien sert en secours."""
        fichier_index = dossier / "index.json"
        index = _lire_index(fichier_index)
        if index is None or time.time() - fichier_index.stat().st_mtime > DUREE_VIE:
            try:
                dossier.mkdir(parents=True, exist_ok=True)
                archive = dossier / "gtfs.zip"
                (telecharger or _telecharger)(archive)
                index = construire_index(archive)
                fichier_index.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
            except (OSError, ValueError, KeyError, zipfile.BadZipFile):
                pass  # hors ligne, ou format changé : on garde l'ancien index s'il existe
        return cls(index) if index else None

    def couvre(self, jour: date) -> bool:
        return self.debut <= jour <= self.fin

    def trains(self, itineraire: Itineraire, jour: date) -> list[TrainPrevu]:
        """Les TGV INOUI / OUIGO directs prévus ce jour-là de l'origine vers la destination."""
        origines = self._gares_du_lieu(itineraire.origine)
        destinations = self._gares_du_lieu(itineraire.destination)
        trains = []
        # Un train parti la veille peut passer à l'origine après minuit (horaire GTFS ≥ 24:00).
        for service_jour in (jour, jour - timedelta(days=1)):
            cle = service_jour.strftime("%Y%m%d")
            for numero, transporteur, service, arrets in self._trains:
                if cle not in self._jours.get(service, ()):
                    continue
                # a = [UIC, arrivée, départ, montée possible, descente possible]
                i = next((k for k, a in enumerate(arrets) if a[0] in origines and a[3]), None)
                j = next((k for k, a in enumerate(arrets) if i is not None and k > i and a[0] in destinations and a[4]), None)
                if i is None or j is None:
                    continue
                depart = _horaire(service_jour, arrets[i][2])
                if depart.date() != jour:
                    continue
                trains.append(
                    TrainPrevu(
                        numero=numero,
                        transporteur=transporteur,
                        depart=depart,
                        arrivee=_horaire(service_jour, arrets[j][1]),
                        gare_depart=self.gares.get(arrets[i][0], arrets[i][0]),
                        gare_arrivee=self.gares.get(arrets[j][0], arrets[j][0]),
                    )
                )
        return sorted(trains, key=lambda t: t.depart)

    def _gares_du_lieu(self, lieu: Lieu) -> set[str]:
        if lieu.type == "STATION" and lieu.uic:
            return {lieu.uic}
        return {uic for uic, nom in self.gares.items() if gare_du_lieu(nom, lieu.nom)}


def construire_index(archive: Path) -> dict:
    """Ne garde que les TGV INOUI et OUIGO : numéro, jours de circulation, arrêts
    (UIC, arrivée, départ, montée possible, descente possible)."""
    with zipfile.ZipFile(archive) as z:

        def lire(nom: str):
            return csv.DictReader(io.TextIOWrapper(z.open(nom), encoding="utf-8-sig"))

        arrets: dict[str, list] = defaultdict(list)
        transporteur_du_trajet: dict[str, str] = {}
        for r in lire("stop_times.txt"):
            prefixe = next((p for p in TRANSPORTEURS if r["stop_id"].startswith(p)), None)
            if prefixe is None:
                continue
            transporteur_du_trajet[r["trip_id"]] = TRANSPORTEURS[prefixe]
            uic = r["stop_id"][len(prefixe):]
            arrets[r["trip_id"]].append(
                (
                    int(r["stop_sequence"]),
                    uic,
                    r["arrival_time"][:5],
                    r["departure_time"][:5],
                    r.get("pickup_type") != "1",
                    r.get("drop_off_type") != "1",
                )
            )

        trains, services = [], set()
        for r in lire("trips.txt"):
            if r["trip_id"] in arrets:
                services.add(r["service_id"])
                liste = [a[1:] for a in sorted(arrets[r["trip_id"]])]
                trains.append([r["trip_headsign"], transporteur_du_trajet[r["trip_id"]], r["service_id"], liste])

        jours: dict[str, list[str]] = defaultdict(list)
        for r in lire("calendar_dates.txt"):
            if r["service_id"] in services and r["exception_type"] == "1":
                jours[r["service_id"]].append(r["date"])

        uics = {a[0] for t in trains for a in t[3]}
        gares = {}
        for r in lire("stops.txt"):
            if r["stop_id"].startswith("StopArea:OCE") and r["stop_id"][12:] in uics:
                gares[r["stop_id"][12:]] = r["stop_name"]

        info = next(iter(lire("feed_info.txt")), {})
        toutes_dates = [d for liste in jours.values() for d in liste]
    return {
        "version": VERSION_INDEX,
        "debut": info.get("feed_start_date") or min(toutes_dates),
        "fin": info.get("feed_end_date") or max(toutes_dates),
        "gares": gares,
        "services": jours,
        "trains": trains,
    }


def _telecharger(archive: Path) -> None:
    temporaire = archive.with_suffix(".tmp")
    requete = urllib.request.Request(URL_GTFS, headers={"User-Agent": "trajets-alternance"})
    with urllib.request.urlopen(requete, timeout=60) as reponse, open(temporaire, "wb") as sortie:
        sortie.write(reponse.read())
    temporaire.replace(archive)


def _lire_index(fichier: Path) -> dict | None:
    try:
        index = json.loads(fichier.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return index if index.get("version") == VERSION_INDEX else None


def _horaire(jour: date, hhmm: str) -> datetime:
    heures, minutes = (int(x) for x in hhmm.split(":"))
    return datetime.combine(jour, datetime.min.time(), tzinfo=PARIS_TZ) + timedelta(hours=heures, minutes=minutes)
