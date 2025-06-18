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

MONITOR_CHANNEL_ID = 1384853874967449640
LOG_CHANNEL_ID = 1384854378820800675

reaction_signups = defaultdict(lambda: defaultdict(set))
message_log_msg_map = {}  # Maps message ID to summary message ID
message_thread_map = {}   # Maps message ID to thread object

# Emoji ID mapping to roles
EMOJI_LABELS = {
    718534017082720339: ("Support", 0xFFA500),
    1025015433054662676: (":csw:", 0xADD8E6),
    1091115981788684318: (":renegade:", None),
    1025067188102643853: (":trident:", 0x0000FF),
    1025067230347661412: (":athena:", None),
    792085274149519420: (":pathfinder:", None),
    663134181089607727: ("Not attending", None),
}

SPECIAL_LABELS = {
    663134181089607727: "Not attending",
    663134181089607728: "Late"
}

def log_line(user: discord.User, emoji: discord.PartialEmoji, action: str):
    time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"[{time_str}] {user} {action} reaction {emoji}"

async def get_announcement_title(message):
    lines = message.content.splitlines()
    for line in lines:
        if line.strip() and not line.strip().startswith("<@"):
            return line.strip()
    return f"Reactions for msg {message.id}"

async def get_or_create_thread(log_channel: discord.TextChannel, message):
    if message.id in message_thread_map:
        return message_thread_map[message.id]

    title = await get_announcement_title(message)
    thread = await log_channel.create_thread(
        name=title,
        auto_archive_duration=1440
    )
    message_thread_map[message.id] = thread

    # Post link to thread
    await log_channel.send(f"Thread created for **{title}**: {thread.jump_url}")
    return thread

async def post_or_edit_summary(log_channel, announcement_msg, message_id):
    title = await get_announcement_title(announcement_msg)
    timestamp = next((word for word in announcement_msg.content.split() if word.startswith("<t:")), "")
    header = f"📋 **Sign-Ups for {title} {timestamp}**"

    emoji_data = reaction_signups[message_id]
    table_lines = [header]

    for emoji, users in emoji_data.items():
        if users:
            label = emoji
            count_str = f"**{len(users)}**"
            try:
                emoji_id = int(emoji.split(':')[2][:-1]) if emoji.startswith('<:') else None
            except:
                emoji_id = None

            if emoji_id in EMOJI_LABELS:
                role_label, _ = EMOJI_LABELS[emoji_id]
                label = f"{emoji} {count_str} {role_label}"
            elif emoji_id in SPECIAL_LABELS:
                label = f"{count_str} {SPECIAL_LABELS[emoji_id]}"
            else:
                label = f"{emoji} {count_str} signed up"

            table_lines.append(label)
            for user in sorted(users):
                table_lines.append(f"- {user}")
            table_lines.append("")

    summary = "\n".join(table_lines)

    if message_id in message_log_msg_map:
        try:
            prev_msg = await log_channel.fetch_message(message_log_msg_map[message_id])
            await prev_msg.edit(content=summary)
            return
        except:
            pass

    msg = await log_channel.send(summary)
    message_log_msg_map[message_id] = msg.id

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return

    guild = bot.get_guild(payload.guild_id)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    message = await guild.get_channel(payload.channel_id).fetch_message(payload.message_id)
    thread = await get_or_create_thread(log_channel, message)
    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji = str(payload.emoji)

    reaction_signups[payload.message_id][emoji].add(user.name)

    await thread.send(log_line(user, emoji, "added"))
    await post_or_edit_summary(log_channel, message, payload.message_id)

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return

    guild = bot.get_guild(payload.guild_id)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    message = await guild.get_channel(payload.channel_id).fetch_message(payload.message_id)
    thread = await get_or_create_thread(log_channel, message)
    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji = str(payload.emoji)

    if user.name in reaction_signups[payload.message_id][emoji]:
        reaction_signups[payload.message_id][emoji].remove(user.name)
        if not reaction_signups[payload.message_id][emoji]:
            del reaction_signups[payload.message_id][emoji]

    await thread.send(log_line(user, emoji, "removed"))
    await post_or_edit_summary(log_channel, message, payload.message_id)

if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ["BOT_TOKEN"])
