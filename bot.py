import asyncio
import os
import discord
import random
import time
from dotenv import load_dotenv
import pymongo
from unidecode import unidecode
import yt_dlp
import io
from discord.ext import commands
import googleapiclient.discovery
from collections import deque

load_dotenv()

conn = os.getenv("MONGODB_CONNECTION_STR")
CORBU_ID = int(os.getenv("CORBU_ID"))
CIORAP_ID = int(os.getenv("CIORAP_ID"))
GUILD = os.getenv("GUILD_NAME")
TOKEN = os.getenv("BOT_TOKEN")
youtube = googleapiclient.discovery.build("youtube", "v3", developerKey= os.getenv("YOUTUBE_API_KEY"))

bot = commands.Bot(command_prefix='!', intents=discord.Intents.all())
mongodb = pymongo.MongoClient(conn)

swear_words_collection = mongodb["bot_db"]["swear_words"]
barbut_wins_collection = mongodb["bot_db"]["barbut_wins"]

barbut_players = []
swear_words = [w["word"] for w in swear_words_collection.find()]

class SongQueue:
    def __init__(self):
        self.queue = deque()
    
    def push(self, song):
        self.queue.append(song)

    def top(self):
        song = self.queue.popleft()
        self.push(song)
        return song
    
    def pop(self):
        return self.queue.popleft()

    def clear(self):
        self.queue.clear()
    
    def __len__(self):
        return len(self.queue)
    
song_queue = SongQueue()

def search_video(query):
    global youtube
    request = youtube.search().list(
        part="id",
        q=query,
        type="video",
        maxResults=1
    )
    response = request.execute()
    video_id = response["items"][0]["id"]["videoId"]
    return video_id

async def check_swear_words(message):
    global swear_words
    for word in swear_words:
        if (word.lower() in unidecode(message.content.lower())) and (message.author.id == CORBU_ID):
            response = 'taci ciorbule'
            await message.channel.send(response, reference=message)
            return

async def add_swear_word(message):
    new_word = message.content[11:]
    if new_word in swear_words:
        await message.channel.send(f'{new_word} is already a swear word.', reference=message)
    else:
        swear_words.append(new_word)
        swear_words_collection.insert_one({"word": new_word})
        await message.channel.send(f'{new_word} added to the swear words list!', reference=message)

async def do_barbut(message):
    global barbut_players

    if len(barbut_players) == 0 or message.author != barbut_players[0]:
        response = 'Nu esti Barbut Leader sau nu este inceput niciun joc de barbut.'
        await message.channel.send(response, reference=message)
        return
    
    response = 'A inceput barbutul!'
    await message.channel.send(response)
    time.sleep(1)

    mx = 0
    winners = []
    for player in barbut_players:
        nr = random.randint(1, 6)
        if nr > mx:
            mx = nr
            winners = [player]
        elif nr == mx:
            winners.append(player)

        msg = f'{player.mention} a dat {nr}.'
        await message.channel.send(msg)
        time.sleep(1)

    if len(winners) == 1:
        msg = f'{winners[0].mention} a castigat cu numarul {mx}!'
        await message.channel.send(msg)

        time.sleep(1)
        if len(barbut_players) > 1:
            result = barbut_wins_collection.find_one({"player_id": winners[0].id})
            if not result:
                barbut_wins_collection.insert_one({"player_id": winners[0].id, "wins": 0})
            barbut_wins_collection.update_one({"player_id": winners[0].id}, {"$inc": {"wins": 1}})

            result = barbut_wins_collection.find_one({"player_id": winners[0].id})
            msg = f'{winners[0].mention} are acum {result["wins"]} win-uri.'
            await message.channel.send(msg)
        else:
            await message.channel.send("Din pacate nu se adauga win pt ca ai jucat singur, prostule.")
    else:
        msg = 'Nimeni nu a castigat:\n'
        for winner in winners:
            msg += winner.mention + '\n' 
        msg += f' au dat numarul {mx}.'
        await message.channel.send(msg)


    barbut_players = []

