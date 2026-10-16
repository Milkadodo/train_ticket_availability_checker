import zipfile
from datetime import date, datetime

import pytest

from trajets.gares import NANCY_PARIS, PARIS_NANCY
from trajets.horaires import Horaires, construire_index
from trajets.models import PARIS_TZ, Offre, Options, ResultatJour, Statut, Trajet
from trajets.providers.ouigo import AUCUN_TRAIN, HORS_VENTE, ResultatOuigo
from trajets.recherche import Moteur
from trajets.ventes import charger_fenetres

# Extrait réduit de l'export GTFS SNCF (mêmes colonnes et mêmes conventions d'identifiants).
GTFS = {
    "feed_info.txt": "feed_id,feed_publisher_name,feed_publisher_url,feed_lang,feed_start_date,feed_end_date\n"
    "0,SNCF,http://www.sncf.com,fr,20261015,20270331\n",
    "stops.txt": "stop_id,stop_name,stop_desc,stop_lat,stop_lon,zone_id,stop_url,location_type,parent_station\n"
    "StopArea:OCE87141002,Nancy,,48.68,6.17,,,1,\n"
    "StopArea:OCE87113001,Paris Est,,48.87,2.35,,,1,\n"
    "StopArea:OCE87171926,Champagne-Ardenne TGV,,49.21,3.99,,,1,\n"
    "StopArea:OCE87212027,Strasbourg,,48.58,7.73,,,1,\n",
    "trips.txt": "route_id,service_id,trip_id,trip_headsign,direction_id,block_id,shape_id\n"
    "L1,S_OUIGO,T_7698,7698,1,1,\n"
    "L1,S_OUIGO,T_7697,7697,0,2,\n"
    "L2,S_TGV,T_2552,2552,1,3,\n"
    "L2,S_TGV,T_2560,2560,1,5,\n"
    "L3,S_TER,T_839164,839164,1,4,\n",
    "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence,stop_headsign,pickup_type,drop_off_type,shape_dist_traveled\n"
    "T_7698,17:00:00,17:05:00,StopPoint:OCEOUIGO-87212027,0,,0,1,\n"
    "T_7698,17:57:00,18:09:00,StopPoint:OCEOUIGO-87141002,1,,0,0,\n"
    "T_7698,18:50:00,18:52:00,StopPoint:OCEOUIGO-87171926,2,,0,0,\n"
    "T_7698,19:50:00,19:50:00,StopPoint:OCEOUIGO-87113001,3,,1,0,\n"
    "T_7697,09:11:00,09:11:00,StopPoint:OCEOUIGO-87113001,0,,0,1,\n"
    "T_7697,10:49:00,10:55:00,StopPoint:OCEOUIGO-87141002,1,,0,0,\n"
    "T_2552,19:24:00,19:24:00,StopPoint:OCETGV INOUI-87141002,0,,0,1,\n"
    "T_2552,21:02:00,21:02:00,StopPoint:OCETGV INOUI-87113001,1,,1,0,\n"
    "T_2560,20:00:00,20:01:00,StopPoint:OCETGV INOUI-87212027,0,,0,1,\n"
    "T_2560,21:10:00,21:12:00,StopPoint:OCETGV INOUI-87141002,1,,1,0,\n"
    "T_2560,22:40:00,22:40:00,StopPoint:OCETGV INOUI-87113001,2,,1,0,\n"
    "T_839164,10:02:00,10:02:00,StopPoint:OCETrain TER-87141002,0,,0,1,\n"
    "T_839164,13:00:00,13:00:00,StopPoint:OCETrain TER-87113001,1,,1,0,\n",
    "calendar_dates.txt": "service_id,date,exception_type\n"
    "S_OUIGO,20270306,1\nS_OUIGO,20270307,1\nS_TGV,20270306,1\nS_TER,20270306,1\n",
}


@pytest.fixture
def horaires(tmp_path):
    def telecharger(archive):
        with zipfile.ZipFile(archive, "w") as z:
            for nom, contenu in GTFS.items():
                z.writestr(nom, contenu)

    return Horaires.charger(tmp_path, telecharger=telecharger)


def test_index_garde_tgv_et_ouigo_seulement(tmp_path, horaires):
    assert {t[0] for t in horaires._trains} == {"7698", "7697", "2552", "2560"}  # pas le TER
    assert (horaires.debut, horaires.fin) == (date(2026, 10, 15), date(2027, 3, 31))


