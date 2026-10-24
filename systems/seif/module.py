"""Seif Dominicans - inventory for RP, restricted to leadership and one channel."""
import asyncio
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from discord import app_commands

from core.bot import bot

CHANNEL_ID = 1533571511783260170
LEADERS = {1554072182735511623, 1528799552075989102, 1527919721629089862}
TZ = ZoneInfo("Europe/Bucharest")
DB_PATH = Path(os.getenv("DATABASE_PATH") or ("/data/pontaj.db" if Path("/data").is_dir() else "pontaj.db"))

CATEGORIES = ["Bani", "Arme", "Munitie", "Materiale", "Componente", "Produse", "Echipamente", "Medicale", "Haine", "Mancare", "Bauturi", "Obiecte de valoare", "Unelte", "Diverse"]
INITIAL = {
    "Bani": ["Bani murdari", "Bani curati"],
    "Materiale": ["Sulf", "Fier", "Praf de pusca", "Otel"],
    "Componente": ["Elemente de fixare", "Cadre", "Tevi", "Mecanisme"],
    "Produse": ["Frunze", "Joint", "Plic coca simpla", "Coca 65%", "Coca 70%", "Coca 80%", "Coca 99%"],
    "Echipamente": ["Armuri", "Casti"],
    "Medicale": ["Seringi"],
}
_lock = asyncio.Lock()


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_PATH), timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=20000")
    return db


