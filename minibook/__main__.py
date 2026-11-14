"""Command line runner (SYS-02) and live cover check (TST-04).

    python -m minibook build --csv export.csv --year 2026 --out wraps.pdf
    python -m minibook check-covers --csv export.csv --limit 5
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import covers, csvimport as c, imaging, net, pdfexport, settings as S


def _load_books(args) -> tuple[list[c.Book], list[c.Book]]:
    books = c.parse_library_csv(Path(args.csv))
    statuses = set(args.status.split(",")) if args.status else None
    dated, undated = c.filter_books(books, statuses=statuses, year=args.year)
    c.apply_default_selection(dated, undated)
    return dated, undated


def _service(args) -> covers.CoverService:
    key = getattr(args, "google_key", None) or S.load_settings().google_api_key or None
    return covers.CoverService(covers.RequestsHttp(), S.cache_dir() / "covers", google_api_key=key)


def cmd_build(args) -> int:
    settings = S.load_settings()
    problems = settings.validate()
    if problems:
        print("Settings problem:", "; ".join(problems), file=sys.stderr)
        return 2
    dated, undated = _load_books(args)
    chosen = [b for b in dated if b.selected]
    if args.include_undated:
        chosen += undated
    chosen = c.sort_books(chosen, settings.sort)
    if not chosen:
        print("No books matched. Try a different --year or --status.", file=sys.stderr)
        return 1
    dups = c.flag_duplicates(chosen)
    if dups:
        print("Note: duplicate titles selected:", ", ".join(dups))
    svc = None if args.offline else _service(args)
    prefs = S.load_book_prefs()
    nets = []
    for i, b in enumerate(chosen, 1):
        src = None
        p = prefs.get(b.id, S.BookPrefs())
        try:
            if p.custom_path and not p.cover_url:
                src = covers.load_local_image(p.custom_path)
            elif svc:
                res = svc.find_covers(b)
                pick = next((x for x in res.candidates if x.url == p.cover_url), None) \
                    or next((x for x in res.candidates if x.tier <= covers.TIER_MAYBE), None)
                if pick:
                    src = svc.load_image(pick)
                for e in res.errors:
                    print(f"  [{b.title}] {e}")
        except covers.CoverError as e:
            print(f"  [{b.title}] cover problem: {e}")
        r = net.build_net(b, src, settings, p.zoom, p.pan_x, p.pan_y, imaging.from_hex(p.spine_color)
                           if src is not None and imaging.same_picture(p.spine_cover, imaging.fingerprint(src)) else None)
        flag = f"  ! {'; '.join(r.warnings)}" if r.warnings else ""
        print(f"{i:>3}/{len(chosen)} {b.title}{flag}")
        nets.append(r)
    grid = pdfexport.export_pdf(nets, settings, args.out)
    print(f"\nWrote {args.out}: {len(nets)} books, {grid.per_page} per page.")
    return 0


def cmd_check_covers(args) -> int:
    """Run on your own machine to confirm Open Library / Google Books are reachable and useful."""
    dated, _ = _load_books(args)
    svc = _service(args)
    ok = 0
    for b in dated[: args.limit]:
        res = svc.find_covers(b, deep=args.more)
        print(f"\n{b.title} [{b.format or '?'}]")
        grades = {covers.TIER_GOOD: "good", covers.TIER_MAYBE: "maybe", covers.TIER_UNLIKELY: "UNLIKELY"}
        for cand in res.candidates:
            why = f" ({cand.why})" if cand.why else ""
            print(f"   {grades[cand.tier]:<8} {cand.source:<13} {cand.size_text:<14} {cand.title or cand.label}{why} {cand.note}")
        for e in res.errors:
            print(f"   ! {e}")
        ok += bool(res.candidates)
    print(f"\n{ok}/{min(args.limit, len(dated))} books had at least one cover.")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="minibook")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("build", cmd_build), ("check-covers", cmd_check_covers)):
        sp = sub.add_parser(name)
        sp.add_argument("--csv", required=True)
        sp.add_argument("--year", type=int)
        sp.add_argument("--status", help="comma list, default 'read'")
        sp.add_argument("--google-key")
        sp.set_defaults(fn=fn)
        if name == "build":
            sp.add_argument("--out", default="minibook_wraps.pdf")
            sp.add_argument("--offline", action="store_true", help="skip cover lookup; use placeholders")
            sp.add_argument("--include-undated", action="store_true")
        else:
            sp.add_argument("--limit", type=int, default=5)
            sp.add_argument("--more", action="store_true", help="also look for other editions (what the picker does)")
    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except c.CsvFormatError as e:
        print(e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
