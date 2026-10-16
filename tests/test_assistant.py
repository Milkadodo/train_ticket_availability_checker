import asyncio

from trajets.assistant import RETOUR, SAUTER, derouler, reponse_valide


def scenario(reponses: dict[str, list]):
    """Chaque étape renvoie successivement les réponses prévues ; on note l'ordre de passage."""
    passages = []

    def etape(nom):
        async def poser():
            passages.append(nom)
            return reponses[nom].pop(0)

        return poser

    return passages, [etape(nom) for nom in reponses]


def test_toutes_les_etapes_validees():
    passages, etapes = scenario({"a": [1], "b": [2], "c": [3]})
    assert asyncio.run(derouler(etapes)) is True
    assert passages == ["a", "b", "c"]


def test_retour_revient_a_l_etape_precedente():
    passages, etapes = scenario({"a": [1, 10], "b": [RETOUR, 2], "c": [3]})
    assert asyncio.run(derouler(etapes)) is True
    assert passages == ["a", "b", "a", "b", "c"]


def test_etape_sautee_dans_les_deux_sens():
    # « b » n'a pas lieu d'être (ex. date de retour d'un aller simple) : sautée à l'aller comme au retour.
    passages, etapes = scenario({"a": [1, 1], "b": [SAUTER, SAUTER, SAUTER], "c": [RETOUR, 3]})
    assert asyncio.run(derouler(etapes)) is True
    assert passages == ["a", "b", "c", "b", "a", "b", "c"]


def test_retour_depuis_la_premiere_etape_quitte():
    passages, etapes = scenario({"a": [RETOUR], "b": [2]})
    assert asyncio.run(derouler(etapes)) is False
    assert passages == ["a"]


def test_annulation():
    passages, etapes = scenario({"a": [1], "b": [None], "c": [3]})
    assert asyncio.run(derouler(etapes)) is False
    assert passages == ["a", "b"]


def test_reponses_fausses_mais_valides():
    # Une liste vide, 0 ou False sont de vraies réponses (aucune date, 0 jour, « non »).
    passages, etapes = scenario({"a": [[]], "b": [0], "c": [False]})
    assert asyncio.run(derouler(etapes)) is True
    assert all(reponse_valide(v) for v in ([], 0, False))
    assert not any(reponse_valide(v) for v in (None, RETOUR, SAUTER))
