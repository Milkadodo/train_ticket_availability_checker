"""Saisie des dates et calcul des week-ends de trajet."""

from __future__ import annotations

import re
from datetime import date, timedelta

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
JOURS_COURTS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MOIS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]
MOIS_COURTS = [
    "janv.", "févr.", "mars", "avr.", "mai", "juin",
    "juil.", "août", "sept.", "oct.", "nov.", "déc.",
]

SAMEDI, DIMANCHE = 5, 6


class DateInvalide(ValueError):
    pass


MOTS_RELATIFS = {"aujourd'hui": 0, "aujourd’hui": 0, "auj": 0, "demain": 1, "après-demain": 2, "apres-demain": 2}


def parse_date(texte: str, aujourd_hui: date) -> date:
    """Accepte JJ/MM/AAAA, JJ/MM/AA, JJ/MM (année déduite), AAAA-MM-JJ (séparateurs / - .),
    ainsi que « aujourd'hui », « demain » et « après-demain »."""
    t = texte.strip()
    if t.lower() in MOTS_RELATIFS:
        return aujourd_hui + timedelta(days=MOTS_RELATIFS[t.lower()])
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", t):
        a, mo, j = (int(x) for x in m.groups())
        return _construire(a, mo, j, texte)
    if m := re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})(?:[/.\-](\d{2}|\d{4}))?", t):
        j, mo = int(m.group(1)), int(m.group(2))
        if m.group(3) is None:
            # Sans année : la prochaine occurrence de cette date (aujourd'hui inclus).
            d = _construire(aujourd_hui.year, mo, j, texte)
            return d if d >= aujourd_hui else _construire(aujourd_hui.year + 1, mo, j, texte)
        a = int(m.group(3))
        return _construire(a + 2000 if a < 100 else a, mo, j, texte)
    raise DateInvalide(f"Date illisible : « {texte} » (formats acceptés : 06/11/2026, 06/11, 2026-11-06)")


def parse_liste_dates(texte: str, aujourd_hui: date) -> list[date]:
    """'06/11 18/12/2026, 15/01' -> dates triées, sans doublon."""
    return sorted({parse_date(morceau, aujourd_hui) for morceau in re.split(r"[\s,;]+", texte.strip()) if morceau})


def format_courte(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _construire(annee: int, mois: int, jour: int, texte: str) -> date:
    try:
        return date(annee, mois, jour)
    except ValueError as exc:
        raise DateInvalide(f"Date impossible : « {texte} »") from exc


def jours_de_trajet(fin_periode: date, jours: list[int] = (SAMEDI, DIMANCHE)) -> list[date]:
    """Le samedi et/ou le dimanche qui suivent la fin de période (normalement un vendredi)."""
    samedi = fin_periode + timedelta(days=(SAMEDI - fin_periode.weekday()) % 7)
    return [samedi + timedelta(days=j - SAMEDI) for j in jours]


def est_vendredi(d: date) -> bool:
    return d.weekday() == 4


def format_jour(d: date, court: bool = False) -> str:
    if court:
        return f"{JOURS_COURTS[d.weekday()]} {d.day} {MOIS_COURTS[d.month - 1]}"
    return f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]} {d.year}"
