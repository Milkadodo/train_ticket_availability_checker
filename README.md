# trajets — billets TGV INOUI et OUIGO au meilleur prix

Application en ligne de commande, **entièrement au clavier, sans aucun argument** : tu lances `trajets` et tu
choisis dans des menus.

```
╭─────────────────────────────────────────────────────────────────────────╮
│ 🚄 Trajets — billets TGV INOUI et OUIGO au meilleur prix                          │
│ ↑↓ choisir · Entrée valider · Échap étape précédente · Ctrl+C menu principal     │
╰─────────────────────────────────────────────────────────────────────────╯
? Que veux-tu faire ? (↑↓ puis Entrée)
 » 🎓  Mode alternance — Paris ⇄ Nancy, autour de tes fins de période
   🧭  Trajet libre — aller simple, aller-retour ou plusieurs A/R, villes au choix
   ⚙️   Réglages
   🚪  Quitter
```

Pour chaque jour cherché, l'outil affiche les trains avec :

- les prix **SNCF Connect** (avec la **Carte Avantage Jeune** si elle est activée) et les prix **OUIGO** ;
- le **trajet le moins cher** (★), puis un récapitulatif (et le total pour un aller-retour) ;
- un **lien direct** vers SNCF Connect et vers OUIGO, déjà réglé sur la bonne date ;
- pour les trajets **pas encore en vente**, la **date d'ouverture des ventes**, avec un **rappel iCalendar** (.ics)
  à ajouter à ton calendrier.

## Installation

Il faut Python 3.10 ou plus récent, et **Google Chrome** (déjà installé sur ton Mac).

```bash
cd ~/Desktop/train_ticket_availability_checker
python3 -m venv .venv
.venv/bin/pip install -e .
```

Sans Google Chrome, installe le Chromium de Playwright : `.venv/bin/playwright install chromium`.

Pour lancer `trajets` depuis n'importe quel dossier, ajoute cet alias dans `~/.zshrc` :

```bash
alias trajets="$HOME/Desktop/train_ticket_availability_checker/.venv/bin/trajets"
```

## Les deux modes

### 🎓 Mode alternance (Paris ⇄ Nancy)

1. Saisis tes **vendredis de fin d'école** : l'outil cherche le trajet **Nancy → Paris**.
2. Saisis tes **vendredis de fin d'entreprise** : trajet **Paris → Nancy**.
3. Choisis les jours :
   - **samedi et dimanche**, **samedi seulement** ou **dimanche seulement** (le week-end qui suit) ;
   - **Flex** : tu indiques combien de jours **avant** et combien de jours **après** la date de fin (la date
     elle-même est toujours cherchée). Ex. 1 avant et 2 après un vendredi = du jeudi au dimanche.

Plusieurs dates à la fois, séparées par des espaces : `18/12/2026 22/01 05/02`. Les dates et le choix des jours
sont **mémorisés** : la fois suivante, ils sont pré-remplis (seules les dates à venir), il suffit de valider.
Ce mode ne garde que les **trains directs**. Le moins cher est cherché sur tous les jours de la période.

### 🧭 Trajet libre

1. **Aller simple**, **aller-retour** ou **plusieurs allers-retours**.
2. **Ville ou gare de départ**, puis d'**arrivée** : tape un nom, puis choisis dans la liste proposée par
   SNCF Connect (« Lyon (ville, toutes les gares) », « Lyon Part-Dieu (gare) »…). Les derniers lieux sont mémorisés.
