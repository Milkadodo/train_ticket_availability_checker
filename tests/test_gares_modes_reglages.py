import json
from datetime import date
from pathlib import Path

import pytest

from trajets.gares import NANCY, NANCY_PARIS, PARIS, PARIS_NANCY, GaresOuigo
from trajets.models import Itineraire, Lieu, gare_du_lieu, meme_ville
from trajets.modes import ChoixJours, apparier, recherches_allers_retours, recherches_alternance
from trajets.reglages import Reglages

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def gares():
    return GaresOuigo(json.loads((FIXTURES / "ouigo_gares.json").read_text()))


def test_code_ouigo_ville_avec_agglomeration(gares):
    assert gares.code_pour(Lieu("Lyon", "CITY_FR_6454573", "CITY")) == "LY1"


def test_code_ouigo_gare_par_uic(gares):
    assert gares.code_pour(Lieu("Lyon Part-Dieu", "RESARAIL_STA_8772319", "STATION", uic="87723197")) == "87723197"


def test_code_ouigo_ville_avec_une_seule_gare(gares):
    assert gares.code_pour(Lieu("Nancy", "CITY_FR_6454307", "CITY")) == "87141002"


def test_code_ouigo_ville_non_desservie(gares):
    assert gares.code_pour(Lieu("Épinal", "CITY_FR_1", "CITY")) is None


def test_liaisons_ouigo(gares):
    assert gares.relies("PT1", "87141002")  # Paris toutes gares -> Nancy
    assert gares.relies("87141002", "PT1")
    assert not gares.relies("87141002", "LY1")  # pas de OUIGO direct Nancy -> Lyon


@pytest.mark.parametrize(
    "gare, lieu, attendu",
    [("Paris Est", "Paris", True), ("Lorraine TGV", "Nancy", False), ("Nancy-Ville", "Nancy", True),
     ("Marseille St Charles", "Marseille Saint-Charles", True), ("Marne-la-Vallée Chessy", "Paris", False)],
)
def test_meme_ville(gare, lieu, attendu):
    assert meme_ville(gare, lieu) is attendu


def test_alternance_sens_et_week_ends():
    recherches, passees = recherches_alternance(
        fins_ecole=[date(2026, 12, 18), date(2026, 10, 9)],
        fins_entreprise=[date(2026, 11, 6)],
        choix=ChoixJours(),
        aujourd_hui=date(2026, 10, 16),
    )
    assert passees == [date(2026, 10, 9)]
    entreprise, ecole = recherches
    assert entreprise.itineraire == PARIS_NANCY and entreprise.jours == [date(2026, 11, 7), date(2026, 11, 8)]
    assert ecole.itineraire == NANCY_PARIS and ecole.titre == "Fin d'école le vendredi 18 décembre 2026"


def test_alternance_garde_le_dimanche_si_le_samedi_est_passe():
    (r,), _ = recherches_alternance([], [date(2026, 10, 16)], ChoixJours(), aujourd_hui=date(2026, 10, 18))
    assert r.jours == [date(2026, 10, 18)]


def test_alternance_flex_avant_et_apres_la_date():
    (r,), _ = recherches_alternance([date(2026, 12, 18)], [], ChoixJours(flex=(1, 2)), aujourd_hui=date(2026, 10, 16))
    assert r.itineraire == NANCY_PARIS
    assert r.jours == [date(2026, 12, 17), date(2026, 12, 18), date(2026, 12, 19), date(2026, 12, 20)]


def test_alternance_flex_ignore_les_jours_passes():
    (r,), _ = recherches_alternance([], [date(2026, 10, 16)], ChoixJours(flex=(2, 1)), aujourd_hui=date(2026, 10, 16))
    assert r.jours == [date(2026, 10, 16), date(2026, 10, 17)]


def test_trajet_libre_aller_retour():
    lyon = Lieu("Lyon", "CITY_FR_6454573", "CITY")
    aller, retour = recherches_allers_retours(Itineraire(PARIS, lyon), [date(2026, 11, 7)], [date(2026, 11, 15)])
    assert aller.itineraire.label == "Paris → Lyon" and aller.jours == [date(2026, 11, 7)]
    assert retour.itineraire.label == "Lyon → Paris" and retour.etiquette == "retour dim. 15 nov."
    assert aller.groupe == retour.groupe == "A/R" and aller.titre == "Aller le samedi 7 novembre 2026"


