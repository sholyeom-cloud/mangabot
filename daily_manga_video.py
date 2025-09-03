# daily_manga_video.py
"""
Daily manga top-5 video generator for GitHub Actions.
Selects 5 unused manga from manga_list.json, generates a vertical video,
updates used.json, and emails the final video with title, hashtags, and descriptions.
"""
import os
import random
import requests
import json
import shutil
from datetime import datetime
from pathlib import Path
import smtplib
from email.message import EmailMessage

from gtts import gTTS
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    VideoFileClip,
    ImageClip,
    CompositeVideoClip,
    concatenate_videoclips,
    AudioFileClip,
)
from moviepy.video.fx.all import loop as clip_loop

# --- Paths ---
PROJECT = Path(__file__).parent.resolve()
ASSETS = PROJECT / "assets"
OUTPUT = PROJECT / "output"
OUTPUT.mkdir(exist_ok=True)

MANGA_JSON = PROJECT / "manga_list.json"
USED_JSON = PROJECT / "used.json"

# --- Config ---
WIDTH = 1080
HEIGHT = 1920
FPS = 30
TITLE_DURATION = 3.0
PER_ITEM_DURATION = 4.5
OUTRO_DURATION = 3.0
NUM_RECS = 5

MINECRAFT_BG = ASSETS / "minecraft.mp4"
CAT_GIF = ASSETS / "cat.gif"
PLACEHOLDER = ASSETS / "placeholder.jpg"
FONT_PATH = ASSETS / "fonts" / "Inter-Bold.ttf"  # optional

SERPAPI_KEY = os.getenv("SERPAPI_KEY")  # optional for image search

TITLES = [
    "Top 5 today's manga (funny picks!)",
    "Today's top 5 manga you need to read",
    "Five manga that ruined my sleep 😹",
]

TAGS = "#manga #recommendation #anime"

# --- JSON helpers ---
def read_json(p: Path):
    if not p.exists():
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def write_json(p: Path, data):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# --- Manga selection ---
def get_unused_items():
    manga = read_json(MANGA_JSON) or []
    used = read_json(USED_JSON) or []
    used_set = set(used)
    remaining = [m for m in manga if m[0] not in used_set]
    return manga, used, remaining

# --- Image download via SerpAPI ---
def search_manga_image_serpapi(title: str):
    if not SERPAPI_KEY:
        return None
    try:
        url = "https://serpapi.com/search.json"
        params = {
            "engine": "google",
            "q": f"{title} manga cover",
            "tbm": "isch",
            "api_key": SERPAPI_KEY,
            "num": 1
        }
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        js = r.json()
        imgs = js.get("images_results") or js.get("images")
        if imgs and len(imgs) > 0:
            img = imgs[0]
            return img.get("original") or img.get("thumbnail")
    except Exception as e:
        print("[!] SerpAPI error:", e)
    return None

def download_image(url: str, dest: Path) -> bool:
    try:
        r = requests.get(url, stream=True, timeout=20)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8192):
                if chunk:
                    f.write(chunk)
        return True
    except Exception as e:
        print("[!] Download failed:", e)
        return False

# --- Text images ---
def make_text_image_fullscreen(text: str, width=WIDTH, height=HEIGHT, font_path=None, font_size=64, bg_color=(10,10,10)):
    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(str(font_path), font_size) if font_path and Path(font_path).exists() else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()
    words = text.split()
    lines = []
    cur = ""
    max_w = int(width * 0.85)
    for w in words:
        test = (cur + " " + w).strip()
        bbox = draw.textbbox((0,0), test, font=font)
        if bbox[2] - bbox[0] <= max_w:
            cur = test
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)
    _, _, _, line_h = draw.textbbox((0,0), "Ay", font=font)
    total_h = len(lines)*(line_h+8)
    y = (height-total_h)//2
    for line in lines:
        w0,h0 = draw.textsize(line, font=font)
        x = (width - w0)//2
        draw.text((x+2,y+2), line, font=font, fill=(0,0,0))
        draw.text((x,y), line, font=font, fill=(255,255,255))
        y += line_h+8
    return img

