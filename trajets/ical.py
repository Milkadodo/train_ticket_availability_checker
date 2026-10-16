"""Génération de rappels iCalendar (RFC 5545) pour les ouvertures de ventes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


@dataclass
class Rappel:
    debut: datetime  # timezone-aware
    titre: str
    description: str
    url: str | None = None
    duree: timedelta = timedelta(minutes=30)
    alarmes: list[timedelta] = field(default_factory=lambda: [timedelta(days=1), timedelta(minutes=15)])

    @property
    def uid(self) -> str:
        cle = f"{self.debut.isoformat()}|{self.titre}".encode()
        return hashlib.sha1(cle).hexdigest()[:20] + "@trajets-alternance"


def generer_ics(rappels: list[Rappel], maintenant: datetime | None = None) -> str:
    maintenant = maintenant or datetime.now(timezone.utc)
    lignes = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//trajets-alternance//Paris-Nancy//FR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for r in rappels:
        lignes += [
            "BEGIN:VEVENT",
            f"UID:{r.uid}",
            f"DTSTAMP:{_utc(maintenant)}",
            f"DTSTART:{_utc(r.debut)}",
            f"DTEND:{_utc(r.debut + r.duree)}",
            f"SUMMARY:{_echapper(r.titre)}",
            f"DESCRIPTION:{_echapper(r.description)}",
        ]
        if r.url:
            lignes.append(f"URL:{r.url}")
        for avance in r.alarmes:
            lignes += [
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"TRIGGER:-{_duree(avance)}",
                f"DESCRIPTION:{_echapper(r.titre)}",
                "END:VALARM",
            ]
        lignes.append("END:VEVENT")
    lignes.append("END:VCALENDAR")
    return "".join(_plier(l) + "\r\n" for l in lignes)


def _utc(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _duree(td: timedelta) -> str:
    jours, reste = divmod(int(td.total_seconds()), 86400)
    heures, reste = divmod(reste, 3600)
    minutes = reste // 60
    texte = "P" + (f"{jours}D" if jours else "")
    if heures or minutes or not jours:
        texte += "T" + (f"{heures}H" if heures else "") + (f"{minutes}M" if minutes or not heures else "")
    return texte


def _echapper(texte: str) -> str:
    return texte.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _plier(ligne: str) -> str:
    """Coupe les lignes à 75 octets (sans couper un caractère UTF-8)."""
    morceaux, courant, taille = [], "", 0
    for car in ligne:
        n = len(car.encode("utf-8"))
        limite = 75 if not morceaux else 74  # les lignes de continuation commencent par une espace
        if taille + n > limite:
            morceaux.append(courant)
            courant, taille = "", 0
        courant += car
        taille += n
    morceaux.append(courant)
    return "\r\n ".join(morceaux)
