def create_summary_view(message_id):
    """Create the button view for summary messages"""
    view = discord.ui.View(timeout=None)  # Persistent view
    
    # Export button
    export_button = discord.ui.Button(
        label="📊 Export Attendance",
        style=discord.ButtonStyle.primary,
        custom_id=f"export_{message_id}"
    )
    
    # Refresh button
    refresh_button = discord.ui.Button(
        label="🔄 Refresh",
        style=discord.ButtonStyle.secondary,
        custom_id=f"refresh_{message_id}"
    )
    
    # Thread button (opens the reaction log thread)
    thread_button = discord.ui.Button(
        label="🧵 View Logs",
        style=discord.ButtonStyle.secondary,
        custom_id=f"thread_{message_id}"
    )
    
    view.add_item(export_button)
    view.add_item(refresh_button)
    view.add_item(thread_button)
    
    return viewimport os
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
    1025015433054662676: ("Carrier Star Wing", None),
    718534017082720339: ("Squadron 1", None),
    663133357592412181: ("Attending", None),
    1025067230347661412: ("Athena Training", None),
    663134181089607727: ("Not attending", None),
    792085274149519420: ("Pathfinders", None),
    1025067188102643853: ("Trident", None),
    1091115981788684318: ("Renegade", None),
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
async def on_interaction(interaction: discord.Interaction):
    """Handle button clicks"""
    if not interaction.data or interaction.type != discord.InteractionType.component:
        return
    
    custom_id = interaction.data.get('custom_id')
    if not custom_id:
        return
    
    # Handle test buttons
    if custom_id == "test_export":
        await interaction.response.send_message("✅ Test export button works! The buttons are functioning correctly.", ephemeral=True)
        return
    elif custom_id == "test_refresh":
        await interaction.response.send_message("✅ Test refresh button works! The buttons are functioning correctly.", ephemeral=True)
        return
    
    # Parse the custom_id to get action and message_id for real buttons
    try:
        action, message_id_str = custom_id.split('_', 1)
        message_id = int(message_id_str)
    except (ValueError, AttributeError):
        await interaction.response.send_message("❌ Invalid button action.", ephemeral=True)
        return
    
    # Handle different button actions
    if action == "export":
        await handle_export_button(interaction, message_id)
    elif action == "refresh":
        await handle_refresh_button(interaction, message_id)
    elif action == "thread":
        await handle_thread_button(interaction, message_id)
    else:
        await interaction.response.send_message("❌ Unknown button action.", ephemeral=True)

