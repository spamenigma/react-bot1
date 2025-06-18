import os
import discord
from discord.ext import commands
from datetime import datetime
from collections import defaultdict
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

MONITOR_CHANNEL_ID = 1384853874967449640  # Where reactions happen
LOG_CHANNEL_ID = 1384854378820800675      # Where threads and logs go

# Map emoji ID or name to custom labels
EMOJI_LABELS = {
    "⏳": "Late",
    1240593798098749500: "Not attending",  # :cross~1:
}

# Store sign-ups per emoji per message
reaction_signups = defaultdict(lambda: defaultdict(set))


def describe_emoji(emoji: discord.PartialEmoji) -> str:
    if emoji.id in EMOJI_LABELS:
        return EMOJI_LABELS[emoji.id]
    if emoji.name in EMOJI_LABELS:
        return EMOJI_LABELS[emoji.name]
    return str(emoji)


def log_line(user: discord.User, emoji: discord.PartialEmoji, action: str):
    time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"[{time_str}] {user} {action} reaction {describe_emoji(emoji)}"


async def get_or_create_thread(log_channel: discord.TextChannel, message: discord.Message):
    message_id = message.id
    active_threads = [thread for thread in log_channel.threads if not thread.archived]
    for thread in active_threads:
        if thread.name.endswith(f"{message_id}"):
            return thread
    title = message.content.splitlines()[0][:80] or f"Reactions for msg {message_id}"
    thread_name = f"{title} ({message_id})"
    thread = await log_channel.create_thread(
        name=thread_name,
        auto_archive_duration=1440
    )
    # Post message linking to the thread
    await log_channel.send(f"📌 [Reaction thread for this announcement]({thread.jump_url})")
    return thread


async def post_summary(thread: discord.Thread, message_id: int):
    table_lines = ["\n📋 **Sign-up Summary**"]
    emoji_data = reaction_signups[message_id]
    for emoji, users in emoji_data.items():
        if users:
            table_lines.append(f"{describe_emoji(emoji)} **{len(users)} signed up:**")
            for user in sorted(users):
                table_lines.append(f"- {user}")
            table_lines.append("")
    if len(table_lines) > 1:
        await thread.send("\n".join(table_lines))


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return
    guild = bot.get_guild(payload.guild_id)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    try:
        message = await guild.get_channel(payload.channel_id).fetch_message(payload.message_id)
    except Exception:
        return

    thread = await get_or_create_thread(log_channel, message)
    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji = payload.emoji

    # Track reaction
    reaction_signups[payload.message_id][emoji].add(user.name)

    await thread.send(log_line(user, emoji, "added"))
    await post_summary(thread, payload.message_id)


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return
    guild = bot.get_guild(payload.guild_id)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    try:
        message = await guild.get_channel(payload.channel_id).fetch_message(payload.message_id)
    except Exception:
        return

    thread = await get_or_create_thread(log_channel, message)
    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji = payload.emoji

    # Remove reaction
    if user.name in reaction_signups[payload.message_id][emoji]:
        reaction_signups[payload.message_id][emoji].remove(user.name)
        if not reaction_signups[payload.message_id][emoji]:
            del reaction_signups[payload.message_id][emoji]

    await thread.send(log_line(user, emoji, "removed"))
    await post_summary(thread, payload.message_id)


if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ["BOT_TOKEN"])
