import os
import discord
from discord.ext import commands
from datetime import datetime
from collections import defaultdict
import re
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

MONITOR_CHANNEL_ID = 1384853874967449640  # Where reactions happen
LOG_CHANNEL_ID = 1384854378820800675      # Where logs & threads go

# Store sign-ups per emoji per message
reaction_signups = defaultdict(lambda: defaultdict(set))

# Cache summary messages and threads per monitored message
summary_messages = {}
summary_threads = {}

# Emoji ID mappings for wording and emoji display
EMOJI_MAP = {
    718534017082720339: ("🧡 Support", 0xFFA500),               # Support orange
    1025015433054662676: ("💙 CSW", 0xADD8E6),                 # CSW light blue
    1091115981788684318: ("💚 Renegade", 0x00FF00),
    1025067188102643853: ("💙 Trident", 0x0000FF),             # Trident blue
    1025067230347661412: ("💜 Athena", 0x800080),
    792085274149519420: ("🏹 Pathfinder", None),               # Use emoji, no color
    663134181089607727: ("🚫 Not attending", None),            # Cross emoji ID
    123456789012345678: ("⏳ Late", None),                      # Placeholder Late emoji ID
}

LATE_EMOJI_IDS = {123456789012345678}  # Replace with actual Late emoji IDs
NOT_ATTENDING_IDS = {663134181089607727}  # Replace with actual cross emoji IDs

# Updated regex patterns
TIMESTAMP_F_RE = re.compile(r"<t:(\d+):F>")  # Match Discord :F timestamps
PING_RE = re.compile(r"^<@!?(\d+)>$")  # Match user mentions
ROLE_MENTION_RE = re.compile(r"^<@&(\d+)>$")  # Match role mentions
MIXED_MENTIONS_RE = re.compile(r"^(<@[!&]?\d+>\s*)+$")  # Match lines with only mentions

def extract_title_and_timestamp(content: str):
    """
    Extract title and timestamp from message content.
    Skip lines that contain only mentions (user or role pings).
    """
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    
    if not lines:
        return "Sign-Ups", ""
    
    title = None
    
    # Find the first line that isn't just mentions
    for line in lines:
        # Skip lines that are only mentions (users or roles)
        if MIXED_MENTIONS_RE.match(line):
            continue
        
        # Skip lines that are just a single user mention
        if PING_RE.match(line):
            continue
            
        # Skip lines that are just a single role mention
        if ROLE_MENTION_RE.match(line):
            continue
        
        # This line has actual content, use it as title
        title = line
        break
    
    # Fallback if no suitable title found
    if not title:
        title = "Sign-Ups"
    
    # Extract timestamp
    timestamp_str = ""
    match = TIMESTAMP_F_RE.search(content)
    if match:
        ts = int(match.group(1))
        dt = datetime.utcfromtimestamp(ts)
        timestamp_str = dt.strftime("%A, %d %B %Y %H:%M UTC")
    
    return title, timestamp_str

def emoji_display_and_label(emoji_obj):
    # Match by ID first if possible
    if hasattr(emoji_obj, "id") and emoji_obj.id in EMOJI_MAP:
        label, color = EMOJI_MAP[emoji_obj.id]
        return label, color
    # Fall back to unicode or name string
    name = str(emoji_obj)
    # Special case Late and Not attending emojis by name if needed here
    if name == "⏳":
        return "⏳ Late", None
    if name == "❌" or name == ":cross~1:":
        return "🚫 Not attending", None
    # Default label is emoji itself, no color
    return name, None

