"""In-app notifications (the bell icon)."""
from extensions import mongo
from utils.helpers import utcnow


def notify(user_id, message, type_="system", link=None):
    mongo.db.notifications.insert_one(
        {
            "user_id": user_id,
            "message": message[:300],
            "type": type_,
            "link": link,
            "is_read": False,
            "created_at": utcnow(),
        }
    )


def notify_admins(message, type_="admin", link=None):
    for admin in mongo.db.users.find({"role": "admin", "is_banned": {"$ne": True}}, {"_id": 1}):
        notify(admin["_id"], message, type_, link)
