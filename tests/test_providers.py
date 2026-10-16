import json
from datetime import date, datetime
from pathlib import Path

from trajets.gares import NANCY, NANCY_PARIS, PARIS, PARIS_NANCY
from trajets.liens import lien_ouigo, lien_sncf_connect
from trajets.models import PARIS_TZ, Itineraire, Lieu, Offre, Options, Statut, Trajet
from trajets.providers.ouigo import analyser_recherche
from trajets.providers.sncf_connect import _prix, analyser_autocompletion, analyser_proposition
from trajets.recherche import fusionner, regrouper_rames_jumelees

FIXTURES = Path(__file__).parent / "fixtures"


def propositions(nom):
    return json.loads((FIXTURES / nom).read_text())["longDistance"]["proposals"]["proposals"]


def test_sncf_tarif_avantage_jeune_et_arrivee_hors_nancy():
    (p,) = propositions("sncf_2026-10-31_paris-nancy.json")
    t = analyser_proposition(p, PARIS_NANCY, date(2026, 10, 31))
    assert t.transporteur == "TGV INOUI" and t.numero == "2503"
    assert t.depart == datetime(2026, 10, 31, 7, 46, tzinfo=PARIS_TZ)
    assert t.statut is Statut.DISPONIBLE
    assert t.meilleur_prix == 35
    assert t.meilleure_offre.tarif == "Tarif AVANTAGE JEUNE"
    # Ce jour-là (travaux) le TGV s'arrête à Lorraine TGV : signalé et exclu du « meilleur prix ».
    assert t.ecarts == ["arrive à Lorraine TGV, pas à Nancy"]


def test_sncf_pas_encore_en_vente_et_filtre_ter():
    jour = date(2027, 1, 16)
    trajets = [analyser_proposition(p, PARIS_NANCY, jour) for p in propositions("sncf_2027-01-16_paris-nancy_pas_en_vente.json")]
    trajets = [t for t in trajets if t]
    assert len(trajets) == 6  # le TER Fluo est écarté
    assert all(t.statut is Statut.PAS_ENCORE_EN_VENTE for t in trajets)
    assert all(t.gare_arrivee == "Nancy" for t in trajets)


def test_sncf_tous_trains_garde_le_ter():
    jour = date(2027, 1, 16)
    options = Options(tous_trains=True)
    trajets = [analyser_proposition(p, PARIS_NANCY, jour, options) for p in propositions("sncf_2027-01-16_paris-nancy_pas_en_vente.json")]
    ter = [t for t in trajets if t and "Fluo" in t.transporteur]
    assert len(ter) == 1 and ter[0].meilleur_prix == 46.8


def test_sncf_ignore_un_autre_jour():
    (p,) = propositions("sncf_2026-10-31_paris-nancy.json")
    assert analyser_proposition(p, PARIS_NANCY, date(2026, 11, 1)) is None


def _proposition_avec_correspondance():
    def train(depart, arrivee, gare_d, gare_a, description, numero):
        return {"train": {"departure": {"stationLabel": gare_d, "timeLabel": depart},
                          "arrival": {"stationLabel": gare_a, "timeLabel": arrivee},
                          "transporter": {"description": description, "number": f"n° {numero}"}}}

    return {
        "travelId": "2026-11-07T08:14_2807, 88520",
        "departure": {"originStationLabel": "Paris Est", "timeLabel": "08:14"},
        "arrival": {"destinationStationLabel": "Nancy", "timeLabel": "11:10"},
        "transporterDescription": "1 correspondance",
        "status": {"isBookable": True},
        "secondComfortClassOffers": {"offers": [{"type": "NORMAL", "priceLabel": "103 €", "travelersFares": [{"subtitles": ["Tarif STANDARD SECONDE"]}]}]},
        "globalTimeline": {"steps": [
            {"onBoarding": {}},
            train("08:14", "09:46", "Paris Est", "Lorraine TGV", "TGV INOUI", 2807),
            {"connection": {"duration": "20 min"}},
            train("10:06", "11:10", "Lorraine TGV", "Nancy", "TGV INOUI", 5440),
        ]},
    }


