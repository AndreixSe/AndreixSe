import os
import discord
from discord import app_commands
from discord.ext import commands

from core.bot import bot
from core.database import migrate_database

# Importurile înregistrează comenzile slash ale fiecărui sistem.
from systems.patrol.module import PatrolView
from systems.attendance.module import AttendanceView
import systems.donations.module  # noqa: F401 - înregistrează comenzile Evidență M/J

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = 1527916365837766667


@bot.event
async def on_ready():
    print(f"✅ Bot conectat ca {bot.user}")
    migrate_database()

    try:
        bot.add_view(PatrolView())
        bot.add_view(AttendanceView())
        print("✅ View-urile persistente au fost încărcate.")
    except Exception as error:
        print(f"❌ Eroare la încărcarea View-urilor: {error}")

    try:
        # Actualizează și lista globală; comenzile vechi vor dispărea după propagarea Discord.
        global_synced = await bot.tree.sync()
        print(f"✅ Au fost sincronizate global {len(global_synced)} comenzi slash.")

        # Copiază comenzile globale în server și le sincronizează imediat acolo.
        guild = discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        guild_synced = await bot.tree.sync(guild=guild)
        print(f"✅ Au fost sincronizate {len(guild_synced)} comenzi slash pe serverul {GUILD_ID}.")
        print("📋 Comenzi pe server: " + ", ".join(cmd.name for cmd in guild_synced))
    except Exception as error:
        print(f"❌ Eroare sincronizare comenzi: {error}")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    print(f"❌ Eroare comandă prefix: {error}")


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
):
    if isinstance(error, app_commands.CheckFailure):
        message = "❌ Nu ai permisiunea necesară pentru această comandă."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
        return

    print(f"❌ Eroare slash command: {error}")


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("Variabila DISCORD_TOKEN nu este configurată.")
    migrate_database()
    bot.run(TOKEN)