async def handle_export_button(interaction: discord.Interaction, message_id: int):
    """Handle export button click"""
    try:
        await interaction.response.defer(ephemeral=True)
        
        monitor_channel = bot.get_channel(MONITOR_CHANNEL_ID)
        message = await monitor_channel.fetch_message(message_id)
        title, timestamp_str = extract_title_and_timestamp(message.content)
        
        if message_id not in reaction_signups:
            await interaction.followup.send("❌ No reaction data found for this message.", ephemeral=True)
            return
        
        emoji_data = reaction_signups[message_id]
        message_author_name = message.author.name
        
        # Build export text (same logic as export_attendance command)
        export_text = f"📊 **ATTENDANCE EXPORT**\n"
        export_text += f"📋 **Event:** {title}\n"
        if timestamp_str:
            export_text += f"⏰ **Time:** {timestamp_str}\n"
        export_text += f"📅 **Exported:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
        export_text += "=" * 50 + "\n\n"
        
        # Process reactions (same logic as before)
        attending_reactions = []
        not_attending_reactions = []
        late_reactions = []
        
        for emoji_key, users in emoji_data.items():
            if not users:
                continue
                
            label, _ = emoji_display_and_label(discord.PartialEmoji.from_str(emoji_key))
            
            try:
                emoji_obj = discord.PartialEmoji.from_str(emoji_key)
                if hasattr(emoji_obj, 'id') and emoji_obj.id and emoji_obj.id in EMOJI_MAP:
                    clean_name = EMOJI_MAP[emoji_obj.id][0]
                elif "Not attending" in label:
                    clean_name = "Not attending"
                elif "Late" in label:
                    clean_name = "Late"
                else:
                    clean_name = emoji_obj.name.replace('_', ' ').title() if hasattr(emoji_obj, 'name') else "Unknown"
            except:
                clean_name = label
            
            if "Not attending" in label:
                not_attending_reactions.append((clean_name, users))
            elif "Late" in label:
                late_reactions.append((clean_name, users))
            else:
                attending_reactions.append((clean_name, users))
        
        # Calculate totals
        unique_attending = set()
        for _, users in attending_reactions:
            unique_attending.update(users)
        
        if message_author_name in unique_attending:
            unique_attending.remove(message_author_name)
        
        total_attending = len(unique_attending)
        total_not_attending = sum(len(users) for _, users in not_attending_reactions)
        total_late = sum(len(users) for _, users in late_reactions)
        
        export_text += f"📈 **SUMMARY**\n"
        export_text += f"✅ Attending: {total_attending}\n"
        export_text += f"⏳ Late: {total_late}\n"
        export_text += f"❌ Not Attending: {total_not_attending}\n"
        export_text += f"👤 Event Creator: {message_author_name} (excluded from attending count)\n\n"
        
        # Add sections
        if attending_reactions:
            export_text += "✅ **ATTENDING**\n"
            for reaction_name, users in attending_reactions:
                filtered_users = [u for u in users if u != message_author_name]
                if filtered_users:
                    export_text += f"**{reaction_name}:** {', '.join(sorted(filtered_users))}\n"
            export_text += "\n"
        
        if late_reactions:
            export_text += "⏳ **LATE**\n"
            for reaction_name, users in late_reactions:
                filtered_users = [u for u in users if u != message_author_name]
                if filtered_users:
                    export_text += f"**{reaction_name}:** {', '.join(sorted(filtered_users))}\n"
            export_text += "\n"
        
        if not_attending_reactions:
            export_text += "❌ **NOT ATTENDING**\n"
            for reaction_name, users in not_attending_reactions:
                if users:
                    export_text += f"**{reaction_name}:** {', '.join(sorted(users))}\n"
            export_text += "\n"
        
        # Send as file if too long, otherwise as message
        if len(export_text) > 1900:
            import io
            file_name = f"attendance_{title.replace(' ', '_')}_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.txt"
            discord_file = discord.File(fp=io.BytesIO(export_text.encode('utf-8')), filename=file_name)
            await interaction.followup.send("📊 **Attendance Export:**", file=discord_file, ephemeral=True)
        else:
            await interaction.followup.send(f"```\n{export_text}\n```", ephemeral=True)
            
    except Exception as e:
        await interaction.followup.send(f"❌ Error exporting attendance: {e}", ephemeral=True)

async def handle_refresh_button(interaction: discord.Interaction, message_id: int):
    """Handle refresh button click"""
    try:
        await interaction.response.defer()
        
        monitor_channel = bot.get_channel(MONITOR_CHANNEL_ID)
        message = await monitor_channel.fetch_message(message_id)
        title, timestamp_str = extract_title_and_timestamp(message.content)
        
        # Refresh the summary
        await post_or_edit_summary_and_get_thread(interaction.channel, message_id, title, timestamp_str)
        
        await interaction.followup.send("✅ Summary refreshed!", ephemeral=True)
        
    except Exception as e:
        await interaction.followup.send(f"❌ Error refreshing: {e}", ephemeral=True)