def init_db():
    with connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS seif_categories (name TEXT PRIMARY KEY COLLATE NOCASE)")
        db.execute("CREATE TABLE IF NOT EXISTS seif_items (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE COLLATE NOCASE NOT NULL, category TEXT NOT NULL, quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity >= 0))")
        db.execute("CREATE TABLE IF NOT EXISTS seif_history (id INTEGER PRIMARY KEY AUTOINCREMENT, item_name TEXT NOT NULL, action TEXT NOT NULL, delta INTEGER NOT NULL, before_qty INTEGER NOT NULL, after_qty INTEGER NOT NULL, actor_id INTEGER NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS seif_config (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.executemany("INSERT OR IGNORE INTO seif_categories(name) VALUES (?)", [(x,) for x in CATEGORIES])
        for category, items in INITIAL.items():
            db.executemany("INSERT OR IGNORE INTO seif_items(name, category, quantity) VALUES (?, ?, 0)", [(name, category) for name in items])


def authorized(interaction: discord.Interaction):
    if interaction.guild is None or interaction.channel_id != CHANNEL_ID:
        return False
    return isinstance(interaction.user, discord.Member) and any(role.id in LEADERS for role in interaction.user.roles)


async def guard(interaction: discord.Interaction):
    if not authorized(interaction):
        await interaction.response.send_message("⛔ Seiful este disponibil doar conducerii, în canalul privat dedicat.", ephemeral=True)
        return False
    return True


def inventory_embed():
    with connect() as db:
        rows = db.execute("SELECT name, category, quantity FROM seif_items ORDER BY category, name").fetchall()
    groups = {}
    for r in rows:
        groups.setdefault(r["category"], []).append(f'• {r["name"]}: **{r["quantity"]:,}**'.replace(",", "."))
    embed = discord.Embed(title="🏦 SEIF DOMINICANS", description="🔐 Inventar privat — doar conducerea\nCantități gestionate manual pentru GTA RP.", color=discord.Color.blurple(), timestamp=datetime.now(TZ))
    for category, lines in groups.items():
        body = "\n".join(lines)
        if len(body) > 1000:
            body = body[:990] + "…"
        if len(embed.fields) < 25:
            embed.add_field(name=category, value=body, inline=False)
    embed.set_footer(text="Dominicans • Seif")
    return embed


async def update_panel():
    with connect() as db:
        row = db.execute("SELECT value FROM seif_config WHERE key='panel_message_id'").fetchone()
    if not row:
        return
    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(CHANNEL_ID)
        except (discord.HTTPException, discord.Forbidden):
            return
    try:
        msg = await channel.fetch_message(int(row["value"]))
        await msg.edit(embed=inventory_embed())
    except (discord.HTTPException, discord.Forbidden, ValueError):
        pass


async def item_autocomplete(interaction: discord.Interaction, current: str):
    if not authorized(interaction):
        return []
    with connect() as db:
        rows = db.execute("SELECT name FROM seif_items WHERE name LIKE ? ORDER BY name LIMIT 25", (f"%{current}%",)).fetchall()
    return [app_commands.Choice(name=r["name"], value=r["name"]) for r in rows]


async def category_autocomplete(interaction: discord.Interaction, current: str):
    if not authorized(interaction):
        return []
    with connect() as db:
        rows = db.execute("SELECT name FROM seif_categories WHERE name LIKE ? ORDER BY name LIMIT 25", (f"%{current}%",)).fetchall()
    return [app_commands.Choice(name=r["name"], value=r["name"]) for r in rows]


async def change_item(interaction, obiect: str, cantitate: int, motiv: str, action: str):
    if not await guard(interaction):
        return
    if cantitate <= 0 or cantitate > 2_000_000_000:
        await interaction.response.send_message("❌ Cantitatea trebuie să fie pozitivă și maximum 2 miliarde.", ephemeral=True)
        return
    if not motiv.strip():
        await interaction.response.send_message("❌ Motivul este obligatoriu.", ephemeral=True)
        return
    async with _lock:
        with connect() as db:
            row = db.execute("SELECT name, quantity FROM seif_items WHERE name=?", (obiect,)).fetchone()
            if not row:
                await interaction.response.send_message("❌ Obiectul nu există.", ephemeral=True)
                return
            before = row["quantity"]
            after = before + cantitate if action == "adaugare" else before - cantitate
            if after < 0:
                await interaction.response.send_message(f"❌ Stoc insuficient. Disponibil: {before}.", ephemeral=True)
                return
            if after > 9_000_000_000_000_000:
                await interaction.response.send_message("❌ Cantitate prea mare.", ephemeral=True)
                return
            db.execute("UPDATE seif_items SET quantity=? WHERE name=?", (after, row["name"]))
            db.execute("INSERT INTO seif_history(item_name, action, delta, before_qty, after_qty, actor_id, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (row["name"], action, cantitate if action == "adaugare" else -cantitate, before, after, interaction.user.id, motiv.strip()[:300], datetime.now(TZ).isoformat()))
    await interaction.response.send_message(f"✅ {row['name']}: **{before:,} → {after:,}** ({action}). Motiv: {motiv}", ephemeral=True)
    await update_panel()


@bot.tree.command(name="setuptrezorerie", description="Publică sau înlocuiește panoul permanent al seifului")
async def setuptrezorerie(interaction: discord.Interaction):
    if not await guard(interaction):
        return
    await interaction.response.defer(ephemeral=True)
    message = await interaction.channel.send(embed=inventory_embed())
    with connect() as db:
        db.execute("INSERT OR REPLACE INTO seif_config(key, value) VALUES ('panel_message_id', ?)", (str(message.id),))
    await interaction.followup.send("✅ Panoul Seif Dominicans a fost publicat și va fi actualizat automat.", ephemeral=True)


@bot.tree.command(name="seif", description="Afișează inventarul Seif Dominicans")
async def seif(interaction: discord.Interaction):
    if await guard(interaction):
        await interaction.response.send_message(embed=inventory_embed(), ephemeral=True)


@bot.tree.command(name="adaugaseif", description="Adaugă obiecte în seif")
@app_commands.autocomplete(obiect=item_autocomplete)
async def adaugaseif(interaction: discord.Interaction, obiect: str, cantitate: int, motiv: str):
    await change_item(interaction, obiect, cantitate, motiv, "adaugare")


@bot.tree.command(name="scoateseif", description="Scoate obiecte din seif")
@app_commands.autocomplete(obiect=item_autocomplete)
async def scoateseif(interaction: discord.Interaction, obiect: str, cantitate: int, motiv: str):
    await change_item(interaction, obiect, cantitate, motiv, "scoatere")


@bot.tree.command(name="setseif", description="Setează stocul corect al unui obiect")
@app_commands.autocomplete(obiect=item_autocomplete)
async def setseif(interaction: discord.Interaction, obiect: str, cantitate: int, motiv: str):
    if not await guard(interaction):
        return
    if not 0 <= cantitate <= 9_000_000_000_000_000:
        await interaction.response.send_message("❌ Cantitate invalidă.", ephemeral=True)
        return
    if not motiv.strip():
        await interaction.response.send_message("❌ Motivul este obligatoriu.", ephemeral=True)
        return
    async with _lock:
        with connect() as db:
            row = db.execute("SELECT name, quantity FROM seif_items WHERE name=?", (obiect,)).fetchone()
            if not row:
                await interaction.response.send_message("❌ Obiectul nu există.", ephemeral=True)
                return
            db.execute("UPDATE seif_items SET quantity=? WHERE name=?", (cantitate, row["name"]))
            db.execute("INSERT INTO seif_history(item_name, action, delta, before_qty, after_qty, actor_id, reason, created_at) VALUES (?, 'corectie', ?, ?, ?, ?, ?, ?)", (row["name"], cantitate-row["quantity"], row["quantity"], cantitate, interaction.user.id, motiv.strip()[:300], datetime.now(TZ).isoformat()))
    await interaction.response.send_message(f"✅ {row['name']}: {row['quantity']} → {cantitate} (corecție).", ephemeral=True)
    await update_panel()


@bot.tree.command(name="adaugaobiect", description="Creează un obiect nou în seif, cu stoc 0")
@app_commands.autocomplete(categorie=category_autocomplete)
async def adaugaobiect(interaction: discord.Interaction, nume: str, categorie: str):
    if not await guard(interaction):
        return
    nume, categorie = nume.strip(), categorie.strip()
    if not 1 <= len(nume) <= 80:
        await interaction.response.send_message("❌ Numele trebuie să aibă între 1 și 80 caractere.", ephemeral=True)
        return
    async with _lock:
        with connect() as db:
            if not db.execute("SELECT 1 FROM seif_categories WHERE name=?", (categorie,)).fetchone():
                await interaction.response.send_message("❌ Categoria nu există. Folosește /adaugacategorie.", ephemeral=True)
                return
            if db.execute("SELECT 1 FROM seif_items WHERE name=?", (nume,)).fetchone():
                await interaction.response.send_message("❌ Obiectul există deja.", ephemeral=True)
                return
            db.execute("INSERT INTO seif_items(name, category, quantity) VALUES (?, ?, 0)", (nume, categorie))
            db.execute("INSERT INTO seif_history(item_name, action, delta, before_qty, after_qty, actor_id, reason, created_at) VALUES (?, 'creare', 0, 0, 0, ?, 'Obiect nou', ?)", (nume, interaction.user.id, datetime.now(TZ).isoformat()))
    await interaction.response.send_message(f"✅ Obiectul **{nume}** a fost adăugat în categoria **{categorie}** cu stoc 0.", ephemeral=True)
    await update_panel()


@bot.tree.command(name="adaugacategorie", description="Adaugă o categorie nouă în seif")
async def adaugacategorie(interaction: discord.Interaction, nume: str):
    if not await guard(interaction):
        return
    nume = nume.strip()
    if not 1 <= len(nume) <= 60:
        await interaction.response.send_message("❌ Nume invalid.", ephemeral=True)
        return
    with connect() as db:
        if db.execute("SELECT 1 FROM seif_categories WHERE name=?", (nume,)).fetchone():
            await interaction.response.send_message("❌ Categoria există deja.", ephemeral=True)
            return
        db.execute("INSERT INTO seif_categories(name) VALUES (?)", (nume,))
    await interaction.response.send_message(f"✅ Categoria **{nume}** a fost creată.", ephemeral=True)


@bot.tree.command(name="stergeobiect", description="Șterge un obiect numai dacă are stoc 0")
@app_commands.autocomplete(obiect=item_autocomplete)
async def stergeobiect(interaction: discord.Interaction, obiect: str):
    if not await guard(interaction):
        return
    async with _lock:
        with connect() as db:
            row = db.execute("SELECT name, quantity FROM seif_items WHERE name=?", (obiect,)).fetchone()
            if not row:
                await interaction.response.send_message("❌ Obiect inexistent.", ephemeral=True)
                return
            if row["quantity"] != 0:
                await interaction.response.send_message("❌ Poți șterge doar obiecte cu stoc 0. Corectează mai întâi stocul.", ephemeral=True)
                return
            db.execute("DELETE FROM seif_items WHERE name=?", (row["name"],))
            db.execute("INSERT INTO seif_history(item_name, action, delta, before_qty, after_qty, actor_id, reason, created_at) VALUES (?, 'stergere', 0, 0, 0, ?, 'Obiect șters', ?)", (row["name"], interaction.user.id, datetime.now(TZ).isoformat()))
    await interaction.response.send_message(f"🗑️ Obiectul **{row['name']}** a fost șters. Istoricul rămâne salvat.", ephemeral=True)
    await update_panel()


@bot.tree.command(name="istoricseif", description="Afișează ultimele operațiuni din seif")
async def istoricseif(interaction: discord.Interaction):
    if not await guard(interaction):
        return
    with connect() as db:
        rows = db.execute("SELECT * FROM seif_history ORDER BY id DESC LIMIT 15").fetchall()
    if not rows:
        await interaction.response.send_message("📜 Nu există încă operațiuni.", ephemeral=True)
        return
    lines = []
    for r in rows:
        stamp = r["created_at"][:16].replace("T", " ")
        lines.append(f'`#{r["id"]}` {stamp} • **{r["action"]}** • {r["item_name"]} • {r["before_qty"]} → {r["after_qty"]}\n<@{r["actor_id"]}> • {discord.utils.escape_markdown(r["reason"][:90])}')
    embed = discord.Embed(title="📜 ISTORIC SEIF — ultimele 15 operațiuni", description="\n\n".join(lines)[:4000], color=discord.Color.gold())
    await interaction.response.send_message(embed=embed, ephemeral=True)


init_db()
