import json
from datetime import date, datetime, timedelta
from pathlib import Path

from trajets.affichage import texte_ouverture
from trajets.gares import PARIS, PARIS_NANCY
from trajets.models import PARIS_TZ, Itineraire, Lieu, OuvertureVentes, ResultatJour, Statut
from trajets.providers.ouigo import (
    AUCUN_TRAIN,
    HORS_VENTE,
    TRAINS,
    ResultatOuigo,
    analyser_etat,
    analyser_recherche,
    dernier_jour_en_vente,
)
from trajets.recherche import Moteur
from trajets.ventes import charger_fenetres

FIXTURES = Path(__file__).parent / "fixtures"
LYON = Lieu("Lyon", "CITY_FR_6454573", "CITY", ouigo="LY1")


def charger(nom):
    return json.loads((FIXTURES / nom).read_text())


def test_etat_hors_vente_avec_alerte_et_horizon():
    donnees = charger("ouigo_2027-07-10_paris-lyon_hors_vente.json")
    assert analyser_etat(donnees["recherche"]) == (HORS_VENTE, None, True)
    # Le calendrier de juillet 2027 a des prix jusqu'au 2 juillet : c'est la fin de la période en vente.
    assert dernier_jour_en_vente(donnees["calendriers"], date(2027, 7, 10)) == date(2027, 7, 2)


def test_etat_aucun_train_avec_prochain_depart():
    # Le OUIGO Paris-Nancy reprend le 13 décembre 2026.
    assert analyser_etat(charger("ouigo_2026-10-17_paris-nancy_aucun_train.json")) == (AUCUN_TRAIN, date(2026, 12, 13), False)


def test_train_complet():
    donnees = charger("ouigo_2026-11-08_lyon-paris_complet.json")
    assert analyser_etat(donnees)[0] == TRAINS
    (t,) = analyser_recherche(donnees, Itineraire(LYON, PARIS))
    assert t.statut is Statut.COMPLET and t.meilleur_prix is None


def _moteur():
    return Moteur(None, charger_fenetres(), cache=None, fichier_gares_ouigo=None, demander_fenetre_visible=None)


def test_hors_vente_donne_date_d_ouverture_et_precisions():
    res = ResultatJour(PARIS_NANCY, date(2027, 7, 10), liens={"OUIGO": "https://ventes.ouigo.com/..."})
    ouigo = ResultatOuigo(HORS_VENTE, en_vente_jusqu_au=date(2027, 7, 2), alerte_possible=True)
    _moteur()._ventes_fermees(res, trajets_sncf=None, ouigo=ouigo)
    (ferme,) = res.fermes
    assert ferme.transporteur == "OUIGO" and ferme.lien == "https://ventes.ouigo.com/..."
    assert ferme.ouverture.date_ouverture.date() == date(2027, 3, 10)  # estimée : 2e mercredi de mars
    assert ferme.precisions == [
        "OUIGO vend pour l'instant jusqu'au vendredi 2 juillet 2027",
        "alerte e-mail d'ouverture possible sur la page OUIGO",
    ]


def test_aucun_train_indique_le_prochain_depart():
    res = ResultatJour(PARIS_NANCY, date(2026, 10, 17))
    _moteur()._ventes_fermees(res, trajets_sncf=None, ouigo=ResultatOuigo(AUCUN_TRAIN, prochain_depart=date(2026, 12, 13)))
    assert not res.fermes
    assert res.infos == ["Aucun OUIGO ce jour-là — prochain OUIGO en vente le dimanche 13 décembre 2026."]


def test_tous_complets():
    donnees = charger("ouigo_2026-11-08_lyon-paris_complet.json")
    trajets = analyser_recherche(donnees, Itineraire(LYON, PARIS))
    res = ResultatJour(Itineraire(LYON, PARIS), date(2026, 11, 8))
    _moteur()._ventes_fermees(res, trajets_sncf=None, ouigo=ResultatOuigo(TRAINS, trajets=trajets))
    assert res.infos == ["Tous les OUIGO de ce jour sont complets."]


def test_date_d_ouverture_depassee():
    passee = OuvertureVentes("OUIGO", datetime.now(PARIS_TZ) - timedelta(days=3), estimee=True)
    assert texte_ouverture(passee)[1].startswith("imminente")
    future = OuvertureVentes("TGV INOUI", datetime(2099, 11, 12, 6, 0, tzinfo=PARIS_TZ), estimee=False)
    assert texte_ouverture(future) == ("ouverture ", "le jeudi 12 novembre 2099 vers 06h00")
