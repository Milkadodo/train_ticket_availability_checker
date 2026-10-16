from datetime import date, datetime, timezone

from trajets.affichage import regrouper_fermes
from trajets.ical import Rappel, generer_ics
from trajets.gares import PARIS_NANCY
from trajets.models import PARIS_TZ, OuvertureVentes, TrajetsFermes
from trajets.rappels import construire_rappels


def test_generer_ics_valide():
    rappel = Rappel(
        debut=datetime(2026, 11, 12, 6, 0, tzinfo=PARIS_TZ),
        titre="Ouverture ventes TGV INOUI, Paris → Nancy",
        description="Ligne 1\nLigne 2; avec point-virgule",
        url="https://example.org",
    )
    ics = generer_ics([rappel], maintenant=datetime(2026, 10, 16, 10, 0, tzinfo=timezone.utc))
    assert ics.startswith("BEGIN:VCALENDAR\r\n")
    assert ics.endswith("END:VCALENDAR\r\n")
    assert "DTSTART:20261112T050000Z" in ics  # 6h à Paris = 5h UTC en novembre
    assert "DTEND:20261112T053000Z" in ics
    assert "SUMMARY:Ouverture ventes TGV INOUI\\, Paris → Nancy" in ics
    assert "Ligne 1\\nLigne 2\\; avec point-virgule" in ics.replace("\r\n ", "")
    assert ics.count("BEGIN:VALARM") == 2
    assert "TRIGGER:-P1D" in ics and "TRIGGER:-PT15M" in ics
    for ligne in ics.split("\r\n"):
        assert len(ligne.encode("utf-8")) <= 75


def test_rappels_groupes_par_ouverture():
    ouverture = OuvertureVentes("TGV INOUI", datetime(2026, 11, 12, 6, 0, tzinfo=PARIS_TZ), estimee=False)
    fermes = [
        TrajetsFermes(PARIS_NANCY, date(2027, 1, 17), "TGV INOUI", ouverture),
        TrajetsFermes(PARIS_NANCY, date(2027, 1, 16), "TGV INOUI", ouverture),
    ]
    groupes = regrouper_fermes(fermes)
    assert len(groupes) == 1
    assert [f.jour for f in groupes[0]] == [date(2027, 1, 16), date(2027, 1, 17)]
    (rappel,) = construire_rappels(groupes)
    assert rappel.debut == ouverture.date_ouverture
    assert "sam. 16 janv." in rappel.titre and "dim. 17 janv." in rappel.titre
    assert "https://www.sncf-connect.com/home/search?userInput=Paris%20Nancy%20le%2016%20janvier%202027" in rappel.description


def test_durees_ical():
    from datetime import timedelta

    from trajets.ical import _duree

    assert _duree(timedelta(minutes=15)) == "PT15M"
    assert _duree(timedelta(hours=1)) == "PT1H"
    assert _duree(timedelta(days=1)) == "P1D"
    assert _duree(timedelta(days=1, hours=2, minutes=5)) == "P1DT2H5M"
