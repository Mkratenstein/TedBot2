import os
import asyncio
import discord
import time
from datetime import datetime, timedelta
from discord.ext import commands, tasks
from atproto import Client as AtprotoClient
from dotenv import load_dotenv
import googleapiclient.discovery
import googleapiclient.errors
import json

# Get the directory where the script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Load environment variables from the .env file in the same directory as the script
load_dotenv()  # This will still work locally with .env file

print("Environment variables loaded:", os.getenv('DISCORD_CHANNEL_ID'))

# Discord setup
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID'))

# Bluesky setup
BLUESKY_EMAIL = os.getenv('BLUESKY_EMAIL')
BLUESKY_PASSWORD = os.getenv('BLUESKY_PASSWORD')

# YouTube API setup
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')

# Initialize Discord bot
intents = discord.Intents.default()
intents.message_content = True  # Enable message content intent for commands
bot = commands.Bot(command_prefix='!', intents=intents)

# Initialize Bluesky client
bluesky = AtprotoClient()
bluesky.login(BLUESKY_EMAIL, BLUESKY_PASSWORD)

# Initialize YouTube API client
youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

# Configuration file path
CONFIG_FILE = os.path.join(SCRIPT_DIR, "bot_config.json")

class SocialMediaBot:
    def __init__(self):
        #self.bluesky_accounts = ['aatgoosepod.bsky.social', 'goose-band.bsky.social']
        self.bluesky_accounts = ['goose-band.bsky.social']
        self.last_bluesky_posts = {}
        
        # YouTube settings
        self.youtube_channels = ['goosetheband']  # YouTube channel handle without @ symbol
        self.youtube_channel_ids = {}  # Will store channel ID from handle
        self.last_videos = {}
        self.last_livestreams = {}
        self.last_community_posts = {}
        
        # Default notification settings
        self.youtube_notification_channel_id = DISCORD_CHANNEL_ID
        self.notify_videos = True
        self.notify_livestreams = True
        self.notify_community_posts = True
        
        # Load saved configuration
        self.load_config()
        
        # Get YouTube channel ID for each handle
        self.init_youtube_channel_ids()

    def save_config(self):
        """Save current configuration to a JSON file"""
        config = {
            'youtube_notification_channel_id': self.youtube_notification_channel_id,
            'notify_videos': self.notify_videos,
            'notify_livestreams': self.notify_livestreams,
            'notify_community_posts': self.notify_community_posts,
            'last_videos': self.last_videos,
            'last_livestreams': self.last_livestreams,
            'last_community_posts': self.last_community_posts,
            'last_bluesky_posts': self.last_bluesky_posts,
            'youtube_channel_ids': self.youtube_channel_ids
        }
        
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f)
            print("Configuration saved successfully")
        except Exception as e:
            print(f"Error saving configuration: {e}")

    def load_config(self):
        """Load configuration from a JSON file if it exists"""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                
                self.youtube_notification_channel_id = config.get('youtube_notification_channel_id', self.youtube_notification_channel_id)
                self.notify_videos = config.get('notify_videos', self.notify_videos)
                self.notify_livestreams = config.get('notify_livestreams', self.notify_livestreams)
                self.notify_community_posts = config.get('notify_community_posts', self.notify_community_posts)
                self.last_videos = config.get('last_videos', {})
                self.last_livestreams = config.get('last_livestreams', {})
                self.last_community_posts = config.get('last_community_posts', {})
                self.last_bluesky_posts = config.get('last_bluesky_posts', {})
                self.youtube_channel_ids = config.get('youtube_channel_ids', {})
                
                print("Configuration loaded successfully")
        except Exception as e:
            print(f"Error loading configuration: {e}")

    def init_youtube_channel_ids(self):
        """Get channel IDs for each YouTube handle"""
        for handle in self.youtube_channels:
            if handle not in self.youtube_channel_ids:
                try:
                    # Search for the channel by handle
                    request = youtube.search().list(
                        part="snippet",
                        q=handle,
                        type="channel",
                        maxResults=1
                    )
                    response = request.execute()
                    
                    if response['items']:
                        channel_id = response['items'][0]['id']['channelId']
                        self.youtube_channel_ids[handle] = channel_id
                        print(f"Found channel ID for {handle}: {channel_id}")
                    else:
                        print(f"Could not find channel ID for {handle}")
                except Exception as e:
                    print(f"Error getting channel ID for {handle}: {e}")

    async def fetch_bluesky_posts(self):
        try:
            for account in self.bluesky_accounts:
                profile = bluesky.get_profile(account)
                posts = bluesky.get_author_feed(account, limit=1)
                if posts and posts.feed:
                    latest_post = posts.feed[0]
                    if account not in self.last_bluesky_posts or self.last_bluesky_posts[account] != latest_post.post.cid:
                        self.last_bluesky_posts[account] = latest_post.post.cid
                        
                        # Create an embed message
                        embed = discord.Embed(
                            title=f"New Bluesky post from {account}",
                            description=latest_post.post.record.text,
                            url=f"https://bsky.app/profile/{account}/post/{latest_post.post.uri.split('/')[-1]}",
                            color=discord.Color.blue()
                        )
                        
                        # Add author information
                        embed.set_author(
                            name=account,
                            url=f"https://bsky.app/profile/{account}",
                            icon_url=profile.avatar if hasattr(profile, 'avatar') else None
                        )
                        
                        # Check for media embeds in the post
                        if hasattr(latest_post.post.record, 'embed'):
                            embed_data = latest_post.post.record.embed
                            
                            # Handle YouTube embeds
                            if hasattr(embed_data, 'type') and embed_data.type == 'app.bsky.embed.external':
                                if 'youtube.com' in embed_data.external.uri or 'youtu.be' in embed_data.external.uri:
                                    embed.add_field(
                                        name="YouTube Link",
                                        value=embed_data.external.uri,
                                        inline=False
                                    )
                            
                            # Handle Spotify embeds
                            if hasattr(embed_data, 'type') and embed_data.type == 'app.bsky.embed.external':
                                if 'spotify.com' in embed_data.external.uri:
                                    embed.add_field(
                                        name="Spotify Link",
                                        value=embed_data.external.uri,
                                        inline=False
                                    )
                        
                        # Save the updated configuration
                        self.save_config()
                        return embed
        except Exception as e:
            print(f"Error fetching Bluesky posts: {e}")
        return None

    async def fetch_youtube_videos(self):
        if not self.notify_videos:
            return None
            
        for handle, channel_id in self.youtube_channel_ids.items():
            try:
                # Get latest videos (not livestreams)
                request = youtube.search().list(
                    part="snippet",
                    channelId=channel_id,
                    maxResults=5,
                    order="date",
                    type="video",
                    eventType="none"  # Exclude livestreams
                )
                response = request.execute()
                
                if response['items']:
                    latest_video = response['items'][0]
                    video_id = latest_video['id']['videoId']
                    
                    if handle not in self.last_videos or self.last_videos[handle] != video_id:
                        self.last_videos[handle] = video_id
                        
                        # Get additional video details (duration, etc.)
                        video_details = youtube.videos().list(
                            part="contentDetails,statistics,snippet",
                            id=video_id
                        ).execute()
                        
                        if video_details['items']:
                            # Parse duration (PT1H2M3S format)
                            duration_str = video_details['items'][0]['contentDetails']['duration']
                            duration = self.parse_duration(duration_str)
                            
                            # Create embed for new video
                            embed = discord.Embed(
                                title=f"**🎵 NEW GOOSE VIDEO!**",
                                description=f"\"{latest_video['snippet']['title']}\"",
                                url=f"https://www.youtube.com/watch?v={video_id}",
                                color=discord.Color.red()
                            )
                            
                            # Add thumbnail
                            if 'high' in latest_video['snippet']['thumbnails']:
                                embed.set_image(url=latest_video['snippet']['thumbnails']['high']['url'])
                            
                            # Add description (truncated if needed)
                            description = latest_video['snippet']['description']
                            if len(description) > 100:
                                description = description[:97] + "..."
                            if description:
                                embed.add_field(name="Description", value=description, inline=False)
                            
                            # Add upload time and duration
                            upload_time = datetime.strptime(latest_video['snippet']['publishedAt'], "%Y-%m-%dT%H:%M:%SZ")
                            embed.add_field(
                                name="Uploaded",
                                value=upload_time.strftime("%Y-%m-%d at %H:%M UTC"),
                                inline=True
                            )
                            embed.add_field(name="Duration", value=duration, inline=True)
                            
                            # Save the updated configuration
                            self.save_config()
                            return embed
            except googleapiclient.errors.HttpError as e:
                if e.resp.status == 403:
                    print(f"YouTube API quota exceeded: {e}")
                    # Don't retry immediately if quota is exceeded
                    await asyncio.sleep(3600)  # Wait for an hour
                else:
                    print(f"Error fetching YouTube videos: {e}")
            except Exception as e:
                print(f"Unknown error fetching YouTube videos: {e}")
        
        return None

    async def fetch_youtube_livestreams(self):
        if not self.notify_livestreams:
            return None
            
        for handle, channel_id in self.youtube_channel_ids.items():
            try:
                # Get active livestreams
                request = youtube.search().list(
                    part="snippet",
                    channelId=channel_id,
                    maxResults=5,
                    eventType="live",
                    type="video"
                )
                response = request.execute()
                
                if response['items']:
                    live_stream = response['items'][0]
                    stream_id = live_stream['id']['videoId']
                    
                    if handle not in self.last_livestreams or self.last_livestreams[handle] != stream_id:
                        self.last_livestreams[handle] = stream_id
                        
                        # Create embed for livestream
                        embed = discord.Embed(
                            title=f"**🔴 GOOSE IS LIVE NOW!**",
                            description=f"\"{live_stream['snippet']['title']}\"",
                            url=f"https://www.youtube.com/watch?v={stream_id}",
                            color=discord.Color.dark_red()
                        )
                        
                        # Add thumbnail
                        if 'high' in live_stream['snippet']['thumbnails']:
                            embed.set_image(url=live_stream['snippet']['thumbnails']['high']['url'])
                        
                        # Add description (truncated if needed)
                        description = live_stream['snippet']['description']
                        if len(description) > 100:
                            description = description[:97] + "..."
                        if description:
                            embed.add_field(name="Description", value=description, inline=False)
                        
                        # Add start time
                        start_time = datetime.strptime(live_stream['snippet']['publishedAt'], "%Y-%m-%dT%H:%M:%SZ")
                        now = datetime.utcnow()
                        time_difference = now - start_time
                        
                        minutes_ago = int(time_difference.total_seconds() / 60)
                        if minutes_ago < 60:
                            time_str = f"{minutes_ago} minute{'s' if minutes_ago != 1 else ''} ago"
                        else:
                            hours = minutes_ago // 60
                            time_str = f"{hours} hour{'s' if hours != 1 else ''} ago"
                            
                        embed.add_field(name="Started streaming", value=time_str, inline=True)
                        
                        # Save the updated configuration
                        self.save_config()
                        return embed
            except googleapiclient.errors.HttpError as e:
                if e.resp.status == 403:
                    print(f"YouTube API quota exceeded: {e}")
                    # Don't retry immediately if quota is exceeded
                    await asyncio.sleep(3600)  # Wait for an hour
                else:
                    print(f"Error fetching YouTube livestreams: {e}")
            except Exception as e:
                print(f"Unknown error fetching YouTube livestreams: {e}")
        
        return None

    async def fetch_youtube_community_posts(self):
        # Note: YouTube Data API v3 doesn't directly support fetching community posts
        # This would require a custom implementation or a third-party solution
        # For now, return None as a placeholder
        return None

    def parse_duration(self, duration_str):
        """Parse ISO 8601 duration format (PT1H2M3S) to human-readable string"""
        hours = 0
        minutes = 0
        seconds = 0
        
        # Remove PT prefix
        duration = duration_str[2:]
        
        # Extract hours, minutes, seconds
        if 'H' in duration:
            hours_str, duration = duration.split('H')
            hours = int(hours_str)
        
        if 'M' in duration:
            minutes_str, duration = duration.split('M')
            minutes = int(minutes_str)
        
        if 'S' in duration:
            seconds_str = duration.split('S')[0]
            seconds = int(seconds_str)
        
        # Format as string
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes}:{seconds:02d}"

