"""Point d'entrée : `python -m etl update [--only wfs,apex_list,...] [--sans-couches]`."""
import argparse
import logging
import sys
import time

from . import (apex_fiche, apex_list, build, db, debits, degel, forestiers, geotech, gps, hauteurs, merge, net, odata, reseaux,
               sismique, villes, wfs, wikiponts)

SOURCES = {m.SOURCE: m for m in (wfs, apex_list, hauteurs, gps, odata.TabBord, odata.Limites, odata.HauteursDetail)}
log = logging.getLogger("etl")


def run_source(conn, s, mod) -> bool:
    started = db.now()
    t0 = time.monotonic()
    try:
        rows = mod.collect(s)
        if not rows:
            raise RuntimeError("aucune ligne extraite")
        suivis = getattr(mod, "TRACKED", None)          # champs de la source journalisés (ex. inspections)
        with conn:                                       # journal et remplacement validés ensemble (audit n° 3)
            if suivis:
                old = {r["num_dossr"]: dict(r) for r in conn.execute(f"SELECT * FROM {mod.TABLE}")}
                merge.journaliser(conn, old, {r["num_dossr"]: r for r in rows}, suivis, presence=False, commit=False)
            db.replace_table(conn, mod.TABLE, rows, commit=False)
    except Exception as e:  # une source en échec ne bloque pas les autres
        log.exception("%s : échec", mod.SOURCE)
        db.record_run(conn, mod.SOURCE, started, status="erreur", note=str(e)[:500])
        return False
    db.record_run(conn, mod.SOURCE, started, status="ok", rows=len(rows), sha256=db.fingerprint(rows))
    log.info("%s : %d lignes (%.0f s)", mod.SOURCE, len(rows), time.monotonic() - t0)
    return True


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m etl")
    sub = p.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("update", help="extrait les sources puis consolide la base")
    up.add_argument("--only", help=f"sources à extraire, parmi : {', '.join(SOURCES)}")
    up.add_argument("--no-fetch", action="store_true", help="consolider sans rien télécharger")
    up.add_argument("--sans-couches", action="store_true",
                    help="ne pas régénérer les couches de la carte (routes, rail, géotechnique, débits, villes, forestiers)")
    co = sub.add_parser("couches", help="régénère les couches de la carte (routes, rail, géotechnique, débits, villes, forestiers, dégel, Wikipédia)")
    co.add_argument("--no-fetch", action="store_true", help="relire data/raw/ sans télécharger")
    sub.add_parser("report", help="rapport de jointure entre sources")
    sub.add_parser("export", help="régénère data/structures.js, data/details.js et data/journal.js depuis la base")
    fi = sub.add_parser("fiches", help="(optionnel) crawl des fiches HTML APEX, ~1 req/s")
    fi.add_argument("--limit", type=int, help="nombre max de fiches")
    fi.add_argument("--refresh-days", type=int, help="retélécharger les fiches plus vieilles que N jours")
    args = p.parse_args(argv)

    for flux in (sys.stdout, sys.stderr):        # console Windows redirigée (cp1252) : « ∩ », « → » du rapport
        if hasattr(flux, "reconfigure"):
            flux.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    conn = db.connect()

    if args.cmd == "report":
        print(merge.report(conn))
        return 0
    if args.cmd == "export":
        _export(conn)
        return 0
    if args.cmd == "couches":
        return 0 if _couches(fetch=not args.no_fetch) else 1
    if args.cmd == "fiches":
        print(apex_fiche.crawl(conn, limit=args.limit, refresh_days=args.refresh_days))
        return 0

    ok = True
    if not args.no_fetch:
        names = args.only.split(",") if args.only else list(SOURCES)
        s = net.session()
        for name in names:
            ok &= run_source(conn, s, SOURCES[name])
    merge.build(conn)
    print(merge.report(conn))
    _export(conn)
    if not args.sans_couches and not args.only:
        ok &= _couches(fetch=not args.no_fetch)
    return 0 if ok else 1


def _couches(fetch: bool) -> bool:
    """Couches complémentaires chargées à la demande par le visualiseur (`data/couche-*.js`, `data/debits.js`).
    Les débits s'apparient aux structures : à lancer après la consolidation."""
    ok = True
    etapes = [("réseaux", lambda: reseaux.run(fetch=fetch)), ("géotechnique", lambda: geotech.run(fetch=fetch)),
              ("débits", lambda: debits.run(fetch=fetch)), ("villes", lambda: villes.run(fetch=fetch)),
              ("ponts forestiers", lambda: forestiers.run(fetch=fetch)),
              ("sismique", lambda: sismique.run(fetch=fetch)),
              ("zones de dégel", lambda: degel.run(fetch=fetch)),
              ("ponts remarquables (Wikipédia)", lambda: wikiponts.run(fetch=fetch))]
    for nom, f in etapes:
        try:
            res = f()
            for info in (res if isinstance(res, list) else [res]):
                log.info("couche %s : %s (%.1f Mo)", nom, info.get("path"), (info.get("bytes") or 0) / 1e6)
        except Exception:  # une couche en échec ne bloque pas les autres
            log.exception("couche %s : échec", nom)
            ok = False
    return ok


def _export(conn) -> None:
    for info in (build.export(conn), build.export_details(conn), build.export_journal(conn)):
        log.info("export : %d structures → %s (%.1f Mo)", info["rows"], info["path"].name, info["bytes"] / 1e6)


if __name__ == "__main__":
    sys.exit(main())
