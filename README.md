# Facebook Group AI Agent

ระบบ AI Agent อัตโนมัติสำหรับ Facebook Groups — ค้นหากลุ่ม, เข้าร่วม, อ่านโพสต์, วิเคราะห์, และตอบ comment อัตโนมัติ พร้อม Monitor Dashboard แบบ real-time

## สถาปัตยกรรม

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Container                      │
│  ┌───────────────┐    ┌──────────────┐    ┌───────────┐ │
│  │  Playwright    │    │  AI Engine   │    │  MongoDB  │ │
│  │  (Chromium)    │◄──►│  (mimo API)  │    │  Atlas    │ │
│  │  Headless      │    │  Vision +    │    │  Storage  │ │
│  │  Browser       │    │  Text Gen    │    │           │ │
│  └───────┬───────┘    └──────────────┘    └─────┬─────┘ │
│          │                                       │       │
│  ┌───────▼───────────────────────────────────────▼─────┐ │
│  │              ai_scanner.py (Agent Loop)              │ │
│  │  Login → Search → Join → Read → Analyze → Reply     │ │
│  └─────────────────────┬───────────────────────────────┘ │
│                        │ JSONL + JSON                    │
└────────────────────────┼─────────────────────────────────┘
                         │
              ┌──────────▼──────────┐
              │   Next.js Dashboard  │
              │   (Real-time Monitor)│
              │   localhost:3456     │
              └─────────────────────┘
```

## ฟีเจอร์

### AI Agent
- **ค้นหากลุ่ม** — ค้นหา Facebook Groups ตาม keyword อัตโนมัติ
- **เข้าร่วมกลุ่ม** — กด Join + ตอบคำถามแอดมินอัตโนมัติ
- **อ่านโพสต์** — เข้ากลุ่ม scroll อ่านโพสต์ล่าสุด
- **AI วิเคราะห์** — ใช้ AI Vision ดู screenshot ตัดสินใจว่าควรตอบหรือไม่
- **ตอบ comment** — พิมพ์ comment แบบ human-like + กดปุ่มส่ง
- **สร้างโพสต์ใหม่** — สร้างโพสต์ในกลุ่มพร้อมรูปภาพ (รองรับ)

### Anti-Detection
- พิมพ์ทีละตัวอักษร ความเร็วไม่สม่ำเสมอ (25-130ms)
- Random delay ระหว่าง action (0.5-2 วินาที)
- Mouse wander เหมือนคนดูหน้าจอ
- Cooldown 45-120 วินาทีหลังตอบ comment
- ข้อความสร้างโดย AI ไม่ซ้ำกัน เขียนเหมือนคนจริง
- Rate limit: 1 comment/กลุ่ม, 2 กลุ่ม/รอบ, scan ทุก 90 นาที

### Monitor Dashboard (Next.js)
- Real-time refresh ทุก 5 วินาที
- แสดง KPI: กลุ่มที่พบ, ข้อความที่ตอบ, AI Calls, ค่าใช้จ่าย (บาท)
- Live Activity log ทุก action ของ AI Agent
- รายชื่อกลุ่มที่พบ (กดลิงก์ไป FB ได้)
- ข้อความที่ตอบไป + สรุปโพสต์
- Dark mode, shadcn/ui

### Storage
- **MongoDB Atlas** — บันทึก groups, replies, agent_logs, rounds
- **JSONL fallback** — ถ้า MongoDB ไม่พร้อม อ่านจาก local files

## โครงสร้างไฟล์

```
scan/
├── ai_scanner.py          # AI Agent หลัก (Playwright + AI Vision)
├── db.py                  # MongoDB Atlas connection
├── config.json            # ตั้งค่า (ไม่ถูก commit — มี secrets)
├── config.example.json    # ตัวอย่าง config
├── requirements.txt       # Python dependencies
├── Dockerfile             # Docker image (Playwright + Chrome)
├── entrypoint.sh          # Docker entrypoint
├── .dockerignore
├── .gitignore
│
├── openclaw/
│   ├── docker-compose.yml # Docker Compose สำหรับ agent
│   └── .env.example       # ตัวอย่าง environment variables
│
├── dashboard/             # Next.js Monitor Dashboard
│   ├── app/
│   │   ├── page.tsx       # หน้า Dashboard หลัก
│   │   └── api/           # API routes
│   │       ├── stats/     # สถิติรวม
│   │       ├── logs/      # Activity logs
│   │       ├── groups/    # กลุ่มที่พบ
│   │       └── replies/   # ข้อความที่ตอบ
│   ├── lib/
│   │   └── db.ts          # MongoDB + JSONL fallback
│   └── components/ui/     # shadcn/ui components
│
├── output/                # ผลลัพธ์ (ไม่ถูก commit)
│   ├── agent_log.jsonl    # Activity log
│   ├── cookies.json       # Facebook session
│   ├── groups_*.json      # กลุ่มที่พบ
│   ├── replies_*.json     # ข้อความที่ตอบ
│   └── screenshots/       # Screenshot ทุก step
│
├── fb_group_scanner.py    # Scanner เดิม (nodriver, ไม่ใช้แล้ว)
├── human_like.py          # Human behavior module เดิม
└── save_results.py        # Script save ผลลัพธ์เดิม
```

## วิธีติดตั้ง

### 1. Clone + ตั้งค่า

```bash
git clone https://github.com/smlsoft/facebookgroupInsight.git
cd facebookgroupInsight

