
import os
import discord
from discord import app_commands
from discord.ext import commands

from core.bot import bot
from core.database import migrate_database

from systems.patrol.module import PatrolView
from systems.attendance.module import AttendanceView
import systems.donations.module  # noqa: F401
import systems.attendance_business.module  # noqa: F401
import systems.seif.module  # noqa: F401

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = 1527916365837766667

_views_registered = False
_commands_synced = False


@bot.event
async def on_ready():
    global _views_registered, _commands_synced

    print(f"✅ Bot conectat ca {bot.user}")

    migrate_database()

    if not _views_registered:
        try:
            bot.add_view(PatrolView())
            bot.add_view(AttendanceView())

            _views_registered = True
            print("✅ View-urile persistente au fost încărcate.")

        except Exception as error:
            print(f"❌ Eroare la încărcarea View-urilor: {error}")

    if not _commands_synced:
        try:
            guild = discord.Object(id=GUILD_ID)

            # Copiem comenzile înregistrate în Python pe server.
            bot.tree.copy_global_to(guild=guild)

            # Ștergem comenzile globale din Discord
            # pentru a elimina duplicatele.
            bot.tree.clear_commands(guild=None)
            await bot.tree.sync()

            # Sincronizăm comenzile doar pe serverul Dominicans.
            guild_synced = await bot.tree.sync(guild=guild)

            _commands_synced = True

            print(
                f"✅ Sincronizate {len(guild_synced)} "
                f"comenzi pe serverul {GUILD_ID}."
            )

            print(
                "📋 Comenzi: "
                + ", ".join(cmd.name for cmd in guild_synced)
            )

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
    error: app_commands.AppCommandError
):
    if isinstance(error, app_commands.CheckFailure):
        message = "❌ Nu ai permisiunea necesară pentru această comandă."

        if interaction.response.is_done():
            await interaction.followup.send(
                message,
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                message,
                ephemeral=True
            )
        return

    print(f"❌ Eroare slash command: {error}")


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError(
            "Variabila DISCORD_TOKEN nu este configurată."
        )

    migrate_database()
    bot.run(TOKEN)
