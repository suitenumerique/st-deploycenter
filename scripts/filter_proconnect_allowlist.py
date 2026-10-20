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
  api-partenaires refuse de rattacher un domaine absent de la liste deployee
  (``attached_email_domain_not_allowed``): le retirer le rendrait impossible a
  rattacher de nouveau apres un detachement. (L'ancien PATCH, lui, verifiait
  TOUS les domaines de la liste: un seul domaine routed absent bloquait tout le
  fournisseur.)
  La regle vaut par couple (fournisseur, domaine): un domaine routed chez l'un
  ne sauve pas la meme ligne chez un autre.

Une exception, qui joue dans l'autre sens: les domaines de proconnect_hacked_sites.tsv
(sites detectes comme pirates) sont retires quelle que soit leur categorie, et meme
s'ils sont deja deployes ou routed. C'est actif par defaut, chaque retrait est
journalise (avec son etat deploye/routed, pour qu'on puisse aussi les detacher
chez nous), et ``--no-hacked`` le desactive.

Toute ligne conservee est recopiee octet pour octet: le diff ne contient que des
suppressions, jamais une reecriture.
"""

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

from validate_proconnect_allowlist import scan_allowlist

DEFAULT_HACKED = Path(__file__).with_name("proconnect_hacked_sites.tsv")
_HOST_RE = re.compile(
    r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+"
)


def mail_domain(host):
    """Le domaine de messagerie d'un site: le meme, sans "www." devant."""
    return host[4:] if host.startswith("www.") else host


def load_hacked(path):
    """Le TSV des sites pirates -> ``{domaine: [raisons]}``."""
    hacked = defaultdict(list)
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            line = line.rstrip("\r\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            host, tab, reason = line.partition("\t")
            host, reason = host.strip().lower(), reason.strip()
            if not tab or not reason or not _HOST_RE.fullmatch(host):
                raise SystemExit(
                    f"{path}:{number}: attendu '<site><TAB><raison>', recu {line!r}"
                )
            reasons = hacked[mail_domain(host)]
            if reason not in reasons:
                reasons.append(reason)
    return dict(hacked)


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


def taken_elsewhere(text, contested):
    """Les couples ``(fournisseur, domaine)`` non routed d'un domaine ``contested``
    que l'on route deja chez un autre fournisseur.

    Un domaine contested est un domaine dont la categorie est retiree (partage entre
    plusieurs collectivites, par exemple). Chez le fournisseur qui le route, il reste.
    Ailleurs il n'a pas sa place: il y serait refuse comme deja rattache, et le
    garder parce qu'il est deploye chez l'autre ne regle rien.
    """
    routed = routed_entries(text)
    routed_uids = defaultdict(set)
    for uid, domain in routed:
        routed_uids[domain].add(uid)
    return {
        (row.uid, row.domain)
        for row in scan_allowlist(text)
        if row.kind == "domain"
        and row.uid is not None
        and row.domain in contested
        and (row.uid, row.domain) not in routed
        and routed_uids.get(row.domain, set()) - {row.uid}
    }


def filter_allowlist(text, keep, hacked=frozenset(), contested=frozenset()):
    """Reecrit une liste en ne gardant que les domaines de ``keep``.

    Les entrees ``source: routed`` sont gardees quoi qu'il arrive, sauf celles des
    domaines de ``hacked``, qui partent toujours (avec ou sans "www."). Les entrees
    non routed d'un domaine de ``contested`` routed chez un autre fournisseur partent
    aussi, meme deployees (voir :func:`taken_elsewhere`).
    """
    routed = routed_entries(text)
    elsewhere = taken_elsewhere(text, contested)

    def kept(row):
        if mail_domain(row.domain) in hacked or (row.uid, row.domain) in elsewhere:
            return False
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


def hacked_log(text, hacked, deployed):
    """Les lignes de journal des retraits "sites pirates", une par domaine."""
    routed = routed_entries(text)
    entries = defaultdict(set)
    for row in scan_allowlist(text):
        if row.kind == "domain" and row.uid is not None:
            entries[mail_domain(row.domain)].add((row.uid, row.domain))
    lines = []
    for domain in sorted(hacked):
        reasons = ", ".join(hacked[domain])
        found = entries.get(domain)
        if not found:
            lines.append(f"  {domain}: absent de la liste ({reasons})")
            continue
        state = [
            "deploye" if any(d in deployed for _, d in found) else "non deploye",
            "routed" if found & routed else "non routed",
        ]
        lines.append(
            f"  {domain}: {len(found)} entree(s) retiree(s), {', '.join(state)} "
            f"({reasons})"
        )
    return lines


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
    parser.add_argument(
        "--hacked",
        default=str(DEFAULT_HACKED),
        help="Le TSV des sites pirates a retirer (defaut: %(default)s).",
    )
    parser.add_argument(
        "--no-hacked",
        action="store_true",
        help="Ne pas retirer les sites pirates.",
    )
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

    hacked = {} if args.no_hacked else load_hacked(args.hacked)
    keep = {d for d, c in categories.items() if c not in drop} | deployed
    contested = frozenset(d for d, c in categories.items() if c in drop)
    elsewhere = taken_elsewhere(text, contested)
    result = filter_allowlist(text, keep, frozenset(hacked), contested)
    Path(args.out).write_text(result, encoding="utf-8")

    kept = len({row.domain for row in scan_allowlist(result) if row.kind == "domain"})
    # Hors sites pirates, qui partent meme deployes ou routed.
    spared = {mail_domain(d) for d in seen} - set(hacked)
    routed = len(
        {d for _, d in routed_entries(text) if mail_domain(d) not in hacked} - keep
    )
    sys.stderr.write(
        f"{args.out}: {kept} domaines conserves, {len(seen) - kept} retires "
        f"({len({d for d in deployed & seen if mail_domain(d) in spared})} deployes "
        f"conserves quoi qu'il arrive, {routed} routed conserves en plus)\n"
    )
    sys.stderr.write(
        f"Domaines deja routes chez un autre fournisseur, retires ici: "
        f"{len(elsewhere)} entree(s)\n"
    )
    for uid, domain in sorted(elsewhere, key=lambda pair: (pair[1], pair[0])):
        sys.stderr.write(f"  {domain} ({uid})\n")
    if args.no_hacked:
        sys.stderr.write("Sites pirates: filtre desactive (--no-hacked).\n")
    else:
        sys.stderr.write(
            f"Sites pirates retires ({len(hacked)} dans {args.hacked}):\n"
        )
        sys.stderr.write("\n".join(hacked_log(text, hacked, deployed)) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
