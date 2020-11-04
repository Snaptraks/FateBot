import discord
from discord.ext import commands

import config


class FateBot(commands.Bot):
    """The Bot for the Fate Bound Discord server."""

    async def on_ready(self):
        permissions = discord.Permissions(permissions=336063568)
        oauth_url = discord.utils.oauth_url(
            self.user.id, permissions=permissions)
        print(
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
    )

    bot.run(config.token)
