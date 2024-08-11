# TODO LIST (no particular order) Dealing with attachment. Dealing with all types of mentions.
# Dealing with edit/delete and syncing with Slack.
# Dealing with reply and thread.
from typing import Any, TYPE_CHECKING
import datetime
import logging

import discord
from discord.client import NotFound
from discord.ext import tasks

import config
from pipe import RelayedSlackMessage, send_discord_msg, recv_slack_msg

if TYPE_CHECKING:
    from multiprocessing.connection import Connection

handler = logging.FileHandler(filename="discord.log", encoding="utf-8", mode="w")

# Task that will be executed periodically.
# Docs: https://discordpy.readthedocs.io/en/latest/ext/tasks/index.html
# Poll for messages then relay to Discord.
@tasks.loop(seconds=2.0)
async def poll_msg(pipe: 'Connection', discord_client: 'MyClient') -> None:
    if (msg := recv_slack_msg(pipe)) is not None:
        await discord_client.relay_msg(msg)


# Docs for Discord py: https://discordpy.readthedocs.io/en/stable/
class MyClient(discord.Client):
    # Map from Slack's user_id to Discord's user_id
    SLACK_USER_MAP: dict[str, int] = config.SLACK_USER_MAP
    # This is for mention mapping.
    # Map from Discord's user_id to Slack's id
    DISCORD_USER_MAP: dict[int, str] = config.DISCORD_USER_MAP
    # # The channel the messages are to be relayed from Slack to Discord.
    # # If we want to have multiple channels then we can define a mapping
    # # between channels.
    # RELEVANT_CHANNEL_ID = config.DISCORD_RELEVANT_CHANNEL_ID
    SLACK_CHANNEL_MAP: dict[str, int] = config.SLACK_CHANNEL_MAP

    user_cache: dict[int, discord.User]

    def __init__(self, pipe: 'Connection', **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # Relevant channel to relay messages from Slack
        # Prob general idk
        self.relevant_channels: dict[str, discord.TextChannel] = {}
        self.pipe = pipe
        self.user_cache = {}

    # This is for cosmetics.
    async def on_ready(self) -> None:
        print(f'Logged on as {self.user}!')

    # Function that runs whenever a message is sent.
    async def on_message(self, message: discord.Message) -> None:
        if (message.author == self.user):
            return

        if message.channel.id not in config.DISCORD_CHANNEL_MAP:
            return
        
        send_discord_msg(self.pipe, {
            "content": self.mention_replace(message),
            "sender_id": message.author.id,
            "channel_id": message.channel.id
        })

    async def relay_msg(self, msg: RelayedSlackMessage, max_len: int = 2000) -> None:
        if len(msg['content']) == 0 or msg['channel_id'] not in self.SLACK_CHANNEL_MAP:
            return

        mapped_id = self.SLACK_CHANNEL_MAP[msg['channel_id']]

        if msg['channel_id'] not in self.relevant_channels:
            channel = await self.fetch_channel(mapped_id)
            if isinstance(channel, discord.TextChannel):  # this should always hold
                self.relevant_channels[msg['channel_id']] = channel
            else:
                return

        discord_id = None
        author = None

        if msg['sender_id'] in self.SLACK_USER_MAP:
            discord_id = self.SLACK_USER_MAP[msg['sender_id']]

        if discord_id is not None and discord_id not in self.user_cache:
            try:
                self.user_cache[discord_id] = await self.fetch_user(discord_id)
                author = self.user_cache[discord_id]
            except NotFound:
                print(f"Could not find user with id {discord_id}")
                return
            
        chunks = [msg['content'][i:i + max_len]
                  for i in range(0, len(msg['content']), max_len)]

        for chunk in chunks:
            await self.relevant_channels[msg['channel_id']].send(
                embed=self.echoed_message_embed(
                    author, chunk
                )
            )

    # The docs use this method to initiate the task.
    # Gonna do the same.
    async def setup_hook(self) -> None:
        poll_msg.start(self.pipe, self)

    # This function is not the most efficient thing in the world.
    # Feel free to optimise idk.
    def mention_replace(self, msg: discord.Message) -> str:
        mentions = msg.mentions
        msg_str = msg.content

        for user in mentions:
            if user.id not in self.DISCORD_USER_MAP:
                continue
            msg_str = msg_str.replace(
                f"<@{user.id}>", f"<@{self.DISCORD_USER_MAP[user.id]}>"
            )

        return msg_str

    def echoed_message_embed(self, 
                             author: discord.User | discord.Member | None,
                             text: str) -> discord.Embed:
        color = discord.Color.default()
        name = "Anon"
        icon_url = None
        
        if author is not None:
            color = author.color
            name = author.name
            icon_url = author.display_avatar.url
        
        return discord.Embed(
                title="Relayed From Slacks",
                description=text or "",
                color=color,
                timestamp=datetime.datetime.now(datetime.timezone.utc)
            ).set_author(name=name, icon_url=icon_url)


def run_bot(token: str, pipe: 'Connection') -> None:
    intents = discord.Intents.default()
    intents.message_content = True
    client = MyClient(pipe, intents=intents)

    client.run(token=token, log_handler=handler)
