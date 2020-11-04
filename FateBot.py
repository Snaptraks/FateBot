import discord
from discord.ext import commands

import config


class FateBot(commands.Bot):
    """The Bot for the Fate Bound Discord server."""


if __name__ == '__main__':
    intents = discord.Intents.all()
    bot = FateBot(
        description="Bot for the Fate Bound EOS Guild.",
        command_prefix="&",
        intents=intents,
    )

    bot.run(token=config.token)