social_bot = SocialMediaBot()

@tasks.loop(minutes=10)  # Check every 10 minutes
async def check_social_media():
    # Get the appropriate channels
    bluesky_channel = bot.get_channel(DISCORD_CHANNEL_ID)
    youtube_channel = bot.get_channel(social_bot.youtube_notification_channel_id)
    
    if not bluesky_channel or not youtube_channel:
        print(f"Warning: Could not find Discord channels. BS: {DISCORD_CHANNEL_ID}, YT: {social_bot.youtube_notification_channel_id}")
        return
    
    try:
        # Check Bluesky
        bluesky_update = await social_bot.fetch_bluesky_posts()
        if bluesky_update and bluesky_channel:
            await bluesky_channel.send(embed=bluesky_update)
        
        # Check YouTube videos
        youtube_video = await social_bot.fetch_youtube_videos()
        if youtube_video and youtube_channel:
            await youtube_channel.send(embed=youtube_video)
        
        # Check YouTube livestreams
        youtube_livestream = await social_bot.fetch_youtube_livestreams()
        if youtube_livestream and youtube_channel:
            await youtube_channel.send(embed=youtube_livestream)
        
        # Check YouTube community posts
        youtube_community = await social_bot.fetch_youtube_community_posts()
        if youtube_community and youtube_channel:
            await youtube_channel.send(embed=youtube_community)
            
    except Exception as e:
        print(f"Error in check_social_media: {e}")

