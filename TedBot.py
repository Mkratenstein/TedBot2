import os
import asyncio
import logging
from datetime import datetime, timedelta

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

    async def setup_instagram_client(self):
        """
        Set up Instagram client with login and error handling
        """
        try:
            self.insta_client = Client()
            self.insta_client.login(self.insta_username, self.insta_password)
            logger.info("Instagram client logged in successfully")
        except LoginRequired:
            logger.error("Instagram login failed. Check credentials.")
        except Exception as e:
            logger.error(f"Error setting up Instagram client: {e}")

    async def on_ready(self):
        logger.info(f'Logged in as {self.user.name}')
        await self.setup_instagram_client()
        self.check_youtube_updates.start()
        self.check_instagram_updates.start()

    def cog_unload(self):
        self.check_youtube_updates.cancel()
        self.check_instagram_updates.cancel()

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

    # Existing YouTube methods remain the same as in previous implementation...

def main():
    intents = discord.Intents.default()
    intents.message_content = True
    
    bot = GooseBandTracker(intents)
    
    @bot.command()
    async def ping(ctx):
        await ctx.send('Pong! Goose Band Tracker is alive!')

    bot.run(os.getenv('DISCORD_TOKEN'))

if __name__ == '__main__':
    main()