async def print_barbut_leaderboard(channel):
    barbut_wins = [el for el in barbut_wins_collection.find()]
    barbut_wins = sorted(barbut_wins, key=lambda x: x["wins"], reverse=True)

    if len(barbut_wins) == 0:
        await channel.send("Leaderboard is empty :(")
    else:
        for idx, el in enumerate(barbut_wins):
            player = channel.guild.get_member(el["player_id"])
            wins = el["wins"]
            msg = f'{idx + 1}. {player.mention} with {wins} wins.'
            await channel.send(msg)

async def add_to_barbut(message):
    if not message.author in barbut_players:
        barbut_players.append(message.author)
        response = f'Ai intrat in barbut. Momentan sunt {len(barbut_players)} jucatori inscrisi.\n Pentru a intra in barbut scrie "!barbut_join".'
        await message.channel.send(response, reference=message)
    else:
        msg = 'Esti deja in barbut.'
        await message.channel.send(msg, reference=message)
    
def get_song_info(url):
    ydl_opts = {'format': 'bestaudio'}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)
    
async def print_queue_info(ctx):
    if len(song_queue) == 0:
        await ctx.channel.send("No songs in the queue.")
        return
    
    for idx, song_info in enumerate(list(song_queue.queue)):
        time.sleep(0.5)
        await ctx.channel.send(f'{idx + 1}. {song_info["title"]}')

async def add_to_queue(ctx, str):
    global song_queue
    url = str
    if not str.startswith('https://www.youtube.com/watch?v='):
        url = f'https://www.youtube.com/watch?v={search_video(str)}'
    song_queue.push(get_song_info(url))
    await ctx.channel.send(f'Song added! Current queue length: {len(song_queue)}', reference=ctx.message)
    
async def play(ctx):
    if not ctx.message.author.voice:
        await ctx.channel.send("You aren't connected to any voice channel.", reference=ctx.message)

    voice_channel = ctx.message.author.voice.channel

    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if not voice_client:
        await voice_channel.connect() 
        voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)

    if voice_client.is_playing():
        return

    ffmpeg_options = {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn'
    }
    while song_queue:
        song_info = song_queue.pop()

        ctx.voice_client.play(discord.FFmpegPCMAudio(song_info["url"], **ffmpeg_options)) 
        await ctx.channel.send(f'Now playing: {song_info["title"]}')

        while voice_client.is_playing():
            await asyncio.sleep(1)

    await voice_client.disconnect()

async def skip(ctx):
    voice_client = ctx.guild.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.stop()

async def clear(ctx):
    global song_queue
    song_queue.clear()

async def stop(ctx):
    await clear(ctx)
    await skip(ctx)

@bot.event
async def on_ready():
    guild = discord.utils.get(bot.guilds, name=GUILD)
    
    print(
        f'{bot.user} is connected to the following guild:\n' 
        f'{guild.name}(id: {guild.id})'
    )

@bot.event
async def on_message(message):
    global barbut_players
    global swear_words
    if message.author == bot.user:
        return
    
    ctx = await bot.get_context(message)

    await check_swear_words(message)

    if message.content.lower() == 'good bot':
        await message.channel.send('thanks', reference=message)
    
    if message.content.startswith('!swear_add ') and message.author.id != CORBU_ID:
        await add_swear_word(message)

    if message.content == '!barbut_leaderboard':
        await print_barbut_leaderboard(message.channel)

    if message.content == '!barbut_join':
        await add_to_barbut(message)

    if message.content == '!barbut_start':
        await do_barbut(message)

    if message.content.startswith('!play '):
        str = message.content[6:]
        if message.author.voice:
            await add_to_queue(ctx, str)
        try:
            await play(ctx)
        except Exception as e:
            print(f"Error playing song: {e}")

    if message.content == "!queue":
        await print_queue_info(ctx)
    
    if message.content == '!skip':
        await skip(ctx)

    if message.content == '!clear':
        await clear(ctx)

    if message.content == '!stop':
        await stop(ctx)

if __name__ == "__main__":
    bot.run(TOKEN)

mongodb.close()
