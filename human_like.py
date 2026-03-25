"""
Human-like behavior module - จำลองพฤติกรรมมนุษย์เพื่อป้องกัน ban
"""
import asyncio
import random


async def random_delay(min_sec: float = 1.0, max_sec: float = 3.0):
    """หน่วงเวลาแบบสุ่ม เหมือนคนคิดก่อนทำ"""
    delay = random.uniform(min_sec, max_sec)
    await asyncio.sleep(delay)


async def human_type(page, selector: str, text: str):
    """พิมพ์ทีละตัว ความเร็วไม่สม่ำเสมอ เหมือนคนพิมพ์จริง"""
    await page.click(selector)
    await random_delay(0.3, 0.8)
    for char in text:
        await page.keyboard.type(char)
        await asyncio.sleep(random.uniform(0.05, 0.2))  # typing speed varies


async def human_scroll(page, times: int = 3):
    """Scroll ลงทีละนิด เหมือนคนอ่าน"""
    for i in range(times):
        scroll_amount = random.randint(300, 700)
        await page.mouse.wheel(0, scroll_amount)
        await random_delay(1.5, 3.5)
        # บางทีเลื่อนขึ้นนิดหน่อย เหมือนคนย้อนกลับอ่าน
        if random.random() < 0.2:
            await page.mouse.wheel(0, -random.randint(50, 150))
            await random_delay(0.5, 1.0)


async def human_mouse_move(page, x: int, y: int):
    """เลื่อน mouse ไปตำแหน่งที่ต้องการ แบบโค้ง ไม่ใช่เส้นตรง"""
    steps = random.randint(5, 15)
    await page.mouse.move(x, y, steps=steps)
    await random_delay(0.1, 0.3)


async def random_mouse_wander(page, viewport_width: int = 1280, viewport_height: int = 720):
    """เลื่อน mouse ไปมาบนหน้าจอแบบสุ่ม เหมือนคนดูหน้าจอ"""
    for _ in range(random.randint(2, 5)):
        x = random.randint(100, viewport_width - 100)
        y = random.randint(100, viewport_height - 100)
        await human_mouse_move(page, x, y)
        await random_delay(0.3, 1.0)


async def human_click(page, selector: str):
    """คลิกแบบมนุษย์ — เลื่อน mouse ไปที่ element ก่อนค่อยคลิก"""
    element = await page.query_selector(selector)
    if element:
        box = await element.bounding_box()
        if box:
            # คลิกไม่ตรงกลาง 100% — มี offset นิดหน่อย
            offset_x = random.uniform(-3, 3)
            offset_y = random.uniform(-3, 3)
            target_x = box["x"] + box["width"] / 2 + offset_x
            target_y = box["y"] + box["height"] / 2 + offset_y
            await human_mouse_move(page, int(target_x), int(target_y))
            await random_delay(0.1, 0.3)
            await page.mouse.click(target_x, target_y)
        else:
            await page.click(selector)
    else:
        await page.click(selector)
