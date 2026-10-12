"""Matching engine: compares a post with open posts of the opposite type.

How the score works (0-100%):
  75%  text similarity of title + category + description + location
       (TF-IDF vectors compared with cosine similarity, from scikit-learn)
  20%  same category
   5%  a shared word in the location ("Library" vs "Library 2nd floor")
Only posts whose dates make sense are compared: a found item must be found on or
after the day the lost item went missing (with one day of slack).
"""
import re
from datetime import timedelta
from difflib import SequenceMatcher

from flask import current_app, url_for
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from extensions import mongo
from utils import mailer
from utils.notifications import notify

CANDIDATE_LIMIT = 500
DATE_SLACK = timedelta(days=1)
LOOKBACK = timedelta(days=90)


def _item_text(item):
    # The title is repeated so it counts more than a long description.
    return " ".join([item["title"], item["title"], item["category"], item["description"], item["location"]])


def _tokens(text):
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def find_matches(item, limit=5):
    """Return [(other_item, score_percent), ...], best first."""
    opposite = "found" if item["type"] == "lost" else "lost"
    query = {"type": opposite, "status": "open", "posted_by": {"$ne": item["posted_by"]}}
    if item["type"] == "lost":
        query["date"] = {"$gte": item["date"] - DATE_SLACK, "$lte": item["date"] + LOOKBACK}
    else:
        query["date"] = {"$gte": item["date"] - LOOKBACK, "$lte": item["date"] + DATE_SLACK}

    candidates = list(mongo.db.items.find(query).sort("created_at", -1).limit(CANDIDATE_LIMIT))
    if not candidates:
        return []

    corpus = [_item_text(item)] + [_item_text(c) for c in candidates]
    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
    try:
        matrix = vectorizer.fit_transform(corpus)
    except ValueError:  # the text was only stop words
        return []
    text_scores = cosine_similarity(matrix[0:1], matrix[1:]).ravel()

    threshold = current_app.config["MATCH_THRESHOLD"]
    my_location = _tokens(item["location"])
    results = []
    for candidate, text_score in zip(candidates, text_scores):
        score = 0.75 * float(text_score)
        if candidate["category"] == item["category"]:
            score += 0.20
        if my_location & _tokens(candidate["location"]):
            score += 0.05
        if score >= threshold:
            results.append((candidate, round(min(score, 1.0) * 100)))
    results.sort(key=lambda pair: pair[1], reverse=True)
    return results[:limit]


def notify_matches(item, notify_limit=3):
    """Run after a new post: alert both sides of each likely match (in-app + email)."""
    matches = find_matches(item, limit=notify_limit)
    if not matches:
        return 0
    users = mongo.db.users
    item_id = str(item["_id"])

    for other, score in matches:
        other_user = users.find_one({"_id": other["posted_by"], "is_banned": {"$ne": True}}, {"name": 1, "email": 1})
        if not other_user:
            continue
        notify(
            other_user["_id"],
            f"A new {item['type']} post “{item['title']}” may match your "
            f"{other['type']} item “{other['title']}” ({score}% match).",
            "match",
            url_for("items.detail", item_id=item_id),
        )
        mailer.send_match_alert(
            other_user["email"], other_user["name"], other, item, score,
            url_for("items.detail", item_id=item_id, _external=True),
        )

    poster = users.find_one({"_id": item["posted_by"]}, {"name": 1, "email": 1})
    if poster:
        best, best_score = matches[0]
        notify(
            poster["_id"],
            f"We found {len(matches)} possible match{'es' if len(matches) > 1 else ''} for "
            f"“{item['title']}”. Open your post to see them.",
            "match",
            url_for("items.detail", item_id=item_id),
        )
        mailer.send_match_alert(
            poster["email"], poster["name"], item, best, best_score,
            url_for("items.detail", item_id=str(best["_id"]), _external=True),
        )
    return len(matches)


def _normalise(text):
    return " ".join(re.findall(r"[a-z0-9]+", (text or "").lower()))


def answer_similarity(answer, expected):
    """A rough 0-100 hint for reviewers comparing a claimant's answer to the finder's.

    It's only a hint: a reviewer still reads both answers before deciding.
    """
    a, b = _normalise(answer), _normalise(expected)
    if not a or not b:
        return 0
    ratio = SequenceMatcher(None, a, b).ratio()
    expected_words = set(b.split())
    covered = len(set(a.split()) & expected_words) / len(expected_words)
    return round(max(ratio, covered) * 100)