async def handle_thread_button(interaction: discord.Interaction, message_id: int):
    """Handle thread button click - show link to the reaction log thread"""
    try:
        await interaction.response.defer(ephemeral=True)
        
        if message_id in summary_messages and message_id in summary_threads:
            thread = summary_threads[message_id]
            try:
                await thread.fetch()  # Check if thread still exists
                await interaction.followup.send(f"🧵 **Reaction Log Thread:** {thread.mention}", ephemeral=True)
            except discord.NotFound:
                await interaction.followup.send("❌ Thread not found. It may have been deleted or archived.", ephemeral=True)
        else:
            await interaction.followup.send("❌ No thread found for this event. Threads are created when reactions are logged.", ephemeral=True)
            
    except Exception as e:
        await interaction.followup.send(f"❌ Error accessing thread: {e}", ephemeral=True)

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
        
        # DON'T clear existing data - check what already exists
        # Find existing summary messages first
        existing_summaries = {}
        async for log_message in log_channel.history(limit=50):
            if log_message.author == bot.user and log_message.embeds:
                embed = log_message.embeds[0]
                # Try to extract message ID from embed or find a way to link it
                # For now, we'll store by embed title to avoid duplicates
                if embed.title and embed.title.startswith("📋"):
                    existing_summaries[embed.title] = log_message
        
        # Get recent messages from monitor channel
        messages = []
        async for message in monitor_channel.history(limit=limit):
            if message.reactions:  # Only process messages with reactions
                messages.append(message)
        
        print(f"Found {len(messages)} messages with reactions")
        
        # Process each message's reactions
        for message in messages:
            print(f"Processing message {message.id}...")
            
            # Clear data for this specific message only
            if message.id in reaction_signups:
                reaction_signups[message.id].clear()
            
            for reaction in message.reactions:
                emoji_str = str(reaction.emoji)
                
                # Get all users who reacted (excluding bots)
                async for user in reaction.users():
                    if not user.bot:
                        reaction_signups[message.id][emoji_str].add(user.name)
                        print(f"  Added {user.name} to {emoji_str}")
        
        print("Reaction sync completed!")
        
        # Create/update summaries for all synced messages
        await create_summaries_for_synced_messages(messages, log_channel, existing_summaries)
        
    except Exception as e:
        print(f"Error during reaction sync: {e}")