def test_trajet_libre_aller_simple_flex():
    (aller,) = recherches_allers_retours(PARIS_NANCY, [date(2026, 11, 7)], [], flex=(1, 1), aujourd_hui=date(2026, 10, 16))
    assert aller.jours == [date(2026, 11, 6), date(2026, 11, 7), date(2026, 11, 8)]
    assert aller.titre == "Aller autour du samedi 7 novembre 2026 (−1 / +1 j)"


def test_appariement_des_allers_retours():
    d = lambda j, m=11: date(2026, m, j)  # noqa: E731
    # Chaque aller prend le premier retour qui suit, avant l'aller suivant.
    assert apparier([d(7), d(13)], [d(8), d(15), d(1, 12)]) == [(d(7), d(8)), (d(13), d(15)), (None, d(1, 12))]
    assert apparier([d(7), d(13)], [d(15)]) == [(d(7), None), (d(13), d(15))]
    assert apparier([d(13), d(7)], [d(15), d(8)]) == [(d(7), d(8)), (d(13), d(15))]  # ordre de saisie libre


def test_plusieurs_allers_retours():
    recherches = recherches_allers_retours(PARIS_NANCY, [date(2026, 11, 7), date(2026, 11, 13)], [date(2026, 11, 8), date(2026, 11, 15)])
    assert [(r.groupe, r.sens, r.itineraire.label) for r in recherches] == [
        ("A/R 1", "aller", "Paris → Nancy"), ("A/R 1", "retour", "Nancy → Paris"),
        ("A/R 2", "aller", "Paris → Nancy"), ("A/R 2", "retour", "Nancy → Paris"),
    ]
    assert recherches[0].titre == "A/R 1 · Aller le samedi 7 novembre 2026"


def test_reglages_aller_retour_fichier(tmp_path):
    fichier = tmp_path / "reglages.json"
    r = Reglages(age=22, fins_ecole=["2026-12-18"], derniere_origine=NANCY.vers_dict())
    r.enregistrer(fichier)
    relu = Reglages.charger(fichier)
    assert relu.age == 22 and relu.fins_ecole == ["2026-12-18"]
    assert relu.lieu("derniere_origine") == NANCY
    assert relu.options(direct_seulement=False).direct_seulement is False


def test_reglages_fichier_absent_ou_abime(tmp_path):
    assert Reglages.charger(tmp_path / "absent.json") == Reglages()
    (tmp_path / "abime.json").write_text("{pas du json")
    assert Reglages.charger(tmp_path / "abime.json") == Reglages()


def test_reglages_fins_a_venir():
    r = Reglages(fins_ecole=["2026-10-09", "2026-10-16", "2026-12-18", "n'importe quoi"])
    assert r.fins_a_venir(r.fins_ecole, date(2026, 10, 17)) == [date(2026, 10, 16), date(2026, 12, 18)]


@pytest.mark.parametrize(
    "gare, lieu, attendu",
    [("Paris Gare de Lyon", "Paris", True), ("Paris Aéroport Roissy-CDG 2", "Paris", False),
     ("Paris Marne-la-Vallée - Chessy - Disneyland®", "Paris", False), ("Lyon Saint-Exupéry TGV", "Lyon", False),
     ("Lyon Saint-Exupéry TGV", "Lyon Saint-Exupéry TGV - Aéroport", True), ("Lorraine TGV", "Nancy", False)],
)
def test_gare_du_lieu(gare, lieu, attendu):
    assert gare_du_lieu(gare, lieu) is attendu


def test_reglages_choix_jours():
    assert Reglages(jours_weekend=[6]).choix_jours() == ChoixJours(jours_semaine=(6,))
    assert Reglages(flex=True, flex_avant=0, flex_apres=3).choix_jours() == ChoixJours(flex=(0, 3))