def test_sncf_correspondance_exclue_en_mode_direct():
    assert analyser_proposition(_proposition_avec_correspondance(), PARIS_NANCY, date(2026, 11, 7)) is None


def test_sncf_correspondance_acceptee_si_demandee():
    t = analyser_proposition(_proposition_avec_correspondance(), PARIS_NANCY, date(2026, 11, 7), Options(direct_seulement=False))
    assert t.correspondances == 1
    assert t.libelle_train == "TGV INOUI 2807 + TGV INOUI 5440"
    assert t.gare_depart == "Paris Est" and t.gare_arrivee == "Nancy"
    assert t.meilleur_prix == 103 and not t.ecarts


def test_prix():
    assert _prix("35 €") == 35
    assert _prix("46,80 €") == 46.8
    assert _prix("1 234,50 €") == 1234.5
    assert _prix(None) is None


def test_autocompletion():
    reponse = {"places": [{"section": {"label": "Villes et gares"}, "results": [
        {"id": "CITY_FR_6454307", "label": "Nancy", "type": {"placeType": "CITY"}, "description": "Grand Est",
         "codes": [{"type": "RESARAIL", "value": "FRENC"}]},
        {"id": "RESARAIL_STA_8714100", "label": "Nancy", "type": {"placeType": "STATION"}, "description": "Grand Est",
         "codes": [{"type": "UIC8", "value": "87141002"}]},
        {"id": "GOOGLE_POI_x", "label": "Musée", "type": {"placeType": "POI"}},
    ]}]}
    ville, gare = analyser_autocompletion(reponse)
    assert (ville.type, ville.uic, ville.region) == ("CITY", None, "Grand Est")
    assert (gare.type, gare.uic, gare.sncf_id) == ("STATION", "87141002", "RESARAIL_STA_8714100")


def test_ouigo():
    donnees = json.loads((FIXTURES / "ouigo_2026-12-19_paris-nancy.json").read_text())
    (t,) = analyser_recherche(donnees, PARIS_NANCY)
    assert t.transporteur == "OUIGO" and t.numero == "7697"
    assert t.depart.hour == 9 and t.depart.minute == 11
    assert t.meilleur_prix == 85
    assert t.gare_arrivee == "Nancy-Ville" and not t.ecarts


def test_fusion_ouigo_vendu_sur_les_deux_sites():
    depart = datetime(2026, 12, 19, 9, 11, tzinfo=PARIS_TZ)
    commun = dict(itineraire=PARIS_NANCY, depart=depart, arrivee=depart, gare_depart="Paris Est",
                  gare_arrivee="Nancy", transporteur="OUIGO", numero="7697")
    sncf = Trajet(**commun, statut=Statut.DISPONIBLE, offres=[Offre("SNCF Connect", 85)])
    ouigo = Trajet(**commun, statut=Statut.DISPONIBLE, offres=[Offre("OUIGO", 79)])
    (t,) = fusionner([sncf], [ouigo])
    assert {o.source for o in t.offres} == {"SNCF Connect", "OUIGO"}
    assert t.meilleure_offre.source == "OUIGO"


def test_rames_jumelees_regroupees():
    depart = datetime(2026, 11, 8, 9, 13, tzinfo=PARIS_TZ)
    commun = dict(itineraire=PARIS_NANCY, depart=depart, arrivee=datetime(2026, 11, 8, 10, 41, tzinfo=PARIS_TZ),
                  gare_depart="Paris Est", gare_arrivee="Nancy", transporteur="TGV INOUI", statut=Statut.DISPONIBLE)
    a = Trajet(**commun, numero="2587", offres=[Offre("SNCF Connect", 30)])
    b = Trajet(**commun, numero="2571", offres=[Offre("SNCF Connect", 25.5)])
    (t,) = regrouper_rames_jumelees([a, b])
    assert t.numero == "2571/2587"
    assert t.meilleur_prix == 25.5