async def create_summaries_for_synced_messages(messages, log_channel, existing_summaries):
    """Create or update summary messages for all synced messages"""
    try:
        for message in messages:
            if message.id in reaction_signups:
                title, timestamp_str = extract_title_and_timestamp(message.content)
                embed_title = f"📋 {title}"
                
                # Check if we already have a summary for this title
                if embed_title in existing_summaries:
                    # Update existing summary
                    existing_message = existing_summaries[embed_title]
                    summary_messages[message.id] = existing_message
                    print(f"Found existing summary for: {title}")
                
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
        clean_name, color = EMOJI_MAP[emoji_obj.id]
        # Create the actual emoji display for Discord
        emoji_display = f"<:{emoji_obj.name}:{emoji_obj.id}>"
        return f"{emoji_display} {clean_name}", color
    
    # Fall back to unicode or name string
    name = str(emoji_obj)
    # Special case Late and Not attending emojis by name if needed here
    if name == "⏳":
        return "⏳ Late", None
    if (name == "❌" or name == ":cross~1:" or "cross" in name.lower() or 
        name == "<:cross:663134181089607727>" or ":cross:" in name):
        return "🚫 Not attending", None
    
    # For custom emojis not in our map, try to display them properly
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
    
    # For now, we can't easily get the message author in a sync function
    # We'll handle author exclusion in the async calling function if needed
    message_author_name = None
    
    # Calculate unique attendees (excluding "Not attending" and "Late")
    unique_attendees = set()
    for emoji_key, users in emoji_data.items():
        label, _ = emoji_display_and_label(discord.PartialEmoji.from_str(emoji_key))
        if "Not attending" not in label and "Late" not in label:
            # Exclude message author from count if we know who it is
            filtered_users = users.copy()
            if message_author_name and message_author_name in filtered_users:
                filtered_users.remove(message_author_name)
            unique_attendees.update(filtered_users)
    
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
        # Filter out message author for display (we'll improve this later)
        filtered_users = users.copy()
        # Note: message_author_name is None for now, but we keep the logic
        if message_author_name and message_author_name in filtered_users:
            filtered_users.remove(message_author_name)
        
        count = len(filtered_users)
        
        # Get clean name from EMOJI_MAP or create one
        try:
            emoji_obj = discord.PartialEmoji.from_str(emoji_key)
            if hasattr(emoji_obj, 'id') and emoji_obj.id and emoji_obj.id in EMOJI_MAP:
                clean_name = EMOJI_MAP[emoji_obj.id][0]
            else:
                clean_name = emoji_obj.name.replace('_', ' ').title() if hasattr(emoji_obj, 'name') else "Unknown"
            
            field_name = f"{clean_name} ({count})"
            # Try to reconstruct the proper emoji format for display
            if hasattr(emoji_obj, 'id') and emoji_obj.id:
                emoji_display = f"<:{emoji_obj.name}:{emoji_obj.id}>"
            else:
                emoji_display = str(emoji_obj)
            
        except:
            field_name = f"{label} ({count})"
            emoji_display = emoji_key
        
        # Create value with emoji and names (no bullets)
        if filtered_users:
            user_list = f"{emoji_display}\n" + "\n".join([user for user in sorted(filtered_users)])
        else:
            user_list = f"{emoji_display}\nNone"
        
        # Discord field value limit is 1024 characters
        if len(user_list) > 1024:
            user_list = user_list[:1020] + "..."
        
        embed.add_field(
            name=field_name,
            value=user_list,
            inline=True
        )
    
    # Add other reactions (Late, Not attending)
    for emoji_key, users, label in other_reactions:
        # For "Not attending", don't filter out author and don't show names
        if "Not attending" in label:
            count = len(users)
            
            try:
                emoji_obj = discord.PartialEmoji.from_str(emoji_key)
                if hasattr(emoji_obj, 'id') and emoji_obj.id and emoji_obj.id in EMOJI_MAP:
                    clean_name = EMOJI_MAP[emoji_obj.id][0]
                else:
                    clean_name = "Not attending"
                
                field_name = f"{clean_name} ({count})"
                # Try to reconstruct the proper emoji format for display
                if hasattr(emoji_obj, 'id') and emoji_obj.id:
                    emoji_display = f"<:{emoji_obj.name}:{emoji_obj.id}>"
                else:
                    emoji_display = "🚫"
                
            except:
                field_name = f"Not attending ({count})"
                emoji_display = "🚫"
            
            # For not attending, just show emoji and count, no names
            user_list = f"{emoji_display}\n{count} not attending"
            
        else:
            # For Late and other reactions, filter out message author
            filtered_users = users.copy()
            if message_author_name and message_author_name in filtered_users:
                filtered_users.remove(message_author_name)
            
            count = len(filtered_users)
            
            try:
                emoji_obj = discord.PartialEmoji.from_str(emoji_key)
                if hasattr(emoji_obj, 'id') and emoji_obj.id and emoji_obj.id in EMOJI_MAP:
                    clean_name = EMOJI_MAP[emoji_obj.id][0]
                elif "Late" in label:
                    clean_name = "Late"
                else:
                    clean_name = emoji_obj.name.replace('_', ' ').title() if hasattr(emoji_obj, 'name') else "Unknown"
                
                field_name = f"{clean_name} ({count})"
                # Try to reconstruct the proper emoji format for display
                if hasattr(emoji_obj, 'id') and emoji_obj.id:
                    emoji_display = f"<:{emoji_obj.name}:{emoji_obj.id}>"
                else:
                    emoji_display = str(emoji_obj)
                
            except:
                field_name = f"{label} ({count})"
                emoji_display = emoji_key
            
            # Create value with emoji and names (no bullets)
            if filtered_users:
                user_list = f"{emoji_display}\n" + "\n".join([user for user in sorted(filtered_users)])
            else:
                user_list = f"{emoji_display}\nNone"
        
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

