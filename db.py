"""
MongoDB Atlas storage — บันทึกผลการทำงานทั้งหมด
Collections:
  - agent_logs    : ทุก action ที่ AI ทำ (real-time log)
  - groups        : กลุ่มที่เจอ
  - posts         : โพสต์ที่วิเคราะห์แล้ว
  - replies       : comment ที่ตอบไป
  - rounds        : สรุปแต่ละรอบ
"""
import json
import os
from datetime import datetime

try:
    from pymongo import MongoClient
    from pymongo.errors import ConnectionFailure
    HAS_MONGO = True
except ImportError:
    HAS_MONGO = False


class DB:
    def __init__(self, config: dict):
        mongo_cfg = config.get("mongodb", {})
        uri = mongo_cfg.get("uri", os.environ.get("MONGODB_URI", ""))
        db_name = mongo_cfg.get("db", os.environ.get("MONGODB_DB", "fb_scanner"))

        self.enabled = bool(uri and HAS_MONGO)
        if not self.enabled:
            print("[DB] MongoDB disabled — ใช้ JSONL fallback")
            return

        try:
            self.client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            self.client.admin.command("ping")
            self.db = self.client[db_name]
            print(f"[DB] MongoDB connected: {db_name}")
        except Exception as e:
            print(f"[DB] MongoDB connection failed: {e} — ใช้ JSONL fallback")
            self.enabled = False

    def log(self, event_type: str, data: dict):
        if not self.enabled:
            return
        try:
            self.db.agent_logs.insert_one({
                "ts": datetime.utcnow(),
                "type": event_type,
                **data,
            })
        except Exception:
            pass

    def save_groups(self, groups: list[dict]):
        if not self.enabled or not groups:
            return
        try:
            for g in groups:
                self.db.groups.update_one(
                    {"url": g["url"]},
                    {"$set": {**g, "updated_at": datetime.utcnow()},
                     "$setOnInsert": {"created_at": datetime.utcnow()}},
                    upsert=True,
                )
        except Exception:
            pass

    def save_post(self, post: dict):
        if not self.enabled:
            return
        try:
            self.db.posts.update_one(
                {"post_url": post.get("post_url", "")},
                {"$set": {**post, "updated_at": datetime.utcnow()},
                 "$setOnInsert": {"created_at": datetime.utcnow()}},
                upsert=True,
            )
        except Exception:
            pass

    def save_reply(self, reply: dict):
        if not self.enabled:
            return
        try:
            self.db.replies.insert_one({
                **reply,
                "created_at": datetime.utcnow(),
            })
        except Exception:
            pass

    def save_round(self, round_data: dict):
        if not self.enabled:
            return
        try:
            self.db.rounds.insert_one({
                **round_data,
                "created_at": datetime.utcnow(),
            })
        except Exception:
            pass
