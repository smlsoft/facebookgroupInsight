"""
Facebook Group AI Agent v2
- Playwright browser automation (เสถียรใน Docker)
- AI Vision ดู screenshot → ตัดสินใจ action
- Flow: หากลุ่ม → เข้าอ่านโพสต์ → ตอบ comment แนะนำแบบผู้เชี่ยวชาญ
- Anti-detection: human-like typing, random delays, realistic mouse
- MongoDB Atlas storage + JSONL fallback
- run ต่อเนื่อง 24/7
"""
import asyncio
import base64
import json
import math
import os
import random
import signal
import sys
import traceback
from datetime import datetime
from pathlib import Path

from db import DB

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")
CONFIG_PATH = os.environ.get("CONFIG_PATH", "config.json")
LOG_FILE = os.path.join(OUTPUT_DIR, "agent_log.jsonl")
DEFAULT_INTERVAL_MIN = 60
MAX_AI_STEPS = 50
RUNNING = True


def handle_signal(sig, frame):
    global RUNNING
    print(f"\n[Signal] {sig} — กำลังหยุด...")
    RUNNING = False


signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def ensure_dirs():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(os.path.join(OUTPUT_DIR, "screenshots"), exist_ok=True)


# ---------------------------------------------------------------------------
# Structured Logging — ทุก action บันทึกเป็น JSONL สำหรับ Dashboard
# ---------------------------------------------------------------------------
_db_ref = None  # จะ set ตอน main()

def log_event(event_type: str, data: dict):
    """บันทึก event เป็น JSONL + MongoDB"""
    entry = {
        "ts": datetime.now().isoformat(),
        "type": event_type,
        **data,
    }
    line = json.dumps(entry, ensure_ascii=False)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    # MongoDB
    if _db_ref:
        _db_ref.log(event_type, data)
    # print สั้นๆ
    msg = data.get("message", data.get("reason", ""))
    print(f"  [{event_type}] {msg}")


# ---------------------------------------------------------------------------
# AI — OpenAI-compatible API
# ---------------------------------------------------------------------------
from openai import OpenAI


def create_ai_client(config: dict) -> tuple[OpenAI, str]:
    ai_cfg = config.get("ai", {})
    api_key = ai_cfg.get("api_key", os.environ.get("AI_API_KEY", ""))
    base_url = ai_cfg.get("base_url", os.environ.get("AI_BASE_URL", ""))
    model = ai_cfg.get("model", os.environ.get("AI_MODEL", "mimo-v2-omni"))
    if not api_key or not base_url:
        raise RuntimeError("ต้อง set ai.api_key + ai.base_url ใน config.json")
    return OpenAI(api_key=api_key, base_url=base_url), model


# --- Prompts ---

BROWSE_SYSTEM = """คุณเป็น AI Agent ควบคุม browser เพื่อ scrape Facebook Groups
ตอบ JSON object เดียว (ไม่มี text อื่น)

## Actions:
{"action": "click", "x": 640, "y": 300, "reason": "..."}
{"action": "type", "text": "...", "reason": "..."}
{"action": "press", "key": "Enter", "reason": "..."}
{"action": "scroll", "direction": "down", "amount": 500, "reason": "..."}
{"action": "wait", "seconds": 3, "reason": "..."}
{"action": "navigate", "url": "https://...", "reason": "..."}
{"action": "extract", "reason": "ดึงข้อมูลจากหน้าปัจจุบัน"}
{"action": "done", "reason": "เสร็จแล้ว"}
{"action": "dismiss_popup", "reason": "ปิด popup"}
{"action": "fill", "selector": "input[name='email']", "text": "...", "reason": "..."}

## กฏ:
- ตอบ JSON เดียว ไม่มี markdown/text อื่น
- เห็น popup → ปิดก่อน
- เห็นหน้า login → fill email/password แล้ว click login
- scroll พอแล้ว → "extract"
- เห็น CAPTCHA → "wait" 30 วินาที"""

