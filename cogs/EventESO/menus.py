from collections import defaultdict
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
    "fill": "\U0001f4ad",  # :thought_balloon:
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
                self._button_add_role,
                skip_if=self._skip_role(role)
            )
            self.add_button(button)

    async def send_initial_message(self, ctx, channel):
        """Send the initial, empty Embed for the registration."""

        self.message = await channel.send("Getting things ready...")
        self.event_id = await self._create_event(self.activation_time)
        self.event_data = await self._get_event_data()
        participants = await self._get_participants()
        self.embed = self.build_embed(participants)
        await self.message.edit(content=None, embed=self.embed)
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

    async def _button_add_role(self, payload):
        """Helper function to add the user to a role."""

        participants = await self._get_participants()
        role_list = self._classify_roles(participants)
        react_role = REVERSE_BUTTONS[payload.emoji.name]

        if len(role_list[react_role]) >= self.template[react_role]['amount']:
            react_role = "fill"

        await self._remove_event_role(payload.user_id)
        await self._add_event_role(payload.user_id, react_role)
        await self.update_page()

    async def update_page(self):
        """Rebuild the embed with the new data."""

        participants = await self._get_participants()
        embed = self.build_embed(participants)
        await self.message.edit(content=None, embed=embed)

    def build_embed(self, participants=None):
        """Build the required Embed for the requested event."""

        role_list = self._classify_roles(participants)

        embed = discord.Embed(
            title=self.template['title'],
            description=self.template['description'],
            url=self.template['url'],
            color=0x200972,
            timestamp=self.activation_time,
        ).set_author(
            name=self.bot.user.name,
            icon_url=self.bot.user.avatar_url,
        ).set_image(
            url=self.template['image'],
        ).set_footer(
            text=f"Event ID {self.event_id} | Happening on ",
        ).add_field(
            name="Guides",
            value=self.template['guides'],
        ).add_field(
            name="Requirements",
            value=self.template['requirements'],
        ).add_field(
            name=f"{BUTTONS['leader']} Leader",
            value=f"<@{role_list['leader'][0]}>"
                  if role_list['leader'] else None,
            inline=False,
        )

        for role in ALL_ROLES:
            if not self._skip_role(role)(self):
                field_name = (
                    f"{BUTTONS[role]} "
                    f"{self.template[role]['name']} "
                    f"({len(role_list[role])}/{self.template[role]['amount']})"
                )
                field_value = '\n'.join(
                    [f"<@{user_id}>" for user_id in role_list[role]])

                embed.add_field(
                    name=field_name,
                    value=field_value if field_value else None,
                )

        fill_field_value = '\n'.join(
            [f"<@{user_id}>" for user_id in role_list['fill']])

        embed.add_field(
            name=f"{BUTTONS['fill']} Fill",
            value=fill_field_value if fill_field_value else None,
            inline=False,
        )

        return embed

    def _classify_roles(self, participants):
        """Counts the number of participants in the roles of the event."""

        role_list = defaultdict(lambda: [])
        for user in participants:
            # classify users in roles
            role_list[user['role']].append(user['user_id'])

        return role_list

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