async def get_or_create_thread_for_summary(summary_message: discord.Message, title: str, send_initial_log=False):
    try:
        if summary_message.id in summary_threads:
            thread = summary_threads[summary_message.id]
            # Confirm thread still exists
            await thread.fetch()
            return thread, False
    except (discord.NotFound, AttributeError):
        summary_threads.pop(summary_message.id, None)

    # Create new thread if missing or invalid - this creates it silently
    thread = await summary_message.create_thread(
        name=f"Reactions for {title}",
        auto_archive_duration=1440
    )
    summary_threads[summary_message.id] = thread
    
    # Only send initial message if specifically requested (when logging reactions)
    if send_initial_log:
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

    # DON'T create thread here - only create when actually needed for logging
    # thread, created = await get_or_create_thread_for_summary(summary_message, title)

    # Return None for thread since we're not creating it yet
    return None

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
    # Update summary
    await post_or_edit_summary_and_get_thread(log_channel, payload.message_id, title, timestamp_str)

    # ALWAYS create/get thread for logging - this was the issue!
    summary_message = summary_messages.get(payload.message_id)
    if summary_message:
        thread, created = await get_or_create_thread_for_summary(summary_message, title, send_initial_log=created)
        
        try:
            await thread.send(log_line(user, payload.emoji, "added"))
        except Exception as e:
            print(f"Failed to send add log in thread: {e}")
    else:
        print(f"Warning: No summary message found for {payload.message_id}")

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
    # Update summary
    await post_or_edit_summary_and_get_thread(log_channel, payload.message_id, title, timestamp_str)

    # ALWAYS create/get thread for logging
    summary_message = summary_messages.get(payload.message_id)
    if summary_message:
        thread, created = await get_or_create_thread_for_summary(summary_message, title, send_initial_log=created)
        
        try:
            await thread.send(log_line(user, payload.emoji, "removed"))
        except Exception as e:
            print(f"Failed to send remove log in thread: {e}")
    else:
        print(f"Warning: No summary message found for {payload.message_id}")

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

@bot.command(name="show_emoji_map")
async def show_emoji_map(ctx):
    """Display the current EMOJI_MAP configuration"""
    embed = discord.Embed(title="🗺️ Current Emoji Map Configuration", color=0x00FFFF)
    
    if not EMOJI_MAP:
        embed.description = "No emojis configured in EMOJI_MAP"
        await ctx.send(embed=embed)
        return
    
    # Show each emoji mapping
    for emoji_id, (clean_name, color) in EMOJI_MAP.items():
        # Try to reconstruct the emoji
        try:
            # Get the emoji from the guild
            guild_emoji = discord.utils.get(ctx.guild.emojis, id=emoji_id)
            if guild_emoji:
                emoji_display = str(guild_emoji)
                status = "✅ Found in server"
            else:
                emoji_display = f"<:unknown:{emoji_id}>"
                status = "❌ Not found in server"
        except:
            emoji_display = f"<:unknown:{emoji_id}>"
            status = "❌ Error"
        
        embed.add_field(
            name=f"ID: {emoji_id}",
            value=f"**Emoji:** {emoji_display}\n**Label:** {clean_name}\n**Status:** {status}",
            inline=True
        )
    
    # Add special unicode emojis info
    embed.add_field(
        name="Unicode Emojis",
        value="⏳ Late\n🚫 Not attending (❌, :cross:)",
        inline=False
    )
    
    await ctx.send(embed=embed)

@bot.command(name="test_emoji_in_server")
async def test_emoji_in_server(ctx, emoji_id: int):
    """Test if a specific emoji ID exists in the server"""
    try:
        guild_emoji = discord.utils.get(ctx.guild.emojis, id=emoji_id)
        if guild_emoji:
            embed = discord.Embed(title="✅ Emoji Found", color=0x00FF00)
            embed.add_field(name="Name", value=guild_emoji.name, inline=True)
            embed.add_field(name="ID", value=guild_emoji.id, inline=True)
            embed.add_field(name="Animated", value=guild_emoji.animated, inline=True)
            embed.add_field(name="Display", value=str(guild_emoji), inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"❌ Emoji with ID {emoji_id} not found in this server.")
    except Exception as e:
        await ctx.send(f"❌ Error testing emoji: {e}")