3. **Date de l'aller** (et du **retour**) : `07/11/2026`, `07/11` ou `demain`. Pour **plusieurs allers-retours**,
   saisis toutes les dates d'aller puis toutes les dates de retour (`07/11 13/11` puis `08/11 15/11`) : chaque
   aller est associé au premier retour qui suit (avant l'aller suivant), et l'outil affiche les paires avant de
   chercher. Une date sans partenaire est cherchée seule.
4. **Dates exactes** ou **Flex** : combien de jours avant et après **chaque** date (ex. 1 et 1 = la veille, le
   jour même et le lendemain).
5. **Directs uniquement** ou **avec correspondances**.

Pour un ou plusieurs allers-retours, un **comparatif** termine les résultats : une ligne par A/R avec le meilleur
aller, le meilleur retour (qui part forcément après l'arrivée de l'aller, utile en Flex) et le total ; le moins
cher est marqué ★.

```
                            Comparatif des allers-retours
┃         ┃ Trajet       ┃ Aller                           ┃ Prix ┃ Retour                          ┃ Prix ┃ Total ┃
│ ★ A/R 1 │ Paris → Lyon │ sam. 7 nov. 19:26 · OUIGO 7805  │ 25 € │ dim. 8 nov. 08:38 · OUIGO 7802  │ 25 € │  50 € │
│ A/R 2   │ Paris → Lyon │ ven. 13 nov. 12:26 · OUIGO 7803 │ 29 € │ dim. 15 nov. 08:38 · OUIGO 7802 │ 29 € │  58 € │
```

Au-delà de 8 journées à chercher (Flex, nombreuses dates), l'outil annonce la durée estimée (≈ 10 s par jour)
et demande confirmation : beaucoup de recherches d'affilée peuvent déclencher la vérification anti-robot.

### ⚙️ Réglages (mémorisés)

| Réglage | Choix |
| --- | --- |
| Âge | utilisé pour le tarif jeune (la Carte Avantage Jeune couvre les 12-27 ans) |
| Carte de réduction | Carte Avantage Jeune ou aucune |
| Sites consultés | SNCF Connect et OUIGO, ou un seul des deux |
| Trains | TGV INOUI et OUIGO seulement, ou tous (TER, Intercités…) |
| Trains complets | détectés grâce aux horaires officiels SNCF (par défaut) ou ignorés |
| Fenêtre du navigateur | cachée (par défaut) ou visible |
| Dossier des rappels | où enregistrer les .ics (par défaut `~/Documents/Rappels trains`) |
| Vider le cache | oublie les résultats gardés 20 minutes |

### Se déplacer

| Touche | Effet |
| --- | --- |
| ↑ ↓ puis Entrée | choisir dans un menu |
| **Échap** (ou le choix **↩ Retour** en bas de chaque menu) | revenir à la question précédente, réponses déjà saisies conservées |
| Ctrl+C | abandonner et revenir au menu principal (dans le menu principal : quitter) |

Les questions sans objet sont sautées dans les deux sens (ex. la date de retour d'un aller simple, ou les jours
avant/après quand Flex n'est pas choisi). Avant une longue recherche, « ↩ Retour » permet de modifier les choix au
lieu de lancer.

## Lire les résultats

- **Prix SNCF Connect** : tarif pour ton âge avec la Carte Avantage Jeune (si activée), en 2de, ou en 1re si c'est
  moins cher (c'est alors indiqué). Les offres qui supposent d'acheter une autre carte sont ignorées.
- **Prix OUIGO** : tarif « Essentiel ». OUIGO n'accepte pas la Carte Avantage Jeune. Un OUIGO vendu aussi sur
  SNCF Connect n'apparaît qu'une fois, avec les deux prix.
- **★ / 💰** : le trajet le moins cher (samedi et dimanche confondus en mode alternance).
- **Rames jumelées** (`2571/2587`) : deux TGV accouplés aux mêmes horaires, regroupés au meilleur prix.
- **« part de… » / « arrive à…, pas à… »** : gare hors du centre (Marne-la-Vallée, Roissy, Massy, Lorraine TGV,
  Lyon Saint-Exupéry…), alors que tu as choisi la ville. Ces trains sont affichés mais ne sont retenus comme « moins
  cher » que s'il n'y a rien d'autre. Pour viser une de ces gares, choisis-la directement dans la liste.
- **« Plus que N places à ce prix »** : repris de SNCF Connect, utile pour savoir s'il faut se dépêcher.

### Disponible, complet ou pas encore en vente ?

| Situation | TGV INOUI (SNCF Connect) | OUIGO (ouigo.com) |
| --- | --- | --- |
| En vente | prix affiché | prix affiché |
| Complet | « complet » sur la ligne du train | « complet » sur la ligne du train ; « Tous les OUIGO de ce jour sont complets » |
| Complet et retiré de la vente | « complet (n'est plus en vente) », grâce aux horaires officiels SNCF | idem (OUIGO retire ses trains complets) |
| Pas encore en vente | « ⏳ pas encore en vente » sur chaque train (ou journée vide) | « ⏳ OUIGO pas encore en vente », avec **jusqu'à quelle date OUIGO vend déjà** (ex. « jusqu'au vendredi 2 juillet 2027 ») |
| Aucun train ce jour-là | — | « Aucun OUIGO ce jour-là — **prochain départ OUIGO le …** » |

**Trains complets invisibles.** OUIGO (et parfois SNCF Connect) retire purement et simplement un train complet :
il n'apparaît plus nulle part, et OUIGO répond « aucun trajet ». Pour le repérer, l'outil compare la vente aux
**horaires officiels SNCF** (données ouvertes GTFS : TGV INOUI et OUIGO, mis à jour chaque jour). Un train qui
circule d'après ces horaires mais qu'aucun site ne vend est affiché « complet (n'est plus en vente) », ou
« pas encore en vente » si la billetterie n'est pas ouverte. Exemple réel : le OUIGO 7698 Nancy 18:09 → Paris Est
du samedi 6 mars 2027. Ces horaires officiels couvrent seulement les mois qui viennent (jusqu'au 31 mars 2027 à ce
jour) ; au-delà, seuls les trains vendus apparaissent. L'export (≈ 5,5 Mo) est téléchargé au plus une fois par
jour d'utilisation ; réglage « Trains complets » pour le désactiver.

OUIGO indique lui-même les autres états. En revanche, ni OUIGO ni SNCF Connect ne donnent la **date d'ouverture de la
billetterie** dans leurs réponses : l'outil la prend dans le calendrier officiel connu, ou l'estime (voir plus
bas), et le précise toujours (« ouverture le … » ou « ouverture estimée le … »). Si cette date est déjà passée
alors que ce n'est toujours pas en vente, il affiche « ouverture imminente (date pas encore annoncée) ». Quand
OUIGO le propose, tu peux aussi créer une **alerte e-mail** d'ouverture directement sur la page OUIGO (lien du jour).

### Les liens

- **SNCF Connect** : ouvre la page de résultats du bon jour (via la recherche en langage naturel du site,
  « Paris Nancy le 7 novembre 2026 à 5h »). La carte de réduction ne peut pas passer dans le lien :
  **connecte-toi à ton compte SNCF Connect avec ta carte enregistrée** pour retrouver les mêmes prix. À la toute
  première visite, réponds au bandeau cookies pour que la recherche se lance.
- **OUIGO** : ouvre directement la liste des trains du jour sur ventes.ouigo.com.

Dans iTerm2, Warp, VS Code ou un Terminal récent, les `SNCF ↗` / `OUIGO ↗` sont cliquables. Sinon, chaque jour
affiche aussi les URL complètes (Cmd+clic).

### Trajets pas encore en vente et rappels iCalendar

Quand SNCF Connect indique « En vente prochainement », l'outil cherche la date d'ouverture :

1. dans le calendrier connu `trajets/data/ouvertures_ventes.json` (sources : pages SNCF) ;
2. sinon il l'**estime** d'après le rythme habituel (2e mercredi de mars pour juillet-décembre, dernier mercredi
   de septembre pour les fêtes et pour OUIGO jusqu'à juillet, 2e jeudi de novembre pour les TGV INOUI de
   janvier à juillet). Une date estimée est toujours marquée « estimée ».

Il propose ensuite un fichier `.ics` : un événement par ouverture, vers 6h (les ventes ouvrent en général un
peu avant 6h ; l'heure exacte n'est pas publiée), avec deux alertes (la veille et 15 min avant) et les liens des
trajets concernés. Choisis « Oui » pour l'ajouter directement à l'app Calendrier.

Quand la SNCF annonce une nouvelle ouverture, ajoute-la dans `~/.trajets-alternance/ouvertures_ventes.json`
(même format que le fichier fourni ; il est prioritaire), par exemple :

```json
{
  "ouvertures": [
    {"transporteur": "TGV INOUI", "voyages_du": "2027-07-03", "voyages_au": "2027-12-11",
     "ouverture": "2027-03-10T06:00", "source": "https://www.sncf-connect.com/aide/l-ouverture-des-ventes"}
  ]
}
```

## Comment ça marche, et limites

Ni SNCF Connect ni OUIGO n'ont d'API publique. L'outil pilote un vrai Chrome (Playwright) en arrière-plan, avec
un profil gardé dans `~/.trajets-alternance/navigateur` :

- **SNCF Connect** : appel de l'API interne du site depuis la page (comme le fait le site lui-même) pour les
  horaires et les prix, et son autocomplétion pour trouver les villes et les gares ;
- **OUIGO** : ouverture du lien de recherche et lecture des réponses que le site reçoit ; la liste des gares
  OUIGO (et de leurs liaisons) est gardée 7 jours ;
- **horaires officiels SNCF** : export GTFS de [transport.data.gouv.fr](https://transport.data.gouv.fr/datasets/horaires-sncf),
  téléchargé directement (pas besoin du navigateur), pour repérer les trains complets retirés de la vente.

SNCF Connect est protégé par un anti-robot (DataDome). Pour rester discret, l'outil ne fait que quelques
requêtes espacées par jour cherché et garde les résultats **20 minutes** en cache. Si une vérification apparaît
malgré tout, l'outil propose d'ouvrir une **fenêtre Chrome** : si un captcha s'affiche, c'est à toi de le
résoudre, la recherche reprend ensuite toute seule. Évite de relancer des recherches en rafale : trop de
requêtes rapprochées font bloquer temporairement ton adresse IP.

Autres limites :

- les sites peuvent changer leur fonctionnement interne : l'outil devra alors être adapté ;
- les prix bougent vite : vérifie toujours le prix final au moment de payer ;
- le **OUIGO Paris ⇄ Nancy reprend le 13 décembre 2026** : avant cette date, aucun OUIGO n'apparaît sur ce trajet ;
- l'outil ne réserve ni ne paie rien : c'est toi qui achètes, via les liens.

Fichiers gardés dans `~/.trajets-alternance/` : `reglages.json` (tes réglages, dates et derniers lieux),
`cache.json`, `ouigo_gares.json`, `horaires/` (export GTFS SNCF et son index), le profil `navigateur/` et, si tu
le crées, `ouvertures_ventes.json`.

## Développement

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

Les tests utilisent des réponses réelles des deux sites enregistrées dans `tests/fixtures/`.

Pour essayer l'application sans toucher à tes réglages ni à ton cache, fais-la travailler dans un autre dossier :
`TRAJETS_DOSSIER=/tmp/essai-trajets .venv/bin/trajets`.

Si l'outil a été arrêté brutalement (terminal fermé pendant une recherche), son Chrome peut rester ouvert et
bloquer le profil : au lancement suivant, l'outil le détecte et propose de le fermer.

```
trajets/
  cli.py              application interactive : menus, saisies, réglages, rappels
  assistant.py        enchaînement des questions avec retour à l'étape précédente
  modes.py            mode alternance (week-end / flex), trajet libre (A/R multiples, flex)
  recherche.py        moteur : une journée = SNCF Connect + OUIGO, fusion, rames jumelées, trains complets
  horaires.py         horaires officiels SNCF (GTFS) : téléchargement, index, trains prévus
  providers/          sncf_connect.py (horaires, prix, autocomplétion), ouigo.py (horaires, prix, gares)
  gares.py            lieux de l'alternance, correspondance avec les gares OUIGO
  models.py           lieux, itinéraires, trajets, gares excentrées
  navigateur.py       Chrome piloté (profil persistant, vérification anti-robot)
  ventes.py           dates d'ouverture des ventes (calendrier + estimation)
  ical.py, rappels.py rappels iCalendar
  liens.py            liens SNCF Connect / OUIGO pré-remplis
  reglages.py         réglages mémorisés
  affichage.py        tableaux Rich
  data/ouvertures_ventes.json
```
