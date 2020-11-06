import itertools
import json
import os

import discord
from discord.ext import menus


ALL_ROLES = [f"{role}{i}" for role, i in
             itertools.product(["dps", "healer", "tank"], range(2))]

BUTTONS = {
    "dps0": "\U0001f5e1\ufe0f",  # :dagger:
    "dps1": "\u2694\ufe0f",  # :crossed_swords:
    "healer0": "\U0001f3e5",  # :hospital:
    "healer1": "\u2695\ufe0f",  # :medical_symbol:
    "tank0": "\U0001f6e1\ufe0f",  # :shield:
    "tank1": "\U0001f9a7",  # :orangutan:
    "leader": "\U0001f451",  # :crown:
    "clear": "\u274c",  # :x:
}
REVERSE_BUTTONS = {v: k for k, v in BUTTONS.items()}

BASE_DICT = {role: {"name": None, "amount": 0} for role in ALL_ROLES}

trials_path = os.path.join("cogs", "EventESO",
                           "templates", "trials.json")
with open(trials_path) as f:
    TRIALS_DATA = json.load(f)


class RegistrationMenu(menus.Menu):
    """Menu for the role selection in an Event."""

    def __init__(self, *args, **kwargs):
        self.activation_time = kwargs.pop('activation_time')
        self.event_id = kwargs.pop('event_id', None)
        self.embed = None
        self.event_data = None
        self.participants = []

        self.event_type = "trial"
        self.event_name = "Maw of Lorkhaj"
        if self.event_type == "trial":
            self.template = {**BASE_DICT, **TRIALS_DATA[self.event_name]}
            # in py 3.9:
            # self.template = BASE_DICT | TRIALS_DATA[self.event_name]
        else:
            raise ValueError

        super().__init__(*args, **kwargs)

        # add the buttonsupon instanciation
        for role in ALL_ROLES:
            button = menus.Button(
                BUTTONS[role],
                self.add_role,
                skip_if=self._skip_role(role)
            )
            self.add_button(button)

    async def send_initial_message(self, ctx, channel):
        """Send the initial, empty Embed for the registration."""

        self.message = await channel.send("Here is the event!")
        await self._create_event(self.activation_time)
        return self.message

    def reaction_check(self, payload):
        """Override the function to allow for everyone to react."""

        if payload.message_id != self.message.id:
            return False

        if payload.user_id == self.bot.user.id:
            return False

        return payload.emoji in self.buttons

    async def start(self, *args, **kwargs):
        """Override the function to get the Embed."""

        await super().start(*args, **kwargs)

        if self.embed is None:
            self.embed = self.message.embeds[0]

        if self.event_data is None:
            self.event_data = await self._get_event_data()

    async def stop(self):
        await self._get_participants()
        super().stop()

    def _skip_role(self, role):
        def check(menu):
            return menu.template[role]['amount'] == 0
        return check

    async def add_role(self, payload):
        """docstring"""
        await self._button_add_role(
            payload, REVERSE_BUTTONS[payload.emoji.name])

    # better way than write all the functions?
    # @menus.button(BUTTONS["dps0"], skip_if=_skip_role("dps0"))
    # async def on_dps0(self, payload):
    #     """Register as dps0 on the Event."""
    #
    #     await self._button_add_role(payload, "dps0")

    @menus.button(BUTTONS["leader"], position=menus.First(0))
    async def on_leader(self, payload):
        """Add the Leader role to the user."""

        await self._add_event_role(payload.user_id, "leader")
        await self.update_page()

    @menus.button(BUTTONS["clear"], position=menus.Last(0))
    async def on_clear(self, payload):
        """Remove yourself from the event."""

        await self._clear_participant(payload.user_id)
        await self.update_page()

    async def _button_add_role(self, payload, role):
        """Helper function to add the user to a role."""

        await self._remove_event_role(payload.user_id)
        await self._add_event_role(payload.user_id, role)
        await self.update_page()

    async def update_page(self):
        rows = await self._get_participants()
        participants = [str(dict(row)) for row in rows]
        participants_str = '\n'.join(participants)

        await self.message.edit(
            content=f"Here is the event!\n{participants_str}")

    async def _create_event(self, activation_time):
        """Insert the Event data in the DB."""

        async with self.bot.db.execute(
                """
                INSERT INTO eventeso_event
                VALUES (:activation_time,
                        :channel_id,
                        :creation_time,
                        :message_id,
                        :type)
                """,
                {
                    'activation_time': activation_time,
                    'channel_id': self.message.channel.id,
                    'creation_time': self.message.created_at,
                    'message_id': self.message.id,
                    'type': 0,
                }
        ) as c:
            event_id = c.lastrowid

        await self.bot.db.commit()

        return event_id

    async def _get_event_data(self):
        """Get the data on the event from the DB and cache it."""

        async with self.bot.db.execute(
                """
                SELECT * FROM eventeso_event
                 WHERE rowid = :event_id
                """,
                {
                    'event_id': self.event_id,
                }
        ) as c:
            row = await c.fetchone()
            print(row)

        return row

    async def _get_participants(self):
        """Get the list of participants, and their roles for the event."""

        async with self.bot.db.execute(
                """
                SELECT * FROM eventeso_participant
                 WHERE event_id = :event_id
                """,
                {
                    'event_id': self.event_id
                }
        ) as c:
            rows = await c.fetchall()

        self.participants = [row['user_id'] for row in rows]

        return rows

    async def _add_event_role(self, user_id, role):
        """Add a role to the user participating to the event."""

        await self.bot.db.execute(
            """
            INSERT OR IGNORE INTO eventeso_participant
            VALUES (:event_id,
                    :role,
                    :user_id)
            """,
            {
                'event_id': self.event_id,
                'role': role,
                'user_id': user_id,
            }
        )

        await self.bot.db.commit()

    async def _clear_participant(self, user_id):
        """Entirely remove a participant from the event."""

        await self.bot.db.execute(
            """
            DELETE FROM eventeso_participant
             WHERE user_id = :user_id
               AND event_id = :event_id
            """,
            {
                'user_id': user_id,
                'event_id': self.event_id,
            }
        )

        await self.bot.db.commit()

    async def _remove_event_role(self, user_id):
        """Remove the role of a user from the event."""

        await self.bot.db.execute(
            """
            DELETE FROM eventeso_participant
             WHERE user_id = :user_id
               AND event_id = :event_id
               AND role != 'leader'
            """,
            {
                'user_id': user_id,
                'event_id': self.event_id,
            }
        )

        await self.bot.db.commit()
