import os
import asyncio
import logging
from datetime import datetime, timedelta
import sys

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from googleapiclient.discovery import build
from instagrapi import Client
from instagrapi.exceptions import LoginRequired

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class GooseBandTracker(commands.Bot):
    def __init__(self, intents):
        super().__init__(command_prefix='!', intents=intents)
        
        # Validate required environment variables
        required_vars = [
            'YOUTUBE_API_KEY',
            'INSTAGRAM_USERNAME',
            'INSTAGRAM_PASSWORD',
            'DISCORD_TOKEN',
            'YOUTUBE_CHANNEL_ID',
            'DISCORD_CHANNEL_ID'
        ]
        
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
        
        # YouTube API setup
        self.youtube = build('youtube', 'v3', developerKey=os.getenv('YOUTUBE_API_KEY'))
        
        # Instagram setup
        self.insta_client = None
        self.insta_username = os.getenv('INSTAGRAM_USERNAME')
        self.insta_password = os.getenv('INSTAGRAM_PASSWORD')
        
        # Tracking variables
        self.last_livestream = None
        self.last_video = None
        self.last_short = None
        self.last_insta_post = None
        self.last_insta_story = None
        
        # Channel IDs
        self.youtube_channel_id = os.getenv('YOUTUBE_CHANNEL_ID')
        self.discord_channel_id = int(os.getenv('DISCORD_CHANNEL_ID'))
        self.goose_insta_username = 'goosetheband'
        
        # Task tracking
        self.active_tasks = set()

    async def setup_instagram_client(self):
        """Set up Instagram client with login and 2FA handling"""
        try:
            self.insta_client = Client()
            two_factor_code = os.getenv('INSTAGRAM_2FA_CODE')
            
            # First try standard login
            try:
                self.insta_client.login(self.insta_username, self.insta_password)
                logger.info("Instagram client logged in successfully")
            except Exception as e:
                logger.warning(f"Standard login failed, attempting 2FA: {e}")
                
                if two_factor_code:
                    try:
                        self.insta_client.login(
                            username=self.insta_username, 
                            password=self.insta_password,
                            verification_code=two_factor_code
                        )
                        logger.info("Instagram client logged in successfully with 2FA")
                    except Exception as e:
                        logger.error(f"2FA Login failed: {e}")
                        # If both login attempts fail, try to handle challenge
                        try:
                            if hasattr(self.insta_client, 'challenge_code_handler'):
                                self.insta_client.challenge_code_handler = lambda username, choice: two_factor_code
                            self.insta_client.login(self.insta_username, self.insta_password)
                            logger.info("Instagram client logged in successfully after challenge")
                        except Exception as challenge_error:
                            logger.error(f"Challenge handling failed: {challenge_error}")
                            self.insta_client = None
                            return
                else:
                    logger.error("2FA code not provided in environment variables")
                    self.insta_client = None
                    return
        except Exception as e:
            logger.error(f"Unexpected error setting up Instagram client: {e}")
            self.insta_client = None

    async def on_ready(self):
        logger.info(f'Logged in as {self.user.name}')
        await self.setup_instagram_client()
        
        # Start background tasks
        self.check_youtube_updates.start()
        self.check_instagram_updates.start()
        
        # Add tasks to active tasks set
        self.active_tasks.add(self.check_youtube_updates)
        self.active_tasks.add(self.check_instagram_updates)

    async def close(self):
        """Gracefully shut down the bot and cancel all tasks"""
        logger.info("Shutting down bot...")
        
        # Cancel all active tasks
        for task in self.active_tasks:
            if task.is_running():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # Close Instagram client if it exists
        if self.insta_client:
            try:
                self.insta_client.logout()
            except Exception as e:
                logger.error(f"Error logging out of Instagram: {e}")
        
        # Call parent class close method
        await super().close()
        logger.info("Bot shutdown complete")

    def cog_unload(self):
        """Cancel all tasks when cog is unloaded"""
        for task in self.active_tasks:
            if task.is_running():
                task.cancel()

    @tasks.loop(minutes=15)
    async def check_instagram_updates(self):
        if not self.insta_client:
            await self.setup_instagram_client()
            return

        try:
            await self.check_instagram_posts()
            await self.check_instagram_stories()
            await self.check_instagram_live()
        except Exception as e:
            logger.error(f"Error checking Instagram updates: {e}")

    async def check_instagram_posts(self):
        try:
            # Get user ID
            user_id = self.insta_client.user_id_from_username(self.goose_insta_username)
            
            # Fetch recent posts
            posts = self.insta_client.user_medias(user_id, amount=3)
            
            for post in posts:
                # Convert to datetime and check if recent
                post_time = post.taken_at
                
                if post_time > datetime.now(post_time.tzinfo) - timedelta(hours=24):
                    if post.pk != self.last_insta_post:
                        channel = self.get_channel(self.discord_channel_id)
                        
                        # Construct post message
                        post_message = f"📸 New Instagram Post by Goose the Band!\n"
                        if post.caption_text:
                            post_message += f"Caption: {post.caption_text}\n"
                        post_message += f"https://www.instagram.com/p/{post.code}"
                        
                        await channel.send(post_message)
                        self.last_insta_post = post.pk
                        
                        break  # Only notify for the most recent post
        except Exception as e:
            logger.error(f"Error checking Instagram posts: {e}")

    async def check_instagram_stories(self):
        try:
            # Get user ID
            user_id = self.insta_client.user_id_from_username(self.goose_insta_username)
            
            # Fetch stories
            stories = self.insta_client.user_stories(user_id)
            
            for story in stories:
                story_time = story.taken_at
                
                if story_time > datetime.now(story_time.tzinfo) - timedelta(hours=24):
                    if story.pk != self.last_insta_story:
                        channel = self.get_channel(self.discord_channel_id)
                        await channel.send(f"📱 New Instagram Story by Goose the Band!\n"
                                           f"Check their Instagram story now!")
                        self.last_insta_story = story.pk
                        
                        break  # Only notify for the most recent story
        except Exception as e:
            logger.error(f"Error checking Instagram stories: {e}")

    async def check_instagram_live(self):
        try:
            # Check if the account is currently live
            user_id = self.insta_client.user_id_from_username(self.goose_insta_username)
            live_broadcast = self.insta_client.search_users_live(user_id)
            
            if live_broadcast:
                channel = self.get_channel(self.discord_channel_id)
                await channel.send(f"🔴 Goose the Band is LIVE on Instagram RIGHT NOW!\n"
                                   f"https://www.instagram.com/{self.goose_insta_username}")
        except Exception as e:
            logger.error(f"Error checking Instagram live: {e}")

    @tasks.loop(minutes=15)
    async def check_youtube_updates(self):
        """Check for new YouTube content"""
        try:
            # Get channel uploads playlist ID
            channel_response = self.youtube.channels().list(
                part='contentDetails',
                id=self.youtube_channel_id
            ).execute()
            
            if not channel_response['items']:
                logger.error("Could not find YouTube channel")
                return
                
            uploads_playlist_id = channel_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
            
            # Get recent videos
            playlist_response = self.youtube.playlistItems().list(
                part='snippet',
                playlistId=uploads_playlist_id,
                maxResults=5
            ).execute()
            
            for item in playlist_response['items']:
                video_id = item['snippet']['resourceId']['videoId']
                published_at = datetime.fromisoformat(item['snippet']['publishedAt'].replace('Z', '+00:00'))
                
                # Check if video is recent (within last 24 hours)
                if published_at > datetime.now(published_at.tzinfo) - timedelta(hours=24):
                    # Check if it's a livestream
                    video_response = self.youtube.videos().list(
                        part='snippet,liveStreamingDetails',
                        id=video_id
                    ).execute()
                    
                    if not video_response['items']:
                        continue
                        
                    video = video_response['items'][0]
                    is_livestream = video.get('snippet', {}).get('liveBroadcastContent') == 'live'
                    is_short = video.get('snippet', {}).get('title', '').lower().startswith('#shorts')
                    
                    channel = self.get_channel(self.discord_channel_id)
                    
                    if is_livestream and video_id != self.last_livestream:
                        await channel.send(f"🔴 Goose is LIVE on YouTube!\n"
                                         f"https://www.youtube.com/watch?v={video_id}")
                        self.last_livestream = video_id
                    elif is_short and video_id != self.last_short:
                        await channel.send(f"🎥 New YouTube Short!\n"
                                         f"https://www.youtube.com/watch?v={video_id}")
                        self.last_short = video_id
                    elif not is_livestream and not is_short and video_id != self.last_video:
                        await channel.send(f"🎥 New YouTube Video!\n"
                                         f"https://www.youtube.com/watch?v={video_id}")
                        self.last_video = video_id
                        
                    break  # Only notify for the most recent video
                    
        except Exception as e:
            logger.error(f"Error checking YouTube updates: {e}")

    @check_youtube_updates.before_loop
    async def before_check_youtube_updates(self):
        """Wait for bot to be ready before starting YouTube check loop"""
        await self.wait_until_ready()

def main():
    try:
        intents = discord.Intents.default()
        intents.message_content = True
        
        bot = GooseBandTracker(intents)
        
        @bot.command()
        async def ping(ctx):
            await ctx.send('Pong! Goose Band Tracker is alive!')
        
        @bot.command()
        async def status(ctx):
            """Check the status of the bot and its services"""
            status_message = "🟢 Bot Status:\n"
            status_message += f"- Discord: Connected as {bot.user.name}\n"
            status_message += f"- Instagram: {'Connected' if bot.insta_client else 'Disconnected'}\n"
            status_message += f"- YouTube: {'Connected' if bot.youtube else 'Disconnected'}\n"
            await ctx.send(status_message)
        
        # Run the bot with error handling
        bot.run(os.getenv('DISCORD_TOKEN'))
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()