def add_description_overlay_to_image(src: Path, description: str, out: Path, font_path=None):
    try:
        image = Image.open(src).convert("RGBA")
    except Exception as e:
        print("[!] open error:", e); return False
    draw = ImageDraw.Draw(image)
    w,h = image.size
    try:
        font = ImageFont.truetype(str(font_path), max(18, w//20)) if font_path and Path(font_path).exists() else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()
    max_w = w - 80
    words = description.split()
    lines, cur = [], ""
    for wd in words:
        test = (cur + " " + wd).strip()
        bbox = draw.textbbox((0,0), test, font=font)
        if bbox[2]-bbox[0] <= max_w:
            cur = test
        else:
            if cur: lines.append(cur)
            cur = wd
    if cur: lines.append(cur)
    _,_,_,lh = draw.textbbox((0,0),"Ay",font=font)
    total_h = len(lines)*(lh+6)
    box_h = total_h + 40
    box_w = max([draw.textbbox((0,0), l, font=font)[2] for l in lines]) + 40
    bx0 = (w-box_w)//2; by0 = h - box_h - 120; bx1 = bx0+box_w; by1 = by0+box_h
    overlay = Image.new("RGBA", image.size, (0,0,0,0))
    ovd = ImageDraw.Draw(overlay)
    ovd.rectangle([bx0,by0,bx1,by1], fill=(0,0,0,180))
    image = Image.alpha_composite(image, overlay)
    draw = ImageDraw.Draw(image)
    tx = bx0 + 20; ty = by0 + 20
    for l in lines:
        draw.text((tx+1,ty+1), l, font=font, fill=(0,0,0,255))
        draw.text((tx,ty), l, font=font, fill=(255,255,255,255))
        ty += lh + 6
    image.convert("RGB").save(out, quality=90)
    return True

# --- TTS ---
def generate_tts(text: str, out: Path, lang="en"):
    try:
        tts = gTTS(text=text, lang=lang)
        tts.save(str(out))
        return True
    except Exception as e:
        print("[!] TTS error:", e)
        return False

# --- Build video ---
def build_video():
    manga, used, remaining = get_unused_items()
    if len(remaining) < NUM_RECS:
        print("[*] Not enough remaining -> resetting used list.")
        used = []
        remaining = manga

    selected = random.sample(remaining, k=NUM_RECS)
    selected_titles = [s[0] for s in selected]
    print("[*] Selected:", selected_titles)

    ts = datetime.utcnow().strftime("%Y-%m-%d")
    out_file = OUTPUT / f"daily_{ts}.mp4"

    total_dur = TITLE_DURATION + len(selected)*PER_ITEM_DURATION + OUTRO_DURATION

    # Background
    if MINECRAFT_BG.exists():
        bg = VideoFileClip(str(MINECRAFT_BG))
        bg = clip_loop(bg, duration=total_dur)
        bg = bg.resize(height=HEIGHT)
        if bg.w < WIDTH: bg = bg.resize(width=WIDTH)
        try: bg = bg.crop(x_center=bg.w/2, y_center=bg.h/2, width=WIDTH, height=HEIGHT)
        except Exception: pass
    else:
        from moviepy.editor import ColorClip
        bg = ColorClip(size=(WIDTH,HEIGHT), color=(10,10,10), duration=total_dur)

    cat_clip = None
    if CAT_GIF.exists():
        cat_clip_raw = VideoFileClip(str(CAT_GIF))
        cat_clip = clip_loop(cat_clip_raw, duration=total_dur)
        cat_clip = cat_clip.resize(width=int(WIDTH*0.28)).set_position(("center", int(HEIGHT*0.74)))

    clips = []
    # Title screen
    title_text = random.choice(TITLES)
    title_img = make_text_image_fullscreen(title_text, font_path=str(FONT_PATH) if FONT_PATH.exists() else None, font_size=72)
    tmp_title = OUTPUT / "title.jpg"
    title_img.save(tmp_title)
    bg_sub = bg.subclip(0, TITLE_DURATION)
    img_clip = ImageClip(str(tmp_title)).set_duration(TITLE_DURATION).resize((WIDTH,HEIGHT)).set_position(("center","center"))
    tts_title = OUTPUT / "tts_title.mp3"
    generate_tts(title_text, tts_title)
    components = [bg_sub, img_clip]
    if cat_clip: components.append(cat_clip.subclip(0, TITLE_DURATION))
    comp = CompositeVideoClip(components, size=(WIDTH,HEIGHT)).set_duration(TITLE_DURATION)
    if tts_title.exists(): comp = comp.set_audio(AudioFileClip(str(tts_title)))
    clips.append(comp)

    cursor = TITLE_DURATION
    slide_meta = []
    idx = 1
    for title, desc in selected:
        print("[*] Processing:", title)
        cover_url = search_manga_image_serpapi(title)
        orig = OUTPUT / f"cover_{idx}_orig.jpg"
        final = OUTPUT / f"cover_{idx}.jpg"
        if cover_url:
            ok = download_image(cover_url, orig)
            if not ok and PLACEHOLDER.exists():
                shutil.copy(PLACEHOLDER, orig)
        else:
            if PLACEHOLDER.exists(): shutil.copy(PLACEHOLDER, orig)
            else:
                im = Image.new("RGB",(720,1024),(20,20,20))
                d = ImageDraw.Draw(im); d.text((40,40), title, fill=(255,255,255)); im.save(orig)

        ok2 = add_description_overlay_to_image(orig, desc, final, font_path=str(FONT_PATH) if FONT_PATH.exists() else None)
        if not ok2: final = orig

        tts_path = OUTPUT / f"tts_{idx}.mp3"
        generate_tts(f"{title}. {desc}", tts_path)

        start = cursor; end = cursor + PER_ITEM_DURATION
        bg_sub = bg.subclip(start, end)
        img_clip = ImageClip(str(final)).set_duration(PER_ITEM_DURATION)
        w_target = int(WIDTH * 0.78)
        img_clip = img_clip.resize(width=w_target).set_position(("center", int(HEIGHT*0.33)))

        banner_img = make_text_image_fullscreen(title, width=WIDTH, height=200, font_path=str(FONT_PATH) if FONT_PATH.exists() else None, font_size=56)
        banner_path = OUTPUT / f"banner_{idx}.png"
        banner_img.crop((0,0,WIDTH,200)).save(banner_path)
        banner_clip = ImageClip(str(banner_path)).set_duration(PER_ITEM_DURATION).set_position(("center", int(HEIGHT*0.08)))

        comps = [bg_sub, img_clip, banner_clip]
        if cat_clip: comps.append(cat_clip.subclip(start, end))
        composed = CompositeVideoClip(comps, size=(WIDTH,HEIGHT)).set_duration(PER_ITEM_DURATION)
        if tts_path.exists(): composed = composed.set_audio(AudioFileClip(str(tts_path)))
        clips.append(composed)

        slide_meta.append({"title": title, "desc": desc, "img": str(final)})
        cursor += PER_ITEM_DURATION; idx += 1

    # Outro
    outro_text = "If you watched til the end, hit follow for more recs!"
    outro_img = make_text_image_fullscreen(outro_text, font_path=str(FONT_PATH) if FONT_PATH.exists() else None, font_size=54)
    outro_path = OUTPUT / "outro.jpg"; outro_img.save(outro_path)
    tts_out = OUTPUT / "tts_outro.mp3"; generate_tts(outro_text, tts_out)
    start = cursor; end = cursor + OUTRO_DURATION
    bg_sub = bg.subclip(start, end)
    out_img_clip = ImageClip(str(outro_path)).set_duration(OUTRO_DURATION).resize((WIDTH,HEIGHT)).set_position(("center","center"))
    comps = [bg_sub, out_img_clip]
    if cat_clip: comps.append(cat_clip.subclip(start, end))
    composed = CompositeVideoClip(comps, size=(WIDTH,HEIGHT)).set_duration(OUTRO_DURATION)
    if tts_out.exists(): composed = composed.set_audio(AudioFileClip(str(tts_out)))
    clips.append(composed)

    final = concatenate_videoclips(clips, method="compose")
    print("[*] Writing final video ...")
    final.write_videofile(str(out_file), fps=FPS, codec="libx264", audio_codec="aac", threads=2, preset="medium", bitrate="4500k")
    print("[+] Video written:", out_file)

    # update used.json (append selected titles)
    used_new = read_json(USED_JSON) or []
    used_new.extend([t for t,_ in selected])
    seen = set(); uniq = []
    for u in used_new:
        if u not in seen:
            seen.add(u); uniq.append(u)
    write_json(USED_JSON, uniq)

    # meta file
    meta = {"timestamp": ts, "slides": slide_meta, "title": title_text, "output": str(out_file)}
    write_json(OUTPUT / f"meta_{ts}.json", meta)
    return out_file, meta

# --- Email sending ---
def send_email(video_path: Path, title: str, slides: list):
    EMAIL_SENDER = os.getenv("GMAIL_USER")
    EMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASS")
    EMAIL_RECEIVER = os.getenv("EMAIL_TO")

    if not all([EMAIL_SENDER, EMAIL_APP_PASSWORD, EMAIL_RECEIVER]):
        print("[!] Missing Gmail environment variables. Skipping email.")
        return

    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER

    body = title + "\n" + TAGS + "\n\n"
    for s in slides:
        body += f"{s['title']}: {s['desc']}\n"
    msg.set_content(body)

    with open(video_path, "rb") as f:
        msg.add_attachment(f.read(), maintype="video", subtype="mp4", filename=video_path.name)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL_SENDER, EMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        print("[+] Email sent successfully!")
    except Exception as e:
        print("[!] Email sending failed:", e)

# --- Main ---
if __name__ == "__main__":
    video_path, meta = build_video()
    send_email(Path(meta["output"]), meta["title"], meta["slides"])