@bot.command(name="list_server_emojis")
async def list_server_emojis(ctx, search: str = None):
    """List all custom emojis available in the server"""
    guild_emojis = ctx.guild.emojis
    
    if not guild_emojis:
        await ctx.send("❌ No custom emojis found in this server.")
        return
    
    # Filter by search term if provided
    if search:
        guild_emojis = [e for e in guild_emojis if search.lower() in e.name.lower()]
        if not guild_emojis:
            await ctx.send(f"❌ No emojis found matching '{search}'.")
            return
    
    embed = discord.Embed(
        title=f"🎭 Server Emojis{f' (filtered: {search})' if search else ''}",
        color=0xFFD700
    )
    
    # Group emojis to avoid hitting embed limits
    emoji_text = ""
    count = 0
    
    for emoji in guild_emojis[:20]:  # Limit to first 20 to avoid embed limits
        emoji_text += f"{emoji} `:{emoji.name}:` (ID: {emoji.id})\n"
        count += 1
    
    if count < len(guild_emojis):
        emoji_text += f"\n... and {len(guild_emojis) - count} more emojis"
    
    embed.description = emoji_text
    embed.set_footer(text=f"Total: {len(ctx.guild.emojis)} emojis in server")
    
    await ctx.send(embed=embed)

@bot.command(name="debug_summary_buttons")
async def debug_summary_buttons(ctx, message_id: int):
    """Debug why buttons aren't showing on summaries"""
    try:
        # Check if we have a summary for this message
        if message_id in summary_messages:
            summary_msg = summary_messages[message_id]
            await ctx.send(f"✅ Found summary message: {summary_msg.jump_url}")
            
            # Try to manually add buttons to this summary
            monitor_channel = bot.get_channel(MONITOR_CHANNEL_ID)
            original_message = await monitor_channel.fetch_message(message_id)
            title, timestamp_str = extract_title_and_timestamp(original_message.content)
            
            # Build new embed and view
            summary_embed = build_summary_embed(message_id, title, timestamp_str)
            view = create_summary_view(message_id)
            
            # Force update with buttons
            await summary_msg.edit(embed=summary_embed, view=view)
            await ctx.send(f"🔄 Manually added buttons to summary for: {title}")
            
        else:
            await ctx.send(f"❌ No summary message found for message ID {message_id}")
            
    except Exception as e:
        await ctx.send(f"❌ Error: {e}")

@bot.command(name="add_buttons_to_all")
async def add_buttons_to_all(ctx):
    """Add buttons to all existing summary messages"""
    if not summary_messages:
        await ctx.send("❌ No summary messages found in memory.")
        return
        
    await ctx.send(f"🔄 Adding buttons to {len(summary_messages)} existing summaries...")
    
    updated_count = 0
    for message_id, summary_msg in summary_messages.items():
        try:
            # Get original message details
            monitor_channel = bot.get_channel(MONITOR_CHANNEL_ID)
            original_message = await monitor_channel.fetch_message(message_id)
            title, timestamp_str = extract_title_and_timestamp(original_message.content)
            
            # Build new embed and view with buttons
            summary_embed = build_summary_embed(message_id, title, timestamp_str)
            view = create_summary_view(message_id)
            
            # Update with buttons
            await summary_msg.edit(embed=summary_embed, view=view)
            updated_count += 1
            
        except Exception as e:
            print(f"Failed to update summary for message {message_id}: {e}")
    
    await ctx.send(f"✅ Successfully added buttons to {updated_count} summaries!")

@bot.command(name="test_buttons")
async def test_buttons(ctx):
    """Test button functionality"""
    embed = discord.Embed(title="🧪 Button Test", description="Testing button functionality", color=0x00FFFF)
    
    # Create test buttons
    view = discord.ui.View(timeout=None)
    
    test_button = discord.ui.Button(
        label="📊 Test Export",
        style=discord.ButtonStyle.primary,
        custom_id="test_export"
    )
    
    refresh_button = discord.ui.Button(
        label="🔄 Test Refresh", 
        style=discord.ButtonStyle.secondary,
        custom_id="test_refresh"
    )
    
    view.add_item(test_button)
    view.add_item(refresh_button)
    
    await ctx.send(embed=embed, view=view)
    await ctx.send("If you see buttons above, the functionality is working! If not, there may be a Discord.py version issue.")

