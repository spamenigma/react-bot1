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
    1025015433054662676: ("<:Carrier_Star_Wing:1025015433054662676> Carrier Star Wing", None),
    718534017082720339: ("<:1_:718534017082720339> Squadron 1", None),
    663133357592412181: ("<:greentick:663133357592412181> Attending", None),
    1025067230347661412: ("<:Athena_Training_SQN:1025067230347661412> Athena Training", None),
    663134181089607727: ("🚫 Not attending", None),
    792085274149519420: ("<:pathfinders:792085274149519420> Pathfinders", None),
    1025067188102643853: ("<:Trident:1025067188102643853> Trident", None),
    1091115981788684318: ("<:RenegadeLogov2:1091115981788684318> Renegade", None),
    # Unicode: "⏳": ("⏳ Late", None),
}

LATE_EMOJI_IDS = {123456789012345678}  # Replace with actual Late emoji IDs
NOT_ATTENDING_IDS = {663134181089607727}  # Cross emoji

# Updated regex patterns
TIMESTAMP_F_RE = re.compile(r"<t:(\d+):F>")  # Match Discord :F timestamps
PING_RE = re.compile(r"^<@!?(\d+)>$")  # Match user mentions
ROLE_MENTION_RE = re.compile(r"^<@&(\d+)>$")  # Match role mentions
MIXED_MENTIONS_RE = re.compile(r"^(<@[!&]?\d+>\s*)+$")  # Match lines with only mentions

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    
    # Sync reactions from recent messages on startup
    await sync_recent_reactions()

async def sync_recent_reactions(limit=10):
    """
    Sync reactions from the last N messages in the monitor channel.
    This rebuilds our reaction tracking from Discord's actual data.
    """
    print(f"Syncing reactions from last {limit} messages...")
    
    try:
        monitor_channel = bot.get_channel(MONITOR_CHANNEL_ID)
        if not monitor_channel:
            print("Monitor channel not found!")
            return
        
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if not log_channel:
            print("Log channel not found!")
            return
        
        # Clear existing data
        reaction_signups.clear()
        summary_messages.clear()
        summary_threads.clear()
        
        # Get recent messages
        messages = []
        async for message in monitor_channel.history(limit=limit):
            if message.reactions:  # Only process messages with reactions
                messages.append(message)
        
        print(f"Found {len(messages)} messages with reactions")
        
        # Process each message's reactions
        for message in messages:
            print(f"Processing message {message.id}...")
            
            for reaction in message.reactions:
                emoji_str = str(reaction.emoji)
                
                # Get all users who reacted (excluding bots)
                async for user in reaction.users():
                    if not user.bot:
                        reaction_signups[message.id][emoji_str].add(user.name)
                        print(f"  Added {user.name} to {emoji_str}")
        
        print("Reaction sync completed!")
        
        # Create/update summaries for all synced messages
        await create_summaries_for_synced_messages(messages, log_channel)
        
    except Exception as e:
        print(f"Error during reaction sync: {e}")

async def create_summaries_for_synced_messages(messages, log_channel):
    """Create or update summary messages for all synced messages"""
    try:
        for message in messages:
            if message.id in reaction_signups:
                title, timestamp_str = extract_title_and_timestamp(message.content)
                await post_or_edit_summary_and_get_thread(log_channel, message.id, title, timestamp_str)
                print(f"Created/updated summary for: {title}")
    
    except Exception as e:
        print(f"Error creating summaries: {e}")

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
    if hasattr(emoji_obj, "id") and emoji_obj.id and emoji_obj.id in EMOJI_MAP:
        label, color = EMOJI_MAP[emoji_obj.id]
        return label, color
    # Fall back to unicode or name string
    name = str(emoji_obj)
    # Special case Late and Not attending emojis by name if needed here
    if name == "⏳":
        return "⏳ Late", None
    if (name == "❌" or name == ":cross~1:" or "cross" in name.lower() or 
        name == "<:cross:663134181089607727>" or ":cross:" in name):
        return "🚫 Not attending", None
    # For custom emojis, try to display them properly
    if hasattr(emoji_obj, 'name') and hasattr(emoji_obj, 'id') and emoji_obj.id:
        # Custom emoji - use the emoji itself as display with a clean name
        emoji_display = f"<:{emoji_obj.name}:{emoji_obj.id}>"
        clean_name = emoji_obj.name.replace('_', ' ').title()
        return f"{emoji_display} {clean_name}", None
    # Default fallback - try to make a clean display
    if name.startswith(':') and name.endswith(':'):
        clean_name = name.strip(':').replace('_', ' ').title()
        return f"{name} {clean_name}", None
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
    
    # Calculate unique attendees (excluding "Not attending" and "Late")
    unique_attendees = set()
    for emoji_key, users in emoji_data.items():
        label, _ = emoji_display_and_label(discord.PartialEmoji.from_str(emoji_key))
        if "Not attending" not in label and "Late" not in label:
            unique_attendees.update(users)
    
    total_attending = len(unique_attendees)
    
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
    
    # Send an initial message in the thread (but don't link to it in main channel)
    try:
        await thread.send(f"🧵 **Reaction log for: {title}**\nAll reaction changes will be logged here.")
    except Exception as e:
        print(f"Failed to send initial thread message: {e}")
    
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

    # Return thread without posting any link message
    return thread

