from collections import defaultdict
from datetime import datetime, timedelta
from dateutil.parser import isoparse
import discord
from discord.ext import commands, tasks
from . import menus


class DateTimeISOError(commands.CommandError):
    """Exception raised when the provided argument is not a valid ISO
    time format.
    """


class EventAbbreviationError(commands.CommandError):
    """Exception raised when the provided abbreviation for the event
    is none of the valid ones.
    """


class DateTimeISO(commands.Converter):
    """Convert a string of ISO time to a datetime object."""

    async def convert(self, ctx, timeiso):
        try:
            dt = isoparse(timeiso)
        except ValueError:
            raise DateTimeISOError("Wrong time format.")

        return dt


class EventESO(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.running_events = defaultdict(lambda: {'task': None, 'menu': None})

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

            id = event['event_id']
            self.running_events[id]['task'] = self.bot.loop.create_task(
                self._registration_task(
                    ctx,
                    event_data=dict(event),
                    message=message,
                    timeout=None,
                )
            )

    @reload_menus.before_loop
    async def reload_menus_before(self):
        await self.bot.wait_until_ready()

    @commands.group(aliases=["trials"], invoke_without_command=True)
    async def trial(self, ctx, trial_name="nAA", *,
                    trigger_at: DateTimeISO = None):
        """Trigger a trial event."""

        if trigger_at is None:
            trigger_at = datetime.utcnow() + timedelta(hours=1)

        if trial_name not in menus.TRIALS_DATA.keys():
            raise EventAbbreviationError(f"Unknown trial `{trial_name}`.")

        event_id = await self._create_event(
            trigger_at,
            trial_name,
            "trial",
        )
        event_data = dict(await self._get_event_data(event_id))

        id = event_data['event_id']
        self.running_events[id]['task'] = self.bot.loop.create_task(
            self._registration_task(
                ctx,
                event_data=event_data,
                timeout=None,
            )
        )

    @trial.error
    async def trial_error(self, ctx, error):
        """Error handler for the trial command."""

        if isinstance(error, DateTimeISOError):
            await ctx.send(
                "Wrong time format. Are you sure it is ISO?\n"
                "You can see the right format with "
                f"`{self.bot.command_prefix}timeiso`."
            )

        elif isinstance(error, EventAbbreviationError):
            await ctx.send(error)

        else:
            raise error

    @trial.command(name="cancel")
    @commands.is_owner()  # to modify for role/permissions
    async def trial_cancel(self, ctx, event_id: int):
        """Cancel a trial of given ID."""

        event_data = await self._get_event_data(event_id)
        channel = self.bot.get_channel(event_data['channel_id'])
        message = await channel.fetch_message(event_data['message_id'])

        await self.running_events[event_id]['menu'].stop()
        self.running_events[event_id]['task'].cancel()
        await message.delete()
        del self.running_events[event_id]
        await self._stop_event(event_id)

    @trial.command(name="list")
    async def trial_list(self, ctx):
        """Print the list of trials available, and their abbreviation."""

        content = []
        for k, v in menus.TRIALS_DATA.items():
            content.append(f"{v['title']} (`{k}`)")

        await ctx.send("\n".join(content))

    @commands.command()
    async def timeiso(self, ctx):
        """Return the current UTC time in ISO format.
        Useful to use as a reference on how to format the time
        for the event commands.
        """

        utcnow = datetime.utcnow().isoformat(sep=' ', timespec='minutes')
        await ctx.send(f"The time is curently `{utcnow}` UTC!")

    async def _registration_task(self, ctx, **kwargs):
        """Task helper to start the registration menus and timer."""

        event_data = kwargs.get('event_data')
        event_id = event_data['event_id']

        menu = menus.RegistrationMenu(**kwargs)
        self.running_events[event_id]['menu'] = menu
        await menu.start(ctx)

        await discord.utils.sleep_until(menu.trigger_at)
        participants = await menu.stop()

        users = []
        for user_id in participants:
            user = (self.bot.get_user(user_id)
                    or await self.bot.fetch_user(user_id))
            users.append(user.mention)

        await ctx.send(f"Trial Time {' '.join(users)}")
        del self.running_events[event_id]
        await self._stop_event(event_id)

    @tasks.loop(count=1)
    async def _create_tables(self):
        """Create the necessary DB tables if they do not exist."""

        await self.bot.db.execute(
            """
            CREATE TABLE IF NOT EXISTS eventeso_event(
                channel_id INTEGER,
                created_at TIMESTAMP,
                event_name TEXT      NOT NULL,
                event_type TEXT      NOT NULL,
                is_done    INTEGER   NOT NULL,
                message_id INTEGER,
                trigger_at TIMESTAMP NOT NULL
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
                    REFERENCES eventeso_event (rowid),
                UNIQUE(event_id, role, user_id)
            )
            """
        )

        await self.bot.db.commit()

    async def _create_event(self, trigger_at, event_name, event_type):
        """Insert the Event data in the DB."""

        async with self.bot.db.execute(
                """
                INSERT INTO eventeso_event
                VALUES (:channel_id,
                        :created_at,
                        :event_name,
                        :event_type,
                        :is_done,
                        :message_id,
                        :trigger_at)
                """,
                {
                    'channel_id': None,
                    'created_at': None,
                    'event_name': event_name,
                    'event_type': event_type,
                    'is_done': 0,
                    'message_id': None,
                    'trigger_at': trigger_at,
                }
        ) as c:
            event_id = c.lastrowid

        await self.bot.db.commit()

        return event_id

    async def _get_event_data(self, event_id):
        """Get the data on the event from the DB and cache it."""

        async with self.bot.db.execute(
                """
                SELECT rowID AS event_id, * FROM eventeso_event
                 WHERE rowid = :event_id
                """,
                {
                    'event_id': event_id,
                }
        ) as c:
            row = await c.fetchone()

        return row

    async def _get_events(self):
        """Return the list of events that are still active."""

        async with self.bot.db.execute(
                """
                SELECT rowid AS event_id, *
                  FROM eventeso_event
                 WHERE trigger_at > :now
                   AND is_done = 0
                """,
                {
                    'now': datetime.utcnow()
                }
        ) as c:
            rows = await c.fetchall()

        return rows

    async def _stop_event(self, event_id):
        """Mark the event as finished in the DB."""

        await self.bot.db.execute(
            """
            UPDATE eventeso_event
               SET is_done = 1
             WHERE rowid = :event_id
            """,
            {
                'event_id': event_id,
            }
        )

        await self.bot.db.commit()
