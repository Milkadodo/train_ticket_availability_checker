"""Structures de données partagées par les fournisseurs, le rendu et l'interface."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

PARIS_TZ = ZoneInfo("Europe/Paris")


def normaliser(texte: str) -> str:
    """'Saint-Étienne Châteaucreux' -> 'saint etienne chateaucreux'."""
    sans_accents = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    return re.sub(r"[\s\-–'’]+", " ", sans_accents.lower()).strip()


def meme_ville(gare: str, lieu: str) -> bool:
    """Compare le premier mot : 'Paris Est' est à Paris, 'Lorraine TGV' n'est pas à Nancy."""
    a, b = normaliser(gare).split(), normaliser(lieu).split()
    return bool(a and b and a[0] == b[0])


# Gares hors du centre, même quand leur nom commence par la ville (« Paris Aéroport Roissy-CDG 2 »).
_EXCENTREES = re.compile(r"\b(tgv|aeroport|roissy|cdg|marne la vallee|chessy|massy|sud de france|pont du gard|saint exupery)\b")


def est_excentree(gare: str) -> bool:
    return bool(_EXCENTREES.search(normaliser(gare)))


def gare_du_lieu(gare: str, lieu: str) -> bool:
    """La gare correspond-elle au lieu choisi ? Une gare excentrée ne compte que si on l'a choisie."""
    return meme_ville(gare, lieu) and (not est_excentree(gare) or est_excentree(lieu))


@dataclass(frozen=True)
class Lieu:
    nom: str  # libellé affiché : "Paris", "Lyon Part-Dieu"
    sncf_id: str  # identifiant SNCF Connect : CITY_FR_6455259, RESARAIL_STA_8714100...
    type: str = "CITY"  # CITY (toutes les gares de la ville) ou STATION
    uic: str | None = None  # code UIC à 8 chiffres pour une gare
    region: str | None = None
    ouigo: str | None = None  # code OUIGO (UIC ou agglomération comme PT1), si connu

    def vers_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def depuis_dict(cls, d: dict) -> "Lieu":
        return cls(**{k: d.get(k) for k in ("nom", "sncf_id", "type", "uic", "region", "ouigo") if k in d})

    def avec_ouigo(self, code: str | None) -> "Lieu":
        return replace(self, ouigo=code)


@dataclass(frozen=True)
class Itineraire:
    origine: Lieu
    destination: Lieu

    @property
    def label(self) -> str:
        return f"{self.origine.nom} → {self.destination.nom}"

    def inverse(self) -> "Itineraire":
        return Itineraire(self.destination, self.origine)


class Statut(Enum):
    DISPONIBLE = "disponible"
    COMPLET = "complet"
    PAS_ENCORE_EN_VENTE = "pas encore en vente"
    INDISPONIBLE = "indisponible"


@dataclass
class Offre:
    source: str  # "SNCF Connect" ou "OUIGO"
    prix: float | None
    tarif: str | None = None
    classe: str | None = None


@dataclass
class Trajet:
    itineraire: Itineraire
    depart: datetime
    arrivee: datetime
    gare_depart: str
    gare_arrivee: str
    transporteur: str  # "TGV INOUI", "OUIGO", ou "TGV INOUI 2807 + TER 88520" avec correspondance
    numero: str | None
    statut: Statut
    offres: list[Offre] = field(default_factory=list)
    message: str | None = None
    avertissements: list[str] = field(default_factory=list)
    correspondances: int = 0
    theorique: bool = False  # prévu aux horaires officiels SNCF mais absent des sites de vente

    @property
    def jour(self) -> date:
        return self.depart.date()

    @property
    def duree(self) -> timedelta:
        return self.arrivee - self.depart

    @property
    def libelle_train(self) -> str:
        return f"{self.transporteur} {self.numero or ''}".strip()

    @property
    def est_ouigo(self) -> bool:
        return "OUIGO" in self.transporteur.upper()

    @property
    def ecarts(self) -> list[str]:
        """Départ ou arrivée ailleurs que dans les villes choisies (gare TGV excentrée, aéroport...)."""
        o, d = self.itineraire.origine.nom, self.itineraire.destination.nom
        ecarts = []
        if self.gare_depart and not gare_du_lieu(self.gare_depart, o):
            ecarts.append(f"part de {self.gare_depart}")
        if self.gare_arrivee and not gare_du_lieu(self.gare_arrivee, d):
            ecarts.append(f"arrive à {self.gare_arrivee}, pas à {d}")
        return ecarts

    def offre(self, source: str) -> Offre | None:
        return next((o for o in self.offres if o.source == source), None)

    @property
    def meilleure_offre(self) -> Offre | None:
        avec_prix = [o for o in self.offres if o.prix is not None]
        return min(avec_prix, key=lambda o: o.prix) if avec_prix else None

    @property
    def meilleur_prix(self) -> float | None:
        offre = self.meilleure_offre
        return offre.prix if offre else None


@dataclass
class OuvertureVentes:
    transporteur: str
    date_ouverture: datetime  # timezone-aware, Europe/Paris
    estimee: bool
    source: str | None = None


@dataclass
class TrajetsFermes:
    """Des trajets d'un jour donné qui ne sont pas encore en vente."""

    itineraire: Itineraire
    jour: date
    transporteur: str
    ouverture: OuvertureVentes
    lien: str | None = None
    precisions: list[str] = field(default_factory=list)  # ex. « OUIGO vend actuellement jusqu'au 2 juillet »


@dataclass
class ResultatJour:
    itineraire: Itineraire
    jour: date
    trajets: list[Trajet] = field(default_factory=list)
    liens: dict[str, str] = field(default_factory=dict)
    erreurs: dict[str, str] = field(default_factory=dict)
    infos: list[str] = field(default_factory=list)
    fermes: list[TrajetsFermes] = field(default_factory=list)


@dataclass
class Recherche:
    """Un bloc de résultats affiché ensemble : un week-end d'alternance, un aller, un retour."""

    titre: str  # "Fin d'école le vendredi 18 décembre 2026"
    etiquette: str  # version courte pour le récapitulatif
    itineraire: Itineraire
    jours: list[date]
    resultats: list[ResultatJour] = field(default_factory=list)
    groupe: str | None = None  # « A/R 1 »... quand plusieurs allers-retours sont comparés
    sens: str | None = None  # « aller » ou « retour » dans ce cas


@dataclass(frozen=True)
class Options:
    """Critères d'une recherche (issus des réglages et des choix faits dans les menus)."""

    age: int = 20
    carte_jeune: bool = True
    tous_trains: bool = False  # sinon seulement TGV INOUI / OUIGO
    direct_seulement: bool = True
    sncf: bool = True
    ouigo: bool = True
    horaires_officiels: bool = True  # repérer les trains complets grâce aux horaires officiels SNCF
