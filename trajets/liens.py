"""Liens « en un clic » vers les recherches pré-remplies sur SNCF Connect et OUIGO."""

from __future__ import annotations

from datetime import date
from urllib.parse import quote, urlencode

from trajets.dates import MOIS
from trajets.models import Itineraire

SNCF_RECHERCHE = "https://www.sncf-connect.com/home/search"
OUIGO_DEEPLINK = "https://ventes.ouigo.com/fr-FR/orientation/deep-edito/"
PAGE_OUVERTURE_VENTES = "https://www.sncf-connect.com/aide/l-ouverture-des-ventes"


def lien_sncf_connect(itineraire: Itineraire, jour: date) -> str:
    # SNCF Connect n'accepte pas de date dans ses liens de redirection, mais sa recherche en langage
    # naturel (« Lyon Toulouse le 3 mars à 19h ») ouvre directement la page de résultats du jour.
    # Les voyageurs ne passent pas dans la phrase : connecté, SNCF Connect applique la carte du compte.
    phrase = (
        f"{itineraire.origine.nom} {itineraire.destination.nom} "
        f"le {jour.day} {MOIS[jour.month - 1]} {jour.year} à 5h"
    )
    return f"{SNCF_RECHERCHE}?userInput={quote(phrase)}"


def lien_ouigo(itineraire: Itineraire, jour: date) -> str | None:
    """None si l'une des deux villes n'a pas de gare OUIGO."""
    origine, destination = itineraire.origine.ouigo, itineraire.destination.ouigo
    if not origine or not destination:
        return None
    # Même format que le moteur de recherche de ouigo.com (qs.stringify sans encodage des crochets).
    params = {
        "target": "routes",
        "origin": origine,
        "destination": destination,
        "outboundDate": jour.isoformat(),
        "passengers[0][type]": "A",
    }
    return f"{OUIGO_DEEPLINK}?{urlencode(params)}"
