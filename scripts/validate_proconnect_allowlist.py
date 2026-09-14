#!/usr/bin/env python3
"""
Relecture d'une pull request sur la liste d'autorisation api-partenaires
(ProConnect).

Le script compare deux versions de la liste et classe chaque domaine de la
nouvelle. Recuperer les deux versions est le travail du shell, pas du script ::

    cd api-partenaires
    f=config/anct/oidc_providers.production.yaml
    git show origin/main:$f > /tmp/base.yaml
    python validate_proconnect_allowlist.py --base /tmp/base.yaml --head $f

Il telecharge deux fichiers publics, tous deux mis en cache dans ``--cache-dir``:
l'export de l'annuaire DILA (service-public.gouv.fr), qui est la source meme que
citent les commentaires de la liste, et le Code officiel geographique de l'INSEE,
qui dit comment chaque commune s'appelle reellement. Avec ``--dila-json`` et
``--cog-csv`` il utilise des copies locales et ne touche jamais au reseau.


LES CINQ CATEGORIES
===================

Router un domaine vers un fournisseur d'identite revient a dire "toute personne
ayant une adresse sur ce domaine s'authentifie en tant que cette collectivite".
Chaque ligne de la liste est donc une revendication de propriete, et le role de ce
script est de dire ce qui la fonde.

Chaque domaine de la nouvelle version tombe dans exactement une categorie. Elles
sont essayees dans l'ordre ci-dessous et la premiere qui correspond gagne: les
cinq totaux font donc toujours le compte des domaines du fichier.

1. not_allowed
   Le domaine, ou un domaine qui le porte, figure sur la liste de refus de ce
   fichier: messageries grand public et fournisseurs d'acces, reseaux sociaux,
   createurs de sites et de blogs, plateformes SaaS vendues aux communes, annuaires
   de mairies, l'Etat, et la poignee de marques tierces qui entrent en collision
   avec un nom de commune. C'est une erreur quoi qu'il en soit par ailleurs, d'ou
   ce test en premier: ``orange.fr`` est une reconstruction parfaite du nom de la
   commune d'Orange (84) et ``vogue.fr`` de celui de Vogue (07), donc n'importe
   quel test ulterieur les laisserait passer.

   Volontairement plus etroite que la liste des domaines generiques du RPNT 2.2
   dans st-home: celle-ci contient aussi des domaines *publics* mutualises (ceux
   d'un CDG, d'un syndicat), qui ne sont le domaine propre d'aucune commune mais
   ne sont pas une erreur pour autant. ``selonnet.fr`` y figure et c'est le site
   officiel de la commune de Selonnet.

2. reconstructible
   L'algorithme de suggestion aurait pu produire ce domaine a partir du nom de la
   collectivite que la ligne designe. C'est une supposition sur le proprietaire du
   nom, pas une preuve, et la liste en contient 139 000. Les regles sont celles de
   ``core/services/domains_candidates.py``, elargies pour reconnaitre les graphies
   qu'une commune a deposees il y a des annees et que le generateur ne proposerait
   plus: ``.com``, ``.net``, ``.org`` et ``.info`` en plus des extensions
   souveraines, davantage de prefixes et de suffixes (``commune-``, ``mairie-de-``,
   ``-village``, ``-officiel``, les formes d'EPCI comme ``-agglo`` et
   ``-communaute``), le numero de departement en fin de nom (``2A``/``2B``
   compris, qu'aucune regle sur les chiffres n'attrape), ``saint``/``st`` dans les
   deux sens, l'article initial supprime, les mots de liaison supprimes, et le
   qualificatif retire d'un nom compose (Coise-Saint-Jean-Pied-Gauthier a depose
   ``coise73.fr``).

   Essaye contre tous les noms que porte la collectivite, pas seulement celui de
   la fiche: voir :func:`load_cog`. Sans cela, un tiers de ce qui demande un
   arbitrage humain n'y est que parce que l'annuaire n'est pas a jour.

3. previous_allowlist
   Le domaine etait deja dans le fichier deploye: cette PR ne l'accorde donc pas.
   Place apres reconstructible a dessein: un domaine qui est les deux etait deja
   une supposition au moment du deploiement, et le dire est plus utile que dire
   qu'il est ancien.

4. dila_ok
   Le domaine est declare sur service-public.gouv.fr par exactement une
   collectivite (mairie, EPCI, conseil departemental ou conseil regional), et
   cette declaration satisfait les trois criteres RPNT qui se lisent sur un
   domaine:

     1.2  l'extension est souveraine et le nom n'est pas internationalise;
     2.2  le domaine porte le nom de la collectivite, ce que le RPNT formule par
          "un nom de domaine est dit generique lorsqu'il ne comporte pas le nom de
          la collectivite";
     2.3  le meme domaine sert le site web et l'adresse de messagerie de la fiche.

   "Exactement une" est ce qui distingue un domaine d'une infrastructure partagee
   sans aucune liste a maintenir: ``facebook.com`` est declare par 49
   collectivites, ``intramuros.org`` par 249, ``wanadoo.fr`` par 10 800.

5. to_be_validated
   Tout le reste. Un humain doit trancher. Typiquement un domaine declare par
   plusieurs collectivites (celui d'un EPCI, d'un departement, d'un CDG), un
   domaine dont la fiche ne donne aucune adresse de messagerie correspondante, ou
   un nom que personne ne declare nulle part.


SORTIES
=======

Le rapport donne, par categorie, combien de domaines et pourquoi. Il ne montre
aucun exemple: sur un fichier de cent mille lignes une poignee de domaines tires
au hasard n'apprend rien, et ``--csv FICHIER`` ecrit l'integralite pour qui doit
la traiter.

Ce CSV est aussi l'entree de filter_proconnect_allowlist.py, qui retire des
categories entieres du fichier pour ramener une PR a ce qu'un relecteur acceptera
sans discuter. Il porte pour cela une colonne ``deployed``, afin que le filtrage
n'ait aucun raisonnement a refaire.

Aucune dependance tierce: le script tourne sur un Python 3 nu, sans rien
d'installe. Il n'y a donc rien d'autre a auditer que ce fichier.

Le code de sortie vaut 1 des qu'un domaine tombe dans ``not_allowed``.
"""

import argparse
import csv
import gzip
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

