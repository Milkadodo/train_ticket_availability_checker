"""Réglages mémorisés entre deux utilisations (~/.trajets-alternance/reglages.json)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from datetime import date
from pathlib import Path

from trajets.models import Lieu, Options
from trajets.modes import ChoixJours

# TRAJETS_DOSSIER permet d'isoler une autre installation (tests, essais) de tes vraies données.
DOSSIER_APP = Path(os.environ.get("TRAJETS_DOSSIER") or Path.home() / ".trajets-alternance")
FICHIER = DOSSIER_APP / "reglages.json"


@dataclass
class Reglages:
    age: int = 20
    carte_jeune: bool = True
    sncf: bool = True
    ouigo: bool = True
    tous_trains: bool = False
    direct_seulement: bool = True
    fenetre_visible: bool = False
    horaires_officiels: bool = True
    dossier_rappels: str = str(Path.home() / "Documents" / "Rappels trains")
    # Mode alternance : derniers vendredis saisis (AAAA-MM-JJ) et jours cherchés (5 = samedi, 6 = dimanche)
    fins_ecole: list[str] = field(default_factory=list)
    fins_entreprise: list[str] = field(default_factory=list)
    jours_weekend: list[int] = field(default_factory=lambda: [5, 6])
    flex: bool = False  # sinon samedi et/ou dimanche
    flex_avant: int = 1  # jours cherchés avant la date de fin de période...
    flex_apres: int = 2  # ... et après (la date elle-même est incluse)
    # Mode trajet libre : flex autour de chaque date, derniers lieux choisis
    libre_flex: bool = False
    libre_flex_avant: int = 1
    libre_flex_apres: int = 1
    derniere_origine: dict | None = None
    derniere_destination: dict | None = None

    @classmethod
    def charger(cls, fichier: Path = FICHIER) -> "Reglages":
        try:
            donnees = json.loads(fichier.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        connus = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in donnees.items() if k in connus})

    def enregistrer(self, fichier: Path = FICHIER) -> None:
        fichier.parent.mkdir(parents=True, exist_ok=True)
        fichier.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    def options(self, direct_seulement: bool | None = None) -> Options:
        return Options(
            age=self.age,
            carte_jeune=self.carte_jeune,
            tous_trains=self.tous_trains,
            direct_seulement=self.direct_seulement if direct_seulement is None else direct_seulement,
            sncf=self.sncf,
            ouigo=self.ouigo,
            horaires_officiels=self.horaires_officiels,
        )

    def fins_a_venir(self, liste: list[str], aujourd_hui: date) -> list[date]:
        """Les vendredis mémorisés dont le week-end n'est pas encore passé."""
        dates = []
        for texte in liste:
            try:
                d = date.fromisoformat(texte)
            except ValueError:
                continue
            if d.toordinal() + 2 >= aujourd_hui.toordinal():
                dates.append(d)
        return sorted(dates)

    def choix_jours(self) -> ChoixJours:
        if self.flex:
            return ChoixJours(flex=(self.flex_avant, self.flex_apres))
        return ChoixJours(jours_semaine=tuple(self.jours_weekend))

    def lieu(self, cle: str) -> Lieu | None:
        valeur = getattr(self, cle)
        return Lieu.depuis_dict(valeur) if valeur else None
