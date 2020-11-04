from .eventESO import EventESO


def setup(bot):
    bot.add_cog(EventESO(bot))