# Seulement les champs que lisent les categories: l'export complet fait 280 Mo,
# celui-ci moins de 10.
DILA_EXPORT_URL = (
    "https://api-lannuaire.service-public.gouv.fr/api/explore/v2.1/catalog/"
    "datasets/api-lannuaire-administration/exports/json"
    "?select=id%2Csiret%2Csiren%2Cnom%2Cpivot%2Ccode_insee_commune"
    "%2Csite_internet%2Cadresse_courriel"
)

# Le Code officiel geographique de l'INSEE: la graphie de reference de chaque nom
# de commune, indexee par code INSEE, qui est la cle que portent deja les fiches
# DILA. Le segment numerique de l'URL est l'identifiant d'une edition donnee et
# change chaque annee: une nouvelle edition demande de mettre a jour cette
# constante (ou de passer --cog-csv).
INSEE_COG_URL = (
    "https://www.insee.fr/fr/statistiques/fichier/8377162/v_commune_2025.csv"
)

# DILA classe chaque fiche locale par `type_service_local`. Ces quatre valeurs
# sont les collectivites auxquelles une ligne de la liste peut legitimement
# appartenir; la PR a l'origine de ce script cite 34 881 mairies, 1 222 EPCI, 95
# conseils departementaux et 17 conseils regionaux, et rien d'autre. `ccas` et
# `police_municipale` sont exclus a dessein, pour qu'une commune qui partage son
# domaine avec son propre CCAS compte toujours pour une seule collectivite
# declarante.
COLLECTIVITE_TYPES = frozenset({"mairie", "epci", "cg", "cr"})

# Critere RPNT 1.2: les extensions qu'une collectivite francaise peut utiliser.
# A garder synchronise avec DOMAIN_EXTENSIONS_ALLOWED dans st-deploycenter et
# st-home.
SOVEREIGN_EXTENSIONS = frozenset(
    {
        "fr",
        "alsace",
        "bzh",
        "corsica",
        "paris",
        "eu",
        "gp",
        "mq",
        "gf",
        "re",
        "pm",
        "yt",
        "wf",
        "pf",
        "nc",
        "tf",
    }
)

# La reconstruction accepte celles-ci en plus des souveraines. Une commune qui a
# depose `vernou-en-sologne.com` en 2004 n'a pas cesse de le posseder le jour ou
# le RPNT 1.2 a ete ecrit: il s'agit de reconnaitre le nom, pas de l'approuver.
RECONSTRUCTIBLE_EXTENSIONS = SOVEREIGN_EXTENSIONS | {"com", "net", "org", "info"}

