# Discord Bot reorganizat

Botul original a fost separat în module fără schimbarea intenționată a comenzilor sau a structurii bazei de date.

## Structură
- `main.py` – pornire, sincronizare și error handling global
- `core/bot.py` – clientul Discord
- `core/database.py` – SQLite, setări și migrări
- `systems/patrol/module.py` – sistem patrule
- `systems/attendance/module.py` – sistem pontaj/prezență
- `systems/donations/module.py` – sistem donații

## Railway
Păstrează variabila `DISCORD_TOKEN` în Railway Variables. Baza de date continuă să folosească `/data/pontaj.db` când volumul `/data` există.

Start command: `python main.py` (este inclus și `Procfile`).

## Important
Înainte de înlocuirea proiectului actual, fă un backup al repository-ului și al volumului/bazei de date Railway.
