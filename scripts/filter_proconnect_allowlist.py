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

Deux choses que le filtrage ne fera pas:

- il ne supprime jamais un fournisseur, meme s'il perd tous ses domaines. L'uid
  est la poignee d'api-partenaires sur un fournisseur, et le supprimer est un
  changement different de le vider; un tel fournisseur recoit un ``[]`` explicite,
  car une cle nue se relit comme null et leur schema attend un tableau;
- il ne supprime jamais un domaine deja deploye (colonne ``deployed`` du CSV),
  quelle que soit sa categorie. Sur la PR pour laquelle ceci a ete ecrit, 117 des
  159 domaines en production sont classes ``reconstructible``: un filtre naif
  aurait donc coupe du courrier qui fonctionne aujourd'hui.

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


def filter_allowlist(text, keep):
    """Reecrit une liste en ne gardant que les domaines de ``keep``."""
    # Premiere passe: quels fournisseurs ne gardent rien, et ont donc besoin de la
    # liste vide explicite sur leur ligne de cle. La seconde ecrit le fichier.
    survivors = defaultdict(int)
    for kind, _, _, uid, match in scan_allowlist(text):
        if kind == "uid":
            survivors.setdefault(uid, 0)
        elif kind == "domain" and uid is not None and match.group(1) in keep:
            survivors[uid] += 1

    out = []
    for kind, line, _, uid, match in scan_allowlist(text):
        if kind == "domain" and uid is not None and match.group(1) not in keep:
            continue
        if kind == "key" and uid is not None and not survivors[uid]:
            out.append(line.rstrip("\r\n").rstrip() + " []\n")
            continue
        out.append(line)
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
    seen = {
        match.group(1)
        for kind, _, _, _, match in scan_allowlist(text)
        if kind == "domain"
    }
    unclassified = seen - set(categories)
    if unclassified:
        raise SystemExit(
            f"{len(unclassified)} domaines de --head absents du CSV, "
            f"par exemple {sorted(unclassified)[:3]}. Le CSV ne vient pas de ce "
            "fichier: relancer le validateur dessus."
        )

    keep = {d for d, c in categories.items() if c not in drop} | deployed
    Path(args.out).write_text(filter_allowlist(text, keep), encoding="utf-8")

    kept = len(seen & keep)
    sys.stderr.write(
        f"{args.out}: {kept} domaines conserves, {len(seen) - kept} retires "
        f"({len(deployed & seen)} deployes conserves quoi qu'il arrive)\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