@bot.command(name="force_refresh_summary")
async def force_refresh_summary(ctx, message_id: int):
    """Force refresh a specific summary with buttons"""
    try:
        monitor_channel = bot.get_channel(MONITOR_CHANNEL_ID)
        message = await monitor_channel.fetch_message(message_id)
        title, timestamp_str = extract_title_and_timestamp(message.content)
        
        # Clear the old summary message reference to force recreation
        if message_id in summary_messages:
            del summary_messages[message_id]
        
        await post_or_edit_summary_and_get_thread(ctx.channel, message_id, title, timestamp_str)
        await ctx.send(f"✅ Force refreshed summary for: {title}")
        await ctx.send("Check if the new summary has buttons below it!")
        
    except Exception as e:
        await ctx.send(f"❌ Error: {e}")

@bot.command(name="update_emoji_map")
async def update_emoji_map(ctx, message_id: int):
    """Generate updated EMOJI_MAP code based on a message's reactions"""
    try:
        monitor_channel = bot.get_channel(MONITOR_CHANNEL_ID)
        message = await monitor_channel.fetch_message(message_id)
        
        if not message.reactions:
            await ctx.send("❌ No reactions found on this message.")
            return
        
        embed = discord.Embed(title="🔧 Updated EMOJI_MAP Code", color=0x00FF00)
        
        emoji_map_code = "EMOJI_MAP = {\n"
        
        for reaction in message.reactions:
            if hasattr(reaction.emoji, 'id') and reaction.emoji.id:
                # Custom emoji
                emoji_name = reaction.emoji.name
                emoji_id = reaction.emoji.id
                
                # Check if this emoji exists in current map
                if emoji_id in EMOJI_MAP:
                    current_label = EMOJI_MAP[emoji_id][0]
                    emoji_map_code += f"    {emoji_id}: (\"{current_label}\", None),  # {emoji_name}\n"
                else:
                    # Generate a reasonable label based on emoji name
                    suggested_label = emoji_name.replace('_', ' ').title()
                    emoji_map_code += f"    {emoji_id}: (\"{suggested_label}\", None),  # NEW: {emoji_name}\n"
            else:
                # Unicode emoji - add as comment
                emoji_str = str(reaction.emoji)
                if emoji_str == "❌":
                    emoji_map_code += f"    # Unicode ❌ handled by emoji_display_and_label function\n"
                elif emoji_str == "⏳":
                    emoji_map_code += f"    # Unicode ⏳ handled by emoji_display_and_label function\n"
                else:
                    emoji_map_code += f"    # Unicode {emoji_str} - add to emoji_display_and_label if needed\n"
        
        emoji_map_code += "}"
        
        # Send the code in a code block
        if len(emoji_map_code) > 1900:
            # Send as file if too long
            import io
            discord_file = discord.File(
                fp=io.BytesIO(emoji_map_code.encode('utf-8')), 
                filename="updated_emoji_map.py"
            )
            await ctx.send("🔧 **Updated EMOJI_MAP (file):**", file=discord_file)
        else:
            await ctx.send(f"```python\n{emoji_map_code}\n```")
        
        embed.description = "Copy this code and replace your current EMOJI_MAP in the bot code!"
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f"❌ Error generating emoji map: {e}")

