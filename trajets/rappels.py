"""Rappels iCalendar pour les ouvertures de ventes."""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path

from trajets.dates import format_jour
from trajets.ical import Rappel, generer_ics
from trajets.liens import PAGE_OUVERTURE_VENTES, lien_sncf_connect
from trajets.models import TrajetsFermes


def construire_rappels(groupes: list[list[TrajetsFermes]]) -> list[Rappel]:
    rappels = []
    for groupe in groupes:
        o = groupe[0].ouverture
        trajets = ", ".join(f"{f.itineraire.label} {format_jour(f.jour, court=True)}" for f in groupe)
        lignes = [
            f"Les billets {o.transporteur} ouvrent à la vente"
            + (" (date estimée, à vérifier)" if o.estimee else "")
            + " : réserve vite pour avoir les meilleurs prix.",
            "",
        ]
        for f in groupe:
            lien = f.lien or lien_sncf_connect(f.itineraire, f.jour)
            lignes.append(f"• {f.itineraire.label} — {format_jour(f.jour)} : {lien}")
        precisions = list(dict.fromkeys(p for f in groupe for p in f.precisions))
        if precisions:
            lignes += ["", *(f"ℹ {p}" for p in precisions)]
        lignes += ["", f"Calendrier officiel des ouvertures : {PAGE_OUVERTURE_VENTES}"]
        if o.source and o.source != PAGE_OUVERTURE_VENTES:
            lignes.append(f"Source : {o.source}")
        rappels.append(
            Rappel(
                debut=o.date_ouverture,
                titre=f"🚄 Ouverture ventes {o.transporteur} — {trajets}",
                description="\n".join(lignes),
                url=PAGE_OUVERTURE_VENTES,
            )
        )
    return rappels


def enregistrer(rappels: list[Rappel], dossier: Path) -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    dates = sorted({r.debut.date() for r in rappels})
    nom = "ouverture-ventes-" + "_".join(d.strftime("%Y%m%d") for d in dates[:3]) + ".ics"
    fichier = dossier / nom
    fichier.write_text(generer_ics(rappels), encoding="utf-8", newline="")
    return fichier


def ouvrir_dans_calendrier(fichier: Path) -> bool:
    commande = {"Darwin": ["open"], "Linux": ["xdg-open"], "Windows": ["cmd", "/c", "start", ""]}.get(platform.system())
    if not commande:
        return False
    try:
        subprocess.run([*commande, str(fichier)], check=True, capture_output=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False