def log_line(user: discord.User, emoji: discord.PartialEmoji, action: str):
    time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    # Handle custom emoji display properly
    if hasattr(emoji, 'id') and emoji.id:
        # Custom emoji - use proper format
        emoji_display = f"<:{emoji.name}:{emoji.id}>"
    else:
        # Unicode emoji
        emoji_display = str(emoji)
    return f"[{time_str}] {user.display_name} {action} reaction {emoji_display}"

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

@bot.command(name="sync_reactions")
async def manual_sync_reactions(ctx, limit: int = 10):
    """Manually sync reactions from recent messages"""
    if ctx.channel.id != LOG_CHANNEL_ID:
        await ctx.send("This command can only be used in the log channel.")
        return
    
    await ctx.send(f"🔄 Syncing reactions from last {limit} messages...")
    await sync_recent_reactions(limit)
    await ctx.send("✅ Reaction sync completed!")

@bot.command(name="debug_reactions")
async def debug_reactions(ctx, message_id: int):
    """Debug command to see current reaction data for a message"""
    if message_id in reaction_signups:
        embed = discord.Embed(title=f"Debug: Reaction Data for {message_id}", color=0x00FFFF)
        for emoji_key, users in reaction_signups[message_id].items():
            embed.add_field(
                name=f"Emoji: {emoji_key}",
                value=f"Users: {', '.join(users) if users else 'None'}",
                inline=False
            )
        await ctx.send(embed=embed)
    else:
        await ctx.send(f"No reaction data found for message {message_id}")

@bot.command(name="refresh_summary")
async def refresh_summary(ctx, message_id: int):
    """Manually refresh a summary for a specific message"""
    if ctx.channel.id != LOG_CHANNEL_ID:
        await ctx.send("This command can only be used in the log channel.")
        return
    
    try:
        monitor_channel = bot.get_channel(MONITOR_CHANNEL_ID)
        message = await monitor_channel.fetch_message(message_id)
        title, timestamp_str = extract_title_and_timestamp(message.content)
        
        await post_or_edit_summary_and_get_thread(ctx.channel, message_id, title, timestamp_str)
        await ctx.send(f"✅ Refreshed summary for: {title}")
    except Exception as e:
        await ctx.send(f"❌ Error refreshing summary: {e}")

@bot.command(name="show_current_reactions")
async def show_current_reactions(ctx, message_id: int):
    """Show what reactions Discord sees on a message"""
    try:
        monitor_channel = bot.get_channel(MONITOR_CHANNEL_ID)
        message = await monitor_channel.fetch_message(message_id)
        
        embed = discord.Embed(title=f"Current Reactions on Message {message_id}", color=0xFFFF00)
        
        if message.reactions:
            for reaction in message.reactions:
                users = []
                async for user in reaction.users():
                    if not user.bot:  # Skip bot reactions
                        users.append(user.display_name)
                
                emoji_info = f"Emoji: {reaction.emoji}"
                if hasattr(reaction.emoji, 'id') and reaction.emoji.id:
                    emoji_info += f" (ID: {reaction.emoji.id})"
                
                embed.add_field(
                    name=emoji_info,
                    value=f"Count: {reaction.count}\nUsers: {', '.join(users) if users else 'None'}",
                    inline=False
                )
        else:
            embed.description = "No reactions found on this message."
        
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Error: {e}")