# Jamais le domaine propre d'une collectivite, quoi que dise le reste de la ligne.
NOT_ALLOWED = frozenset(
    {
        # -- messageries grand public et fournisseurs d'acces -------------------
        # La plupart viennent de GENERIC_EMAIL_DOMAINS dans suitenumerique/st-home
        # (data/tasks/defs.py), ou le RPNT 2.2 est maintenu. Les autres sont des
        # noms qui ont atteint la premiere PR api-partenaires parce qu'ils y
        # manquaient: `gmail.com` etait sur la liste, `gmail.fr` non.
        "9business.fr",
        "9online.fr",
        "adeli.biz",
        "akeonet.com",
        "aliceadsl.fr",
        "alsatis.net",
        "aol.com",
        "aricia.fr",
        "bbox.fr",
        "bouyguestelecom.fr",
        "cegetel.net",
        "club-internet.fr",
        "club.fr",
        "evc.net",
        "free.fr",
        "gmail.com",
        "gmail.fr",
        "gmx.com",
        "gmx.fr",
        "gmx.net",
        "googlemail.com",
        "hotmail.com",
        "hotmail.fr",
        "icloud.com",
        "idyle-telecom.com",
        "laposte.net",
        "lgtel.fr",
        "live.com",
        "live.fr",
        "mail.com",
        "mailo.com",
        "mailoo.org",
        "mcom.fr",
        "me.com",
        "msn.com",
        "netcourrier.com",
        "neuf.fr",
        "nordnet.fr",
        "numericable.com",
        "numericable.fr",
        "online.fr",
        "orange-business.fr",
        "orange.fr",
        "outlook.com",
        "outlook.fr",
        "ovh.fr",
        "ovh.net",
        "ozone.net",
        "pagesperso-orange.fr",
        "proton.me",
        "protonmail.com",
        "rtvc.fr",
        "sfr.fr",
        "telwan.fr",
        "tubeo.eu",
        "tutanota.com",
        "tv-com.net",
        "vialis.net",
        "voila.fr",
        "wanadoo.fr",
        "west-telecom.com",
        "wibox.fr",
        "yahoo.com",
        "yahoo.fr",
        "ymail.com",
        "yandex.com",
        "zoho.com",
        # -- reseaux sociaux, blogs et createurs de sites -----------------------
        # Une commune dont le site declare est une page Wix n'y a aucune boite aux
        # lettres a router, et le nom sous lequel elle est hebergee appartient a la
        # plateforme.
        "blog4ever.com",
        "blogspot.com",
        "blogspot.fr",
        "canalblog.com",
        "e-monsite.com",
        "facebook.com",
        "google.com",
        "instagram.com",
        "jimdo.com",
        "jimdofree.com",
        "jimdosite.com",
        "jimdoweb.com",
        "linkedin.com",
        "monsite.com",
        "over-blog.com",
        "sitego.fr",
        "sitew.com",
        "sitew.fr",
        "twitter.com",
        "webnode.fr",
        "weebly.com",
        "wix.com",
        "wixsite.com",
        "wordpress.com",
        "x.com",
        "youtube.com",
        # -- messageries mutualisees distribuees a plusieurs communes -----------
        # Un syndicat, un centre de gestion ou un prestataire de secretariat
        # heberge le courrier des communes membres. Le domaine est celui du
        # prestataire, pas d'une commune en particulier: le router laisserait
        # chaque membre s'authentifier comme celle que la ligne designe. Meme
        # famille que les entrees ci-dessus, mise a part parce qu'il s'agit
        # d'organismes publics et non de produits grand public.
        "collectivite47.fr",  # CDG 47, Lot-et-Garonne
        "info46.fr",  # Syndicat des Inforoutes, Lot
        "inforoutes-ardeche.fr",  # Syndicat des Inforoutes de l'Ardeche
        "inforoutes.fr",  # same syndicat
        "pole-secretariat.fr",  # private secretariat provider
        "sivucesny.fr",  # SIVU de Cesny, Calvados
        # -- plateformes SaaS vendues aux communes ------------------------------
        "espace-citoyens.net",
        "illiwap.com",
        "intramuros.org",
        "lapagelocale.fr",
        "maelis.info",
        "neopse-site.com",
        "padlet.com",
        "panneaupocket.com",
        # -- annuaires qui repertorient les mairies -----------------------------
        "annuaire-mairie.fr",
        "commune-mairie.fr",
        "info-mairie.com",
        "la-mairie.com",
        "mairie.com",
        # -- marques tierces sur lesquelles tombe un nom de commune -------------
        # Chacune verifiee sur ce que le domaine sert reellement et sur qui le
        # detient, pas devinee d'apres le nom. Ajouter a cette liste, ne jamais en
        # retirer sans verifier de nouveau.
        "champagne.fr",  # registrar de protection de marque, pas la commune (17)
        "durance.fr",  # Durance, cosmetiques
        "ens.fr",  # Ecole normale superieure, pas la commune (65)
        "faurie.fr",  # Groupe Faurie, concessions automobiles
        "laas.fr",  # LAAS-CNRS, pas la commune (32/45/64)
        "lagrange.fr",  # Lagrange, petit electromenager
        "lamontagne.fr",  # La Montagne, quotidien
        "lancome.fr",  # Lancome, L'Oreal
        "lapeyre.fr",  # Lapeyre, Saint-Gobain
        "lascaux.fr",  # Lascaux IV, Semitour Perigord
        "lissac.fr",  # Lissac, opticien
        "lunion.fr",  # L'Union, quotidien
        "reunion.fr",  # tourisme de La Reunion, pas la commune (47)
        "union.fr",  # Union, magazine
        "vogue.fr",  # Vogue France, Conde Nast
        # -- l'Etat -------------------------------------------------------------
        # Teste sur les domaines parents aussi, donc ceci couvre tout *.gouv.fr.
        # Une commune qui en declare un nous dit que son courrier est traite par un
        # ministere, une prefecture ou un service national, jamais qu'elle possede
        # le nom: `villeberny.cotedor.gouv.fr` appartient a la prefecture de la
        # Cote-d'Or, `espacesurdemande.anct.gouv.fr` a l'ANCT.
        "gouv.fr",
        # -- institutions et operateurs nationaux -------------------------------
        # Router l'un de ces domaines donnerait a un fournisseur d'identite
        # communal le pouvoir d'authentifier "en tant que" l'Elysee, la Cour de
        # cassation ou l'assurance maladie. Aucun n'appartient a une collectivite:
        # verifie sur l'export DILA, ou aucun n'est declare par une mairie, un
        # EPCI, un departement ou une region, et sur le COG, ou aucun nom de
        # collectivite ne les reconstruit.
        #
        # Les domaines en *.gouv.fr ne sont pas repris ici: la regle ci-dessus les
        # couvre deja tous. Ceux-ci sont ceux qui n'y sont pas.
        #
        # L'Etat et ses pouvoirs
        "assemblee-nationale.fr",
        "conseil-constitutionnel.fr",
        "conseil-etat.fr",
        "courdecassation.fr",
        "elysee.fr",
        "gouvernement.fr",
        "justice.fr",
        "senat.fr",
        "service-public.fr",
        # Organismes qui traitent les donnees des administres
        "ameli.fr",
        "caf.fr",
        "francetravail.fr",
        "msa.fr",
        "pole-emploi.fr",
        "urssaf.fr",
        # Regulateurs, autorites, banque centrale
        "arcep.fr",
        "arcom.fr",
        "banque-france.fr",
        "cnil.fr",
        # Sante ("sante.fr" couvre aussi ars.sante.fr)
        "has-sante.fr",
        "sante.fr",
        "santepubliquefrance.fr",
        # Operateurs d'importance vitale et grands services publics
        "edf.fr",
        "enedis.fr",
        "engie.fr",
        "grdf.fr",
        "laposte.fr",
        "ratp.fr",
        "sncf.fr",
        # Agences et etablissements publics
        "ademe.fr",
        "anah.fr",
        "anru.fr",
        "ign.fr",
        "insee.fr",
        "meteofrance.fr",
        "onf.fr",
        # Union europeenne
        "europa.eu",
    }
)

# Teste avant la liste de refus, et en correspondance exacte plutot que par
# domaine parent: ce sont les domaines de service qu'un operateur route
# volontairement, et que la regle large `gouv.fr` ci-dessus qualifierait sinon
# d'erreur. Nommer ici toute la zone `anct.gouv.fr` laisserait aussi passer
# `espacesurdemande.anct.gouv.fr`, un service de l'ANCT que la commune de
# Nollieux a declare comme s'il etait le sien.
ALLOWED = frozenset({"suite.anct.gouv.fr", "suiteterritoriale.anct.gouv.fr"})

# A real domain name: at least two dot-separated labels, each alphanumeric with
# optional interior hyphens. Same shape st-deploycenter stores.
HOSTNAME_RE = re.compile(
    r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+"
)

CATEGORIES = [
    ("not_allowed", "on the deny list in this script, or under a domain that is"),
    ("reconstructible", "the suggest rules could have produced it from the name"),
    ("previous_allowlist", "already in the deployed allowlist"),
    ("dila_ok", "declared by exactly one collectivite, RPNT 1.2 + 2.2 + 2.3"),
    ("to_be_validated", "none of the above; a human has to decide"),
]
CATEGORY_ORDER = {name: index for index, (name, _) in enumerate(CATEGORIES)}


# --- telechargement et cache -------------------------------------------------


def default_cache_dir():
    """Ou les fichiers telecharges sont conserves entre deux executions."""
    base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return Path(base) / "proconnect-allowlist"