@bot.command(name="setytchannel")
async def set_youtube_channel(ctx, channel: discord.TextChannel = None):
    """Set the YouTube notification channel"""
    if channel is None:
        channel = ctx.channel
    
    social_bot.youtube_notification_channel_id = channel.id
    social_bot.save_config()
    await ctx.send(f"YouTube notifications will now be sent to {channel.mention}")

@bot.command(name="togglelive")
async def toggle_livestreams(ctx):
    """Toggle YouTube livestream notifications"""
    social_bot.notify_livestreams = not social_bot.notify_livestreams
    status = "enabled" if social_bot.notify_livestreams else "disabled"
    social_bot.save_config()
    await ctx.send(f"YouTube livestream notifications are now {status}")

@bot.command(name="togglevideos")
async def toggle_videos(ctx):
    """Toggle YouTube video notifications"""
    social_bot.notify_videos = not social_bot.notify_videos
    status = "enabled" if social_bot.notify_videos else "disabled"
    social_bot.save_config()
    await ctx.send(f"YouTube video notifications are now {status}")

@bot.command(name="toggleposts")
async def toggle_posts(ctx):
    """Toggle YouTube community post notifications"""
    social_bot.notify_community_posts = not social_bot.notify_community_posts
    status = "enabled" if social_bot.notify_community_posts else "disabled"
    social_bot.save_config()
    await ctx.send(f"YouTube community post notifications are now {status}")