@bot.command(name="get_emoji_map")
async def get_emoji_map(ctx, message_id: int):
    """Generate a proper EMOJI_MAP from a message's reactions"""
    try:
        monitor_channel = bot.get_channel(MONITOR_CHANNEL_ID)
        message = await monitor_channel.fetch_message(message_id)
        
        if not message.reactions:
            await ctx.send("No reactions found on this message.")
            return
        
        emoji_map_code = "EMOJI_MAP = {\n"
        
        for reaction in message.reactions:
            if hasattr(reaction.emoji, 'id') and reaction.emoji.id:
                # Custom emoji
                emoji_name = reaction.emoji.name
                emoji_id = reaction.emoji.id
                emoji_display = f"<:{emoji_name}:{emoji_id}>"
                
                # Generate a reasonable label based on emoji name
                label = f"{emoji_display} {emoji_name.title()}"
                
                emoji_map_code += f"    {emoji_id}: (\"{label}\", None),\n"
            else:
                # Unicode emoji
                emoji_str = str(reaction.emoji)
                
                # Try to give it a meaningful name
                if emoji_str == "❌":
                    label = "🚫 Not attending"
                elif emoji_str == "⏳":
                    label = "⏳ Late"
                elif emoji_str == "✅":
                    label = "✅ Attending"
                else:
                    label = f"{emoji_str} React"
                
                emoji_map_code += f"    # Unicode: \"{emoji_str}\": (\"{label}\", None),\n"
        
        emoji_map_code += "}"
        
        # Send as code block
        await ctx.send(f"```python\n{emoji_map_code}\n```")
        await ctx.send("Copy this code and replace your current EMOJI_MAP!")
        
    except Exception as e:
        await ctx.send(f"❌ Error: {e}")

@bot.command(name="clear_all_logs")
async def clear_all_logs(ctx, confirm: str = None):
    """Delete all messages in the log channel (for testing)"""
    if ctx.channel.id != LOG_CHANNEL_ID:
        await ctx.send("This command can only be used in the log channel.")
        return
    
    if confirm != "CONFIRM":
        await ctx.send("⚠️ **WARNING**: This will delete ALL messages in this channel!\n"
                      "To confirm, use: `!clear_all_logs CONFIRM`")
        return
    
    try:
        await ctx.send("🗑️ Starting to clear all logs...")
        
        # Clear bot's cache first
        summary_messages.clear()
        
        deleted_count = 0
        
        # Delete messages in batches (Discord has limits)
        async for message in ctx.channel.history(limit=None):
            try:
                await message.delete()
                deleted_count += 1
                
                # Add small delay to avoid rate limits
                if deleted_count % 10 == 0:
                    await ctx.send(f"Deleted {deleted_count} messages...", delete_after=3)
                    
            except discord.NotFound:
                # Message already deleted
                pass
            except discord.Forbidden:
                await ctx.send(f"❌ Permission denied deleting message {message.id}")
                break
            except Exception as e:
                print(f"Error deleting message: {e}")
        
        # Send final confirmation (this will be the only message left)
        await ctx.send(f"✅ Cleared {deleted_count} messages from log channel!")
        
    except Exception as e:
        await ctx.send(f"❌ Error clearing logs: {e}")

@bot.command(name="clear_all_threads")
async def clear_all_threads(ctx, confirm: str = None):
    """Delete all threads in the log channel (for testing)"""
    if ctx.channel.id != LOG_CHANNEL_ID:
        await ctx.send("This command can only be used in the log channel.")
        return
    
    if confirm != "CONFIRM":
        await ctx.send("⚠️ **WARNING**: This will delete ALL threads in this channel!\n"
                      "To confirm, use: `!clear_all_threads CONFIRM`")
        return
    
    try:
        await ctx.send("🧵 Starting to clear all threads...")
        
        # Clear bot's cache first
        summary_threads.clear()
        
        deleted_count = 0
        
        # Get all threads (active and archived)
        active_threads = ctx.channel.threads
        
        # Also get archived threads
        archived_threads = []
        async for thread in ctx.channel.archived_threads(limit=None):
            archived_threads.append(thread)
        
        all_threads = active_threads + archived_threads
        
        for thread in all_threads:
            try:
                await thread.delete()
                deleted_count += 1
                print(f"Deleted thread: {thread.name}")
                
            except discord.NotFound:
                # Thread already deleted
                pass
            except discord.Forbidden:
                await ctx.send(f"❌ Permission denied deleting thread {thread.name}")
            except Exception as e:
                print(f"Error deleting thread {thread.name}: {e}")
        
        await ctx.send(f"✅ Cleared {deleted_count} threads from log channel!")
        
    except Exception as e:
        await ctx.send(f"❌ Error clearing threads: {e}")

