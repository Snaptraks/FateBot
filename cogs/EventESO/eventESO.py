from discord.ext import commands


class EventESO(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def trial(self, ctx):
        """Trigger a trial event."""
