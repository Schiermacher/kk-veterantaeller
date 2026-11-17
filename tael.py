#!/usr/bin/env python3
"""
Klassikerkanalen – veterantæller.

Henter Motorregistrets (DMR) ugentlige, offentlige XML-eksport fra
Motorstyrelsens FTP-server, læser den som en strøm (filen er for stor til
at pakke ud) og tæller køretøjer, der er mindst GRAENSE år gamle.

Resultat:
  data/latest.json    – seneste optælling (det WordPress-pluginnet henter)
  data/historik.json  – én linje pr. uge, så vi kan vise udvikling

Kør lokalt:
  python3 tael.py                 # hent nyeste eksport og tæl
  python3 tael.py --fil eksport.zip
  python3 tael.py --undersoeg 3   # vis feltnavne i de første 3 poster og stop
"""
import argparse
import datetime as dt
import ftplib
import json
import os
import re
import sys
import zipfile
from collections import Counter

FTP_HOST = "5.44.137.84"
FTP_DIR = "/ESStatistikListeModtag/"
GRAENSE = 35  # år

# Feltnavne i DMR-eksporten (lokale navne, uden namespace).
# Hvis Motorstyrelsen ændrer et navn, så kør --undersoeg og ret her.
FELTER = {
    "art": ["KoeretoejArtNavn"],
    "status": ["KoeretoejRegistreringStatus"],
    "foerste_reg": ["KoeretoejOplysningFoersteRegistreringDato"],
    "modelaar": ["KoeretoejOplysningModelAar"],
    "maerke": ["KoeretoejMaerkeTypeNavn"],
    "model": ["KoeretoejModelTypeNavn"],
    "anvendelse": ["KoeretoejAnvendelseNavn"],
    "farve": ["FarveTypeNavn"],
    "drivkraft": ["DrivkraftTypeNavn"],
}
MAERKE_ALIAS = {"Vw": "Volkswagen", "Mercedes": "Mercedes-Benz", "Mercedes Benz": "Mercedes-Benz"}
POST_TAG = "Statistik"


