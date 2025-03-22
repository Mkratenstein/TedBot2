import os
import asyncio
import discord
import time
import logging
from datetime import datetime, timedelta
from discord.ext import commands, tasks
from atproto import Client as AtprotoClient
from dotenv import load_dotenv
import googleapiclient.discovery
import googleapiclient.errors
import json
from instagrapi import Client as InstagrapiClient
from instagrapi.exceptions import LoginRequired

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("TedBot")

# Get the directory where the script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Load environment variables from the .env file in the same directory as the script
load_dotenv()  # This will still work locally with .env file

logger.info("Environment variables loaded: %s", os.getenv('DISCORD_CHANNEL_ID'))

# Discord setup
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID'))

# Bluesky setup
BLUESKY_EMAIL = os.getenv('BLUESKY_EMAIL')
BLUESKY_PASSWORD = os.getenv('BLUESKY_PASSWORD')

# YouTube API setup
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')

# Instagram setup
INSTAGRAM_USERNAME = os.getenv('INSTAGRAM_USERNAME')
INSTAGRAM_PASSWORD = os.getenv('INSTAGRAM_PASSWORD')

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
        self.bluesky_accounts = ['aatgoosepod.bsky.social', 'goose-band.bsky.social']
        self.last_bluesky_posts = {}
        
        # YouTube settings
        self.youtube_channels = ['goosetheband']  # YouTube channel handle without @ symbol
        self.youtube_channel_ids = {}  # Will store channel ID from handle
        self.last_videos = {}
        self.last_livestreams = {}
        self.last_community_posts = {}
        
        # Instagram settings
        self.instagram_accounts = ['goosetheband']  # Instagram handles without @ symbol
        self.instagram_client = None
        self.last_instagram_posts = {}
        self.last_instagram_stories = {}
        self.last_instagram_lives = {}
        self.notify_instagram_posts = True
        self.notify_instagram_stories = True
        self.notify_instagram_lives = True
        self.instagram_notification_channel_id = DISCORD_CHANNEL_ID
        
        # Default notification settings
        self.youtube_notification_channel_id = DISCORD_CHANNEL_ID
        self.notify_videos = True
        self.notify_livestreams = True
        self.notify_community_posts = True
        
        # Load saved configuration
        self.load_config()
        
        # Get YouTube channel ID for each handle
        self.init_youtube_channel_ids()
        
        # Initialize Instagram client
        self.init_instagram_client()

    def save_config(self):
        """Save current configuration to a JSON file"""
        config = {
            'youtube_notification_channel_id': self.youtube_notification_channel_id,
            'instagram_notification_channel_id': self.instagram_notification_channel_id,
            'notify_videos': self.notify_videos,
            'notify_livestreams': self.notify_livestreams,
            'notify_community_posts': self.notify_community_posts,
            'notify_instagram_posts': self.notify_instagram_posts,
            'notify_instagram_stories': self.notify_instagram_stories,
            'notify_instagram_lives': self.notify_instagram_lives,
            'last_videos': self.last_videos,
            'last_livestreams': self.last_livestreams,
            'last_community_posts': self.last_community_posts,
            'last_bluesky_posts': self.last_bluesky_posts,
            'last_instagram_posts': self.last_instagram_posts,
            'last_instagram_stories': self.last_instagram_stories,
            'last_instagram_lives': self.last_instagram_lives,
            'youtube_channel_ids': self.youtube_channel_ids
        }
        
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f)
            logger.info("Configuration saved successfully")
        except Exception as e:
            logger.error(f"Error saving configuration: {e}")

    def load_config(self):
        """Load configuration from a JSON file if it exists"""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                
                self.youtube_notification_channel_id = config.get('youtube_notification_channel_id', self.youtube_notification_channel_id)
                self.instagram_notification_channel_id = config.get('instagram_notification_channel_id', self.instagram_notification_channel_id)
                self.notify_videos = config.get('notify_videos', self.notify_videos)
                self.notify_livestreams = config.get('notify_livestreams', self.notify_livestreams)
                self.notify_community_posts = config.get('notify_community_posts', self.notify_community_posts)
                self.notify_instagram_posts = config.get('notify_instagram_posts', self.notify_instagram_posts)
                self.notify_instagram_stories = config.get('notify_instagram_stories', self.notify_instagram_stories)
                self.notify_instagram_lives = config.get('notify_instagram_lives', self.notify_instagram_lives)
                self.last_videos = config.get('last_videos', {})
                self.last_livestreams = config.get('last_livestreams', {})
                self.last_community_posts = config.get('last_community_posts', {})
                self.last_bluesky_posts = config.get('last_bluesky_posts', {})
                self.last_instagram_posts = config.get('last_instagram_posts', {})
                self.last_instagram_stories = config.get('last_instagram_stories', {})
                self.last_instagram_lives = config.get('last_instagram_lives', {})
                self.youtube_channel_ids = config.get('youtube_channel_ids', {})
                
                logger.info("Configuration loaded successfully")
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")

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
                        logger.info(f"Found channel ID for {handle}: {channel_id}")
                    else:
                        logger.warning(f"Could not find channel ID for {handle}")
                except Exception as e:
                    logger.error(f"Error getting channel ID for {handle}: {e}")

    def init_instagram_client(self):
        """Initialize the Instagram client"""
        try:
            if not INSTAGRAM_USERNAME or not INSTAGRAM_PASSWORD:
                logger.warning("Instagram credentials not found in environment variables")
                return
                
            self.instagram_client = InstagrapiClient()
            
            # Try to load session from file if it exists
            session_file = os.path.join(SCRIPT_DIR, "instagram_session.json")
            if os.path.exists(session_file):
                try:
                    self.instagram_client.load_settings(session_file)
                    self.instagram_client.get_timeline_feed()  # Test if session is still valid
                    logger.info("Instagram session loaded successfully")
                    return
                except LoginRequired:
                    logger.info("Instagram session expired, logging in again")
                except Exception as e:
                    logger.error(f"Error loading Instagram session: {e}")
            
            # If we couldn't load a valid session, log in
            self.instagram_client.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
            
            # Save the session for future use
            self.instagram_client.dump_settings(session_file)
            logger.info("Instagram login successful, session saved")
            
        except Exception as e:
            logger.error(f"Error initializing Instagram client: {e}")
            self.instagram_client = None

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
            logger.error(f"Error fetching Bluesky posts: {e}")
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
                    logger.error(f"YouTube API quota exceeded: {e}")
                    # Don't retry immediately if quota is exceeded
                    await asyncio.sleep(3600)  # Wait for an hour
                else:
                    logger.error(f"Error fetching YouTube videos: {e}")
            except Exception as e:
                logger.error(f"Unknown error fetching YouTube videos: {e}")
        
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
                    logger.error(f"YouTube API quota exceeded: {e}")
                    # Don't retry immediately if quota is exceeded
                    await asyncio.sleep(3600)  # Wait for an hour
                else:
                    logger.error(f"Error fetching YouTube livestreams: {e}")
            except Exception as e:
                logger.error(f"Unknown error fetching YouTube livestreams: {e}")
        
        return None

    async def fetch_youtube_community_posts(self):
        # Note: YouTube Data API v3 doesn't directly support fetching community posts
        # This would require a custom implementation or a third-party solution
        # For now, return None as a placeholder
        return None

    async def fetch_instagram_posts(self):
        """Fetch latest Instagram posts for tracked accounts"""
        if not self.instagram_client or not self.notify_instagram_posts:
            return None
            
        try:
            for account in self.instagram_accounts:
                # Get user ID from username
                user_id = self.instagram_client.user_id_from_username(account)
                
                # Get user's recent media
                medias = self.instagram_client.user_medias(user_id, 1)
                
                if medias:
                    latest_media = medias[0]
                    media_id = latest_media.id
                    
                    if account not in self.last_instagram_posts or self.last_instagram_posts[account] != media_id:
                        self.last_instagram_posts[account] = media_id
                        
                        # Determine post type
                        if latest_media.media_type == 1:
                            post_type = "Photo"
                            emoji = "📷"
                            color = discord.Color.from_rgb(138, 58, 185)  # Instagram purple
                        elif latest_media.media_type == 2:
                            post_type = "Video"
                            emoji = "🎬"
                            color = discord.Color.from_rgb(233, 89, 80)  # Instagram reddish
                        elif latest_media.media_type == 8:
                            post_type = "Album"
                            emoji = "🖼️"
                            color = discord.Color.from_rgb(193, 53, 132)  # Instagram pink
                        else:
                            post_type = "Post"
                            emoji = "📱"
                            color = discord.Color.from_rgb(64, 93, 230)  # Instagram blue
                        
                        # Create embed for new post
                        embed = discord.Embed(
                            title=f"**{emoji} NEW GOOSE INSTAGRAM {post_type.upper()}!**",
                            description=latest_media.caption_text[:2000] if latest_media.caption_text else "",
                            url=f"https://www.instagram.com/p/{latest_media.code}/",
                            color=color
                        )
                        
                        # Add thumbnail
                        embed.set_image(url=latest_media.thumbnail_url)
                        
                        # Add profile information
                        embed.set_author(
                            name=f"@{account}",
                            url=f"https://www.instagram.com/{account}/",
                            icon_url="https://www.instagram.com/static/images/ico/favicon-192.png/68d99ba29cc8.png"
                        )
                        
                        # Add post timestamp
                        post_time = datetime.fromtimestamp(latest_media.taken_at)
                        embed.add_field(
                            name="Posted",
                            value=post_time.strftime("%Y-%m-%d at %H:%M"),
                            inline=True
                        )
                        
                        # Add like count if available
                        if hasattr(latest_media, 'like_count'):
                            embed.add_field(
                                name="Likes",
                                value=f"{latest_media.like_count:,}",
                                inline=True
                            )
                        
                        # Add footer
                        embed.set_footer(text="Instagram")
                        
                        # Save the updated configuration
                        self.save_config()
                        return embed
                        
        except Exception as e:
            logger.error(f"Error fetching Instagram posts: {e}")
            # Try to re-login if there was an authentication error
            if "login_required" in str(e).lower():
                logger.info("Instagram login required, attempting to reconnect")
                self.init_instagram_client()
                
        return None

    async def fetch_instagram_stories(self):
        """Fetch latest Instagram stories for tracked accounts"""
        if not self.instagram_client or not self.notify_instagram_stories:
            return None
            
        try:
            for account in self.instagram_accounts:
                # Get user ID from username
                user_id = self.instagram_client.user_id_from_username(account)
                
                # Get user's recent stories
                stories = self.instagram_client.user_stories(user_id)
                
                if stories:
                    # Get the most recent story that we haven't seen yet
                    for story in stories:
                        story_id = story.id
                        
                        if account not in self.last_instagram_stories or story_id not in self.last_instagram_stories[account]:
                            # Initialize the list if it doesn't exist
                            if account not in self.last_instagram_stories:
                                self.last_instagram_stories[account] = []
                                
                            # Add this story to the list of seen stories
                            self.last_instagram_stories[account].append(story_id)
                            
                            # Limit the list to the last 50 stories to prevent unlimited growth
                            self.last_instagram_stories[account] = self.last_instagram_stories[account][-50:]
                            
                            # Determine story type
                            if story.media_type == 1:
                                story_type = "Photo"
                                emoji = "📱"
                                color = discord.Color.from_rgb(233, 89, 80)  # Instagram reddish
                            elif story.media_type == 2:
                                story_type = "Video"
                                emoji = "🎥"
                                color = discord.Color.from_rgb(64, 93, 230)  # Instagram blue
                            else:
                                story_type = "Story"
                                emoji = "📱"
                                color = discord.Color.from_rgb(193, 53, 132)  # Instagram pink
                            
                            # Create embed for new story
                            embed = discord.Embed(
                                title=f"**{emoji} NEW GOOSE INSTAGRAM STORY!**",
                                url=f"https://www.instagram.com/stories/{account}/",
                                color=color
                            )
                            
                            # Add thumbnail if available
                            embed.set_image(url=story.thumbnail_url)
                            
                            # Add profile information
                            embed.set_author(
                                name=f"@{account}",
                                url=f"https://www.instagram.com/{account}/",
                                icon_url="https://www.instagram.com/static/images/ico/favicon-192.png/68d99ba29cc8.png"
                            )
                            
                            # Add timestamp
                            story_time = datetime.fromtimestamp(story.taken_at)
                            embed.add_field(
                                name="Posted",
                                value=story_time.strftime("%Y-%m-%d at %H:%M"),
                                inline=True
                            )
                            
                            # Add type information
                            embed.add_field(
                                name="Type",
                                value=story_type,
                                inline=True
                            )
                            
                            # Add footer
                            embed.set_footer(text="Instagram Story - View before it expires!")
                            
                            # Save the updated configuration
                            self.save_config()
                            return embed
                        
        except Exception as e:
            logger.error(f"Error fetching Instagram stories: {e}")
            # Try to re-login if there was an authentication error
            if "login_required" in str(e).lower():
                logger.info("Instagram login required, attempting to reconnect")
                self.init_instagram_client()
                
        return None

    async def fetch_instagram_lives(self):
        """Fetch active Instagram livestreams for tracked accounts"""
        if not self.instagram_client or not self.notify_instagram_lives:
            return None
            
        try:
            for account in self.instagram_accounts:
                # Get user ID from username
                user_id = self.instagram_client.user_id_from_username(account)
                
                # Check if user is currently live
                broadcasts = self.instagram_client.user_broadcast(user_id)
                
                if broadcasts:
                    broadcast = broadcasts[0]  # Get the most recent broadcast
                    broadcast_id = broadcast.id
                    
                    if account not in self.last_instagram_lives or self.last_instagram_lives[account] != broadcast_id:
                        self.last_instagram_lives[account] = broadcast_id
                        
                        # Create embed for livestream
                        embed = discord.Embed(
                            title=f"**🔴 GOOSE IS LIVE ON INSTAGRAM NOW!**",
                            url=f"https://www.instagram.com/{account}/live/",
                            color=discord.Color.from_rgb(255, 48, 108)  # Instagram live red
                        )
                        
                        # Add thumbnail if available
                        if hasattr(broadcast, 'cover_frame_url'):
                            embed.set_image(url=broadcast.cover_frame_url)
                        
                        # Add profile information
                        embed.set_author(
                            name=f"@{account}",
                            url=f"https://www.instagram.com/{account}/",
                            icon_url="https://www.instagram.com/static/images/ico/favicon-192.png/68d99ba29cc8.png"
                        )
                        
                        # Add viewer count if available
                        if hasattr(broadcast, 'viewer_count'):
                            embed.add_field(
                                name="Viewers",
                                value=f"{broadcast.viewer_count:,}",
                                inline=True
                            )
                        
                        # Add started time if available
                        if hasattr(broadcast, 'broadcast_start_time'):
                            start_time = datetime.fromtimestamp(broadcast.broadcast_start_time)
                            now = datetime.now()
                            time_difference = now - start_time
                            
                            minutes_ago = int(time_difference.total_seconds() / 60)
                            if minutes_ago < 60:
                                time_str = f"{minutes_ago} minute{'s' if minutes_ago != 1 else ''} ago"
                            else:
                                hours = minutes_ago // 60
                                time_str = f"{hours} hour{'s' if hours != 1 else ''} ago"
                                
                            embed.add_field(name="Started streaming", value=time_str, inline=True)
                        
                        # Add footer
                        embed.set_footer(text="Instagram Live")
                        
                        # Save the updated configuration
                        self.save_config()
                        return embed
                        
        except Exception as e:
            logger.error(f"Error fetching Instagram livestreams: {e}")
            # Try to re-login if there was an authentication error
            if "login_required" in str(e).lower():
                logger.info("Instagram login required, attempting to reconnect")
                self.init_instagram_client()
                
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
    blue