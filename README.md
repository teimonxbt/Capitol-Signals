# Capitol Signals

Privates Dashboard für offengelegte Aktien-Trades von US-Kongressabgeordneten (STOCK Act).

## Starten
Terminal öffnen und ausführen:

    bash ~/Documents/CapitolSignals/start.sh

Beim ersten Mal dauert es ein paar Minuten (ca. 3.000 Ticker Kurshistorie). Danach lädt jeder Start nur die neuen Tage.
Nur das Dashboard öffnen, ohne Update: `bash start.sh --nur-web`

## Was passiert
- `update.py` lädt alle Trades (Senat + Repräsentantenhaus, ab 2020) aus dem offenen Datensatz
  kadoa-org/congress-trading-monitor (baut täglich aus den offiziellen Quellen House Clerk und Senate eFD).
- Kurse kommen kostenlos von Yahoo Finance (yfinance), dividendenbereinigt, Benchmark SPY.
- Jeder Trade wird **ab Veröffentlichung** bewertet: Einstieg = Schlusskurs des ersten Handelstags nach dem Meldedatum.
  „Ab Trade-Datum“ wird nur zum Vergleich gezeigt.
- Ergebnis landet in `web/data/`, das Dashboard (`web/index.html`) liest nur diese Dateien.

## Ansichten
- **Hot Stocks**: was in den letzten 14–90 Tagen gekauft wurde, mit Vorlauf (was du verpasst hast) und Kurs seit Meldung.
- **Abgeordnete**: Rangliste nach Winrate, Rendite, Outperformance vs. S&P, Anzahl Trades; Filter nach Haltedauer, Kammer, Partei, Zeitraum, Betrag.
- **Abgeordneter**: alle Trades, Chart mit Markern (Einstieg nach Meldung + tatsächliches Trade-Datum).
- **Backtest**: Kapitalkurve vs. SPY, rollierende Auswahl ohne Rückblick-Vorteil, Vergleich mit Einstieg am Trade-Datum.

## Online stellen (automatisch, kostenlos über GitHub)
1. Auf github.com ein kostenloses Konto anlegen, dann **New repository** → Name `capitol-signals` → **Public** → Create.
2. **Add file → Upload files** und aus diesem Ordner hineinziehen: `update.py`, `requirements.txt`, `README.md`, den Ordner `web` (ohne `web/data`) und den Ordner `cache` (nur `seed.pkl.gz`). → Commit changes.
   Dann **Add file → Create new file**, als Namen `.github/workflows/update.yml` eintippen und den Inhalt von `github-workflow.yml` hineinkopieren. → Commit changes.
3. Im Repo: **Settings → Pages → Source: GitHub Actions**.
4. **Actions → „Daten aktualisieren und veröffentlichen“ → Run workflow.** Nach ca. 15–30 Minuten ist die Seite unter `https://DEINNAME.github.io/capitol-signals/` online.
Danach aktualisiert sie sich jeden Werktag nach US-Börsenschluss von selbst.