def lokal(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _forbind():
    ftp = ftplib.FTP(FTP_HOST, timeout=300)
    ftp.login()
    ftp.cwd(FTP_DIR)
    ftp.voidcmd("TYPE I")
    return ftp


def hent_nyeste(maal_mappe, forsoeg=40):
    """Henter nyeste eksport. Går forbindelsen i stå, genoptages overførslen,
    hvor den slap (FTP REST), i stedet for at starte forfra."""
    ftp = _forbind()
    navne = sorted(n for n in ftp.nlst() if n.lower().endswith(".zip"))
    if not navne:
        sys.exit("Ingen zip-filer fundet på FTP-serveren.")
    navn = navne[-1]
    try:
        total = ftp.size(navn)
    except ftplib.all_errors:
        total = None
    try:
        ftp.quit()
    except ftplib.all_errors:
        pass

    sti = os.path.join(maal_mappe, navn)
    if os.path.exists(sti):
        return sti
    del_sti = sti + ".del"
    gb = lambda b: f"{b / 1e9:.2f} GB"
    print(f"Henter {navn}" + (f" ({gb(total)})" if total else "") + " …", flush=True)

    for nr in range(1, forsoeg + 1):
        har = os.path.getsize(del_sti) if os.path.exists(del_sti) else 0
        if total and har >= total:
            break
        try:
            ftp = _forbind()
            with open(del_sti, "ab") as f:
                naeste = [har + 500_000_000]

                def skriv(blok):
                    f.write(blok)
                    if f.tell() >= naeste[0]:
                        print(f"  {gb(f.tell())} hentet", flush=True)
                        naeste[0] += 500_000_000

                ftp.retrbinary("RETR " + navn, skriv, blocksize=1024 * 1024, rest=har or None)
            try:
                ftp.quit()
            except ftplib.all_errors:
                pass
            if not total or os.path.getsize(del_sti) >= total:
                break
        except (OSError, EOFError) + tuple(ftplib.all_errors) as e:
            print(f"  Forbindelsen stoppede ved {gb(os.path.getsize(del_sti))} ({type(e).__name__}). Fortsætter – forsøg {nr + 1}.", flush=True)
            try:
                ftp.close()
            except Exception:
                pass
    else:
        sys.exit("Kunne ikke hente hele filen efter mange forsøg.")

    if total and os.path.getsize(del_sti) != total:
        sys.exit(f"Filen har forkert størrelse: {os.path.getsize(del_sti)} af {total} bytes.")
    os.replace(del_sti, sti)
    print(f"Hentet: {gb(os.path.getsize(sti))}", flush=True)
    return sti


def aar_af(post):
    for kilde in ("foerste_reg", "modelaar"):
        v = post.get(kilde) or ""
        m = re.match(r"(\d{4})", v)
        if m:
            return int(m.group(1)), kilde
    return None, None


def aarti(aar):
    return f"{aar // 10 * 10}'erne"


def tael(zip_sti, undersoeg=0):
    from lxml import etree

    with zipfile.ZipFile(zip_sti) as z:
        xml_navn = max(z.infolist(), key=lambda i: i.file_size).filename
        print(f"Læser {xml_navn} …", flush=True)
        with z.open(xml_navn) as strøm:
            return _tael_strøm(strøm, undersoeg, etree)


def _tael_strøm(strøm, undersoeg, etree):
    i_aar = dt.date.today().year
    skaering = i_aar - GRAENSE  # fx 2026 - 35 = 1991: årgang 1991 og ældre tæller
    opslag = {navn: noegle for noegle, navne in FELTER.items() for navn in navne}

    total_poster = 0
    vet_status = Counter()
    vet_art = Counter()
    vet_aarti = Counter()
    vet_aargang = Counter()
    vet_maerke = Counter()
    vet_model = Counter()
    vet_anvendelse = Counter()
    aarkilde = Counter()
    naeste_aargang = Counter()  # dem, der bliver veteraner 1. januar
    vet_farve = Counter()
    vet_drivkraft = Counter()
    aeldste = []  # (dato, mærke, model)
    feltnavne = Counter()

    for _, elem in etree.iterparse(strøm, events=("end",), tag="{*}" + POST_TAG, huge_tree=True):
        total_poster += 1
        post = {}
        if undersoeg:
            print("--- post", total_poster)
        for d in elem.iter():
            n = lokal(d.tag)
            if total_poster <= 200:
                feltnavne[n] += 1
            if undersoeg and d.text and d.text.strip():
                print(f"  {n} = {d.text.strip()[:60]}")
            k = opslag.get(n)
            if k and k not in post and d.text:
                post[k] = d.text.strip()
        elem.clear()
        while elem.getprevious() is not None:
            del elem.getparent()[0]
        if undersoeg:
            if total_poster >= undersoeg:
                return None
            continue

        aar, kilde = aar_af(post)
        if aar is None:
            continue
        status = post.get("status", "Ukendt")
        art = post.get("art", "Ukendt")
        if aar == skaering + 1 and art == "Personbil" and status == "Registreret":
            naeste_aargang[aar] += 1
        if aar > skaering or aar < 1880:
            continue
        vet_status[(art, status)] += 1
        if status != "Registreret":
            continue
        vet_art[art] += 1
        if art != "Personbil":
            continue
        aarkilde[kilde] += 1
        vet_aarti[aarti(aar)] += 1
        vet_aargang[str(aar)] += 1
        maerke = (post.get("maerke") or "Ukendt").strip()
        if len(maerke) > 3:  # MG og BMW skal blive store bogstaver
            maerke = maerke.title()
        maerke = MAERKE_ALIAS.get(maerke, maerke)
        model = (post.get("model") or "").strip().strip("-").strip()
        vet_maerke[maerke] += 1
        if model:
            vet_model[f"{maerke} {model}"] += 1
        vet_anvendelse[post.get("anvendelse", "Ukendt")] += 1
        vet_farve[post.get("farve", "Ukendt")] += 1
        vet_drivkraft[post.get("drivkraft", "Ukendt")] += 1
        if aar <= 1915:
            aeldste.append(((post.get("foerste_reg") or str(aar))[:10], maerke, model))

        if total_poster % 1_000_000 == 0:
            print(f"  {total_poster:,} poster læst".replace(",", "."), flush=True)

    if total_poster == 0:
        sys.exit(f"Ingen <{POST_TAG}>-poster fundet. Kør med --undersoeg 3 og ret feltnavnene.")
    if not vet_art:
        sys.exit("Ingen veteraner fundet – feltnavnene passer sandsynligvis ikke. Kør --undersoeg 3.")

    personbil_status = {s: n for (a, s), n in vet_status.items() if a == "Personbil"}
    return {
        "graense_aar": GRAENSE,
        "aargang_til_og_med": skaering,
        "poster_i_eksport": total_poster,
        "veteranbiler_registreret": vet_art.get("Personbil", 0),
        "personbiler_status": dict(sorted(personbil_status.items(), key=lambda x: -x[1])),
        "alle_koeretoejsarter_registreret": dict(vet_art.most_common()),
        "pr_aarti": dict(sorted(vet_aarti.items())),
        "pr_aargang": dict(sorted(vet_aargang.items())),
        "top_maerker": vet_maerke.most_common(25),
        "top_modeller": vet_model.most_common(25),
        "alle_maerker": dict(vet_maerke.most_common()),
        "modeller_min_10": {k: v for k, v in vet_model.most_common() if v >= 10},
        "farver": dict(vet_farve.most_common()),
        "drivkraft": dict(vet_drivkraft.most_common()),
        "aeldste": [{"dato": d, "maerke": m, "model": mo} for d, m, mo in sorted(aeldste)[:30]],
        "feltnavne_eksempel": sorted(feltnavne),
        "anvendelse": dict(vet_anvendelse.most_common(10)),
        "aarstal_kilde": dict(aarkilde),
        "bliver_veteran_1_januar": sum(naeste_aargang.values()),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fil", help="brug en allerede hentet zip-fil")
    ap.add_argument("--mappe", default="eksport")
    ap.add_argument("--data", default="data")
    ap.add_argument("--undersoeg", type=int, default=0)
    a = ap.parse_args()

    os.makedirs(a.mappe, exist_ok=True)
    os.makedirs(a.data, exist_ok=True)
    zip_sti = a.fil or hent_nyeste(a.mappe)
    filnavn = os.path.basename(zip_sti)

    latest_sti = os.path.join(a.data, "latest.json")
    if not a.undersoeg and os.path.exists(latest_sti):
        with open(latest_sti, encoding="utf-8") as f:
            gammel = json.load(f)
            if gammel.get("fil") == filnavn and "farver" in gammel:
                print("Denne eksport er allerede talt. Intet at gøre.")
                return

    res = tael(zip_sti, a.undersoeg)
    if res is None:
        return

    m = re.search(r"(20\d{6})", filnavn)
    eksportdato = (
        dt.datetime.strptime(m.group(1), "%Y%m%d").date().isoformat() if m else dt.date.today().isoformat()
    )

    hist_sti = os.path.join(a.data, "historik.json")
    historik = []
    if os.path.exists(hist_sti):
        with open(hist_sti, encoding="utf-8") as f:
            historik = json.load(f)
    forrige = historik[-1]["veteranbiler_registreret"] if historik else None
    historik = [h for h in historik if h["dato"] != eksportdato]
    historik.append(
        {
            "dato": eksportdato,
            "veteranbiler_registreret": res["veteranbiler_registreret"],
            "personbiler_status": res["personbiler_status"],
        }
    )

    ud = {
        "kilde": "Motorregistret (DMR), Motorstyrelsens ugentlige eksport",
        "fil": filnavn,
        "eksportdato": eksportdato,
        "opgjort": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "aendring_siden_sidst": (res["veteranbiler_registreret"] - forrige) if forrige is not None else None,
        **res,
    }
    with open(latest_sti, "w", encoding="utf-8") as f:
        json.dump(ud, f, ensure_ascii=False, indent=1)
    with open(hist_sti, "w", encoding="utf-8") as f:
        json.dump(historik, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: ud[k] for k in ("eksportdato", "veteranbiler_registreret", "aendring_siden_sidst")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