@bot.command(name="testyoutube")
async def test_youtube(ctx):
    """Test the YouTube notification system"""
    await ctx.send("Testing YouTube notifications...")
    
    channel = bot.get_channel(social_bot.youtube_notification_channel_id)
    if not channel:
        await ctx.send(f"Error: Could not find YouTube notification channel (ID: {social_bot.youtube_notification_channel_id})")
        return
    
    # Create a test video notification
    video_embed = discord.Embed(
        title=f"**🎵 NEW GOOSE VIDEO! (TEST)**",
        description=f"\"This is a test video notification\"",
        url=f"https://www.youtube.com/watch?v=example",
        color=discord.Color.red()
    )
    video_embed.set_image(url="https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg")
    video_embed.add_field(name="Description", value="This is a test description for a video notification.", inline=False)
    video_embed.add_field(name="Uploaded", value="Today at 12:00 PM", inline=True)
    video_embed.add_field(name="Duration", value="3:30", inline=True)
    
    # Create a test livestream notification
    livestream_embed = discord.Embed(
        title=f"**🔴 GOOSE IS LIVE NOW! (TEST)**",
        description=f"\"This is a test livestream notification\"",
        url=f"https://www.youtube.com/watch?v=example",
        color=discord.Color.dark_red()
    )
    livestream_embed.set_image(url="https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg")
    livestream_embed.add_field(name="Description", value="This is a test description for a livestream notification.", inline=False)
    livestream_embed.add_field(name="Started streaming", value="5 minutes ago", inline=True)
    
    await channel.send(embed=video_embed)
    await channel.send(embed=livestream_embed)
    
    await ctx.send(f"Test notifications sent to {channel.mention}")

@bot.command(name="ytstatus")
async def youtube_status(ctx):
    """Show the current YouTube notification settings"""
    embed = discord.Embed(
        title="YouTube Notification Settings",
        color=discord.Color.blue()
    )
    
    channel = bot.get_channel(social_bot.youtube_notification_channel_id)
    channel_mention = channel.mention if channel else f"Unknown (ID: {social_bot.youtube_notification_channel_id})"
    
    embed.add_field(name="Notification Channel", value=channel_mention, inline=False)
    embed.add_field(name="Video Notifications", value="Enabled" if social_bot.notify_videos else "Disabled", inline=True)
    embed.add_field(name="Livestream Notifications", value="Enabled" if social_bot.notify_livestreams else "Disabled", inline=True)
    embed.add_field(name="Community Post Notifications", value="Enabled" if social_bot.notify_community_posts else "Disabled", inline=True)
    
    # Add tracked channels
    channels_str = "\n".join([f"@{handle} (ID: {id})" for handle, id in social_bot.youtube_channel_ids.items()])
    embed.add_field(name="Tracked Channels", value=channels_str or "None", inline=False)
    
    await ctx.send(embed=embed)

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    check_social_media.start()

# Run the bot
bot.run(DISCORD_TOKEN)
