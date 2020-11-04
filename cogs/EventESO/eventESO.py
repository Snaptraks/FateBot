from datetime import datetime, timedelta
from dateutil.parser import isoparse
from discord.ext import commands, tasks
from . import menus


class DateTimeISO(commands.Converter):
    """Convert a string of ISO time to a datetime object."""

    async def convert(self, ctx, timeiso):
        dt = isoparse(timeiso)
        return dt


class EventESO(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        self._create_tables.start()
        self.reload_menus.start()

    @tasks.loop(count=1)
    async def reload_menus(self):
        """Reload the menus upon startup."""

        events = await self._get_events()

        for event in events:
            channel = (self.bot.get_channel(event['channel_id'])
                       or await self.bot.fetch_channel(event['channel_id']))
            message = await channel.fetch_message(event['message_id'])
            ctx = await self.bot.get_context(message)

            menu = menus.RegistrationMenu(
                timeout=None,
                activation_time=event['activation_time'],
                event_id=event['rowid'],
                message=message,
            )

            await menu.start(ctx)

    @reload_menus.before_loop
    async def reload_menus_before(self):
        await self.bot.wait_until_ready()

    @commands.command()
    async def trial(self, ctx, *, activation_time: DateTimeISO = None):
        """Trigger a trial event."""

        if activation_time is None:
            activation_time = datetime.utcnow() + timedelta(hours=1)

        menu = menus.RegistrationMenu(
            timeout=None,
            activation_time=activation_time,
        )

        await menu.start(ctx)

    @trial.error
    async def trial_error(self, ctx, error):
        """Error handler for the trial command."""

        if isinstance(error, commands.ConversionError):
            await ctx.send("Wrong time format. Are you sure it is ISO?")

    @tasks.loop(count=1)
    async def _create_tables(self):
        """Create the necessary DB tables if they do not exist."""

        await self.bot.db.execute(
            """
            CREATE TABLE IF NOT EXISTS eventeso_event(
                activation_time TIMESTAMP NOT NULL,
                channel_id      INTEGER   NOT NULL,
                creation_time   TIMESTAMP NOT NULL,
                message_id      INTEGER   NOT NULL,
                type            INTEGER   NOT NULL
            )
            """
        )

        await self.bot.db.execute(
            """
            CREATE TABLE IF NOT EXISTS eventeso_participant(
                event_id INTEGER NOT NULL,
                role     TEXT    NOT NULL,
                user_id  INTEGER NOT NULL,
                FOREIGN KEY (event_id)
                    REFERENCES eventeso_event (rowid)
            )
            """
        )

        await self.bot.db.commit()

    async def _get_events(self):
        """Return the list of events that are still active."""

        async with self.bot.db.execute(
                """
                SELECT rowid, *
                  FROM eventeso_event
                 WHERE activation_time > :now
                """,
                {
                    'now': datetime.utcnow()
                }
        ) as c:
            rows = await c.fetchall()

        return rows