# สร้าง config จาก example
cp config.example.json config.json
# แก้ไข config.json ใส่ข้อมูลจริง:
#   - ai.api_key       → API key ของ AI provider
#   - ai.base_url      → URL ของ AI API
#   - mongodb.uri      → MongoDB Atlas connection string
#   - facebook.email    → Facebook email
#   - facebook.password → Facebook password
#   - keywords          → คำค้นหากลุ่ม
```

### 2. Run AI Agent (Docker)

```bash
cd openclaw

# Build + Start
docker compose up -d --build

# ดู log
docker compose logs -f fb-scanner

# หยุด
docker compose stop fb-scanner
```

### 3. Run Monitor Dashboard

```bash
cd dashboard

# ติดตั้ง dependencies
npm install

# สร้าง .env.local
echo "MONGODB_URI=mongodb+srv://..." > .env.local
echo "MONGODB_DB=fb_scanner" >> .env.local

# Start
npm run dev -- -p 3456

# เปิด http://localhost:3456
```

## Config Reference

```jsonc
{
  "ai": {
    "base_url": "https://api.example.com/v1",  // OpenAI-compatible API
    "api_key": "sk-xxx",                        // API key
    "model": "mimo-v2-omni"                     // Model ที่รองรับ vision
  },
  "mongodb": {
    "uri": "mongodb+srv://...",                 // MongoDB Atlas URI
    "db": "fb_scanner"                          // Database name
  },
  "facebook": {
    "email": "your@email.com",
    "password": "your_password"
  },
  "keywords": [
    "จำนองบ้าน",
    "ขายฝากที่ดิน"
  ],
  "settings": {
    "max_scroll": 8,              // จำนวนครั้งที่ scroll ดูกลุ่ม
    "continuous": true,           // run ต่อเนื่อง 24/7
    "interval_minutes": 90,       // scan ใหม่ทุก 90 นาที
    "max_replies_per_group": 1,   // comment สูงสุด/กลุ่ม/รอบ
    "max_groups_per_round": 2     // จำนวนกลุ่มที่เข้า/รอบ
  }
}
```

## Flow การทำงาน

```
Agent เริ่มทำงาน
    │
    ▼
[Login Facebook] ← ใช้ cookies ถ้ามี
    │
    ▼
[ค้นหากลุ่ม] ← ไป URL /search/groups/?q=keyword
    │ scroll 8 ครั้ง
    ▼
[Extract กลุ่ม] ← ดึงชื่อ URL สมาชิก จาก DOM
    │
    ▼
┌─── วน loop กลุ่ม (max 2/รอบ) ───┐
│                                   │
│  [เข้ากลุ่ม]                      │
│      │                            │
│      ▼                            │
│  [ตรวจ Join] ── ยังไม่สมาชิก ──►  │
│      │          กด Join +         │
│      │          ตอบคำถามแอดมิน    │
│      │              │             │
│      │          pending? ── ข้าม  │
│      ▼                            │
│  [Scroll อ่านโพสต์]               │
│      │                            │
│      ▼                            │
│  ┌─ วน loop โพสต์ ──┐            │
│  │                    │            │
│  │  [AI วิเคราะห์]   │            │
│  │  ดู screenshot     │            │
│  │  + ข้อความโพสต์    │            │
│  │      │             │            │
│  │  should_reply?     │            │
│  │  ├─ No → ข้าม     │            │
│  │  └─ Yes ↓          │            │
│  │  [พิมพ์ comment]   │            │
│  │  human-like typing │            │
│  │      │             │            │
│  │  [กดส่ง]           │            │
│  │  ปุ่มลูกศร →       │            │
│  │      │             │            │
│  │  [Cooldown]        │            │
│  │  พัก 45-120s       │            │
│  └────────────────────┘            │
│                                    │
└────────────────────────────────────┘
    │
    ▼
[Save ผลลัพธ์] → MongoDB + JSONL + JSON
    │
    ▼
[Sleep 90 นาที] → วน loop ใหม่
```

## Screenshots

### Monitor Dashboard
- Dark mode, real-time, แสดง KPI + Live Activity + กลุ่ม + ข้อความที่ตอบ

### AI Agent ทำงาน
- Login → Search → Join → Read → Comment อัตโนมัติ
- Screenshot ทุก step เก็บใน `output/screenshots/`

## AI Provider

ระบบใช้ **OpenAI-compatible API** — รองรับ provider อะไรก็ได้ที่มี Vision:
- mimo-v2-omni (xiaomimimo)
- GPT-4o (OpenAI)
- Claude (Anthropic)
- Gemini (Google)
- หรือ OpenRouter, Together AI, etc.

แก้ `ai.base_url` + `ai.api_key` + `ai.model` ใน config.json

## ข้อควรระวัง

- **อย่า run ถี่เกินไป** — Facebook จะ shadow ban
- แนะนำ: 1-2 comment/วัน/กลุ่ม, scan ทุก 2-4 ชั่วโมง
- **อย่าใช้ข้อความซ้ำ** — AI สร้างข้อความใหม่ทุกครั้ง
- **ตรวจสอบ output** — ดู Dashboard + screenshot เป็นระยะ
- **config.json มี credentials** — อย่า commit ขึ้น git

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Browser Automation | Playwright (Chromium headless) |
| AI Vision + Text | OpenAI-compatible API (mimo-v2-omni) |
| Container | Docker (mcr.microsoft.com/playwright) |
| Database | MongoDB Atlas |
| Dashboard | Next.js 16 + shadcn/ui + Tailwind CSS |
| Language | Python 3.12 + TypeScript |

## License

MIT