def test_trains_prevus_nancy_paris(horaires):
    trains = horaires.trains(NANCY_PARIS, date(2027, 3, 6))
    assert [(t.transporteur, t.numero, f"{t.depart:%H:%M}", f"{t.arrivee:%H:%M}", t.gare_arrivee) for t in trains] == [
        ("OUIGO", "7698", "18:09", "19:50", "Paris Est"),
        ("TGV INOUI", "2552", "19:24", "21:02", "Paris Est"),
    ]
    assert [t.numero for t in horaires.trains(NANCY_PARIS, date(2027, 3, 7))] == ["7698"]
    # Le 2560 ne fait que déposer des voyageurs à Nancy (pickup_type = 1) : on ne peut pas y monter.
    assert "2560" not in [t.numero for t in horaires.trains(NANCY_PARIS, date(2027, 3, 6))]
    assert horaires.trains(NANCY_PARIS, date(2027, 3, 8)) == []
    assert [t.numero for t in horaires.trains(PARIS_NANCY, date(2027, 3, 6))] == ["7697"]


def test_index_relu_sans_retelechargement(tmp_path, horaires):
    relu = Horaires.charger(tmp_path, telecharger=lambda archive: pytest.fail("ne doit pas retélécharger"))
    assert [t.numero for t in relu.trains(NANCY_PARIS, date(2027, 3, 6))] == ["7698", "2552"]


def _moteur():
    return Moteur(None, charger_fenetres(), cache=None, fichier_gares_ouigo=None, demander_fenetre_visible=None)


def _tgv_2552_en_vente():
    depart = datetime(2027, 3, 6, 19, 24, tzinfo=PARIS_TZ)
    return Trajet(NANCY_PARIS, depart, datetime(2027, 3, 6, 21, 2, tzinfo=PARIS_TZ), "Nancy", "Paris Est",
                  "TGV INOUI", "2552", Statut.DISPONIBLE, offres=[Offre("SNCF Connect", 28)])


def test_ouigo_absent_de_la_vente_marque_complet(horaires):
    # 06/03/2027 : OUIGO répond « aucun résultat » alors que le 7698 circule.
    res = ResultatJour(NANCY_PARIS, date(2027, 3, 6), trajets=[_tgv_2552_en_vente()])
    ouigo = ResultatOuigo(AUCUN_TRAIN, prochain_depart=date(2027, 3, 8))
    moteur = _moteur()
    moteur._ajouter_trains_absents(res, horaires.trains(NANCY_PARIS, date(2027, 3, 6)), Options(), ouigo)
    moteur._ventes_fermees(res, trajets_sncf=[res.trajets[-1]], ouigo=ouigo)
    ouigo_7698 = next(t for t in res.trajets if t.numero == "7698")
    assert ouigo_7698.statut is Statut.COMPLET and ouigo_7698.theorique
    assert ouigo_7698.message == "complet (n'est plus en vente)"
    assert [t.numero for t in res.trajets] == ["7698", "2552"]  # le TGV déjà en vente n'est pas dupliqué
    assert "OUIGO ne vend plus aucun train ce jour-là (complet) — prochain OUIGO en vente le lundi 8 mars 2027." in res.infos


def test_ouigo_pas_encore_en_vente(horaires):
    res = ResultatJour(NANCY_PARIS, date(2027, 3, 6), trajets=[_tgv_2552_en_vente()])
    _moteur()._ajouter_trains_absents(res, horaires.trains(NANCY_PARIS, date(2027, 3, 6)), Options(), ResultatOuigo(HORS_VENTE))
    ouigo_7698 = next(t for t in res.trajets if t.numero == "7698")
    assert ouigo_7698.statut is Statut.PAS_ENCORE_EN_VENTE


def test_rame_jumelee_pas_dupliquee(horaires):
    # Le 2552 est vendu sous un autre numéro de rame accouplée : mêmes horaires, pas de doublon.
    jumele = _tgv_2552_en_vente()
    jumele.numero = "12152"
    res = ResultatJour(NANCY_PARIS, date(2027, 3, 6), trajets=[jumele])
    _moteur()._ajouter_trains_absents(res, horaires.trains(NANCY_PARIS, date(2027, 3, 6)), Options(), None)
    assert [t.numero for t in res.trajets] == ["7698", "12152"]

