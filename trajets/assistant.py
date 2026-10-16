"""Enchaînement de questions où l'on peut revenir à l'étape précédente."""

from __future__ import annotations

from typing import Any, Awaitable, Callable


class _Marqueur:
    def __init__(self, nom: str):
        self.nom = nom

    def __repr__(self) -> str:
        return self.nom


RETOUR = _Marqueur("RETOUR")  # revenir à la question précédente (Échap ou « ↩ Retour »)
SAUTER = _Marqueur("SAUTER")  # étape sans objet ici (ex. date de retour pour un aller simple)


def reponse_valide(valeur: Any) -> bool:
    """Ni annulation (None), ni retour, ni étape sautée."""
    return valeur is not None and valeur is not RETOUR and valeur is not SAUTER


async def derouler(etapes: list[Callable[[], Awaitable[Any]]]) -> bool:
    """Pose les étapes dans l'ordre. Chacune renvoie sa réponse, RETOUR, SAUTER ou None (annulation).
    Une étape sautée l'est aussi quand on recule. Renvoie True si la dernière étape est validée,
    False si l'utilisateur annule ou revient avant la première."""
    i, sens = 0, 1
    while 0 <= i < len(etapes):
        reponse = await etapes[i]()
        if reponse is None:
            return False
        if reponse is RETOUR:
            sens = -1
        elif reponse is not SAUTER:
            sens = 1
        i += sens
    return i >= len(etapes)