@bot.command(name="clear_all_data")
async def clear_all_data(ctx, confirm: str = None):
    """Clear all bot data, logs, and threads (nuclear option for testing)"""
    if ctx.channel.id != LOG_CHANNEL_ID:
        await ctx.send("This command can only be used in the log channel.")
        return
    
    if confirm != "NUCLEAR":
        await ctx.send("⚠️ **NUCLEAR WARNING**: This will:\n"
                      "• Delete ALL messages in this channel\n"
                      "• Delete ALL threads in this channel\n"
                      "• Clear ALL bot reaction data\n"
                      "To confirm, use: `!clear_all_data NUCLEAR`")
        return
    
    try:
        await ctx.send("💥 NUCLEAR CLEANUP INITIATED...")
        
        # Clear all bot data
        reaction_signups.clear()
        summary_messages.clear()
        summary_threads.clear()
        
        # Clear threads first
        await clear_all_threads(ctx, "CONFIRM")
        
        # Then clear messages
        await clear_all_logs(ctx, "CONFIRM")
        
        # Final message
        await ctx.send("💥 **NUCLEAR CLEANUP COMPLETE!**\n"
                      "All data, logs, and threads have been cleared.\n"
                      "Ready for fresh testing!")
        
    except Exception as e:
        await ctx.send(f"❌ Error during nuclear cleanup: {e}")

@bot.command(name="debug_emoji_detection")
async def debug_emoji_detection(ctx, message_id: int):
    """Debug what emoji data we're actually getting from Discord"""
    try:
        monitor_channel = bot.get_channel(MONITOR_CHANNEL_ID)
        message = await monitor_channel.fetch_message(message_id)
        
        embed = discord.Embed(title=f"Emoji Debug for Message {message_id}", color=0xFF0000)
        
        if message.reactions:
            for reaction in message.reactions:
                emoji = reaction.emoji
                
                # Get detailed emoji info
                emoji_info = f"str(emoji): {str(emoji)}\n"
                if hasattr(emoji, 'name'):
                    emoji_info += f"emoji.name: {emoji.name}\n"
                if hasattr(emoji, 'id'):
                    emoji_info += f"emoji.id: {emoji.id}\n"
                
                # Test our label function
                label, _ = emoji_display_and_label(emoji)
                emoji_info += f"Our label: {label}\n"
                
                # Check if it's in our map
                if hasattr(emoji, 'id') and emoji.id and emoji.id in EMOJI_MAP:
                    emoji_info += f"Found in EMOJI_MAP: {EMOJI_MAP[emoji.id][0]}"
                else:
                    emoji_info += "NOT in EMOJI_MAP"
                
                embed.add_field(
                    name=f"Reaction: {emoji}",
                    value=f"```{emoji_info}```",
                    inline=False
                )
        else:
            embed.description = "No reactions found on this message."
        
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Error: {e}")

@bot.command(name="test_status")
async def test_status(ctx):
    """Show current bot status for testing"""
    embed = discord.Embed(title="🧪 Bot Test Status", color=0x00FFFF)
    
    # Reaction data
    total_messages = len(reaction_signups)
    total_reactions = sum(len(emojis) for emojis in reaction_signups.values())
    
    embed.add_field(
        name="📊 Data Status",
        value=f"Tracking {total_messages} messages\n"
              f"With {total_reactions} different reactions",
        inline=False
    )
    
    # Summary messages
    embed.add_field(
        name="📋 Summary Status",
        value=f"Active summaries: {len(summary_messages)}\n"
              f"Active threads: {len(summary_threads)}",
        inline=False
    )
    
    # Channel info
    embed.add_field(
        name="🎯 Channel Config",
        value=f"Monitor: <#{MONITOR_CHANNEL_ID}>\n"
              f"Logs: <#{LOG_CHANNEL_ID}>",
        inline=False
    )
    
    await ctx.send(embed=embed)

if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ["BOT_TOKEN"])