REPLY_ANALYZER_SYSTEM = """คุณเป็นคนไทยธรรมดาที่มีประสบการณ์ด้านสินเชื่อ จำนอง ขายฝาก อสังหาริมทรัพย์
คุณ comment ใน Facebook Group — ต้องตอบเหมือนคนจริงๆ ที่ผ่านมาเจอเรื่องพวกนี้มาก่อน

วิเคราะห์โพสต์แล้วตอบ JSON:

{
  "should_reply": true/false,
  "reason": "ทำไมถึงควร/ไม่ควรตอบ",
  "reply_text": "ข้อความตอบ (ถ้า should_reply=true)",
  "post_summary": "สรุปเนื้อหาโพสต์สั้นๆ"
}

## ควรตอบ (should_reply=true) — ตอบเยอะหน่อย:
- คนถามเรื่อง จำนอง ขายฝาก สินเชื่อ ขั้นตอน เอกสาร
- คนต้องการคำปรึกษาเรื่อง บ้าน ที่ดิน ราคา
- คนประกาศหาทุน / หาที่ดิน / หาบ้าน
- คนประกาศขาย → แนะนำเรื่องราคา ทำเล ขั้นตอนได้
- คนถามคำถามสั้นๆ เช่น "แถวไหน" "ราคาเท่าไหร่" → ช่วยตอบแบบเป็นกันเอง
- โพสต์ที่มีรายละเอียดที่ดิน/บ้านน่าสนใจ → comment ชมหรือให้ข้อมูลเพิ่ม

## ไม่ควรตอบ (should_reply=false):
- spam / โฆษณาซ้ำๆ / ลิงก์อย่างเดียว
- โพสต์ภาษาอื่นที่ไม่เกี่ยว
- โพสต์ที่ไม่เกี่ยวกับอสังหาเลย

## สไตล์ (สำคัญมาก — ห้ามให้จับได้ว่าเป็น AI):
- พูดเหมือนคนไทยทั่วไป สบายๆ เป็นกันเอง
- ใช้ภาษาพูด ไม่ต้องเป็นทางการ
- มีคำลงท้ายแบบคนจริง เช่น "ครับ" "นะครับ" "ลองดูครับ"
- สั้นๆ 1-3 บรรทัด เหมือนคอมเมนต์ FB จริง
- ให้ความรู้จริงจัง แต่ไม่เหมือนบทความ
- ห้ามใช้คำว่า "ผม/ดิฉัน ยินดีให้ข้อมูล" หรือ "สรุปว่า" หรือ "ข้อแนะนำ"
- ห้าม bullet points ห้ามหัวข้อ ห้าม emoji เยอะ
- ถ้าตอบได้จากประสบการณ์จริง จะดีมาก เช่น "เคยทำขายฝากมา..."
- ใช้ emoji แค่ 0-1 ตัว (ถ้าจะใช้)

ตัวอย่างดี:
"ถ้าที่ดินมีโฉนด น่าจะกู้ได้ไม่ยากครับ ลองเช็คกับสถาบันการเงินแถวบ้านก่อน บางทีสหกรณ์ให้ดอกถูกกว่าธนาคารอีก"
"เคยเจอแบบนี้ครับ ขอแนะนำว่าอย่าเพิ่งเซ็นอะไร ไปปรึกษาที่ดินก่อน เอาโฉนดไปตรวจสอบให้ชัวร์"

ตอบเฉพาะ JSON"""


_token_usage = {"prompt": 0, "completion": 0, "calls": 0}


def track_usage(response):
    """บันทึก token usage + log ทุก call"""
    usage = getattr(response, "usage", None)
    if usage:
        _token_usage["prompt"] += getattr(usage, "prompt_tokens", 0)
        _token_usage["completion"] += getattr(usage, "completion_tokens", 0)
    _token_usage["calls"] += 1
    # Log token stats ทุก 5 calls
    if _token_usage["calls"] % 5 == 0:
        log_event("token_update", {"tokens": get_token_stats()})


def get_token_stats() -> dict:
    total = _token_usage["prompt"] + _token_usage["completion"]
    # ประมาณราคา (mimo-v2-omni ~$0.002/1K tokens)
    cost_usd = total * 0.002 / 1000
    cost_thb = cost_usd * 35  # ~35 THB/USD
    return {
        "prompt_tokens": _token_usage["prompt"],
        "completion_tokens": _token_usage["completion"],
        "total_tokens": total,
        "api_calls": _token_usage["calls"],
        "cost_usd": round(cost_usd, 4),
        "cost_thb": round(cost_thb, 2),
    }


async def ai_browse(client: OpenAI, model: str, screenshot_b64: str,
                    context: str, history: list[str]) -> dict:
    """AI ดู screenshot แล้วตัดสินใจ action"""
    history_text = "\n".join(f"  {i+1}: {h}" for i, h in enumerate(history[-8:]))
    response = client.chat.completions.create(
        model=model,
        max_tokens=200,
        messages=[
            {"role": "system", "content": BROWSE_SYSTEM},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{screenshot_b64}", "detail": "low"}},
                {"type": "text", "text": f"{context}\n\nประวัติ:\n{history_text or '(เริ่มใหม่)'}\n\nตอบ JSON action:"},
            ]},
        ],
    )
    track_usage(response)
    text = response.choices[0].message.content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text)


