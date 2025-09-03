# daily_manga_video.py
import os
import random
import json
import shutil
import smtplib
from email.message import EmailMessage
from datetime import datetime
from pathlib import Path

from gtts import gTTS
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    VideoFileClip, ImageClip, CompositeVideoClip,
    concatenate_videoclips, AudioFileClip, ColorClip
)
from moviepy.video.fx.all import loop as clip_loop

PROJECT = Path(__file__).parent.resolve()
ASSETS = PROJECT / "assets"
OUTPUT = PROJECT / "output"
OUTPUT.mkdir(exist_ok=True)

MANGA_JSON = PROJECT / "manga_list.json"
USED_JSON = PROJECT / "used.json"

WIDTH = 1080
HEIGHT = 1920
FPS = 30
TITLE_DURATION = 3.0
PER_ITEM_DURATION = 4.5
OUTRO_DURATION = 3.0
NUM_RECS = 5

PLACEHOLDER = ASSETS / "placeholder.jpg"
FONT_PATH = ASSETS / "fonts" / "Inter-Bold.ttf"

TITLES = [
    "Top 5 Today's Manga (Funny Picks!)",
    "Today's Top 5 Manga You Need to Read",
    "Five Manga That Ruined My Sleep 😹"
]
TAGS = "#manga #recommendation #anime"

GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_APP_PASSWORD")
TO_EMAIL = os.getenv("TO_EMAIL")

# ------------------- Helpers -------------------
def read_json(p: Path):
    if not p.exists():
        return []
    with open(p, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []

def write_json(p: Path, data):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_unused_items():
    manga = read_json(MANGA_JSON)
    used = read_json(USED_JSON)
    used_set = set(used)
    remaining = [m for m in manga if m[0] not in used_set]
    return manga, used, remaining

def make_text_image_fullscreen(text: str, width=WIDTH, height=HEIGHT, font_path=None, font_size=120, bg_color=(10,10,10)):
    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(str(font_path), font_size) if font_path and Path(font_path).exists() else ImageFont.load_default()
    except:
        font = ImageFont.load_default()

    words = text.split()
    lines = []
    cur = ""
    max_w = int(width * 0.85)
    for w in words:
        test = (cur + " " + w).strip()
        bbox = draw.textbbox((0,0), test, font=font)
        if bbox[2]-bbox[0] <= max_w:
            cur = test
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)

    _, _, _, line_h = draw.textbbox((0,0), "Ay", font=font)
    total_h = len(lines)*(line_h+10)
    y = (height-total_h)//2
    for line in lines:
        w0,h0 = draw.textbbox((0,0), line, font=font)[2:4]
        x = (width - w0)//2
        draw.text((x+2,y+2), line, font=font, fill=(0,0,0))
        draw.text((x,y), line, font=font, fill=(255,255,255))
        y += line_h + 10
    return img

def generate_tts(text: str, out: Path):
    tts = gTTS(text=text, lang="en")
    tts.save(str(out))

def send_email_with_attachment(subject, body, attachment_path):
    if not GMAIL_USER or not GMAIL_PASS or not TO_EMAIL:
        print("[!] Gmail env variables missing")
        return

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = GMAIL_USER
    msg['To'] = TO_EMAIL
    msg.set_content(body)

    with open(attachment_path, 'rb') as f:
        file_data = f.read()
        file_name = attachment_path.name
    msg.add_attachment(file_data, maintype='video', subtype='mp4', filename=file_name)

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(GMAIL_USER, GMAIL_PASS)
        smtp.send_message(msg)
        print(f"[+] Email sent to {TO_EMAIL}")

# ------------------- Video Builder -------------------
def build_video():
    manga, used, remaining = get_unused_items()
    if len(remaining) < NUM_RECS:
        used = []
        remaining = manga

    selected = random.sample(remaining, k=NUM_RECS)
    print("[*] Selected:", [s[0] for s in selected])
    ts = datetime.utcnow().strftime("%Y-%m-%d")
    out_file = OUTPUT / f"daily_{ts}.mp4"

    clips = []
    # Title
    title_text = random.choice(TITLES)
    title_img = make_text_image_fullscreen(title_text)
    tmp_title = OUTPUT / "title.jpg"
    title_img.save(tmp_title)
    img_clip = ImageClip(str(tmp_title)).set_duration(TITLE_DURATION).resize((WIDTH, HEIGHT))
    tts_title = OUTPUT / "tts_title.mp3"
    generate_tts(title_text, tts_title)
    if tts_title.exists(): img_clip = img_clip.set_audio(AudioFileClip(str(tts_title)))
    clips.append(img_clip)

    # Manga slides
    idx = 1
    for title, desc in selected:
        # Cover image fallback
        cover_path = PLACEHOLDER if not PLACEHOLDER.exists() else PLACEHOLDER
        slide_img = make_text_image_fullscreen(f"{title}\n\n{desc}", font_size=80)
        slide_path = OUTPUT / f"slide_{idx}.jpg"
        slide_img.save(slide_path)
        tts_path = OUTPUT / f"tts_{idx}.mp3"
        generate_tts(f"{title}. {desc}", tts_path)

        clip = ImageClip(str(slide_path)).set_duration(PER_ITEM_DURATION).resize((WIDTH, HEIGHT))
        if tts_path.exists(): clip = clip.set_audio(AudioFileClip(str(tts_path)))
        clips.append(clip)
        idx += 1

    # Outro
    outro_text = "If you watched till the end, hit follow for more recs!"
    outro_img = make_text_image_fullscreen(outro_text)
    outro_path = OUTPUT / "outro.jpg"
    outro_img.save(outro_path)
    tts_out = OUTPUT / "tts_outro.mp3"
    generate_tts(outro_text, tts_out)
    outro_clip = ImageClip(str(outro_path)).set_duration(OUTRO_DURATION).resize((WIDTH, HEIGHT))
    if tts_out.exists(): outro_clip = outro_clip.set_audio(AudioFileClip(str(tts_out)))
    clips.append(outro_clip)

    final = concatenate_videoclips(clips, method="compose")
    final.write_videofile(str(out_file), fps=FPS, codec="libx264", audio_codec="aac", threads=2, preset="medium", bitrate="4500k")
    print("[+] Video created:", out_file)

    # Update used.json
    used_new = read_json(USED_JSON) or []
    used_new.extend([t for t,_ in selected])
    write_json(USED_JSON, list(dict.fromkeys(used_new)))

    # Send email
    send_email_with_attachment(f"Daily Manga Video {ts}", "Here's your daily manga video!", out_file)

    return out_file

if __name__ == "__main__":
    build_video()
