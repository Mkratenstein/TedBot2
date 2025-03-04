import os
import asyncio
import discord
from discord.ext import commands, tasks
# import tweepy  # Commented out Twitter
from atproto import Client as AtprotoClient
# import requests  # Commented out Instagram
from dotenv import load_dotenv

# Get the directory where the script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Load environment variables from the .env file in the same directory as the script
load_dotenv(os.path.join(SCRIPT_DIR, 'TedBot.env'))

print("Environment variables loaded:", os.getenv('DISCORD_CHANNEL_ID'))

# Discord setup
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID'))

# Comment out Twitter setup
# TWITTER_API_KEY = os.getenv('TWITTER_API_KEY')
# TWITTER_API_SECRET = os.getenv('TWITTER_API_SECRET')
# TWITTER_ACCESS_TOKEN = os.getenv('TWITTER_ACCESS_TOKEN')
# TWITTER_ACCESS_SECRET = os.getenv('TWITTER_ACCESS_SECRET')

# Bluesky setup
BLUESKY_EMAIL = os.getenv('BLUESKY_EMAIL')
BLUESKY_PASSWORD = os.getenv('BLUESKY_PASSWORD')

# Comment out Instagram setup
# INSTAGRAM_ACCESS_TOKEN = os.getenv('INSTAGRAM_ACCESS_TOKEN')

# Initialize Discord bot
intents = discord.Intents.default()
bot = commands.Bot(command_prefix='!', intents=intents)

# Comment out Twitter client initialization
# twitter_auth = tweepy.OAuthHandler(TWITTER_API_KEY, TWITTER_API_SECRET)
# twitter_auth.set_access_token(TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET)
# twitter_api = tweepy.API(twitter_auth)

bluesky = AtprotoClient()
bluesky.login(BLUESKY_EMAIL, BLUESKY_PASSWORD)

class SocialMediaBot:
    def __init__(self):
        # self.twitter_accounts = ['example_twitter']  # Commented out
        self.bluesky_accounts = ['aatgoosepod.bsky.social', 'goose-band.bsky.social']
        # self.instagram_accounts = ['example_instagram']  # Commented out
        # self.last_tweet_ids = {}  # Commented out
        self.last_bluesky_posts = {}
        # self.last_instagram_posts = {}  # Commented out

    # Comment out Twitter method
    # async def fetch_twitter_posts(self):
    #     try:
    #         for account in self.twitter_accounts:
    #             tweets = twitter_api.user_timeline(screen_name=account, count=1)
    #             if tweets:
    #                 latest_tweet = tweets[0]
    #                 if account not in self.last_tweet_ids or self.last_tweet_ids[account] != latest_tweet.id:
    #                     self.last_tweet_ids[account] = latest_tweet.id
    #                     return f"New tweet from {account}:\n{latest_tweet.text}"
    #     except Exception as e:
    #         print(f"Error fetching Twitter posts: {e}")
    #     return None

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
                        
                        return embed
        except Exception as e:
            print(f"Error fetching Bluesky posts: {e}")
        return None

    # Comment out Instagram method
    # async def fetch_instagram_posts(self):
    #     try:
    #         for account in self.instagram_accounts:
    #             url = f"https://graph.instagram.com/me/media?fields=id,caption,permalink&access_token={INSTAGRAM_ACCESS_TOKEN}"
    #             response = requests.get(url)
    #             if response.status_code == 200:
    #                 data = response.json()
    #                 if data['data']:
    #                     latest_post = data['data'][0]
    #                     if account not in self.last_instagram_posts or self.last_instagram_posts[account] != latest_post['id']:
    #                         self.last_instagram_posts[account] = latest_post['id']
    #                         return f"New Instagram post from {account}:\n{latest_post['permalink']}"
    #     except Exception as e:
    #         print(f"Error fetching Instagram posts: {e}")
    #     return None

social_bot = SocialMediaBot()

@tasks.loop(minutes=5)
async def check_social_media():
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if channel:
        # Comment out Twitter check
        # twitter_update = await social_bot.fetch_twitter_posts()
        # if twitter_update:
        #     await channel.send(twitter_update)

        bluesky_update = await social_bot.fetch_bluesky_posts()
        if bluesky_update:
            await channel.send(embed=bluesky_update)

        # Comment out Instagram check
        # instagram_update = await social_bot.fetch_instagram_posts()
        # if instagram_update:
        #     await channel.send(instagram_update)

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    check_social_media.start()

# Run the bot
bot.run(DISCORD_TOKEN)

