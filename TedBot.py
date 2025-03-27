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
        self.pending_2fa = False
        self.two_factor_code = None
        self.twofa_message_id = None  # Store the message ID for deletion
        
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
        
        # Register commands
        @self.command()
        async def ping(ctx):
            await ctx.send('Pong! Goose Band Tracker is alive!')
            
        @self.command()
        async def status(ctx):
            """Check the status of the bot and its services"""
            status_message = "🟢 Bot Status:\n"
            status_message += f"- Discord: Connected as {self.user.name}\n"
            status_message += f"- Instagram: {'Connected' if self.insta_client else 'Disconnected'}\n"
            status_message += f"- YouTube: {'Connected' if self.youtube else 'Disconnected'}\n"
            await ctx.send(status_message)
            
        @self.command()
        async def twofa(self, ctx, code: str):
            """Handle 2FA code input from Discord"""
            if not self.pending_2fa:
                await ctx.send("❌ No pending 2FA request. Please try logging in again.")
                return
                
            # Delete the original 2FA request message if it exists
            if self.twofa_message_id:
                try:
                    channel = self.get_channel(self.discord_channel_id)
                    message = await channel.fetch_message(self.twofa_message_id)
                    await message.delete()
                except Exception as e:
                    logger.error(f"Error deleting 2FA message: {e}")
                finally:
                    self.twofa_message_id = None
                
            self.two_factor_code = code
            self.pending_2fa = False
            await ctx.send("✅ 2FA code received! Attempting to complete login...")
            
            # Attempt to complete login
            await self.setup_instagram_client()
            
            if self.insta_client:
                await ctx.send("✅ Instagram login successful!")
            else:
                await ctx.send("❌ Instagram login failed. Please check the logs for details.")

    async def setup_instagram_client(self):
        """Set up Instagram client with login and 2FA handling"""
        try:
            self.insta_client = Client()
            logger.info("Starting Instagram login process...")
            
            def handle_challenge(username, choice):
                """Handle Instagram challenge verification"""
                logger.info(f"Challenge received for {username} with choice {choice}")
                
                # Handle both string and enum values
                choice_str = str(choice).upper()
                
                if 'PHONE' in choice_str or choice == 0:
                    logger.info("Handling phone verification challenge")
                    return self.two_factor_code
                elif 'EMAIL' in choice_str or choice == 1:
                    logger.info("Handling email verification challenge")
                    return self.two_factor_code
                elif 'SMS' in choice_str:
                    logger.info("Handling SMS verification challenge")
                    return self.two_factor_code
                    
                logger.warning(f"Unknown challenge choice: {choice}")
                return None
            
            # Set up challenge handler
            self.insta_client.challenge_code_handler = handle_challenge
            
            # Run login in a thread pool to prevent blocking
            loop = asyncio.get_event_loop()
            
            # Initial delay to avoid rate limiting
            logger.info("Waiting 60 seconds before first login attempt...")
            await asyncio.sleep(60)
            
            # Try login with retries
            max_retries = 3
            retry_delay = 300  # 5 minutes
            
            for attempt in range(max_retries):
                try:
                    # Try standard login first
                    logger.info(f"Attempting standard login (attempt {attempt + 1}/{max_retries})...")
                    await loop.run_in_executor(None,
                        self.insta_client.login,
                        self.insta_username,
                        self.insta_password
                    )
                    logger.info("Instagram client logged in successfully")
                    return
                except Exception as e:
                    error_msg = str(e)
                    logger.warning(f"Login attempt {attempt + 1} failed: {error_msg}")
                    
                    # Check if we're getting a 2FA challenge
                    if "challenge" in error_msg.lower() or "verification" in error_msg.lower():
                        logger.info("Detected 2FA challenge")
                        if not self.pending_2fa:
                            self.pending_2fa = True
                            channel = self.get_channel(self.discord_channel_id)
                            message = await channel.send("🔐 Instagram 2FA Required!\n"
                                                       "Please use the command `!2fa <code>` to provide the 2FA code.")
                            self.twofa_message_id = message.id
                            
                            # Wait for 2FA code with timeout
                            try:
                                await asyncio.wait_for(self.wait_for_2fa(), timeout=300)  # 5 minute timeout
                            except asyncio.TimeoutError:
                                logger.error("Timeout waiting for 2FA code")
                                # Try to delete the message on timeout
                                try:
                                    message = await channel.fetch_message(self.twofa_message_id)
                                    await message.delete()
                                except Exception as e:
                                    logger.error(f"Error deleting 2FA message on timeout: {e}")
                                self.insta_client = None
                                return
                            
                            # If we have a 2FA code, try login with it
                            if self.two_factor_code:
                                try:
                                    logger.info("Attempting login with 2FA...")
                                    await loop.run_in_executor(None,
                                        lambda: self.insta_client.login(
                                            username=self.insta_username,
                                            password=self.insta_password,
                                            verification_code=self.two_factor_code
                                        )
                                    )
                                    logger.info("Instagram client logged in successfully with 2FA")
                                    self.two_factor_code = None
                                    return
                                except Exception as e:
                                    logger.error(f"2FA login failed: {e}")
                                    if "Please wait a few minutes" in str(e):
                                        if attempt < max_retries - 1:
                                            logger.info(f"Rate limited during 2FA, waiting {retry_delay} seconds...")
                                            await asyncio.sleep(retry_delay)
                                            continue
                                        else:
                                            logger.error("Max retries reached for 2FA rate limiting")
                                            self.insta_client = None
                                            return
                    
                    # Handle rate limiting
                    if "Please wait a few minutes" in error_msg or "rate limit" in error_msg.lower():
                        if attempt < max_retries - 1:
                            logger.info(f"Rate limited, waiting {retry_delay} seconds before retry...")
                            await asyncio.sleep(retry_delay)
                            continue
                        else:
                            logger.error("Max retries reached for rate limiting")
                            self.insta_client = None
                            return
                    
                    if attempt < max_retries - 1:
                        logger.info(f"Waiting {retry_delay} seconds before next attempt...")
                        await asyncio.sleep(retry_delay)
            
            logger.error("All login attempts failed")
            self.insta_client = None
                    
        except Exception as e:
            logger.error(f"Unexpected error setting up Instagram client: {e}")
            self.insta_client = None

    async def wait_for_2fa(self):
        """Wait for 2FA code to be provided"""
        while self.pending_2fa and self.two_factor_code is None:
            await asyncio.sleep(1)

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