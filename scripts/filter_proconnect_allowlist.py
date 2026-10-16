#!/usr/bin/env python3
"""
Retire des categories entieres d'une liste d'autorisation api-partenaires.

Sert a ramener une grosse PR a ce qu'un relecteur acceptera sans discuter ::

    python validate_proconnect_allowlist.py --base b.yaml --head h.yaml --csv c.csv
    python filter_proconnect_allowlist.py --head h.yaml --categories c.csv \\
        --drop not_allowed,to_be_validated --out submit.yaml

Ce script ne decide rien. Tout ce qu'il sait vient du CSV produit par
validate_proconnect_allowlist.py: la categorie de chaque domaine, et s'il est
deja deploye. Il ne relit ni l'annuaire DILA, ni le COG, ni le fichier de base,
et ne refait aucun classement. C'est voulu: le fichier a auditer est le
validateur, celui-ci ne fait que decouper.

La grammaire du fichier YAML n'est pas non plus reecrite ici: ``scan_allowlist``
est importe du validateur, pour qu'il n'existe qu'une seule definition de ce a
quoi ressemble une liste.

Trois choses que le filtrage ne fera pas:

- il ne supprime jamais un fournisseur, meme s'il perd tous ses domaines. L'uid
  est la poignee d'api-partenaires sur un fournisseur, et le supprimer est un
  changement different de le vider; un tel fournisseur recoit un ``[]`` explicite,
  car une cle nue se relit comme null et leur schema attend un tableau;
- il ne supprime jamais un domaine deja deploye (colonne ``deployed`` du CSV),
  quelle que soit sa categorie. Sur la PR pour laquelle ceci a ete ecrit, 117 des
  159 domaines en production sont classes ``reconstructible``: un filtre naif
  aurait donc coupe du courrier qui fonctionne aujourd'hui;
- il ne supprime jamais une entree ``source: routed`` de ``--head``, quelle que
  soit sa categorie: ce domaine est deja rattache au fournisseur chez nous, et
  api-partenaires verifie TOUS les domaines d'un PATCH contre la liste deployee,
  pas seulement les nouveaux. Un domaine routed absent de la liste fait donc
  refuser chaque PATCH de ce fournisseur (``attached_email_domain_not_allowed``).
  La regle vaut par couple (fournisseur, domaine): un domaine routed chez l'un
  ne sauve pas la meme ligne chez un autre.

Toute ligne conservee est recopiee octet pour octet: le diff ne contient que des
suppressions, jamais une reecriture.
"""

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

from validate_proconnect_allowlist import scan_allowlist


def load_categories(path):
    """Le CSV du validateur -> ``(categorie par domaine, domaines deployes)``."""
    categories, deployed = {}, set()
    with open(path, encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = {"domain", "category", "deployed"} - set(reader.fieldnames or ())
        if missing:
            raise SystemExit(
                f"{path}: colonnes manquantes {sorted(missing)}. "
                "Produire le fichier avec validate_proconnect_allowlist.py --csv."
            )
        for row in reader:
            categories[row["domain"]] = row["category"]
            if row["deployed"] == "yes":
                deployed.add(row["domain"])
    if not categories:
        raise SystemExit(f"{path}: aucun domaine.")
    return categories, deployed


def routed_entries(text):
    """Les couples ``(fournisseur, domaine)`` dont l'entree porte ``source: routed``."""
    return {
        (row.uid, row.domain)
        for row in scan_allowlist(text)
        if row.kind == "field"
        and row.uid is not None
        and row.match.group(1) == "source"
        and row.match.group(2) == "routed"
    }


def filter_allowlist(text, keep):
    """Reecrit une liste en ne gardant que les domaines de ``keep``.

    Les entrees ``source: routed`` sont gardees quoi qu'il arrive.
    """
    routed = routed_entries(text)

    def kept(row):
        return row.domain in keep or (row.uid, row.domain) in routed

    # Premiere passe: quels fournisseurs ne gardent rien, et ont donc besoin de la
    # liste vide explicite sur leur ligne de cle. La seconde ecrit le fichier.
    survivors = defaultdict(int)
    for row in scan_allowlist(text):
        if row.kind == "uid":
            survivors.setdefault(row.uid, 0)
        elif row.kind == "domain" and row.uid is not None and kept(row):
            survivors[row.uid] += 1

    out = []
    for row in scan_allowlist(text):
        # Une entree s'etend sur plusieurs lignes (le domaine, puis ses champs):
        # elles partent toutes ensemble.
        if row.kind in ("domain", "field") and row.uid is not None:
            if not kept(row):
                continue
        if row.kind == "key" and row.uid is not None and not survivors[row.uid]:
            out.append(row.text.rstrip("\r\n").rstrip() + " []\n")
            continue
        out.append(row.text)
    return "".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--head", required=True, help="La liste a filtrer.")
    parser.add_argument(
        "--categories", required=True, help="Le CSV produit par le validateur."
    )
    parser.add_argument(
        "--drop",
        required=True,
        help="Categories a retirer, separees par des virgules, par exemple "
        "'not_allowed,to_be_validated'.",
    )
    parser.add_argument("--out", required=True, help="Ou ecrire le resultat.")
    args = parser.parse_args(argv)

    categories, deployed = load_categories(args.categories)
    drop = {part.strip() for part in args.drop.split(",") if part.strip()}
    unknown = drop - set(categories.values())
    if unknown:
        raise SystemExit(
            f"categorie absente du CSV: {sorted(unknown)}; "
            f"il contient {sorted(set(categories.values()))}"
        )

    text = Path(args.head).read_text(encoding="utf-8")
    seen = {row.domain for row in scan_allowlist(text) if row.kind == "domain"}
    unclassified = seen - set(categories)
    if unclassified:
        raise SystemExit(
            f"{len(unclassified)} domaines de --head absents du CSV, "
            f"par exemple {sorted(unclassified)[:3]}. Le CSV ne vient pas de ce "
            "fichier: relancer le validateur dessus."
        )

    keep = {d for d, c in categories.items() if c not in drop} | deployed
    result = filter_allowlist(text, keep)
    Path(args.out).write_text(result, encoding="utf-8")

    kept = len({row.domain for row in scan_allowlist(result) if row.kind == "domain"})
    routed = len({domain for _, domain in routed_entries(text)} - keep)
    sys.stderr.write(
        f"{args.out}: {kept} domaines conserves, {len(seen) - kept} retires "
        f"({len(deployed & seen)} deployes conserves quoi qu'il arrive, "
        f"{routed} routed conserves en plus)\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
