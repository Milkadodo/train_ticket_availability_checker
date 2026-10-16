"""Lieux de l'alternance et correspondance entre les lieux SNCF Connect et les gares OUIGO."""

from __future__ import annotations

from trajets.models import Itineraire, Lieu, normaliser

# « Paris » ville couvre toutes les gares parisiennes (les TGV pour Nancy partent de Paris Est) ;
# côté OUIGO, PT1 = « Paris toutes gares ».
PARIS = Lieu("Paris", "CITY_FR_6455259", "CITY", region="Île-de-France", ouigo="PT1")
NANCY = Lieu("Nancy", "RESARAIL_STA_8714100", "STATION", uic="87141002", region="Grand Est", ouigo="87141002")

PARIS_NANCY = Itineraire(PARIS, NANCY)
NANCY_PARIS = Itineraire(NANCY, PARIS)


class GaresOuigo:
    """Liste des gares OUIGO (telle que renvoyée par ventes.ouigo.com)."""

    def __init__(self, gares: list[dict]):
        self.par_code = {g["_u_i_c_station_code"]: g for g in gares}
        self._enfants: dict[str, set[str]] = {}
        for g in gares:
            if g.get("parent"):
                self._enfants.setdefault(g["parent"], set()).add(g["_u_i_c_station_code"])

    def code_pour(self, lieu: Lieu) -> str | None:
        if lieu.ouigo:
            return lieu.ouigo
        if lieu.uic and lieu.uic in self.par_code:
            return lieu.uic
        nom = normaliser(lieu.nom)

        def noms(g: dict) -> set[str]:
            return {normaliser(g["name"]), *(normaliser(s) for s in g.get("synonyms") or [])}

        if lieu.type == "CITY":
            agglos = [c for c, g in self.par_code.items() if g.get("is_agglomeration") and nom in noms(g)]
            if agglos:
                return agglos[0]
        candidats = [c for c, g in self.par_code.items() if not g.get("is_agglomeration") and nom in noms(g)]
        return candidats[0] if len(candidats) == 1 else None

    def nom(self, code: str) -> str:
        return self.par_code.get(code, {}).get("name", code)

    def relies(self, origine: str, destination: str) -> bool:
        """Y a-t-il un OUIGO direct entre ces deux gares (ou agglomérations) ?"""
        sources = {origine} | self._enfants.get(origine, set())
        cibles = {destination} | self._enfants.get(destination, set())
        return any(
            cible in (self.par_code.get(source) or {}).get("connected_stations", [])
            for source in sources
            for cible in cibles
        )