async def ai_analyze_post(client: OpenAI, model: str, screenshot_b64: str,
                          post_text: str = "") -> dict:
    """AI วิเคราะห์โพสต์ว่าควรตอบหรือไม่ + สร้างข้อความตอบ"""
    content = [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{screenshot_b64}", "detail": "low"}},
        {"type": "text", "text": f"วิเคราะห์โพสต์นี้:\n{post_text or '(ดูจาก screenshot)'}\n\nตอบ JSON:"},
    ]
    response = client.chat.completions.create(
        model=model,
        max_tokens=300,
        messages=[
            {"role": "system", "content": REPLY_ANALYZER_SYSTEM},
            {"role": "user", "content": content},
        ],
    )
    track_usage(response)
    text = response.choices[0].message.content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text)


# ---------------------------------------------------------------------------
# Anti-detection — Human-like behavior
# ---------------------------------------------------------------------------
async def human_delay(min_s=0.5, max_s=2.0):
    """หน่วงเวลาแบบสุ่ม เหมือนคนคิดก่อนทำ"""
    await asyncio.sleep(random.uniform(min_s, max_s))


async def human_type(page, text: str):
    """พิมพ์ทีละตัว — ความเร็วไม่สม่ำเสมอ มี typo chance บ้าง"""
    for i, ch in enumerate(text):
        # ความเร็วพิมพ์ไม่สม่ำเสมอ (burst + pause)
        if random.random() < 0.1 and i > 0:
            await asyncio.sleep(random.uniform(0.3, 0.8))  # pause คิด
        await page.keyboard.type(ch, delay=random.randint(25, 130))
    await asyncio.sleep(random.uniform(0.2, 0.6))


async def human_scroll(page, times=3):
    """Scroll เหมือนคนอ่าน — บางทีเลื่อนกลับขึ้นนิดหน่อย"""
    for _ in range(times):
        dy = random.randint(300, 600)
        await page.mouse.wheel(0, dy)
        await asyncio.sleep(random.uniform(1.5, 3.5))
        # 20% chance เลื่อนกลับขึ้นเล็กน้อย
        if random.random() < 0.2:
            await page.mouse.wheel(0, -random.randint(50, 150))
            await asyncio.sleep(random.uniform(0.5, 1.0))


async def human_mouse_wander(page, width=1280, height=720):
    """เลื่อน mouse ไปมา เหมือนคนดูหน้าจอ"""
    for _ in range(random.randint(1, 3)):
        x = random.randint(100, width - 100)
        y = random.randint(100, height - 100)
        await page.mouse.move(x, y, steps=random.randint(5, 15))
        await asyncio.sleep(random.uniform(0.2, 0.8))


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------
async def take_screenshot(page, name: str = "") -> tuple[str, str]:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = f"{ts}_{name}" if name else ts
    path = os.path.join(OUTPUT_DIR, "screenshots", f"{label}.jpg")
    # JPEG quality 40 + scale 50% ลดขนาดให้ mimo API รับได้
    await page.screenshot(path=path, full_page=False, type="jpeg", quality=40,
                          scale="css")
    # Resize ให้เล็กลงอีก ถ้า Pillow มี
    try:
        from PIL import Image as PILImage
        img = PILImage.open(path)
        img = img.resize((512, 300), PILImage.LANCZOS)
        img.save(path, "JPEG", quality=40)
    except ImportError:
        pass
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return path, b64