def download(url, destination, note):
    """Recupere ``url`` dans ``destination``, sauf si le fichier est deja la."""
    if destination.exists() and destination.stat().st_size > 0:
        return destination
    if not url.startswith("https://"):
        raise SystemExit(f"refus de telecharger une URL non https: {url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    sys.stderr.write(f"Telechargement de {note}...\n")
    request = urllib.request.Request(  # noqa: S310
        url, headers={"Accept-Encoding": "gzip, deflate"}
    )
    with urllib.request.urlopen(request, timeout=900) as response:  # noqa: S310
        payload = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            payload = gzip.decompress(payload)
    partial.write_bytes(payload)
    # Renomme seulement une fois le corps complet, pour qu'une execution
    # interrompue ne laisse pas un fichier tronque que toutes les suivantes
    # reutiliseraient sans broncher.
    partial.replace(destination)
    return destination


# --- noms --------------------------------------------------------------------


def slugify(value):
    """Le ``slugify`` de Django: accents retires, minuscules, suites en '-'.

    Reimplemente plutot qu'importe pour que le script n'ait pas besoin de Django,
    et parce que les domaines candidats examines ont ete construits avec
    exactement cette fonction.
    """
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-_")


ARTICLES = ("les ", "le ", "la ", "l'", "l’")

# Mots qui ne portent aucune identite a eux seuls: un domaine n'est jamais l'un
# d'eux, et un nom compose n'est jamais abrege jusqu'a l'un d'eux.
CONNECTORS = frozenset(
    {
        "sur",
        "sous",
        "en",
        "et",
        "de",
        "du",
        "des",
        "la",
        "le",
        "les",
        "aux",
        "au",
        "d",
        "l",
        "lez",
        "ls",
        "saint",
        "sainte",
        "st",
        "ste",
        "mont",
        "val",
        "ville",
    }
)

# Mots qu'une collectivite supprime ou abrege au moment de deposer un domaine.
GROUPING_WORDS = (
    "communaute-de-communes",
    "communaute-d-agglomeration",
    "communaute-urbaine",
    "agglomeration",
    "communaute",
    "metropole",
    "agglo",
)


def _articleless(name):
    """Le slug d'un nom prive de son article initial, ou ``None``.

    Travaille sur le nom plutot que sur le slug, parce que ``slugify`` colle un
    article apostrophe au mot qui suit: "L'Abergement-de-Varey" devient
    "labergement-de-varey", ou l'article n'est plus separable.
    """
    stripped = (name or "").strip()
    lowered = stripped.lower()
    for article in ARTICLES:  # le plus long d'abord, pour ne pas lire "le " dans "les "
        if lowered.startswith(article):
            return slugify(stripped[len(article) :])
    return None


def _saint_forms(slug):
    """``saint``/``st`` et ``sainte``/``ste`` echanges, dans les deux sens."""
    forms = set()
    for long, short in (("saint-", "st-"), ("sainte-", "ste-")):
        if slug.startswith(long) or f"-{long}" in slug:
            forms.add(slug.replace(long, short))
        if slug.startswith(short) or f"-{short}" in slug:
            forms.add(slug.replace(short, long))
    return forms


def name_stems(name):
    """Toutes les graphies d'un nom de collectivite dont un domaine peut venir.

    Renvoyees sans tirets, parce que la comparaison de :func:`reconstructs` se
    fait sur des formes sans tirets: "abbans-dessous" et "abbansdessous" sont
    ainsi un seul cas et non deux.
    """
    base = slugify(name)
    # Une ligature n'a pas de decomposition ASCII, donc slugify la supprime:
    # "Chambœuf" ecrit avec la ligature oe donne "chambuf". C'est ce que produit
    # le generateur, donc cette forme reste dans l'ensemble, mais la commune a
    # depose "chamboeuf.fr": la graphie developpee doit y figurer aussi.
    expanded = slugify(
        name.replace("œ", "oe").replace("Œ", "Oe").replace("æ", "ae").replace("Æ", "Ae")
    )
    if not base and not expanded:
        return set()
    forms = {f for f in (base, expanded) if f}

    bare = _articleless(name)
    if bare:
        forms.add(bare)

    # "Fougeres Agglomeration" a depose "fougeres-agglo.bzh", et
    # "Guingamp-Paimpol-Agglomeration" a depose "guingamp-paimpol.bzh".
    for form in list(forms):
        for word in GROUPING_WORDS:
            if form.endswith(f"-{word}"):
                forms.add(form[: -len(word) - 1])
                forms.add(f"{form[: -len(word) - 1]}-agglo")
                forms.add(f"{form[: -len(word) - 1]}-co")

    for form in list(forms):
        forms |= _saint_forms(form)

    # Le qualificatif supprime: Coise-Saint-Jean-Pied-Gauthier a depose
    # "coise73.fr".
    for form in list(forms):
        head = form.split("-")[0]
        if len(head) >= 5 and head not in CONNECTORS:
            forms.add(head)

    # Les mots de liaison supprimes au milieu du nom.
    for form in list(forms):
        kept = [t for t in form.split("-") if t not in CONNECTORS]
        if 0 < len(kept) < len(form.split("-")):
            forms.add("-".join(kept))

    return {form.replace("-", "") for form in forms if form}


# --- reconstruction ----------------------------------------------------------

PREFIXES = (
    "la-mairie-de-",
    "mairie-de-",
    "mairie-du-",
    "mairie-la-",
    "ville-de-",
    "ville-du-",
    "commune-de-",
    "commune-du-",
    "la-mairie-",
    "mairiede-",
    "villede-",
    "communede-",
    "mairie-",
    "ville-",
    "commune-",
    "agglo-",
    "cdc-",
    "cc-",
    "ca-",
    "cu-",
    "mairie",
    "ville",
    "commune",
)

SUFFIXES = (
    "-agglomeration",
    "-communaute",
    "-metropole",
    "-officiel",
    "-commune",
    "-village",
    "-mairie",
    "-agglo",
    "-ville",
    "-comm",
    "-off",
    "-co",
    "-fr",
    "mairie",
    "ville",
    "commune",
)


def _cores(label, departement):
    """Tous les noyaux restants apres retrait des prefixes, suffixes et numeros.

    Eplucher le domaine est le sens econome: engendrer toutes les graphies qu'une
    commune aurait pu deposer explose combinatoirement, alors que retirer ce que
    l'on reconnait a l'avant et a l'arriere d'un libelle, non.
    """
    seen, queue = set(), [label]
    while queue:
        value = queue.pop()
        if value in seen:
            continue
        seen.add(value)
        for prefix in PREFIXES:
            if value.startswith(prefix) and len(value) > len(prefix) + 2:
                queue.append(value[len(prefix) :])
        for suffix in SUFFIXES:
            if value.endswith(suffix) and len(value) > len(suffix) + 2:
                queue.append(value[: -len(suffix)])
        # Un nombre en fin de nom: le departement, ou un code postal.
        match = re.match(r"^(.*?)-?(\d{2,5})$", value)
        if match and len(match.group(1)) > 2:
            queue.append(match.group(1))
        # Le departement ecrit en toutes lettres, a l'une ou l'autre extremite. La
        # Corse est la raison pour laquelle ceci n'est pas laisse a la regle sur
        # les chiffres ci-dessus: "ajaccio2a" finit par une lettre, donc
        # `\d{2,5}` ne le voit jamais.
        if departement:
            code = departement.lower()
            for form in (code, f"-{code}"):
                if value.endswith(form) and len(value) > len(form) + 2:
                    queue.append(value[: -len(form)])
                if value.startswith(form) and len(value) > len(form) + 2:
                    queue.append(value[len(form) :])
    return {value.replace("-", "").strip("-") for value in seen if value}


def reconstructs(domain, name, departement):
    """Si les regles de suggestion auraient pu produire ``domain`` a partir de ``name``."""
    labels = domain.lower().split(".")
    if len(labels) < 2 or labels[-1] not in RECONSTRUCTIBLE_EXTENSIONS:
        return False
    stems = name_stems(name)
    if not stems:
        return False
    # Chaque libelle sauf l'extension, et les libelles accoles: une commune
    # hebergee sur "caden.questembert-communaute.fr" est reconnaissable a son
    # propre libelle.
    bodies = set(labels[:-1]) | {"".join(labels[:-1])}
    return any(_cores(body, departement) & stems for body in bodies)


def carries_name(domain, name):
    """RPNT 2.2: si le domaine porte le nom de la collectivite.

    "Un nom de domaine est dit generique lorsqu'il ne comporte pas le nom de la
    collectivite": c'est donc un test de sous-chaine, pas la reconstruction
    ci-dessus. Un domaine peut porter le nom sous une forme que les regles de
    suggestion ne produiraient jamais ("questembert-communaute.fr" pour
    Questembert).
    """
    flat = domain.lower().replace("-", "").replace(".", "")
    return any(stem and stem in flat for stem in name_stems(name))


# --- DILA --------------------------------------------------------------------


def coerce_dila_values(raw):
    """Normalise un champ DILA multivalue en liste de chaines ou de dictionnaires.

    L'export les stocke soit encodes en JSON (une liste, eventuellement de
    dictionnaires ``{"valeur": ...}``, comme ``site_internet``), soit en simple
    chaine separee par des ``;`` (comme ``adresse_courriel`` parfois). On accepte
    les deux plutot que de presumer d'une forme, pour qu'une difference de format
    ne puisse pas produire silencieusement des domaines aberrants. Une fiche mal
    formee n'apporte rien.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        if text[0] in "[{":
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError:
                return [text]
            return decoded if isinstance(decoded, list) else [decoded]
        return [part.strip() for part in text.split(";") if part.strip()]
    return [raw]


def domain_from_url(url):
    """Le nom d'hote nu d'une URL de site ('https://www.x.fr/a' -> 'x.fr')."""
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if "://" not in url:
        url = "http://" + url
    host = (urlparse(url).netloc or "").lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host or None


def domain_from_email(email):
    """La partie domaine d'une adresse ('a@x.fr' -> 'x.fr')."""
    if not email or not isinstance(email, str) or "@" not in email:
        return None
    return email.split("@", 1)[1].strip().lower() or None


def _values(raw, extract):
    out = set()
    for item in coerce_dila_values(raw):
        value = extract(item.get("valeur") if isinstance(item, dict) else item)
        if value:
            out.add(value)
    return out


def service_type(record):
    """Le ``type_service_local`` de la fiche ("mairie", "epci", "ccas", ...)."""
    pivot = record.get("pivot")
    if not pivot:
        return None
    try:
        pivot = json.loads(pivot) if isinstance(pivot, str) else pivot
    except json.JSONDecodeError:
        return None
    for item in pivot if isinstance(pivot, list) else [pivot]:
        kind = (item or {}).get("type_service_local")
        if kind:
            return kind
    return None


def organization_name(record):
    """Le nom propre de la collectivite ("Mairie - Acigne" -> "Acigne").

    Decoupage approximatif, et c'est voulu: il sert a proposer une graphie de plus
    a la reconstruction, et a nommer la collectivite dans le rapport. Il ne decide
    de rien. Le `nom` DILA n'a pas de structure garantie ("Centre Ouest (3CO) -
    Tsingoni (Mayotte)", "Mairie - Saint-Malo - annexe Saint-Servan"), donc tout
    ce qui compte passe par le code INSEE ou le SIREN, jamais par cette chaine.
    """
    nom = (record.get("nom") or "").strip()
    return nom.split(" - ", 1)[1].strip() if " - " in nom else nom


def siren_of(record):
    """Le SIREN de la collectivite, a defaut les 9 premiers chiffres du SIRET.

    C'est l'identite qui compte: plusieurs fiches d'une meme commune (la mairie et
    ses annexes) le partagent, et deux communes distinctes ne peuvent pas l'avoir
    en commun. Une fiche qui n'a ni l'un ni l'autre est sa propre entite plutot
    qu'une correspondance avec toutes les autres qui en manquent aussi.
    """
    siren = (record.get("siren") or "").strip()
    siret = (record.get("siret") or "").strip()
    return siren or siret[:9] or f"fiche:{record.get('id')}"


def departement_of(record):
    """Le departement ou se trouve la fiche, d'apres son code INSEE commune."""
    code = (record.get("code_insee_commune") or "").strip()
    if len(code) < 2:
        return None
    return code[:3] if code[:2] in ("97", "98") else code[:2]


class Fiche:
    """La part d'une fiche collectivite DILA que lisent les categories."""

    __slots__ = (
        "id",
        "siren",
        "name",
        "names",
        "departement",
        "kind",
        "sites",
        "mails",
    )

    def __init__(self, record, cog=None):
        self.id = record.get("id")
        self.siren = siren_of(record)
        self.name = organization_name(record)
        self.departement = departement_of(record)
        self.kind = service_type(record)
        self.sites = _values(record.get("site_internet"), domain_from_url)
        self.mails = _values(record.get("adresse_courriel"), domain_from_email)
        # Toutes les graphies sous lesquelles cette collectivite est connue. Le
        # nom DILA est celui que designe le commentaire de la liste, les noms du
        # COG sont ceux que l'INSEE donne a la commune; voir :func:`load_cog` pour
        # les raisons de leurs divergences frequentes.
        self.names = {self.name} if self.name else set()
        code = (record.get("code_insee_commune") or "").strip()
        if cog and code:
            self.names |= cog.get(code, set())

    @property
    def domains(self):
        return self.sites | self.mails

    def serves(self, domain):
        """RPNT 2.3: ce domaine est ici a la fois celui du site et de la messagerie."""
        return domain in self.sites and domain in self.mails


class Dila:
    """L'export DILA, indexe des deux facons dont les categories ont besoin."""

    def __init__(self, records, cog=None):
        self.fiches = {}
        self.declared_by = defaultdict(list)
        for record in records:
            if service_type(record) not in COLLECTIVITE_TYPES:
                continue
            fiche = Fiche(record, cog)
            if not fiche.id:
                continue
            self.fiches[fiche.id] = fiche
            for domain in fiche.domains:
                self.declared_by[domain].append(fiche)

    def sole_owner(self, domain):
        """La seule collectivite qui declare ce domaine, ou ``None`` s'il y en a
        plusieurs.

        Compte par SIREN et non par fiche ni par nom: plusieurs fiches d'une meme
        commune (la mairie et ses annexes) font une collectivite et non trois, et
        rien ne depend ici du decoupage approximatif de :func:`organization_name`.
        """
        fiches = self.declared_by.get(domain)
        if not fiches:
            return None
        sirens = {fiche.siren for fiche in fiches}
        return fiches[0] if len(sirens) == 1 else None


def load_cog(path, cache_dir):
    """Code INSEE -> tous les noms que le COG donne a cette commune.

    L'annuaire DILA est tenu par chaque commune elle-meme: il s'ecarte donc de la
    reference de trois facons, que ceci corrige.

    - il est perime. "Aix-lez-Orchies" s'appelle aujourd'hui Aix-en-Pevele,
      "Faverges" Faverges-Seythenex, et la fiche porte encore l'ancien nom;
    - il perd des caracteres. "Labastide-d Anjou" pour Labastide-d'Anjou,
      "Le Foeil" pour Le Fœil ecrit avec la ligature. Les domaines candidats ont
      ete engendres depuis la graphie de reference: la version abimee ne peut pas
      les reproduire;
    - il nomme une commune deleguee la ou le domaine appartient a la commune
      nouvelle. Le COG garde les deux sous un seul code, parce qu'une commune
      nouvelle herite du code INSEE de l'un de ses predecesseurs: le code 22209
      est a la fois ``COM Beaussais-sur-Mer`` et ``COMD Ploubalay``. Lire toutes
      les lignes d'un code donne donc le nouveau nom et les anciens ensemble,
      ce qui permet de reconnaitre un domaine depose sous l'une ou l'autre
      graphie.

    Une fiche d'EPCI porte le code INSEE de son siege: ceci donne donc aussi
    "Compiegne" pour l'agglomeration de Compiegne, dont le domaine porte ce nom.
    """
    if path:
        source = Path(path)
    else:
        source = cache_dir / Path(INSEE_COG_URL).name
        download(INSEE_COG_URL, source, "la reference des communes INSEE (~4 Mo)")

    names = defaultdict(set)
    with open(source, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            spellings = {row.get(key) for key in ("LIBELLE", "NCCENR")}
            spellings = {s for s in spellings if s}
            if not spellings:
                continue
            for code in (row.get("COM"), row.get("COMPARENT")):
                if code:
                    names[code] |= spellings
    return names


def load_dila(path, cache_dir, cog=None):
    """Charge l'export DILA depuis ``path``, le cache, ou le reseau."""
    source = Path(path) if path else cache_dir / f"dila-{date.today():%Y-%m-%d}.json"
    if not path:
        download(DILA_EXPORT_URL, source, "l'export de l'annuaire DILA (~8 Mo)")
    with open(source, encoding="utf-8") as handle:
        return Dila(json.load(handle), cog)


# --- lecture de la liste -----------------------------------------------------

UID_RE = re.compile(r'^\s*-\s+uid:\s*"?([^"\s]+)"?\s*$')
ENTRY_RE = re.compile(r"^\s*-\s+(\S+)\s*(?:#\s*(.*?))?\s*$")
FICHE_RE = re.compile(
    r"lannuaire\.service-public\.gouv\.fr/(?:[^/\s]+/)*"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
)


@dataclass(slots=True)
class Entry:
    """Une ligne ``- domaine # Source: <src> | <url fiche>`` de la liste."""

    domain: str
    source: str | None
    url: str | None
    uid: str
    line: int
    fiche: str | None = None

    def __post_init__(self):
        match = FICHE_RE.search(self.url or "")
        self.fiche = match.group(1) if match else None


def parse_source_comment(comment):
    """Decoupe ``"Source: <src> | <url>"`` en ``(source, url)``; l'un ou l'autre peut etre None."""
    if not comment:
        return None, None
    text = comment.strip()
    if text.lower().startswith("source:"):
        text = text.split(":", 1)[1].strip()
    parts = re.split(r"\s*\|\s*", text, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip() or None, parts[1].strip() or None
    return text or None, None


BLANK_RE = re.compile(r"^\s*$")
COMMENT_RE = re.compile(r"^\s*#")
DOC_MARKER_RE = re.compile(r"^(---|\.\.\.)\s*$")
ROOT_RE = re.compile(r"^oidc_providers:\s*$")
DOMAINS_KEY_RE = re.compile(r"^\s*allowed_attached_email_domains:\s*$")

MAX_PROBLEMS = 20


def scan_allowlist(text):
    """Etiquette chaque ligne du fichier: ``(kind, line, number, uid, match)``.

    Le seul endroit qui dit a quoi ressemble une liste d'autorisation. Le lecteur
    et l'ecrivain ci-dessous passent tous deux par ici: un relecteur verifie donc
    la grammaire une seule fois, et sait qu'aucun des deux ne peut s'en ecarter.

    ``kind`` vaut ``uid``, ``domain``, ``key`` (la ligne
    ``allowed_attached_email_domains:``), ``other`` (ligne vide, commentaire,
    marqueur de document, cle racine) ou ``unknown``. ``uid`` est le fournisseur
    auquel la ligne appartient, ``None`` avant le premier.

    Le risque d'un analyseur ecrit a la main est qu'un changement dans la sortie
    du generateur lui fasse sauter des lignes en silence, ce qui ferait de ce
    script un outil annoncant "rien a relire" sur un fichier plein de domaines.
    Rien ne passe au travers: une ligne qui ne correspond a aucune forme revient
    en ``unknown`` et est signalee. C'est une garantie plus forte qu'une
    comparaison avec une bibliotheque YAML, et elle ne coute aucune dependance.
    """
    uid = None
    for number, line in enumerate(text.splitlines(keepends=True), start=1):
        if (
            BLANK_RE.match(line)
            or COMMENT_RE.match(line)
            or DOC_MARKER_RE.match(line)
            or ROOT_RE.match(line)
        ):
            yield "other", line, number, uid, None
            continue
        if DOMAINS_KEY_RE.match(line):
            yield "key", line, number, uid, None
            continue
        match = UID_RE.match(line)
        if match:
            uid = match.group(1)
            yield "uid", line, number, uid, match
            continue
        match = ENTRY_RE.match(line)
        if match and ":" not in match.group(1):
            yield "domain", line, number, uid, match
            continue
        yield "unknown", line, number, uid, None


def parse_allowlist(text):
    """Lit une liste d'autorisation en ``(entries, uids, problems)``.

    Ligne a ligne plutot qu'avec un chargeur YAML, parce que les commentaires en
    fin de ligne ``# Source: ... | ...`` portent la fiche que chaque ligne invoque
    et qu'un chargeur les supprime.
    """
    entries, uids, problems = [], [], []

    def note(number, line, why):
        if len(problems) < MAX_PROBLEMS:
            problems.append(f"ligne {number}: {why}: {line.strip()[:60]!r}")

    for kind, line, number, uid, match in scan_allowlist(text):
        if kind == "uid":
            if uid not in uids:
                uids.append(uid)
        elif kind == "unknown":
            note(number, line, "forme inconnue de cet analyseur")
        elif kind == "domain":
            if uid is None:
                note(number, line, "un domaine avant tout uid de fournisseur")
                continue
            source, url = parse_source_comment(match.group(2))
            entries.append(Entry(match.group(1), source, url, uid, number))

    if not uids and text.strip():
        problems.append("aucun uid de fournisseur dans le fichier")
    return entries, uids, problems


# --- classification ----------------------------------------------------------


def parent_domains(domain):
    """Tous les suffixes de ``domain`` comptant encore au moins deux libelles."""
    labels = domain.split(".")
    return [".".join(labels[index:]) for index in range(1, len(labels) - 1)]


def denied_by(domain):
    """L'entree de la liste de refus que ce domaine active, lui ou un parent.

    Parcourir les parents est ce qui fait qu'une seule entree ``wixsite.com``
    couvre la page Wix de chaque commune, et qu'une seule entree ``gouv.fr``
    couvre tous les sous-domaines de l'Etat. :data:`ALLOWED` est teste en
    correspondance exacte, sans parcours: une exception ne couvre donc que le
    domaine de service qu'elle nomme, et rien d'autre dans sa zone.
    """
    if domain in ALLOWED:
        return None
    for name in [domain, *parent_domains(domain)]:
        if name in NOT_ALLOWED:
            return name
    return None


def is_internationalized(domain):
    """Si un domaine est internationalise, en unicode ou en punycode."""
    value = domain.strip().lower()
    if not value.isascii():
        return True
    return any(label.startswith("xn--") for label in value.split("."))


@dataclass(slots=True)
class Domain:
    """Un domaine de la liste, avec toutes les lignes qui l'accordent."""

    name: str
    uids: set = field(default_factory=set)
    fiches: list = field(default_factory=list)
    sources: set = field(default_factory=set)
    rows: int = 0
    category: str | None = None
    reason: str = ""
    detail: str = ""

    def add(self, entry, dila):
        self.uids.add(entry.uid)
        self.sources.add((entry.source or "").strip() or "none")
        self.rows += 1
        fiche = dila.fiches.get(entry.fiche) if entry.fiche else None
        if fiche is not None and fiche not in self.fiches:
            self.fiches.append(fiche)


def classify(domain, previous, dila):
    """Place un domaine dans la premiere categorie qui convient.

    Renvoie ``(category, reason, detail)``: la raison est assez grossiere pour
    etre denombree sur toute une categorie, le detail nomme la collectivite
    concernee.

    L'ordre est toute la conception. ``orange.fr`` est une reconstruction
    parfaite du nom de la commune d'Orange et ``vogue.fr`` de celui de Vogue: la
    liste de refus doit donc etre consultee avant tout le reste.
    """
    name = domain.name

    denied = denied_by(name)
    if denied:
        return "not_allowed", f"listed: {denied}", ""

    for fiche in domain.fiches:
        for spelling in fiche.names:
            if reconstructs(name, spelling, fiche.departement):
                return "reconstructible", "built from the collectivite name", fiche.name

    if name in previous:
        return "previous_allowlist", "already in the deployed allowlist", ""

    owner = dila.sole_owner(name)
    if owner is not None:
        extension = name.rsplit(".", 1)[-1]
        if extension not in SOVEREIGN_EXTENSIONS or is_internationalized(name):
            return "to_be_validated", "RPNT 1.2: extension is not sovereign", owner.name
        if not any(carries_name(name, spelling) for spelling in owner.names):
            return "to_be_validated", "RPNT 2.2: does not carry the name", owner.name
        if not owner.serves(name):
            return (
                "to_be_validated",
                "RPNT 2.3: site and mail domains differ",
                owner.name,
            )
        return "dila_ok", "declared by one collectivite", owner.name

    declaring = {f.siren for f in dila.declared_by.get(name, ())}
    if len(declaring) > 1:
        return (
            "to_be_validated",
            "shared: several collectivites declare it",
            f"{len(declaring)} collectivites",
        )
    return "to_be_validated", "no collectivite declares it", ""


# --- report ------------------------------------------------------------------

WIDTH = 96


def thousands(number):
    """``166949`` -> ``166 949``: lisible, et toujours en ASCII."""
    return f"{number:,}".replace(",", " ")


def rule(char="-"):
    return char * WIDTH


def render(meta, domains, problems):
    """Le rapport complet, en ASCII simple."""
    out = [rule("="), "  ProConnect allowlist review", rule("="), ""]
    for key, value in meta:
        out.append(f"  {key:<12}{value}")
    out.append("")

    buckets = defaultdict(list)
    for domain in domains:
        buckets[domain.category].append(domain)

    total_domains = len(domains)
    total_rows = sum(domain.rows for domain in domains)

    head = f"  +{'-' * 22}+{'-' * 11}+{'-' * 11}+{'-' * 9}+"
    out.append(head)
    out.append(f"  | {'category':<20} | {'domains':>9} | {'rows':>9} | {'share':>7} |")
    out.append(head)
    for name, _ in CATEGORIES:
        rows = sum(d.rows for d in buckets.get(name, ()))
        count = len(buckets.get(name, ()))
        share = (100.0 * count / total_domains) if total_domains else 0.0
        out.append(
            f"  | {name:<20} | {thousands(count):>9} | {thousands(rows):>9} "
            f"| {share:>6.1f}% |"
        )
    out.append(head)
    out.append(
        f"  | {'total':<20} | {thousands(total_domains):>9} "
        f"| {thousands(total_rows):>9} | {100.0 if total_domains else 0.0:>6.1f}% |"
    )
    out.append(head)
    out.append("")

    denied = len(buckets.get("not_allowed", ()))
    review = len(buckets.get("to_be_validated", ()))
    if denied:
        out.append(f"  RESULT: {thousands(denied)} domains are not allowed here and")
        out.append("          must be removed before this can be merged.")
    else:
        out.append("  RESULT: nothing on the deny list.")
    if review:
        out.append(f"          {thousands(review)} more need a human decision.")
    out.append("")

    if problems:
        out.append(rule())
        out.append("  PARSING")
        out.append(rule())
        out.extend(f"    {problem}" for problem in problems)
        out.append("")

    # Par categorie: combien, et pourquoi. Pas d'exemples de domaines: sur un
    # fichier de cent mille lignes, une poignee de lignes tirees au hasard
    # n'apprend rien, et --csv donne l'integralite a qui doit la traiter.
    for index, (name, blurb) in enumerate(CATEGORIES, start=1):
        rows = buckets.get(name, ())
        if not rows:
            continue
        out.append(rule())
        out.append(
            f"  {index}. {name}   {thousands(len(rows))} domains, "
            f"{thousands(sum(d.rows for d in rows))} rows"
        )
        out.append(rule())
        out.append(f"  {blurb}.")
        out.append("")
        tally = defaultdict(int)
        for domain in rows:
            tally[domain.reason] += 1
        for reason, count in sorted(tally.items(), key=lambda kv: (-kv[1], kv[0])):
            out.append(f"    {thousands(count):>9}  {reason}")
        out.append("")

    return "\n".join(out) + "\n"


# --- point d'entree ----------------------------------------------------------


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--base", required=True, help="La liste avant le changement.")
    parser.add_argument("--head", required=True, help="La liste apres le changement.")
    parser.add_argument(
        "--dila-json",
        help="Export DILA local (par defaut: telecharge et mis en cache).",
    )
    parser.add_argument(
        "--cog-csv",
        help="Fichier INSEE v_commune_AAAA.csv local (par defaut: telecharge).",
    )
    parser.add_argument(
        "--csv", help="Ecrit chaque domaine et sa categorie dans ce fichier."
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Ou sont conserves les telechargements.",
    )
    return parser.parse_args(argv)


def write_csv(path, domains, previous):
    """Chaque domaine et son classement, pour qui doit le traiter.

    La colonne ``deployed`` dit si le domaine figurait deja dans ``--base``.
    C'est ce qui permet a filter_proconnect_allowlist.py de ne jamais retirer une
    ligne en production sans avoir a relire le fichier de base ni a refaire le
    moindre raisonnement: tout ce qu'il doit savoir est ici.
    """
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("domain,category,deployed,rows,providers,sources,reason,detail\n")
        for domain in domains:
            handle.write(
                f"{domain.name},{domain.category},"
                f"{'yes' if domain.name in previous else 'no'},"
                f"{domain.rows},{len(domain.uids)},"
                f"{'+'.join(sorted(domain.sources))},"
                f'"{domain.reason}","{domain.detail}"\n'
            )


def main(argv=None):
    args = parse_args(argv)
    cache_dir = args.cache_dir or default_cache_dir()

    base_text = Path(args.base).read_text(encoding="utf-8")
    head_text = Path(args.head).read_text(encoding="utf-8")

    cog = load_cog(args.cog_csv, cache_dir)
    dila = load_dila(args.dila_json, cache_dir, cog)

    base_entries, _, base_problems = parse_allowlist(base_text)
    entries, uids, head_problems = parse_allowlist(head_text)
    previous = {entry.domain for entry in base_entries}
    problems = [f"{args.base}: {p}" for p in base_problems]
    problems += [f"{args.head}: {p}" for p in head_problems]

    domains = {}
    for entry in entries:
        domain = domains.get(entry.domain)
        if domain is None:
            domain = domains[entry.domain] = Domain(entry.domain)
        domain.add(entry, dila)

    for domain in domains.values():
        domain.category, domain.reason, domain.detail = classify(domain, previous, dila)

    meta = [
        ("base", args.base),
        ("head", args.head),
        ("providers", str(len(uids))),
        (
            "domains",
            f"{thousands(len(domains))} distinct, "
            f"{thousands(len(entries))} rows, "
            f"{thousands(len(previous))} in the previous version",
        ),
        (
            "DILA",
            f"{thousands(len(dila.fiches))} collectivite records, "
            f"{thousands(len(dila.declared_by))} domains",
        ),
        ("INSEE", f"{thousands(len(cog))} communes in the COG"),
    ]

    ordered = sorted(
        domains.values(), key=lambda d: (CATEGORY_ORDER[d.category], d.name)
    )

    sys.stdout.write(render(meta, ordered, problems))

    if args.csv:
        write_csv(args.csv, ordered, previous)

    denied = any(d.category == "not_allowed" for d in ordered)
    return 1 if (denied or problems) else 0


if __name__ == "__main__":
    sys.exit(main())
