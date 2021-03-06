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
            await self._start_event(ctx, id, message, event)

    @reload_menus.before_loop
    async def reload_menus_before(self):
        await self.bot.wait_until_ready()

    @commands.command(aliases=["arenas"])
    async def arena(self, ctx, arena_name, *,
                    trigger_at: DateTimeISO = None):
        """Trigger an arena event."""

        await self._event_master(
            ctx,
            "arena",
            arena_name,
            trigger_at,
        )

    @commands.command(aliases=["dungeons"])
    async def dungeon(self, ctx, dungeon_name, *,
                      trigger_at: DateTimeISO = None):
        """Trigger a dungeon event."""

        await self._event_master(
            ctx,
            "dungeon",
            dungeon_name,
            trigger_at,
        )

    @commands.command(aliases=["trials"])
    async def trial(self, ctx, trial_name, *,
                    trigger_at: DateTimeISO = None):
        """Trigger a trial event."""

        await self._event_master(
            ctx,
            "trial",
            trial_name,
            trigger_at,
        )

    @arena.error
    @dungeon.error
    @trial.error
    async def base_event_error(self, ctx, error):
        """Error handler for the event commands."""

        if isinstance(error, DateTimeISOError):
            await ctx.send(
                "Wrong time format. Are you sure it is ISO?\n"
                "You can see the right format with "
                f"`{self.bot.command_prefix}timeiso`."
            )

        elif isinstance(error, (EventAbbreviationError,
                                commands.MissingRequiredArgument)):
            await ctx.send(error)

        else:
            raise error

    async def _event_master(self, ctx, event_type, event_name, trigger_at):
        """Function to create the event of type event_type, with
        the provided arguments.
        """

        if trigger_at is None:
            trigger_at = datetime.utcnow() + timedelta(weeks=1)

        event_data = self._get_event_type_data(event_type)

        if event_name not in event_data.keys():
            raise EventAbbreviationError(
                f"Unknown {ctx.invoked_with} `{event_name}`.")

        event_id = await self._create_event(
            event_type,
            event_name,
            trigger_at,
        )

        await self._start_event(ctx, event_id)

    @commands.group(aliases=["events"])
    @commands.has_any_role(*ADMIN_ROLES)
    async def event(self, ctx):
        """Command group to administrate event registrations."""

    @event.command(name="cancel")
    async def event_cancel(self, ctx, event_id: int):
        """Cancel an event of given ID."""

        if event_id not in self.running_events.keys():
            raise EventIDNotRunning(f"No event running at ID `{event_id}`.")

        await self._cancel_event(event_id, stop_event=True, delete_message=True)

    @event.command(name="add")
    async def event_add(self, ctx, event_id: int, role: str,
                        member: discord.Member):
        """Administrator command to add a member to the event.
        Must specify the event ID and desired role of the member.
        """

        if event_id not in self.running_events.keys():
            raise EventIDNotRunning(f"No event running at ID `{event_id}`.")

        if role not in menus.ALL_ROLES:
            raise EventRoleNotFound(f"Role {role} is not valid.")

        menu = self.running_events[event_id]['menu']
        button = menus.BUTTONS[role]

        await self.fake_button_press(menu, member, button)

    @event.command(name="remove")
    async def event_remove(self, ctx, event_id: int, member: discord.Member):
        """Administrator command to remove a member to the event.
        Must specify the event ID.
        """

        if event_id not in self.running_events.keys():
            raise EventIDNotRunning(f"No event running at ID `{event_id}`.")

        menu = self.running_events[event_id]['menu']
        button = menus.BUTTONS['clear']

        await self.fake_button_press(menu, member, button)

    @event.command(name="edit")
    async def event_edit(self, ctx, event_id: int):
        """Administrator command to edit an event."""

        if event_id not in self.running_events.keys():
            raise EventIDNotRunning(f"No event running at ID `{event_id}`.")

        event_data = await self._get_event_data(event_id)

        menu = menus.EditMenu(
            clear_reactions_after=True,
            delete_message_after=True,
        )
        to_edit = await menu.prompt(ctx)

        question_message = await ctx.send("What should be the new value?")

        def check(message):
            return (message.channel == question_message.channel
                    and message.author == ctx.author)

        answer_message = await self.bot.wait_for("message", check=check)

        # check for conversions
        if to_edit == "trigger_at":
            new_value = await DateTimeISO().convert(ctx, answer_message.content)

        elif to_edit == "event_type":
            # SHOULD NOT BE USED. You should create a new event instead
            new_value = answer_message.content
            if new_value not in ("trial", "arena", "dungeon"):
                raise ValueError

        elif to_edit == "event_name":
            new_value = answer_message.content
            event_type_data = self._get_event_type_data(
                event_data["event_type"])

            if new_value not in event_type_data.keys():
                raise EventAbbreviationError(
                    f"Unknown {event_data['event_type']} `{new_value}`.")

        await self._edit_event(event_id, to_edit, new_value)

        # cancel the event and restart the menu
        await self._cancel_event(event_id)
        event_data = await self._get_event_data(event_id)
        channel = (self.bot.get_channel(event_data['channel_id'])
                   or await self.bot.fetch_channel(event_data['channel_id']))
        menu_message = await channel.fetch_message(event_data['message_id'])
        menu_ctx = await self.bot.get_context(menu_message)
        await self._start_event(menu_ctx, event_id, menu_message, event_data)

        # delete the remaining editing messages
        await ctx.channel.delete_messages(
            [question_message, answer_message, ctx.message])
        await ctx.send(f"Successfully edited Event ID {event_id}!",
                       delete_after=10)
        await self.running_events[event_id]["menu"].update_page()

    @event.error
    @event_cancel.error
    @event_add.error
    @event_remove.error
    async def event_admin_error(self, ctx, error):
        """Error handler for the trial administration commands."""

        if isinstance(error, (
                EventIDNotRunning,
                EventRoleNotFound,
                commands.MemberNotFound,
        )):
            await ctx.send(error)

        elif isinstance(error, commands.MissingAnyRole):
            await ctx.send("You do not have the required role(s).")

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

    @commands.command(name="list")
    async def _list(self, ctx, event_type):
        """Print the list of events available, and their abbreviation."""

        if event_type.endswith("s"):
            event_type = event_type[:-1]

        event_data = self._get_event_type_data(event_type)

        content = []
        for k, v in event_data.items():
            content.append(f"{v['title']} (`{k}`)")

        await ctx.send("\n".join(content))

    @_list.error
    async def _list_error(self, ctx, error):
        """Error handler for the list command."""

        if isinstance(error.original, ValueError):
            await ctx.send(error.original)

        else:
            raise error

    def _get_event_type_data(self, event_type):
        """Helper command to return the list of event keys."""

        if event_type == "arena":
            event_list = menus.ARENAS_DATA

        elif event_type == "dungeon":
            event_list = menus.DUNGEONS_DATA

        elif event_type == "trial":
            event_list = menus.TRIALS_DATA

        else:
            raise ValueError(f"No known event type {event_type}.")

        return event_list

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

    async def _start_event(self, ctx, event_id, message=None, event_data=None):
        """Helper function to start an event."""

        if event_data is None:
            event_data = await self._get_event_data(event_id)

        id = event_data['event_id']
        self.running_events[id]['task'] = self.bot.loop.create_task(
            self._registration_task(
                ctx,
                event_data=event_data,
                timeout=None,
                message=message,
                clear_reactions_after=True,
            )
        )

    async def _cancel_event(self, event_id, stop_event=False,
                            delete_message=False):
        """Helper function to cancel an event."""

        event_data = await self._get_event_data(event_id)
        channel = self.bot.get_channel(event_data['channel_id'])
        message = await channel.fetch_message(event_data['message_id'])

        await self.running_events[event_id]['menu'].stop()
        self.running_events[event_id]['task'].cancel()
        del self.running_events[event_id]
        if stop_event:
            await self._stop_event(event_id)

        if delete_message:
            await message.delete()

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

    async def _create_event(self, event_type, event_name, trigger_at):
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

    async def _edit_event(self, event_id, to_edit, new_value):
        """Edit an entry for an event in the DB."""

        await self.bot.db.execute(
            f"""
            UPDATE eventeso_event
               SET {to_edit} = :new_value
             WHERE rowid = :event_id
            """,
            {
                "event_id": event_id,
                "new_value": new_value,
            }
        )

        await self.bot.db.commit()

    async def _get_event_data(self, event_id):
        """Get the data on the event from the DB and cache it."""

        async with self.bot.db.execute(
                """
                SELECT rowid AS event_id, *
                  FROM eventeso_event
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
