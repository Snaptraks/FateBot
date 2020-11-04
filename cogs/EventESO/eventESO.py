from discord.ext import commands, tasks


class EventESO(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        self._create_tables.start()

    @commands.command()
    async def trial(self, ctx):
        """Trigger a trial event."""

    @tasks.loop(count=1)
    async def _create_tables(self):
        """Create the necessary DB tables if they do not exist."""

        await self.bot.db.execute(
            """
            CREATE TABLE IF NOT EXISTS eventeso_event(
                activation_time TIMESTAMP NOT NULL,
                channel_id      INTEGER   NOT NULL,
                creation_time   TIMESTAMP NOT NULL,
                message_id      INTEGER   NOT NULL
            )
            """
        )

        await self.bot.db.execute(
            """
            CREATE TABLE IF NOT EXISTS eventeso_participant(
                user_id  INTEGER NOT NULL,
                role     TEXT    NOT NULL,
                event_id INTEGER NOT NULL,
                FOREIGN KEY (event_id)
                    REFERENCES eventeso_event (rowid)
            )
            """
        )

        await self.bot.db.commit()
