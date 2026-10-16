"""Affichage des résultats dans le terminal (Rich)."""

from __future__ import annotations

from datetime import datetime, timedelta

from rich.console import Console, Group
from rich.panel import Panel
from rich.style import Style
from rich.table import Table
from rich.text import Text

from trajets.dates import format_jour
from trajets.models import PARIS_TZ, OuvertureVentes, Recherche, ResultatJour, Statut, Trajet, TrajetsFermes
from trajets.providers.ouigo import SOURCE as OUIGO
from trajets.providers.sncf_connect import SOURCE as SNCF


def euros(prix: float) -> str:
    return f"{prix:.0f} €" if prix == int(prix) else f"{prix:.2f} €".replace(".", ",")


def duree(td: timedelta) -> str:
    minutes = int(td.total_seconds() // 60)
    return f"{minutes // 60}h{minutes % 60:02d}"


def lien(texte: str, url: str, style: str = "bold cyan") -> Text:
    return Text(texte, style=Style.parse(style) + Style(link=url))


def meilleur_trajet(resultats: list[ResultatJour], apres: datetime | None = None) -> tuple[ResultatJour, Trajet] | None:
    """Le moins cher parmi les trajets achetables qui partent et arrivent bien dans les villes choisies ;
    s'il n'y en a aucun (ville desservie seulement par une gare TGV excentrée), parmi tous.
    `apres` : ne garder que les trajets qui partent après ce moment (le retour après l'aller)."""
    achetables = [
        (r, t)
        for r in resultats
        for t in r.trajets
        if t.statut is Statut.DISPONIBLE and t.meilleur_prix is not None and (apres is None or t.depart >= apres)
    ]
    candidats = [(r, t) for r, t in achetables if not t.ecarts] or achetables
    return min(candidats, key=lambda rt: (rt[1].meilleur_prix, rt[1].depart)) if candidats else None


def afficher_recherche(console: Console, recherche: Recherche) -> None:
    titre = Text.assemble((recherche.titre, "bold"), "  →  ", (recherche.itineraire.label, "bold magenta"))
    console.print()
    console.rule(titre)
    meilleur = meilleur_trajet(recherche.resultats)
    for res in recherche.resultats:
        _afficher_jour(console, res, meilleur[1] if meilleur else None)
    if meilleur:
        res, t = meilleur
        offre = t.meilleure_offre
        resume = Text.assemble(
            ("💰 Le moins cher : ", "bold green"),
            (f"{format_jour(t.jour, court=True)} {t.depart:%H:%M} → {t.arrivee:%H:%M}", "bold"),
            f" · {t.libelle_train} · ",
            (euros(offre.prix), "bold green"),
            f" ({offre.source}{', ' + offre.tarif if offre.tarif else ''})  ",
            lien("Réserver ↗", res.liens.get(offre.source, "")),
            ("\n⚠ " + " · ".join(t.ecarts) if t.ecarts else "", "yellow"),
        )
        console.print(Panel(resume, border_style="green", expand=False))
    else:
        console.print(Text("Aucun trajet achetable pour l'instant.", style="yellow"))


def _afficher_jour(console: Console, res: ResultatJour, meilleur: Trajet | None) -> None:
    console.print(Text(f"\n{format_jour(res.jour).capitalize()}", style="bold underline"))
    if res.trajets:
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
        table.add_column(" ")
        table.add_column("Départ")
        table.add_column("Arrivée")
        table.add_column("Durée")
        table.add_column("Train")
        sources = [s for s in (SNCF, OUIGO) if s in res.liens]
        for source in sources:
            table.add_column(source, justify="right")
        table.add_column("Infos")
        table.add_column("Réserver")
        for t in res.trajets:
            table.add_row(*_ligne(t, res, sources, t is meilleur))
        console.print(table)
    elif not res.erreurs:
        console.print(Text("  Aucun trajet trouvé avec ces critères.", style="dim"))
    for source, erreur in res.erreurs.items():
        console.print(Text(f"  ⚠ {source} : {erreur}", style="yellow"))
    for info in res.infos:
        console.print(Text(f"  ℹ {info}", style="dim"))
    for ferme in res.fermes:
        console.print(_texte_ferme(ferme))
    for source, url in res.liens.items():
        # soft_wrap : l'URL reste sur une seule ligne logique, donc cliquable même si elle déborde.
        console.print(Text.assemble(("  🔗 ", ""), (f"{source:<13}", "dim"), lien(url, url, "cyan")), soft_wrap=True)


def _ligne(t: Trajet, res: ResultatJour, sources: list[str], est_meilleur: bool) -> list:
    style = "bold green" if est_meilleur else ""
    prix_cells = []
    for source in sources:
        offre = t.offre(source)
        if offre and offre.prix is not None:
            prix_cells.append(Text(euros(offre.prix), style=style or "bold"))
        elif source == OUIGO and not t.est_ouigo:
            prix_cells.append(Text(""))
        else:
            prix_cells.append(Text("—", style="dim"))

    infos = []
    if t.statut is Statut.PAS_ENCORE_EN_VENTE:
        infos.append(Text("⏳ pas encore en vente", style="yellow"))
    elif t.statut is Statut.COMPLET:
        infos.append(Text(t.message or "complet", style="red"))
    elif t.statut is Statut.INDISPONIBLE:
        infos.append(Text(t.message or "indisponible", style="red"))
    elif (offre := t.meilleure_offre) and offre.tarif:
        infos.append(Text(offre.tarif + (f" ({offre.classe})" if offre.classe == "1re" else ""), style="dim"))
    if t.correspondances:
        infos.insert(0, Text(f"{t.correspondances} corresp.", style="magenta"))
    infos += [Text(a, style="yellow") for a in t.ecarts + t.avertissements]

    reserver = Text()
    for source in sources:
        if source == SNCF or t.est_ouigo:
            if reserver:
                reserver.append(" ")
            reserver.append_text(lien("SNCF ↗" if source == SNCF else "OUIGO ↗", res.liens[source]))

    return [
        Text("★", style="bold green") if est_meilleur else Text(""),
        Text(f"{t.depart:%H:%M}", style=style),
        Text(f"{t.arrivee:%H:%M}", style=style),
        Text(duree(t.duree), style="dim"),
        Text(t.libelle_train, style=style),
        *prix_cells,
        Text(" · ").join(infos) if infos else Text(""),
        reserver,
    ]


def texte_ouverture(o: OuvertureVentes) -> tuple[str, str]:
    """('ouverture estimée ', 'le jeudi 12 novembre 2026 vers 06h00'), ou une mention si la date est dépassée."""
    if o.date_ouverture <= datetime.now(PARIS_TZ):
        return "ouverture ", "imminente (date pas encore annoncée, vérifie régulièrement)"
    quand = f"le {format_jour(o.date_ouverture.date())} vers {o.date_ouverture:%Hh%M}"
    return ("ouverture estimée " if o.estimee else "ouverture "), quand


def _texte_ferme(ferme: TrajetsFermes) -> Text:
    debut, quand = texte_ouverture(ferme.ouverture)
    return Text.assemble(
        ("  ⏳ ", ""),
        (f"{ferme.transporteur} pas encore en vente", "yellow"),
        f" — {debut}",
        (quand, "bold"),
        (" · " + " · ".join(ferme.precisions) if ferme.precisions else "", "dim"),
    )


def afficher_recapitulatif(console: Console, recherches: list[Recherche], titre: str) -> None:
    if len(recherches) < 2:
        return
    table = Table(title=titre, title_style="bold", header_style="bold")
    table.add_column("Recherche")
    table.add_column("Trajet")
    table.add_column("Meilleur choix")
    table.add_column("Prix", justify="right")
    table.add_column("Réserver")
    total, manquants = 0.0, 0
    for recherche in recherches:
        meilleur = meilleur_trajet(recherche.resultats)
        if meilleur:
            res, t = meilleur
            offre = t.meilleure_offre
            total += offre.prix
            table.add_row(
                recherche.etiquette,
                recherche.itineraire.label,
                f"{format_jour(t.jour, court=True)} {t.depart:%H:%M} · {t.libelle_train}",
                Text(euros(offre.prix), style="bold green"),
                lien(f"{offre.source} ↗", res.liens.get(offre.source, "")),
            )
        else:
            manquants += 1
            fermes = [f for r in recherche.resultats for f in r.fermes]
            etat = "⏳ pas encore en vente" if fermes else "aucun trajet achetable"
            table.add_row(recherche.etiquette, recherche.itineraire.label, etat, "—", "")
    console.print()
    console.print(table)
    if total:
        texte = f"Total des meilleurs prix : {euros(total)}"
        if manquants:
            texte += f" (hors {manquants} trajet(s) pas encore achetable(s))"
        console.print(Text(texte, style="bold"))


def afficher_comparatif_allers_retours(console: Console, recherches: list[Recherche]) -> None:
    """Un A/R par ligne : meilleur aller, meilleur retour (qui part après l'arrivée de l'aller), total."""
    groupes: dict[str, dict[str, Recherche]] = {}
    for r in recherches:
        groupes.setdefault(r.groupe or "", {})[r.sens or "aller"] = r
    lignes = []
    for groupe, sens in groupes.items():
        aller = meilleur_trajet(sens["aller"].resultats) if "aller" in sens else None
        retour = None
        if "retour" in sens:
            retour = meilleur_trajet(sens["retour"].resultats, apres=aller[1].arrivee if aller else None)
        total = aller[1].meilleur_prix + retour[1].meilleur_prix if aller and retour else None
        lignes.append((groupe, sens, aller, retour, total))
    totaux = [l[4] for l in lignes if l[4] is not None]
    meilleur_total = min(totaux) if len(totaux) > 1 else None

    table = Table(title="Comparatif des allers-retours", title_style="bold", header_style="bold")
    for colonne, alignement in (("", "left"), ("Trajet", "left"), ("Aller", "left"), ("Prix", "right"),
                                ("Retour", "left"), ("Prix", "right"), ("Total", "right")):
        table.add_column(colonne, justify=alignement)
    for groupe, sens, aller, retour, total in lignes:
        etoile = total is not None and total == meilleur_total
        itineraire_aller = sens["aller"].itineraire if "aller" in sens else sens["retour"].itineraire.inverse()
        table.add_row(
            Text("★ " + groupe, style="bold green") if etoile else Text(groupe),
            itineraire_aller.label,
            *_cellules_comparatif(sens.get("aller"), aller),
            *_cellules_comparatif(sens.get("retour"), retour),
            Text(euros(total), style="bold green" if etoile else "bold") if total is not None else Text("—", style="dim"),
        )
    console.print()
    console.print(table)


def _cellules_comparatif(recherche: Recherche | None, meilleur: tuple[ResultatJour, Trajet] | None) -> list[Text]:
    if recherche is None:
        return [Text(""), Text("")]
    if meilleur is None:
        fermes = any(r.fermes for r in recherche.resultats)
        return [Text("⏳ pas encore en vente" if fermes else "aucun trajet achetable", style="yellow"), Text("—", style="dim")]
    res, t = meilleur
    offre = t.meilleure_offre
    texte = f"{format_jour(t.jour, court=True)} {t.depart:%H:%M} · {t.libelle_train}" + (" ⚠" if t.ecarts else "")
    return [lien(texte, res.liens.get(offre.source, ""), ""), Text(euros(offre.prix))]


def regrouper_fermes(fermes: list[TrajetsFermes]) -> list[list[TrajetsFermes]]:
    """Regroupe par date d'ouverture et transporteur (un rappel par ouverture)."""
    groupes: dict = {}
    for f in sorted(fermes, key=lambda f: (f.ouverture.date_ouverture, f.transporteur, f.jour)):
        groupes.setdefault((f.ouverture.date_ouverture, f.transporteur), []).append(f)
    return list(groupes.values())


def afficher_ouvertures(console: Console, groupes: list[list[TrajetsFermes]]) -> None:
    lignes = []
    for groupe in groupes:
        o = groupe[0].ouverture
        debut, quand = texte_ouverture(o)
        jours = ", ".join(f"{f.itineraire.label} {format_jour(f.jour, court=True)}" for f in groupe)
        precisions = list(dict.fromkeys(p for f in groupe for p in f.precisions))
        lignes.append(
            Text.assemble(
                ("• ", ""),
                (f"{o.transporteur} : ", "bold"),
                debut,
                (quand, "bold yellow"),
                f"\n  pour : {jours}",
                ("".join(f"\n  {p}" for p in precisions), ""),
                (f"\n  source : {o.source}" if o.source else "", "dim"),
            )
        )
    console.print()
    console.print(Panel(Group(*lignes), title="⏳ Trajets pas encore en vente", border_style="yellow"))