@bot.command(name="export_attendance")
async def export_attendance(ctx, message_id: int):
    """Export attendance list including not attending users"""
    try:
        monitor_channel = bot.get_channel(MONITOR_CHANNEL_ID)
        message = await monitor_channel.fetch_message(message_id)
        title, timestamp_str = extract_title_and_timestamp(message.content)
        
        if message_id not in reaction_signups:
            await ctx.send("❌ No reaction data found for this message.")
            return
        
        emoji_data = reaction_signups[message_id]
        
        # Get message author to identify them in export
        message_author_name = message.author.name
        
        # Build export text
        export_text = f"📊 **ATTENDANCE EXPORT**\n"
        export_text += f"📋 **Event:** {title}\n"
        if timestamp_str:
            export_text += f"⏰ **Time:** {timestamp_str}\n"
        export_text += f"📅 **Exported:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
        export_text += "=" * 50 + "\n\n"
        
        # Track all users and their attendance status
        all_users = {}
        attending_reactions = []
        not_attending_reactions = []
        late_reactions = []
        
        for emoji_key, users in emoji_data.items():
            if not users:
                continue
                
            label, _ = emoji_display_and_label(discord.PartialEmoji.from_str(emoji_key))
            
            # Get clean emoji name
            try:
                emoji_obj = discord.PartialEmoji.from_str(emoji_key)
                if hasattr(emoji_obj, 'id') and emoji_obj.id and emoji_obj.id in EMOJI_MAP:
                    clean_name = EMOJI_MAP[emoji_obj.id][0]
                elif "Not attending" in label:
                    clean_name = "Not attending"
                elif "Late" in label:
                    clean_name = "Late"
                else:
                    clean_name = emoji_obj.name.replace('_', ' ').title() if hasattr(emoji_obj, 'name') else "Unknown"
            except:
                clean_name = label
            
            if "Not attending" in label:
                not_attending_reactions.append((clean_name, users))
            elif "Late" in label:
                late_reactions.append((clean_name, users))
            else:
                attending_reactions.append((clean_name, users))
            
            # Track each user's status
            for user in users:
                if user not in all_users:
                    all_users[user] = []
                all_users[user].append(clean_name)
        
        # Calculate totals
        unique_attending = set()
        for _, users in attending_reactions:
            unique_attending.update(users)
        
        # Remove message author from attending count
        if message_author_name in unique_attending:
            unique_attending.remove(message_author_name)
        
        total_attending = len(unique_attending)
        total_not_attending = sum(len(users) for _, users in not_attending_reactions)
        total_late = sum(len(users) for _, users in late_reactions)
        
        export_text += f"📈 **SUMMARY**\n"
        export_text += f"✅ Attending: {total_attending}\n"
        export_text += f"⏳ Late: {total_late}\n"
        export_text += f"❌ Not Attending: {total_not_attending}\n"
        export_text += f"👤 Event Creator: {message_author_name} (excluded from attending count)\n\n"
        
        # List attending users
        if attending_reactions:
            export_text += "✅ **ATTENDING**\n"
            for reaction_name, users in attending_reactions:
                # Filter out message author
                filtered_users = [u for u in users if u != message_author_name]
                if filtered_users:
                    export_text += f"**{reaction_name}:** {', '.join(sorted(filtered_users))}\n"
            export_text += "\n"
        
        # List late users
        if late_reactions:
            export_text += "⏳ **LATE**\n"
            for reaction_name, users in late_reactions:
                # Filter out message author
                filtered_users = [u for u in users if u != message_author_name]
                if filtered_users:
                    export_text += f"**{reaction_name}:** {', '.join(sorted(filtered_users))}\n"
            export_text += "\n"
        
        # List not attending users
        if not_attending_reactions:
            export_text += "❌ **NOT ATTENDING**\n"
            for reaction_name, users in not_attending_reactions:
                # Don't filter message author for not attending
                if users:
                    export_text += f"**{reaction_name}:** {', '.join(sorted(users))}\n"
            export_text += "\n"
        
        # If export is too long, send as file
        if len(export_text) > 1900:
            # Create a text file
            import io
            file_content = export_text
            file_name = f"attendance_{title.replace(' ', '_')}_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.txt"
            
            file_buffer = io.StringIO(file_content)
            file_buffer.seek(0)
            
            discord_file = discord.File(fp=io.BytesIO(file_content.encode('utf-8')), filename=file_name)
            await ctx.send("📊 **Attendance export (file too large for message):**", file=discord_file)
        else:
            # Send as message
            await ctx.send(f"```\n{export_text}\n```")
            
    except Exception as e:
        await ctx.send(f"❌ Error exporting attendance: {e}")

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
