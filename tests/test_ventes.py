import json
from datetime import date, datetime

import pytest

from trajets.models import PARIS_TZ
from trajets.ventes import charger_fenetres, estimer_ouverture, ouverture_pour


def test_fenetre_connue_tgv_inoui_janvier_2027():
    o = ouverture_pour("TGV INOUI", date(2027, 1, 16), charger_fenetres())
    assert o.date_ouverture == datetime(2026, 11, 12, 6, 0, tzinfo=PARIS_TZ)
    assert not o.estimee


def test_fenetre_connue_ouigo_janvier_2027():
    o = ouverture_pour("OUIGO Grande Vitesse", date(2027, 1, 16), charger_fenetres())
    assert o.transporteur == "OUIGO"
    assert o.date_ouverture.date() == date(2026, 9, 30)


@pytest.mark.parametrize(
    "transporteur, jour, ouverture",
    [
        # Le rythme estimé doit retrouver les ouvertures réelles de 2026...
        ("TGV INOUI", date(2026, 7, 4), date(2026, 3, 11)),
        ("TGV INOUI", date(2026, 12, 12), date(2026, 3, 11)),
        ("TGV INOUI", date(2026, 12, 19), date(2026, 9, 30)),
        ("TGV INOUI", date(2027, 1, 2), date(2026, 9, 30)),
        ("TGV INOUI", date(2027, 1, 16), date(2026, 11, 12)),
        ("OUIGO", date(2027, 1, 16), date(2026, 9, 30)),
        ("OUIGO", date(2027, 7, 2), date(2026, 9, 30)),
        # ... et prolonger pour la suite.
        ("TGV INOUI", date(2027, 9, 4), date(2027, 3, 10)),
        ("OUIGO", date(2027, 7, 3), date(2027, 3, 10)),
    ],
)
def test_estimation_suit_le_rythme_sncf(transporteur, jour, ouverture):
    assert estimer_ouverture(transporteur, jour).date() == ouverture


def test_date_hors_calendrier_est_estimee():
    o = ouverture_pour("TGV INOUI", date(2027, 9, 4), charger_fenetres())
    assert o.estimee
    assert o.date_ouverture == datetime(2027, 3, 10, 6, 0, tzinfo=PARIS_TZ)


def test_fichier_utilisateur_prioritaire(tmp_path):
    fichier = tmp_path / "ouvertures_ventes.json"
    fichier.write_text(json.dumps({"ouvertures": [
        {"transporteur": "TGV INOUI", "voyages_du": "2027-01-07", "voyages_au": "2027-07-02",
         "ouverture": "2026-11-12T05:45", "source": "annonce"}
    ]}))
    o = ouverture_pour("TGV INOUI", date(2027, 2, 1), charger_fenetres(fichier))
    assert o.date_ouverture == datetime(2026, 11, 12, 5, 45, tzinfo=PARIS_TZ)
    assert o.source == "annonce"
