from discord.ext import menus


BUTTONS = [
    "\u2694",  # :crossed_swords:
    "\U0001f6e1",  # :shield:
    "\u274c",  # :x:
]


class RegistrationMenu(menus.Menu):
    """Menu for the role selection in an Event."""

    def __init__(self, *args, **kwargs):
        self.activation_time = kwargs.pop('activation_time')
        self.event_id = kwargs.pop('event_id', None)
        self.participants = []
        super().__init__(*args, **kwargs)

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

    async def stop(self):
        await self._get_participants()
        super().stop()

    @menus.button(BUTTONS[0])
    async def on_dps(self, payload):
        """Register as DPS on the Event."""

        await self._remove_participant(payload.user_id)
        await self._add_participant(payload.user_id, "dps")
        await self.update_page()

    @menus.button(BUTTONS[1])
    async def on_tank(self, payload):
        """Register as Tank on the Event."""

        await self._remove_participant(payload.user_id)
        await self._add_participant(payload.user_id, "tank")
        await self.update_page()

    @menus.button(BUTTONS[-1])
    async def on_cancel(self, payload):
        """Remove yourself from the event."""

        await self._remove_participant(payload.user_id)
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
            self.event_id = c.lastrowid

        await self.bot.db.commit()

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

    async def _add_participant(self, user_id, role):
        """Add a user to the events with the given role."""

        await self.bot.db.execute(
            """
            INSERT INTO eventeso_participant
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

    async def _remove_participant(self, user_id):
        """Remove the user from the event."""

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
