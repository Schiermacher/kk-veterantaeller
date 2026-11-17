# Klassikerkanalen – veterantæller

Tæller hver uge veteranbiler i Motorregistrets offentlige eksport og gemmer resultatet i `data/latest.json`.
WordPress-pluginnet **Klassikerkanalen Marked** henter den fil og viser tallet øverst på sitet.

## Opsætning (én gang)

1. Opret en gratis konto på github.com.
2. Klik **+** → **New repository**. Navn: `kk-veterantaeller`. Vælg **Public**. Klik **Create repository**.
3. Klik **uploading an existing file**, træk hele indholdet af denne mappe ind (også mappen `.github`) og klik **Commit changes**.
   Mappen `.github` er skjult på Mac: tryk Cmd+Shift+punktum i Finder for at se den.
4. Gå til fanen **Actions** → **Veterantælling** → **Run workflow**. Første kørsel tager 1–3 timer.
5. Når den er grøn, ligger tallet her:
   `https://raw.githubusercontent.com/DIT-BRUGERNAVN/kk-veterantaeller/main/data/latest.json`
   Den adresse sættes ind i WordPress under **Markedstal → Datafil**.

Herefter kører tællingen selv mandag og torsdag.

## Definition

En veteranbil er her en **personbil med status "Registreret"**, hvis modelår (eller første registreringsår, hvis modelår mangler) er mindst 35 år før indeværende år.
Grænsen står i `tael.py` som `GRAENSE = 35`.

## Hvis tællingen fejler

Motorstyrelsen kan ændre feltnavne. Kør `python3 tael.py --undersoeg 3` for at se navnene og ret listen `FELTER` i `tael.py`.
Pluginnet beholder det gamle tal, hvis en ny fil ser forkert ud.
