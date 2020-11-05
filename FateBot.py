import aiosqlite
import discord
from discord.ext import commands

import config


async def create_db_connection(db_name):
    """Create the connection to the SQLite database."""

    return await aiosqlite.connect(
        db_name, detect_types=1)  # 1: parse declared types


class FateBot(commands.Bot):
    """The Bot for the Fate Bound Discord server."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Create the DB connection and allow for name-based
        # access of data columns
        self.db = self.loop.run_until_complete(
            create_db_connection(kwargs.get('db_name', ':memory:')))
        self.db.row_factory = aiosqlite.Row

    async def close(self):
        """Subclass the method to close underlying processes."""
        await self.db.close()
        await super().close()

    async def on_ready(self):
        permissions = discord.Permissions(permissions=336063568)
        oauth_url = discord.utils.oauth_url(
            self.user.id, permissions=permissions)
        print(
            "--------\n"
            f"Logged in as {self.user.name} (ID:{self.user.id}) "
            f"Use this link to invite {self.user.name}:\n"
            f"{oauth_url}\n"
            "--------"
        )


if __name__ == '__main__':
    intents = discord.Intents.all()
    bot = FateBot(
        description="Bot for the Fate Bound ESO Guild.",
        command_prefix="&",
        intents=intents,
        db_name='FateBot.db',
    )

    startup_extensions = [
        'cogs.EventESO',
    ]

    for extension in startup_extensions:
        bot.load_extension(extension)

    bot.run(config.token)
