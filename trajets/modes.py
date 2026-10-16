"""Les façons de chercher : le mode alternance et le trajet libre (simple, aller-retour, plusieurs A/R)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from trajets.dates import format_jour, jours_de_trajet
from trajets.gares import NANCY_PARIS, PARIS_NANCY
from trajets.models import Itineraire, Recherche


@dataclass(frozen=True)
class ChoixJours:
    """Quels jours chercher autour d'une fin de période (un vendredi en général)."""

    jours_semaine: tuple[int, ...] = (5, 6)  # 5 = samedi, 6 = dimanche
    flex: tuple[int, int] | None = None  # (jours avant, jours après) la date, date incluse

    def jours(self, fin: date) -> list[date]:
        if self.flex:
            avant, apres = self.flex
            return [fin + timedelta(days=d) for d in range(-avant, apres + 1)]
        return jours_de_trajet(fin, list(self.jours_semaine))


def recherches_alternance(
    fins_ecole: list[date], fins_entreprise: list[date], choix: ChoixJours, aujourd_hui: date
) -> tuple[list[Recherche], list[date]]:
    """Fin d'école (à Nancy) -> on rentre à Paris ; fin d'entreprise (à Paris) -> on va à Nancy.
    Renvoie les recherches et les fins de période dont tous les jours sont déjà passés."""
    periodes = [(fin, "école", NANCY_PARIS) for fin in fins_ecole] + [(fin, "entreprise", PARIS_NANCY) for fin in fins_entreprise]
    recherches, passees = [], []
    for fin, periode, itineraire in sorted(periodes, key=lambda p: p[0]):
        a_venir = [j for j in choix.jours(fin) if j >= aujourd_hui]
        if not a_venir:
            passees.append(fin)
            continue
        recherches.append(
            Recherche(
                titre=f"Fin d'{periode} le {format_jour(fin)}",
                etiquette=f"fin d'{periode} {format_jour(fin, court=True)}",
                itineraire=itineraire,
                jours=a_venir,
            )
        )
    return recherches, passees


def apparier(allers: list[date], retours: list[date]) -> list[tuple[date | None, date | None]]:
    """Associe chaque aller au premier retour qui suit, avant l'aller suivant.
    Les dates sans partenaire restent seules : (aller, None) ou (None, retour)."""
    allers, restants = sorted(set(allers)), sorted(set(retours))
    paires: list[tuple[date | None, date | None]] = []
    for i, aller in enumerate(allers):
        suivant = allers[i + 1] if i + 1 < len(allers) else None
        retour = next((r for r in restants if r >= aller and (suivant is None or r < suivant)), None)
        if retour:
            restants.remove(retour)
        paires.append((aller, retour))
    paires += [(None, r) for r in restants]
    return sorted(paires, key=lambda p: p[0] or p[1])


def recherches_allers_retours(
    itineraire: Itineraire,
    allers: list[date],
    retours: list[date],
    flex: tuple[int, int] | None = None,
    aujourd_hui: date | None = None,
) -> list[Recherche]:
    """Aller simple, aller-retour ou plusieurs allers-retours : une recherche par date (ou par plage de
    dates en mode flex), regroupées par A/R. Les jours déjà passés sont ignorés."""
    paires = apparier(allers, retours)

    def jours(d: date) -> list[date]:
        plage = [d + timedelta(days=k) for k in range(-flex[0], flex[1] + 1)] if flex else [d]
        return [j for j in plage if aujourd_hui is None or j >= aujourd_hui]

    def titre(sens: str, d: date) -> str:
        if not flex:
            return f"{sens.capitalize()} le {format_jour(d)}"
        return f"{sens.capitalize()} autour du {format_jour(d)} (−{flex[0]} / +{flex[1]} j)"

    recherches = []
    for numero, (aller, retour) in enumerate(paires, 1):
        if aller and retour:
            groupe = f"A/R {numero}" if len(paires) > 1 else "A/R"
        else:
            groupe = "aller seul" if aller else "retour seul"
        for sens, d, itin in (("aller", aller, itineraire), ("retour", retour, itineraire.inverse())):
            jours_a_chercher = jours(d) if d else []
            if not jours_a_chercher:
                continue
            prefixe = f"{groupe} · " if len(paires) > 1 else ""
            recherches.append(
                Recherche(
                    titre=prefixe + titre(sens, d),
                    etiquette=f"{sens} {format_jour(d, court=True)}",
                    itineraire=itin,
                    jours=jours_a_chercher,
                    groupe=groupe,
                    sens=sens,
                )
            )
    return recherches
