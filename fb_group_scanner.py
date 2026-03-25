"""
Facebook Group Scanner v7 (nodriver + Docker + continuous loop)
- nodriver = undetected Chrome ไม่มี WebDriver signature
- Facebook ตรวจจับไม่ได้
- เก็บ cookies ใช้ซ้ำ login ครั้งเดียว
- รองรับ Docker (Xvfb virtual display)
- run ต่อเนื่องตลอด — scan ซ้ำทุก interval
"""
import sys
import io

# Windows UTF-8 fix
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import asyncio
import json
import os
import random
import re
import signal
import traceback
from datetime import datetime

import nodriver as uc


def load_config(path="config.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")
COOKIES_FILE = os.path.join(OUTPUT_DIR, "fb_nodriver_cookies.json")

# Continuous loop settings
DEFAULT_INTERVAL_MIN = 60  # scan ซ้ำทุก 60 นาที (ปรับใน config.json ได้)
RUNNING = True


def handle_signal(sig, frame):
    global RUNNING
    print(f"\n[Signal] ได้รับ signal {sig} — กำลังหยุด...")
    RUNNING = False


signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)


def ensure_dirs():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(os.path.join(OUTPUT_DIR, "screenshots"), exist_ok=True)


async def safe_navigate(tab, url, wait_sec=5):
    """Navigate แบบไม่ค้าง — ใช้ JS location.href แทน tab.get()
    เพราะ Facebook เป็น SPA ไม่ fire page load event ทำให้ tab.get() ค้าง"""
    try:
        await tab.evaluate(f'location.href = "{url}"')
    except Exception:
        try:
            await asyncio.wait_for(tab.get(url), timeout=15)
        except Exception:
            print(f"  [Nav] fallback timeout — ลองต่อ")
    await tab.wait(wait_sec)


async def screenshot(tab, name):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(OUTPUT_DIR, "screenshots", f"{ts}_{name}.png")
    try:
        await tab.save_screenshot(path)
        print(f"  [Shot] {path}")
    except Exception as e:
        print(f"  [Shot Error] {e}")
    return path


async def save_cookies(browser):
    try:
        cookies = await asyncio.wait_for(browser.cookies.get_all(), timeout=10)
        with open(COOKIES_FILE, "w", encoding="utf-8") as f:
            json.dump([c.__dict__ for c in cookies] if hasattr(cookies[0], '__dict__') else cookies, f, default=str)
        print(f"  [Cookies] saved ({len(cookies)})")
    except asyncio.TimeoutError:
        print(f"  [Cookies] timeout — ข้ามไป")
    except Exception as e:
        print(f"  [Cookies Error] {e}")


