from datetime import date

import pytest

from trajets.dates import DateInvalide, format_jour, jours_de_trajet, parse_date, parse_liste_dates

AUJOURD_HUI = date(2026, 10, 16)


@pytest.mark.parametrize(
    "texte, attendu",
    [
        ("06/11/2026", date(2026, 11, 6)),
        ("6/11/26", date(2026, 11, 6)),
        ("2026-11-06", date(2026, 11, 6)),
        ("06.11.2026", date(2026, 11, 6)),
        ("06/11", date(2026, 11, 6)),
        ("09/01", date(2027, 1, 9)),  # sans année et déjà passé cette année -> l'an prochain
        ("16/10", date(2026, 10, 16)),  # aujourd'hui reste cette année
    ],
)
def test_parse_date(texte, attendu):
    assert parse_date(texte, AUJOURD_HUI) == attendu


@pytest.mark.parametrize("texte", ["31/02/2027", "lundi prochain", "2026/11/06/1"])
def test_parse_date_invalide(texte):
    with pytest.raises(DateInvalide):
        parse_date(texte, AUJOURD_HUI)


def test_week_end_apres_un_vendredi():
    assert jours_de_trajet(date(2026, 11, 6)) == [date(2026, 11, 7), date(2026, 11, 8)]


def test_week_end_un_seul_jour():
    assert jours_de_trajet(date(2026, 11, 6), [6]) == [date(2026, 11, 8)]


def test_week_end_si_la_date_n_est_pas_un_vendredi():
    assert jours_de_trajet(date(2026, 11, 4)) == [date(2026, 11, 7), date(2026, 11, 8)]
    assert jours_de_trajet(date(2026, 11, 7)) == [date(2026, 11, 7), date(2026, 11, 8)]


def test_mots_relatifs():
    assert parse_date("demain", AUJOURD_HUI) == date(2026, 10, 17)
    assert parse_date("Aujourd'hui", AUJOURD_HUI) == AUJOURD_HUI


def test_liste_de_dates():
    assert parse_liste_dates("18/12/2026, 06/11 06/11;15/01", AUJOURD_HUI) == [
        date(2026, 11, 6), date(2026, 12, 18), date(2027, 1, 15)
    ]
    assert parse_liste_dates("   ", AUJOURD_HUI) == []


def test_format_jour():
    assert format_jour(date(2026, 11, 7)) == "samedi 7 novembre 2026"
    assert format_jour(date(2027, 1, 16), court=True) == "sam. 16 janv."