def build_summary_embed(message_id, title, timestamp_str):
    """Build a rich embed with names listed one per line under each reaction"""
    emoji_data = reaction_signups[message_id]
    
    if not emoji_data:
        embed = discord.Embed(
            title="📋 No sign-ups yet", 
            description="Be the first to react!",
            color=0x808080  # Gray color
        )
        return embed
    
    # Calculate total attendees (excluding "Not attending" and "Late")
    total_attending = 0
    for emoji_key, users in emoji_data.items():
        label, _ = emoji_display_and_label(discord.PartialEmoji.from_str(emoji_key))
        if "Not attending" not in label and "Late" not in label:
            total_attending += len(users)
    
    # Main embed with title and color
    embed = discord.Embed(
        title=f"📋 {title}",
        description=f"**{total_attending}** total attending",
        color=0x00FF00  # Green for active event
    )
    
    # Add timestamp if available
    if timestamp_str:
        embed.add_field(
            name="⏰ Event Time", 
            value=f"```{timestamp_str}```", 
            inline=False
        )
    
    # Sort reactions to show attending first, then others
    attending_reactions = []
    other_reactions = []
    
    for emoji_key, users in emoji_data.items():
        if not users:
            continue
            
        label, color = emoji_display_and_label(discord.PartialEmoji.from_str(emoji_key))
        
        if "Not attending" in label or "Late" in label:
            other_reactions.append((emoji_key, users, label))
        else:
            attending_reactions.append((emoji_key, users, label))
    
    # Add attending reactions first
    for emoji_key, users, label in attending_reactions:
        count = len(users)
        
        # Create field name with count
        field_name = f"{label} ({count})"
        
        # Create value with names one per line
        if users:
            user_list = "\n".join([f"• {user}" for user in sorted(users)])
        else:
            user_list = "None"
        
        # Discord field value limit is 1024 characters
        if len(user_list) > 1024:
            # Truncate and add indication
            user_list = user_list[:1020] + "..."
        
        embed.add_field(
            name=field_name,
            value=user_list,
            inline=True  # Allow multiple columns if they fit
        )
    
    # Add other reactions (Late, Not attending)
    for emoji_key, users, label in other_reactions:
        count = len(users)
        
        # Create field name with count
        field_name = f"{label} ({count})"
        
        # Create value with names one per line
        if users:
            user_list = "\n".join([f"• {user}" for user in sorted(users)])
        else:
            user_list = "None"
        
        # Discord field value limit is 1024 characters
        if len(user_list) > 1024:
            user_list = user_list[:1020] + "..."
        
        embed.add_field(
            name=field_name,
            value=user_list,
            inline=True
        )
    
    # Add footer with last updated time
    embed.set_footer(text=f"Last updated: {datetime.utcnow().strftime('%H:%M UTC')}")
    
    return embed

async def get_or_create_thread_for_summary(summary_message: discord.Message, title: str):
    try:
        if summary_message.id in summary_threads:
            thread = summary_threads[summary_message.id]
            # Confirm thread still exists
            await thread.fetch()
            return thread, False
    except (discord.NotFound, AttributeError):
        summary_threads.pop(summary_message.id, None)

    # Create new thread if missing or invalid
    thread = await summary_message.create_thread(
        name=f"Reactions for {title}",
        auto_archive_duration=1440
    )
    summary_threads[summary_message.id] = thread
    return thread, True

async def post_or_edit_summary_and_get_thread(log_channel, message_id, title, timestamp_str):
    # Build embed instead of text
    summary_embed = build_summary_embed(message_id, title, timestamp_str)
    summary_message = None

    if message_id in summary_messages:
        try:
            summary_message = summary_messages[message_id]
            await summary_message.edit(embed=summary_embed)
        except discord.NotFound:
            summary_messages.pop(message_id, None)

    if summary_message is None:
        summary_message = await log_channel.send(embed=summary_embed)
        summary_messages[message_id] = summary_message

    thread, created = await get_or_create_thread_for_summary(summary_message, title)

    # If just created, post a link message in logs channel
    if created:
        try:
            link_msg = await log_channel.send(f"Created thread for {title} → {thread.mention}")
            # Optionally store or pin link_msg if needed
        except Exception as e:
            print(f"Failed to send thread link message: {e}")

    return thread

def log_line(user: discord.User, emoji: discord.PartialEmoji, action: str):
    time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"[{time_str}] {user} {action} reaction {emoji}"

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    if not log_channel:
        return
    try:
        monitor_channel = guild.get_channel(payload.channel_id)
        message = await monitor_channel.fetch_message(payload.message_id)
    except Exception:
        return

    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji_str = str(payload.emoji)

    # Track sign-up
    reaction_signups[payload.message_id][emoji_str].add(user.name)

    title, timestamp_str = extract_title_and_timestamp(message.content)
    thread = await post_or_edit_summary_and_get_thread(log_channel, payload.message_id, title, timestamp_str)

    try:
        await thread.send(log_line(user, payload.emoji, "added"))
    except Exception as e:
        print(f"Failed to send add log in thread: {e}")

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    if not log_channel:
        return
    try:
        monitor_channel = guild.get_channel(payload.channel_id)
        message = await monitor_channel.fetch_message(payload.message_id)
    except Exception:
        return

    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji_str = str(payload.emoji)

    # Remove sign-up
    if user.name in reaction_signups[payload.message_id][emoji_str]:
        reaction_signups[payload.message_id][emoji_str].remove(user.name)
        if not reaction_signups[payload.message_id][emoji_str]:
            del reaction_signups[payload.message_id][emoji_str]

    title, timestamp_str = extract_title_and_timestamp(message.content)
    thread = await post_or_edit_summary_and_get_thread(log_channel, payload.message_id, title, timestamp_str)

    try:
        await thread.send(log_line(user, payload.emoji, "removed"))
    except Exception as e:
        print(f"Failed to send remove log in thread: {e}")

if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ["BOT_TOKEN"])