async def execute_action(page, action: dict) -> str:
    act = action.get("action", "wait")
    try:
        if act == "click":
            x_val = action.get("x", 0)
            y_val = action.get("y", 0)
            if isinstance(x_val, list):
                x, y = x_val[0], x_val[1] if len(x_val) > 1 else 0
            else:
                x, y = int(x_val), int(y_val)
            await page.mouse.click(x, y)
            await asyncio.sleep(random.uniform(0.5, 1.5))
            return f"clicked ({x},{y})"
        elif act == "type":
            await human_type(page, action["text"])
            return f"typed '{action['text'][:20]}...'"
        elif act == "press":
            await page.keyboard.press(action["key"])
            await asyncio.sleep(random.uniform(1, 3))
            return f"pressed {action['key']}"
        elif act == "scroll":
            dy = action.get("amount", 500)
            if action.get("direction") == "up":
                dy = -dy
            await page.mouse.wheel(0, dy)
            await asyncio.sleep(random.uniform(1, 2))
            return f"scrolled {action.get('direction','down')} {abs(dy)}px"
        elif act == "wait":
            await asyncio.sleep(action.get("seconds", 3))
            return f"waited {action.get('seconds',3)}s"
        elif act == "navigate":
            await page.goto(action["url"], wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(random.uniform(2, 4))
            return f"navigated"
        elif act == "fill":
            await page.fill(action.get("selector", ""), action.get("text", ""))
            await asyncio.sleep(0.5)
            return f"filled"
        elif act == "dismiss_popup":
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
            return "dismissed"
        elif act == "extract":
            return "extract_requested"
        elif act == "done":
            return "done"
        else:
            return f"unknown: {act}"
    except Exception as e:
        return f"error: {e}"


async def extract_groups(page, keyword: str) -> list[dict]:
    try:
        raw = await page.evaluate(r"""
            (() => {
                const results = [];
                const links = document.querySelectorAll('a[href*="/groups/"]');
                for (const link of links) {
                    const href = link.href || '';
                    const text = link.innerText?.trim() || '';
                    if (!text || text.length < 3) continue;
                    if (/join|create|feed|discover|search|login/i.test(href)) continue;
                    let members = 'N/A', privacy = 'unknown';
                    const p = link.closest('[role="article"]')
                        || link.parentElement?.parentElement?.parentElement?.parentElement;
                    if (p) {
                        const pt = p.innerText || '';
                        const m = pt.match(/([\d,.]+\s*[KkMm]?)\s*(?:members|สมาชิก)/);
                        if (m) members = m[1].trim();
                        if (/สาธารณะ|Public/.test(pt)) privacy = 'public';
                        else if (/ส่วนตัว|Private/.test(pt)) privacy = 'private';
                    }
                    results.push({ name: text.split('\n')[0], url: href.split('?')[0], members, privacy });
                }
                return results;
            })()
        """)
    except Exception:
        return []
    seen = set()
    groups = []
    for item in raw:
        url = item["url"].rstrip("/")
        if url not in seen:
            seen.add(url)
            groups.append({**item, "url": url, "keyword": keyword,
                           "scraped_at": datetime.now().isoformat()})
    return groups


async def extract_posts(page) -> list[dict]:
    """ดึงโพสต์จากหน้ากลุ่ม"""
    try:
        raw = await page.evaluate(r"""
            (() => {
                const posts = [];
                // Facebook posts อยู่ใน role="article"
                const articles = document.querySelectorAll('[role="article"]');
                for (const art of articles) {
                    const text = art.innerText?.trim() || '';
                    if (text.length < 20) continue;
                    // หา link ไปโพสต์
                    const timeLink = art.querySelector('a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid"]');
                    const url = timeLink?.href?.split('?')[0] || '';
                    // หาชื่อคนโพสต์
                    const authorEl = art.querySelector('a[role="link"] strong, h3 a, h4 a');
                    const author = authorEl?.innerText?.trim() || 'unknown';
                    posts.push({
                        author,
                        text: text.substring(0, 500),
                        url,
                        hasImage: art.querySelectorAll('img').length > 1,
                    });
                }
                return posts;
            })()
        """)
        return raw[:20]  # จำกัด 20 โพสต์
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Phase 1: หากลุ่ม
# ---------------------------------------------------------------------------
async def phase_find_groups(page, keyword: str, config: dict,
                            client: OpenAI, model: str) -> list[dict]:
    """AI Agent ค้นหากลุ่ม"""
    email = config["facebook"]["email"]
    password = config["facebook"]["password"]
    settings = config["settings"]

    # Navigate ไป search URL ตรงๆ (ไม่ต้องให้ AI หา search bar)
    import urllib.parse
    search_url = f"https://www.facebook.com/search/groups/?q={urllib.parse.quote(keyword)}"
    log_event("action", {"phase": "find_groups", "action": "navigate",
                         "reason": f"ไป search groups: {keyword}"})
    try:
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        await page.evaluate(f'location.href = "{search_url}"')
    await asyncio.sleep(random.uniform(4, 7))

    context = f"""อยู่ที่หน้าผลการค้นหากลุ่ม Facebook สำหรับ "{keyword}"
ถ้าเห็นผลลัพธ์กลุ่ม → scroll ลงดูเพิ่ม
ถ้ายังไม่เห็น → กดแท็บ "กลุ่ม" หรือ "Groups"
ถ้ามีหน้า login → กรอก email:{email} pass:{password}
ถ้ามี popup → ปิด
scroll ครบ {settings.get('max_scroll', 8)} ครั้ง → extract"""

    history = []
    scroll_count = 0
    max_scroll = settings.get("max_scroll", 8)

    error_count = 0
    for step in range(MAX_AI_STEPS):
        if not RUNNING:
            break
        # ถ้า error ติดกัน 5 ครั้ง → ข้ามไปใช้กลุ่มที่เคย save ไว้
        if error_count >= 5:
            log_event("fallback", {"message": "error มากเกินไป — ข้าม find_groups"})
            break

        shot_path, b64 = await take_screenshot(page, f"find_{step:02d}_{keyword[:6]}")

        try:
            action = await ai_browse(client, model, b64, context, history)
            error_count = 0  # reset
        except json.JSONDecodeError:
            history.append("AI JSON error — skip")
            error_count += 1
            continue
        except Exception as e:
            log_event("error", {"message": f"AI error: {e}", "phase": "find_groups"})
            error_count += 1
            await asyncio.sleep(5)
            continue

        reason = action.get("reason", "")
        log_event("action", {"phase": "find_groups", "keyword": keyword,
                             "step": step, "action": action.get("action"),
                             "reason": reason, "screenshot": shot_path})

        result = await execute_action(page, action)
        history.append(f"{action.get('action')}: {reason} → {result}")

        if action["action"] == "scroll":
            scroll_count += 1
        if scroll_count >= max_scroll or result in ("extract_requested", "done"):
            groups = await extract_groups(page, keyword)
            log_event("extract", {"phase": "find_groups", "keyword": keyword,
                                  "count": len(groups)})
            return groups

        await asyncio.sleep(random.uniform(0.3, 1))

    return await extract_groups(page, keyword)


# ---------------------------------------------------------------------------
# Phase 2: อ่านโพสต์ + ตอบ comment
# ---------------------------------------------------------------------------
async def try_join_group(page, group_name: str, client: OpenAI, model: str) -> bool:
    """ตรวจว่าเป็นสมาชิกกลุ่มหรือยัง ถ้ายัง → กด Join + ตอบคำถาม
    Return True ถ้าเป็นสมาชิกแล้ว (comment ได้), False ถ้ายังไม่ได้"""

    # ตรวจว่าเป็นสมาชิกแล้วหรือยัง — ดูว่ามีปุ่ม "เข้าร่วม" หรือไม่
    join_selectors = [
        'div[aria-label*="เข้าร่วมกลุ่ม"]',
        'div[aria-label*="Join group"]',
        'div[aria-label*="Join Group"]',
        'a:has-text("เข้าร่วม")',
        'span:has-text("+ เข้าร่วม")',
    ]

    # ตรวจว่ามีปุ่ม Join หรือไม่
    join_btn = None
    for sel in join_selectors:
        try:
            join_btn = await page.wait_for_selector(sel, timeout=2000)
            if join_btn:
                break
        except Exception:
            continue

    if not join_btn:
        # ไม่มีปุ่ม Join → อาจเป็นสมาชิกแล้ว หรือ pending
        # ตรวจ pending
        try:
            pending = await page.wait_for_selector(
                'span:has-text("กำลังรออนุมัติ"), span:has-text("Pending")', timeout=1000)
            if pending:
                log_event("join_pending", {"group": group_name,
                                           "message": f"รออนุมัติ: {group_name}"})
                return False
        except Exception:
            pass
        # ไม่มีปุ่ม Join ไม่มี Pending → น่าจะเป็นสมาชิกแล้ว
        log_event("already_member", {"group": group_name,
                                      "message": f"เป็นสมาชิกแล้ว: {group_name}"})
        return True

    # กด Join
    log_event("joining", {"group": group_name, "message": f"กด Join: {group_name}"})
    await join_btn.click()
    await human_delay(3, 5)

    # ตรวจว่ามี popup คำถามจากแอดมินหรือไม่
    for attempt in range(5):
        # หา checkbox / radio
        try:
            checkbox = await page.wait_for_selector(
                'input[type="checkbox"], input[type="radio"], '
                'div[role="checkbox"], div[role="radio"]', timeout=2000)
            if checkbox:
                await checkbox.click()
                log_event("join_answer", {"group": group_name, "step": attempt,
                                          "message": "เลือก checkbox/radio"})
                await human_delay(0.5, 1)
                continue
        except Exception:
            pass

        # หาปุ่ม "ส่ง" / "Submit" / "ตกลง"
        submit_found = False
        for txt in ["ส่งคำตอบ", "ส่ง", "ตกลง", "Submit", "ยืนยัน"]:
            try:
                btn = await page.wait_for_selector(f'div[role="button"]:has-text("{txt}")', timeout=1000)
                if btn:
                    await btn.click()
                    submit_found = True
                    log_event("join_submit", {"group": group_name,
                                              "message": f"กด '{txt}'"})
                    await human_delay(2, 4)
                    break
            except Exception:
                continue

        if not submit_found:
            # ไม่มี popup แล้ว → ใช้ AI ดูสถานะ
            _, b64 = await take_screenshot(page, f"join_{attempt}_{group_name[:8]}")
            try:
                q_action = await ai_browse(client, model, b64,
                    f"""หลังกด Join กลุ่ม "{group_name}" — ดู screenshot:
1. ถ้ามีคำถาม/checkbox → click เลือกตัวเลือกที่เหมาะสม (เช่น "ใช่มาซื้อ")
2. ถ้ามีปุ่ม "ส่ง"/"Submit"/"ตกลง" → click
3. ถ้าไม่มี popup → action "done"
ตอบ JSON action เดียว""",
                    [])
                if q_action.get("action") == "done":
                    break
                await execute_action(page, q_action)
                await human_delay(1, 2)
            except Exception:
                break

    await human_delay(2, 3)

    # ตรวจผล — ยังมีปุ่ม Join อยู่ไหม?
    still_join = False
    for sel in join_selectors[:3]:
        try:
            btn = await page.wait_for_selector(sel, timeout=1500)
            if btn:
                still_join = True
                break
        except Exception:
            continue

    # ตรวจ pending
    is_pending = False
    try:
        pending = await page.wait_for_selector(
            'span:has-text("กำลังรออนุมัติ"), span:has-text("Pending")', timeout=1500)
        if pending:
            is_pending = True
    except Exception:
        pass

    if is_pending:
        log_event("join_pending", {"group": group_name,
                                    "message": f"รออนุมัติ: {group_name} — ข้ามไป"})
        return False
    elif still_join:
        log_event("join_failed", {"group": group_name,
                                   "message": f"Join ไม่สำเร็จ: {group_name}"})
        return False
    else:
        log_event("join_success", {"group": group_name,
                                    "message": f"เข้าร่วมสำเร็จ: {group_name}"})
        return True


async def phase_read_and_reply(page, group: dict, config: dict,
                               client: OpenAI, model: str) -> list[dict]:
    """เข้ากลุ่ม → ตรวจ/Join → อ่านโพสต์ → AI วิเคราะห์ → ตอบ comment"""
    settings = config["settings"]
    max_replies = settings.get("max_replies_per_group", 3)
    replied = []

    group_url = group["url"]
    group_name = group["name"]
    log_event("enter_group", {"group": group_name, "url": group_url})

    # navigate เข้ากลุ่ม
    try:
        await page.goto(group_url, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        await page.evaluate(f'location.href = "{group_url}"')
    await asyncio.sleep(random.uniform(3, 5))

    # ตรวจ + Join ถ้ายังไม่เป็นสมาชิก
    is_member = await try_join_group(page, group_name, client, model)
    if not is_member:
        log_event("skip_group", {"group": group_name,
                                  "message": f"ข้ามกลุ่ม {group_name} — ยังไม่เป็นสมาชิก"})
        return []

    # scroll ลงดูโพสต์
    for i in range(5):
        await page.mouse.wheel(0, random.randint(400, 700))
        await asyncio.sleep(random.uniform(1.5, 3))

    # ดึงโพสต์
    posts = await extract_posts(page)
    log_event("posts_found", {"group": group_name, "count": len(posts)})

    if not posts:
        return []

    # วิเคราะห์ทีละโพสต์
    reply_count = 0
    for i, post in enumerate(posts):
        if not RUNNING or reply_count >= max_replies:
            break

        post_text = post.get("text", "")
        if len(post_text) < 30:
            continue

        # ถ่าย screenshot แล้วให้ AI วิเคราะห์
        shot_path, b64 = await take_screenshot(page, f"post_{i:02d}_{group_name[:8]}")

        try:
            analysis = await ai_analyze_post(client, model, b64, post_text)
        except Exception as e:
            log_event("error", {"message": f"Analyze error: {e}", "post_index": i})
            continue

        should_reply = analysis.get("should_reply", False)
        reply_text = analysis.get("reply_text", "")
        post_summary = analysis.get("post_summary", "")

        log_event("post_analyzed", {
            "group": group_name,
            "post_index": i,
            "post_summary": post_summary,
            "should_reply": should_reply,
            "reply_text": reply_text[:100] if reply_text else "",
            "screenshot": shot_path,
        })

        if should_reply and reply_text:
            post_url = post.get("url", "")

            # navigate ไปที่โพสต์
            if post_url:
                try:
                    await page.goto(post_url, wait_until="domcontentloaded", timeout=20000)
                    await asyncio.sleep(random.uniform(3, 6))
                except Exception:
                    pass

            # scroll ลงหา comment box
            await page.mouse.wheel(0, 500)
            await human_delay(1, 2)

            # ตรวจก่อนว่ามีช่อง comment หรือไม่ — ถ้าไม่มีก็ข้ามเลย
            typed_ok = False
            comment_selectors = [
                'div[aria-label*="เขียนความคิดเห็น"]',
                'div[aria-label*="Write a comment"]',
                'div[aria-label*="Write a public comment"]',
                'div[aria-label*="แสดงความคิดเห็น"]',
                'form div[contenteditable="true"][role="textbox"]',
            ]
            for sel in comment_selectors:
                try:
                    box = await page.wait_for_selector(sel, timeout=3000)
                    if box:
                        await box.click()
                        await human_delay(0.5, 1.0)
                        await human_type(page, reply_text)
                        await human_delay(0.5, 1.0)
                        typed_ok = True
                        log_event("typing", {"group": group_name, "selector": sel,
                                             "message": f"พิมพ์ comment สำเร็จ"})
                        break
                except Exception:
                    continue

            if not typed_ok:
                log_event("reply_failed", {"group": group_name,
                                           "reason": "หา comment box ไม่เจอ"})
            else:
                # ถ่าย screenshot ก่อนส่ง
                shot_typed, _ = await take_screenshot(page, f"typed_{i:02d}_{group_name[:8]}")

                # กดส่ง — หาปุ่มลูกศรส่ง (icon 16x16 aria-label="แสดงความคิดเห็น")
                sent_ok = False

                # วิธี 1: หาปุ่ม submit ขนาดเล็ก (icon ลูกศร) ด้วย JS
                try:
                    clicked = await page.evaluate('''() => {
                        const btns = document.querySelectorAll('div[role="button"][aria-label="แสดงความคิดเห็น"], div[role="button"][aria-label="Comment"]');
                        for (const btn of btns) {
                            const rect = btn.getBoundingClientRect();
                            // ปุ่มลูกศรส่งจะเล็ก (< 30px) อยู่ใกล้ comment box
                            if (rect.width <= 30 && rect.height <= 30 && rect.width > 5) {
                                btn.click();
                                return true;
                            }
                        }
                        return false;
                    }''')
                    if clicked:
                        sent_ok = True
                        log_event("submit", {"method": "arrow_button"})
                except Exception:
                    pass

                # วิธี 2: click ตำแหน่งปุ่มลูกศรโดยตรง (ใกล้ขวาล่างของ comment box)
                if not sent_ok:
                    try:
                        box_rect = await page.evaluate('''() => {
                            const box = document.querySelector('[aria-label*="เขียนความคิดเห็น"]');
                            if (!box) return null;
                            const rect = box.getBoundingClientRect();
                            return {x: rect.right + 20, y: rect.bottom + 15};
                        }''')
                        if box_rect:
                            await page.mouse.click(int(box_rect["x"]), int(box_rect["y"]))
                            sent_ok = True
                            log_event("submit", {"method": "click_near_box"})
                    except Exception:
                        pass

                await human_delay(3, 5)

                # ถ่าย screenshot หลังส่ง
                shot_sent, _ = await take_screenshot(page, f"sent_{i:02d}_{group_name[:8]}")

                reply_count += 1
                log_event("replied", {
                    "group": group_name,
                    "post_url": post_url,
                    "post_summary": post_summary,
                    "reply_text": reply_text,
                    "screenshot_typed": shot_typed,
                    "screenshot_sent": shot_sent,
                })
                replied.append({
                    "group": group_name,
                    "post_url": post_url,
                    "post_summary": post_summary,
                    "reply_text": reply_text,
                    "replied_at": datetime.now().isoformat(),
                })

            # กลับไปหน้ากลุ่ม
            try:
                await page.goto(group_url, wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(random.uniform(3, 5))
            except Exception:
                pass

            # พักหลังตอบ (ป้องกันแบน)
            wait_after = random.randint(45, 120)
            log_event("cooldown", {"seconds": wait_after, "message": f"พักหลังตอบ {wait_after}s"})
            await asyncio.sleep(wait_after)

    return replied


# ---------------------------------------------------------------------------
# Main Loop
# ---------------------------------------------------------------------------
async def main():
    global RUNNING

    config = load_config()
    ensure_dirs()

    try:
        client, model = create_ai_client(config)
    except RuntimeError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    global _db_ref
    db = DB(config)
    _db_ref = db
    keywords = config["keywords"]
    settings = config["settings"]
    continuous = settings.get("continuous", False)
    interval_min = settings.get("interval_minutes", DEFAULT_INTERVAL_MIN)

    log_event("startup", {
        "message": "Facebook AI Agent v2 started",
        "model": model,
        "keywords": keywords,
        "continuous": continuous,
    })
    print("=" * 60)
    print("  Facebook AI Agent v2")
    print(f"  AI: {config['ai']['base_url']} / {model}")
    print(f"  Continuous: {continuous} | Interval: {interval_min}m")
    print(f"  Keywords: {', '.join(keywords)}")
    print("=" * 60)

    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                  "--disable-notifications", "--lang=th-TH"],
        )
        context = await browser.new_context(
            viewport={"width": 1024, "height": 600},
            locale="th-TH", timezone_id="Asia/Bangkok",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )

        # Load cookies
        cookies_file = os.path.join(OUTPUT_DIR, "cookies.json")
        if os.path.exists(cookies_file):
            try:
                with open(cookies_file) as f:
                    await context.add_cookies(json.load(f))
                log_event("cookies", {"message": "loaded"})
            except Exception:
                pass

        page = await context.new_page()
        await page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        # === Main Loop ===
        round_num = 0
        while RUNNING:
            round_num += 1
            start_time = datetime.now()
            log_event("round_start", {"round": round_num})

            try:
                config = load_config()
                keywords = config["keywords"]
                settings = config["settings"]
                all_groups = []
                all_replies = []

                # Phase 1: หากลุ่ม (ใช้ keyword แรก — หมุนเวียน)
                kw = keywords[(round_num - 1) % len(keywords)]
                log_event("phase", {"phase": "find_groups", "keyword": kw})

                groups = await phase_find_groups(page, kw, config, client, model)
                all_groups.extend(groups)

                # Save groups
                if groups:
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    path = os.path.join(OUTPUT_DIR, f"groups_{ts}.json")
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(groups, f, ensure_ascii=False, indent=2)
                    db.save_groups(groups)

                # Phase 2: เข้ากลุ่ม top 3 → อ่าน + ตอบ
                max_groups = settings.get("max_groups_per_round", 3)
                target_groups = [g for g in groups if g["privacy"] == "public"][:max_groups]

                for g in target_groups:
                    if not RUNNING:
                        break
                    log_event("phase", {"phase": "read_reply", "group": g["name"]})

                    try:
                        replies = await phase_read_and_reply(page, g, config, client, model)
                        all_replies.extend(replies)
                    except Exception as e:
                        log_event("error", {"message": str(e), "group": g["name"]})

                    # พัก
                    await asyncio.sleep(random.uniform(15, 45))

                # Save replies
                if all_replies:
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    path = os.path.join(OUTPUT_DIR, f"replies_{ts}.json")
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(all_replies, f, ensure_ascii=False, indent=2)
                    for r in all_replies:
                        db.save_reply(r)

                # Save cookies
                try:
                    cookies = await context.cookies()
                    with open(cookies_file, "w") as f:
                        json.dump(cookies, f)
                except Exception:
                    pass

                elapsed = (datetime.now() - start_time).total_seconds()
                token_stats = get_token_stats()
                round_data = {
                    "round": round_num,
                    "keyword": kw,
                    "elapsed_sec": int(elapsed),
                    "groups_found": len(all_groups),
                    "replies_sent": len(all_replies),
                    "tokens": token_stats,
                }
                log_event("round_end", {
                    **round_data,
                    "message": f"รอบ {round_num}: {len(all_groups)} กลุ่ม, {len(all_replies)} ตอบ ({elapsed:.0f}s)",
                })
                db.save_round(round_data)

            except Exception as e:
                log_event("error", {"message": str(e), "round": round_num})
                traceback.print_exc()

            if not continuous:
                break

            interval_min = settings.get("interval_minutes", DEFAULT_INTERVAL_MIN)
            jitter = random.randint(-5, 5)
            wait_sec = max(60, (interval_min + jitter) * 60)
            log_event("sleep", {"minutes": wait_sec // 60,
                                "message": f"รอ {wait_sec // 60} นาที"})
            for _ in range(int(wait_sec)):
                if not RUNNING:
                    break
                await asyncio.sleep(1)

        await browser.close()

    log_event("shutdown", {"message": "Agent หยุดทำงาน"})


if __name__ == "__main__":
    asyncio.run(main())