async def load_cookies(browser):
    if not os.path.exists(COOKIES_FILE):
        return False
    try:
        with open(COOKIES_FILE, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        for c in cookies:
            try:
                await browser.cookies.set_all([c])
            except Exception:
                pass
        print(f"  [Cookies] loaded ({len(cookies)})")
        return True
    except Exception:
        return False


async def dismiss_popups(tab):
    """ปิด popup ทั้งหมดอัตโนมัติ — notifications, save password, cookies"""
    for _ in range(1):  # 1 รอบพอ — ลด overhead ใน Docker
        # Notification + Cookie + Save password
        for text in ["Block", "Not Now", "ไม่ใช่ตอนนี้", "Close", "ปิด",
                      "Allow all cookies", "ยอมรับทั้งหมด", "Accept All"]:
            try:
                btn = await asyncio.wait_for(
                    tab.find(text, best_match=True, timeout=1), timeout=3
                )
                if btn:
                    await btn.click()
                    print(f"  [Popup] กด '{text}'")
                    await tab.wait(0.3)
            except Exception:
                pass

        # ปิด dialog อื่นๆ ด้วย Escape
        try:
            await tab.send_keys("\x1b")  # Escape
            await tab.wait(0.3)
        except Exception:
            pass


async def auto_login(tab, browser, email, password):
    """Login Facebook — ตรวจ session เก่าก่อน"""
    print("\n[Login] ตรวจสอบ...")

    await safe_navigate(tab, "https://www.facebook.com/", wait_sec=4)
    await screenshot(tab, "01_home")

    # ตรวจว่า login แล้ว — หา search bar
    try:
        search = await tab.find("ค้นหาบน Facebook", best_match=True, timeout=3)
        if search:
            print("  [OK] มี session เดิม!")
            return True
    except Exception:
        pass

    try:
        search = await tab.find("Search Facebook", best_match=True, timeout=2)
        if search:
            print("  [OK] มี session เดิม!")
            return True
    except Exception:
        pass

    # ยังไม่ login — ไปหน้า login ตรงๆ
    print("  [Login] กำลัง login...")
    await safe_navigate(tab, "https://www.facebook.com/login/", wait_sec=3)
    await screenshot(tab, "02_login_page")

    try:
        # หา email field หลายแบบ
        email_field = None
        for sel in ["#email", 'input[name="email"]', 'input[type="email"]', 'input[type="text"]']:
            try:
                email_field = await tab.select(sel, timeout=2)
                if email_field:
                    break
            except Exception:
                continue

        if email_field:
            await email_field.click()
            await tab.wait(0.3)
            await email_field.send_keys(email)
            await tab.wait(random.uniform(0.5, 1.0))
        else:
            print("  [!] หา email field ไม่เจอ")

        # หา password field
        pass_field = None
        for sel in ["#pass", 'input[name="pass"]', 'input[type="password"]']:
            try:
                pass_field = await tab.select(sel, timeout=2)
                if pass_field:
                    break
            except Exception:
                continue

        if pass_field:
            await pass_field.click()
            await tab.wait(0.3)
            await pass_field.send_keys(password)
            await tab.wait(random.uniform(0.3, 0.7))

        await screenshot(tab, "02_filled")

        # กด login — ลองหลายวิธี
        clicked_login = False

        # วิธี 1: หาปุ่มด้วย text "Log in" หรือ "เข้าสู่ระบบ"
        for text in ["Log in", "Log In", "เข้าสู่ระบบ"]:
            try:
                btn = await tab.find(text, best_match=True, timeout=2)
                if btn:
                    await btn.click()
                    clicked_login = True
                    break
            except Exception:
                continue

        # วิธี 2: selector
        if not clicked_login:
            for sel in ['button[name="login"]', '#loginbutton', 'button[type="submit"]', 'button[data-testid="royal_login_button"]']:
                try:
                    btn = await tab.select(sel, timeout=2)
                    if btn:
                        await btn.click()
                        clicked_login = True
                        break
                except Exception:
                    continue

        # วิธี 3: กด Enter ใน password field
        if not clicked_login:
            print("  [!] หาปุ่ม login ไม่เจอ — กด Enter แทน")
            if pass_field:
                await pass_field.click()
                await tab.wait(0.2)
            await tab.send_keys("\n")

        await tab.wait(5)
        await screenshot(tab, "03_after_click")
    except Exception as e:
        print(f"  [!] Login error: {e}")

    # รอ login สำเร็จ (max 2 นาที สำหรับ 2FA)
    print("  [Wait] รอ login... (ถ้ามี 2FA ทำใน Chrome)")
    for i in range(60):
        await tab.wait(2)
        try:
            search = await tab.find("ค้นหาบน Facebook", best_match=True, timeout=2)
            if search:
                await dismiss_popups(tab)
                await screenshot(tab, "04_logged_in")
                await save_cookies(browser)
                print("  [OK] Login สำเร็จ!")
                return True
        except Exception:
            pass
        try:
            search = await tab.find("Search Facebook", best_match=True, timeout=1)
            if search:
                await dismiss_popups(tab)
                await screenshot(tab, "04_logged_in")
                await save_cookies(browser)
                print("  [OK] Login สำเร็จ!")
                return True
        except Exception:
            pass

        if i % 15 == 14:
            print(f"  ... ยังรอ ({(i+1)*2}s)")

    print("  [FAIL] Login timeout")
    return False


async def search_keyword(tab, keyword, settings):
    """ค้นหากลุ่มด้วย keyword"""
    print(f"\n[Search] '{keyword}'")

    # ไปหน้า Groups > ค้นพบ (discover)
    await safe_navigate(tab, "https://www.facebook.com/groups/discover/", wait_sec=random.uniform(3, 4))
    await dismiss_popups(tab)
    await screenshot(tab, f"05a_discover_{keyword[:8]}")

    # หาช่อง "ค้นหากลุ่ม" ใน sidebar ซ้าย
    search_box = None
    for sel in [
        'input[placeholder*="ค้นหากลุ่ม"]',
        'input[placeholder*="Search groups"]',
        'input[aria-label*="ค้นหากลุ่ม"]',
        'input[aria-label*="Search groups"]',
    ]:
        try:
            search_box = await tab.select(sel, timeout=2)
            if search_box:
                break
        except Exception:
            continue

    # fallback: หาด้วย text
    if not search_box:
        try:
            search_box = await tab.find("ค้นหากลุ่ม", best_match=True, timeout=3)
        except Exception:
            pass

    if search_box:
        await search_box.click()
        await tab.wait(0.5)
        print("  [OK] เจอช่องค้นหากลุ่ม")
    else:
        print("  [!] หาช่อง search ไม่เจอ — ใช้ search bar หลัก")
        try:
            sb = await tab.find("ค้นหาบน Facebook", best_match=True, timeout=3)
            if sb:
                await sb.click()
                await tab.wait(0.5)
        except Exception:
            pass

    # พิมพ์ keyword ทีละตัว
    for ch in keyword:
        await tab.send_keys(ch)
        await tab.wait(random.uniform(0.04, 0.12))

    await tab.wait(random.uniform(1, 2))
    await screenshot(tab, f"05_typed_{keyword[:8]}")

    # กด Enter
    await tab.send_keys("\n")
    await tab.wait(random.uniform(3, 5))
    await screenshot(tab, f"06_results_{keyword[:8]}")

    # ถ้าใช้ search bar หลัก → ต้องกดแท็บ "กลุ่ม"
    tab_ok = False
    try:
        group_tab = await tab.find("กลุ่ม", best_match=True, timeout=5)
        if group_tab:
            await group_tab.click()
            tab_ok = True
            await tab.wait(random.uniform(3, 5))
    except Exception:
        pass

    if not tab_ok:
        try:
            group_tab = await tab.find("Groups", best_match=True, timeout=3)
            if group_tab:
                await group_tab.click()
                tab_ok = True
                await tab.wait(random.uniform(3, 5))
        except Exception:
            pass

    print(f"  [Tab] {'กดแท็บกลุ่มแล้ว' if tab_ok else 'หาแท็บไม่เจอ'}")
    await screenshot(tab, f"07_tab_{keyword[:8]}")

    # Scroll
    max_scroll = settings.get("max_scroll", 10)
    print(f"  [Scroll] {max_scroll} ครั้ง...")
    for i in range(max_scroll):
        try:
            await tab.evaluate("window.scrollBy(0, 600)")
            await tab.wait(random.uniform(
                settings.get("delay_min_sec", 2),
                settings.get("delay_max_sec", 5),
            ))
        except Exception:
            break
        if (i + 1) % 3 == 0:
            await screenshot(tab, f"08_scroll_{keyword[:8]}_{i+1}")
            print(f"  [Scroll] {i+1}/{max_scroll}")

    await screenshot(tab, f"09_done_{keyword[:8]}")

    # Parse
    groups = await parse_page(tab, keyword)
    print(f"  [OK] พบ {len(groups)} กลุ่ม")
    return groups


async def parse_page(tab, keyword):
    """ดึงข้อมูลกลุ่มจาก DOM"""
    try:
        raw = await tab.evaluate(r"""
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
                        else {
                            const m2 = pt.match(/สมาชิก\s*([\d,.]+\s*[KkMm]?)/);
                            if (m2) members = m2[1].trim();
                        }
                        if (/สาธารณะ|Public/.test(pt)) privacy = 'public';
                        else if (/ส่วนตัว|Private/.test(pt)) privacy = 'private';
                    }
                    results.push({
                        name: text.split('\n')[0],
                        url: href.split('?')[0],
                        members, privacy
                    });
                }
                return results;
            })()
        """)
    except Exception as e:
        print(f"  [Parse Error] {e}")
        return []

    seen = set()
    groups = []
    for item in raw:
        url = item["url"].rstrip("/")
        if url in seen:
            continue
        seen.add(url)
        groups.append({
            "name": item["name"],
            "url": url,
            "members": item["members"],
            "privacy": item["privacy"],
            "keyword": keyword,
            "scraped_at": datetime.now().isoformat(),
        })
    return groups


async def scan_once(tab, browser, keywords, settings):
    """scan ครั้งเดียว — return จำนวนกลุ่มที่พบ"""
    all_groups = []
    for i, kw in enumerate(keywords):
        if not RUNNING:
            break
        print(f"\n{'─'*50}")
        print(f"  [{i+1}/{len(keywords)}] {kw}")
        print(f"{'─'*50}")

        try:
            groups = await search_keyword(tab, kw, settings)
            all_groups.extend(groups)
        except Exception as e:
            print(f"  [Error] {e}")
            await screenshot(tab, f"error_{kw[:8]}")

        if i < len(keywords) - 1:
            w = random.randint(8, 20)
            print(f"  [Wait] พัก {w}s...")
            await tab.wait(w)

    # ลบซ้ำ
    seen = set()
    unique = []
    for g in all_groups:
        if g["url"] not in seen:
            seen.add(g["url"])
            unique.append(g)

    # Save JSON
    if unique:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(OUTPUT_DIR, f"groups_{ts}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(unique, f, ensure_ascii=False, indent=2)
        print(f"\n[Save] {path} ({len(unique)} กลุ่ม)")
    else:
        print("\n[!] ไม่พบกลุ่ม — ดู screenshots")

    # แสดงผล
    print(f"\n{'='*60}")
    print(f"  ผลลัพธ์: {len(unique)} กลุ่ม")
    print(f"{'='*60}")
    for g in unique[:15]:
        print(f"  - {g['name']}")
        print(f"    {g['url']}  ({g['members']})")
    print()

    await save_cookies(browser)
    return len(unique)


async def main():
    global RUNNING
    config = load_config()
    keywords = config["keywords"]
    settings = config["settings"]
    ensure_dirs()

    # continuous mode settings
    continuous = settings.get("continuous", False)
    interval_min = settings.get("interval_minutes", DEFAULT_INTERVAL_MIN)
    is_docker = os.environ.get("DOCKER_MODE", "").lower() in ("1", "true", "yes")
    use_headless = settings.get("headless", False) or is_docker

    print("=" * 60)
    print("  Facebook Group Scanner v7 (nodriver)")
    print(f"  Mode: {'Docker' if is_docker else 'Host'} | "
          f"Headless: {use_headless} | "
          f"Continuous: {continuous}")
    if continuous:
        print(f"  Interval: ทุก {interval_min} นาที")
    print(f"  Keywords: {', '.join(keywords)}")
    print("=" * 60)

    # เปิด Chrome
    print("\n[Start] เปิด Chrome (undetected)...")
    chrome_args = [
        "--disable-notifications",
        "--disable-popup-blocking",
        "--disable-save-password-bubble",
        "--no-first-run",
    ]
    if is_docker:
        chrome_args.extend([
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ])

    browser = await uc.start(
        headless=use_headless,
        lang="th-TH",
        browser_args=chrome_args,
    )

    tab = await browser.get("about:blank")

    # Login
    email = config["facebook"]["email"]
    password = config["facebook"]["password"]
    ok = await auto_login(tab, browser, email, password)
    if not ok:
        print("[!] Login ไม่สำเร็จ — ปิดโปรแกรม")
        browser.stop()
        return

    # === Scan loop ===
    round_num = 0
    while RUNNING:
        round_num += 1
        start_time = datetime.now()
        print(f"\n{'='*60}")
        print(f"  รอบที่ {round_num} — {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")

        try:
            # reload config ทุกรอบ (เพื่อเปลี่ยน keywords ได้ระหว่าง run)
            config = load_config()
            keywords = config["keywords"]
            settings = config["settings"]

            count = await scan_once(tab, browser, keywords, settings)
            elapsed = (datetime.now() - start_time).total_seconds()
            print(f"\n[Done] รอบ {round_num} เสร็จ ({elapsed:.0f}s) — พบ {count} กลุ่ม")
        except Exception as e:
            print(f"\n[Error] รอบ {round_num} ล้มเหลว: {e}")
            traceback.print_exc()
            # ลอง recover — กลับหน้า FB
            try:
                await safe_navigate(tab, "https://www.facebook.com/", wait_sec=3)
            except Exception:
                print("[!] Chrome อาจ crash — เปิดใหม่...")
                try:
                    browser.stop()
                except Exception:
                    pass
                browser = await uc.start(
                    headless=use_headless,
                    lang="th-TH",
                    browser_args=chrome_args,
                )
                tab = await browser.get("about:blank")
                await auto_login(tab, browser, email, password)

        if not continuous:
            break

        # รอก่อน scan รอบถัดไป
        # reload interval ล่าสุดจาก config
        interval_min = settings.get("interval_minutes", DEFAULT_INTERVAL_MIN)
        jitter = random.randint(-5, 5)  # ±5 นาที สุ่มให้ไม่ซ้ำ pattern
        wait_sec = max(60, (interval_min + jitter) * 60)
        next_time = datetime.now().strftime('%H:%M')
        print(f"\n[Sleep] รอ {wait_sec // 60} นาที — scan ถัดไปประมาณ {next_time}")

        # sleep แบบ interruptible
        for _ in range(int(wait_sec)):
            if not RUNNING:
                break
            await asyncio.sleep(1)

    print("\n[Stop] กำลังปิด...")
    try:
        await save_cookies(browser)
        browser.stop()
    except Exception:
        pass
    print("จบการทำงาน!")


if __name__ == "__main__":
    uc.loop().run_until_complete(main())