def test_lien_ouigo():
    url = lien_ouigo(NANCY_PARIS, date(2026, 12, 20))
    assert url.startswith("https://ventes.ouigo.com/fr-FR/orientation/deep-edito/?target=routes")
    assert "origin=87141002&destination=PT1&outboundDate=2026-12-20" in url
    assert "passengers%5B0%5D%5Btype%5D=A" in url


def test_lien_ouigo_sans_gare_ouigo():
    brive = Lieu("Brive-la-Gaillarde", "CITY_FR_1", "CITY")
    assert lien_ouigo(Itineraire(PARIS, brive), date(2026, 12, 20)) is None


def test_lien_sncf_connect_ville_quelconque():
    lyon = Lieu("Lyon Part-Dieu", "RESARAIL_STA_8772319", "STATION", uic="87723197")
    url = lien_sncf_connect(Itineraire(lyon, NANCY), date(2026, 12, 20))
    assert url == "https://www.sncf-connect.com/home/search?userInput=Lyon%20Part-Dieu%20Nancy%20le%2020%20d%C3%A9cembre%202026%20%C3%A0%205h"


def test_fusion_ouigo_parti_d_une_autre_gare_parisienne():
    # Avec « Paris toutes gares », OUIGO montre le train depuis Roissy, SNCF Connect depuis Marne-la-Vallée.
    lyon = Lieu("Lyon", "CITY_FR_6454573", "CITY", ouigo="LY1")
    arrivee = datetime(2026, 11, 7, 11, 3, tzinfo=PARIS_TZ)
    commun = dict(itineraire=Itineraire(PARIS, lyon), arrivee=arrivee, gare_arrivee="Lyon Part Dieu",
                  transporteur="OUIGO", numero="7867", statut=Statut.DISPONIBLE)
    sncf = Trajet(**commun, depart=datetime(2026, 11, 7, 9, 13, tzinfo=PARIS_TZ), gare_depart="Marne-La-Vallee - Chessy",
                  offres=[Offre("SNCF Connect", 39)])
    ouigo = Trajet(**commun, depart=datetime(2026, 11, 7, 8, 55, tzinfo=PARIS_TZ), gare_depart="Paris Aéroport Roissy-CDG 2",
                   offres=[Offre("OUIGO", 39)])
    (t,) = fusionner([sncf], [ouigo])
    assert {o.source for o in t.offres} == {"SNCF Connect", "OUIGO"}
    assert t.ecarts == ["part de Marne-La-Vallee - Chessy"]


def test_comparatif_retour_apres_l_aller():
    from trajets.affichage import meilleur_trajet
    from trajets.models import ResultatJour

    def trajet(itineraire, jour, heure, prix):
        depart = datetime(2026, 11, jour, heure, 0, tzinfo=PARIS_TZ)
        return Trajet(itineraire=itineraire, depart=depart, arrivee=depart.replace(hour=heure + 1),
                      gare_depart=itineraire.origine.nom, gare_arrivee=itineraire.destination.nom,
                      transporteur="TGV INOUI", numero=str(heure), statut=Statut.DISPONIBLE, offres=[Offre("SNCF Connect", prix)])

    # Flex qui se chevauche : le retour le moins cher (le 7 à 8h) part avant l'arrivée de l'aller (le 7 à 11h).
    retours = [ResultatJour(NANCY_PARIS, date(2026, 11, 7), trajets=[trajet(NANCY_PARIS, 7, 8, 20), trajet(NANCY_PARIS, 7, 18, 35)])]
    arrivee_aller = datetime(2026, 11, 7, 11, 0, tzinfo=PARIS_TZ)
    assert meilleur_trajet(retours)[1].meilleur_prix == 20
    assert meilleur_trajet(retours, apres=arrivee_aller)[1].meilleur_prix == 35
