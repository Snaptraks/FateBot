from collections import defaultdict
from datetime import datetime, timedelta
from dateutil.parser import isoparse
import discord
from discord.ext import commands, tasks
from . import menus

ADMIN_ROLES = [
    612353582628470835,  # Officer
    704199892339261550,  # Senior Officer
    612352389973934102,  # Guildmasters
    758707783330693161,  # Bot Tester Role (don't mind me)
]


class DateTimeISOError(commands.CommandError):
    """Exception raised when the provided argument is not a valid ISO
    time format.
    """


class EventAbbreviationError(commands.CommandError):
    """Exception raised when the provided abbreviation for the event
    is none of the valid ones.
    """


class EventIDNotRunning(commands.CommandError):
    """Exception raised when there is no running event at the provided ID."""


class EventRoleNotFound(commands.CommandError):
    """Exception raised when the provided role for the event is not found."""


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
    async def trial(self, ctx, trial_name, *,
                    trigger_at: DateTimeISO = None):
        """Trigger a trial event."""

        if trigger_at is None:
            trigger_at = datetime.utcnow() + timedelta(weeks=1)

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
    @commands.has_any_role(ADMIN_ROLES)
    async def trial_cancel(self, ctx, event_id: int):
        """Cancel a trial of given ID."""

        if event_id not in self.running_events.keys():
            raise EventIDNotRunning(f"No event running at ID `{event_id}`.")

        event_data = await self._get_event_data(event_id)
        channel = self.bot.get_channel(event_data['channel_id'])
        message = await channel.fetch_message(event_data['message_id'])

        await self.running_events[event_id]['menu'].stop()
        self.running_events[event_id]['task'].cancel()
        await message.delete()
        del self.running_events[event_id]
        await self._stop_event(event_id)

    @trial.command(name="add")
    @commands.has_any_role(ADMIN_ROLES)
    async def trial_add(self, ctx, event_id: int, role: str,
                        member: discord.Member):
        """Administrator command to add a member to the event.
        Must specify the event ID and desired role of the member.
        """

        try:
            menu = self.running_events[event_id]['menu']
        except KeyError:
            raise EventIDNotRunning(f"No event running at ID `{event_id}`.")

        if role not in menus.ALL_ROLES:
            raise EventRoleNotFound(f"Role {role} is not valid.")

        button = menus.BUTTONS[role]

        await self.fake_button_press(menu, member, button)

    @trial.command(name="remove")
    @commands.has_any_role(ADMIN_ROLES)
    async def trial_remove(self, ctx, event_id: int, member: discord.Member):
        """Administrator command to remove a member to the event.
        Must specify the event ID.
        """

        try:
            menu = self.running_events[event_id]['menu']
        except KeyError:
            raise EventIDNotRunning(f"No event running at ID `{event_id}`.")

        button = menus.BUTTONS['clear']

        await self.fake_button_press(menu, member, button)

    @trial_cancel.error
    @trial_add.error
    @trial_remove.error
    async def trial_admin_error(self, ctx, error):
        """Error handler for the trial administration commands."""

        if isinstance(error, (
                EventIDNotRunning,
                EventRoleNotFound,
                commands.MemberNotFound,
        )):
            await ctx.send(error)

        else:
            raise error

    async def fake_button_press(self, menu, member, button):
        """Call the function that handles button press with a fake payload."""

        # this is hackish
        emoji = discord.PartialEmoji(name=button)
        payload = discord.RawReactionActionEvent(
            data={
                'message_id': menu.message.id,
                'channel_id': menu.message.channel.id,
                'user_id': member.id,
                'guild_id': menu.message.guild.id,
            },
            emoji=emoji,
            event_type='REACTION_ADD',
        )

        if emoji.name == menus.BUTTONS['clear']:
            await menu.on_clear(payload)
        else:
            await menu._button_add_role(payload)

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

        users = set()
        for user_id in participants:
            user = (self.bot.get_user(user_id)
                    or await self.bot.fetch_user(user_id))
            users.add(user.mention)

        await ctx.send(
            f"Hey {', '.join(list(users))}! It is time for the "
            f"{menu.template['title']}."
        )
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
