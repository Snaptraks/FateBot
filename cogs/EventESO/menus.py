from collections import defaultdict
import itertools
import json
import os

import discord
from discord.ext import menus


ALL_ROLES = [f"{role}{i}" for role, i in
             itertools.product(["dps", "healer", "tank"], range(4))]

BUTTONS = {
    "dps0": "<:dps0:818209538846621726>",
    "dps1": "<:dps1:818210522851704852>",
    "dps2": "<:dps2:818196727118168084>",
    "dps3": "<:dps3:818196726895869952>",
    "healer0": "<:healer0:818213228978634784>",
    "healer1": "<:healer1:818196727302455306>",
    "healer2": "<:healer2:818196727148052500>",
    "healer3": "<:healer3:818208818231246869>",
    "tank0": "<:tank0:818214243194241036>",
    "tank1": "<:tank1:818199098997473340>",
    "tank2": "<:tank2:773377781513977926>",
    "tank3": "<:tank3:773377679160246282>",
    "leader": "\N{CROWN}",
    "fill": "\N{THOUGHT BALLOON}",
    "clear": "\N{CROSS MARK}",
}
REVERSE_BUTTONS = {v: k for k, v in BUTTONS.items()}

BASE_DICT = {role: {"name": None, "amount": 0} for role in ALL_ROLES}

template_path = os.path.join(os.path.dirname(__file__), "templates")
with open(os.path.join(template_path, "arenas.json")) as f:
    ARENAS_DATA = json.load(f)
with open(os.path.join(template_path, "dungeons.json")) as f:
    DUNGEONS_DATA = json.load(f)
with open(os.path.join(template_path, "trials.json")) as f:
    TRIALS_DATA = json.load(f)

EMBED_COLOR = 0x200972


class RegistrationMenu(menus.Menu):
    """Menu for the role selection in an Event."""

    def __init__(self, *args, **kwargs):
        event_data = kwargs.pop('event_data')
        self.load_data(event_data)

        super().__init__(*args, **kwargs)

        # add the buttons upon instanciation
        for role in ALL_ROLES:
            button = menus.Button(
                BUTTONS[role],
                self._button_add_role,
                skip_if=self._skip_role(role)
            )
            self.add_button(button)

    def load_data(self, event_data):
        self.trigger_at = event_data['trigger_at']
        self.event_id = event_data['event_id']
        self.event_name = event_data['event_name']
        self.event_type = event_data['event_type']

        if self.event_type == "arena":
            template = ARENAS_DATA[self.event_name]

        elif self.event_type == "dungeon":
            template = DUNGEONS_DATA[self.event_name]

        elif self.event_type == "trial":
            template = TRIALS_DATA[self.event_name]
        else:
            raise ValueError

        self.template = BASE_DICT | template

    async def send_initial_message(self, ctx, channel):
        """Send the initial, empty Embed for the registration."""

        self.message = await channel.send("Getting things ready...")
        # update DB with message details
        await self._update_event()
        participants = await self._get_participants()
        embed = self.build_embed(participants)
        await self.message.edit(content=None, embed=embed)
        return self.message

    def reaction_check(self, payload):
        """Override the function to allow for everyone to react."""

        if payload.message_id != self.message.id:
            return False

        if payload.user_id == self.bot.user.id:
            return False

        return payload.emoji in self.buttons

    async def stop(self):
        participants = await self._get_participants()
        user_ids = [user['user_id'] for user in participants]
        super().stop()
        return user_ids

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

        participants = await self._get_participants()
        user_ids = [user['user_id'] for user in participants]
        if payload.user_id not in user_ids:
            # do not let unregistered users in the Leader role
            return

        role_list = self._classify_roles(participants)
        if len(role_list["leader"]) == 1:
            # no more than one Leader
            return

        await self._add_event_role(payload.user_id, "leader")
        await self.update_page()

    @menus.button(BUTTONS["fill"], position=menus.Last(0))
    async def on_fill(self, payload):
        """Add the user to the Fill list."""

        await self._clear_participant(payload.user_id)
        await self._add_event_role(payload.user_id, "fill")
        await self.update_page()

    @menus.button(BUTTONS["clear"], position=menus.Last(1))
    async def on_clear(self, payload):
        """Remove yourself from the event."""

        await self._clear_participant(payload.user_id)
        await self.update_page()

    async def _button_add_role(self, payload):
        """Helper function to add the user to a role."""

        participants = await self._get_participants()
        user_ids = [user['user_id'] for user in participants]
        role_list = self._classify_roles(participants)
        try:
            # unicode emoji
            react_role = REVERSE_BUTTONS[payload.emoji.name]
        except KeyError:
            # custom emoji
            e = payload.emoji
            tag = f"<:{e.name}:{e.id}>"
            react_role = REVERSE_BUTTONS[tag]
        role_max = self.template[react_role]['amount']
        already_in_event = payload.user_id in user_ids

        if len(role_list[react_role]) >= role_max:
            if not already_in_event:
                react_role = "fill"

            else:
                # already in a role, the requested one is full,
                # then do not change the user's role
                return

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

        trigger_at_fmt = self.trigger_at.strftime("%Y-%m-%d %H:%M UTC")

        embed = discord.Embed(
            title=self.template['title'],
            description=self.template['description'],
            url=self.template['url'],
            color=EMBED_COLOR,
        ).set_author(
            name=self.bot.user.name,
            icon_url=self.bot.user.avatar_url,
        ).set_image(
            url=self.template['image'],
        ).set_footer(
            text=(
                f"Event ID {self.event_id:03d} | "
                f"Happening on {trigger_at_fmt}"
            ),
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

    async def _update_event(self):
        """Update the DB entry with the info from the message
        containing the Menu.
        """
        await self.bot.db.execute(
            """
            UPDATE eventeso_event
               SET message_id = :message_id,
                   channel_id = :channel_id,
                   created_at = :created_at
             WHERE rowid = :event_id
            """,
            {
                'event_id': self.event_id,
                'channel_id': self.message.channel.id,
                'created_at': self.message.created_at,
                'message_id': self.message.id,
            }
        )

        await self.bot.db.commit()

    async def _get_participants(self):
        """Get the list of participants, and their roles for the event."""

        async with self.bot.db.execute(
                """
                SELECT *
                  FROM eventeso_participant
                 WHERE event_id = :event_id
                """,
                {
                    'event_id': self.event_id
                }
        ) as c:
            rows = await c.fetchall()

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


class EditMenu(menus.Menu):
    """Menu to edit the data of an Event."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.result = None

    async def send_initial_message(self, ctx, channel):

        description = "\n".join([
            f"{emoji}: `{button.action.__name__.replace('on_', '')}`"
            for emoji, button in self.buttons.items()
        ])

        embed = discord.Embed(
            title="What do you want to edit?",
            description=description,
            color=EMBED_COLOR,
        )
        return await ctx.send(embed=embed)

    # trigger_at
    @menus.button("\N{MANTELPIECE CLOCK}")
    async def on_trigger_at(self, payload):
        self.result = "trigger_at"
        self.stop()

    # event_type
    # @menus.button("\N{BAR CHART}")
    # async def on_event_type(self, payload):
    #     self.result = "event_type"
    #     self.stop()

    # event_name
    @menus.button("\N{NAME BADGE}")
    async def on_event_name(self, payload):
        self.result = "event_name"
        self.stop()

    async def prompt(self, ctx):
        await self.start(ctx, wait=True)
        return self.result
