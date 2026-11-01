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
import math
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
except (ImportError, ModuleNotFoundError):
    # Pure Python robust fallback for TF-IDF and Cosine Similarity
    class PureCosineResult:
        def __init__(self, scores):
            self.scores = scores
        def ravel(self):
            return self.scores

    def cosine_similarity(target_mat, cand_mat):
        # target_mat is [vec0], cand_mat is [vec1, vec2, ...]
        t_vec = target_mat[0]
        t_norm = math.sqrt(sum(v * v for v in t_vec.values())) or 1.0
        scores = []
        for c_vec in cand_mat:
            dot = sum(t_vec.get(term, 0.0) * val for term, val in c_vec.items())
            c_norm = math.sqrt(sum(v * v for v in c_vec.values())) or 1.0
            scores.append(dot / (t_norm * c_norm))
        return PureCosineResult(scores)

    class TfidfVectorizer:
        def __init__(self, stop_words="english", ngram_range=(1, 2), sublinear_tf=True):
            self.stop_words = {"a", "an", "the", "in", "on", "at", "to", "for", "of", "and", "or", "is", "was"}

        def fit_transform(self, corpus):
            import re
            docs_tokens = []
            doc_freq = {}
            for doc in corpus:
                tokens = [t for t in re.findall(r"[a-z0-9]+", doc.lower()) if t not in self.stop_words]
                # 1-gram and 2-gram
                ngrams = list(tokens)
                for i in range(len(tokens) - 1):
                    ngrams.append(f"{tokens[i]} {tokens[i+1]}")
                docs_tokens.append(ngrams)
                for term in set(ngrams):
                    doc_freq[term] = doc_freq.get(term, 0) + 1

            n_docs = len(corpus)
            matrix = []
            for ngrams in docs_tokens:
                tf = {}
                for t in ngrams:
                    tf[t] = tf.get(t, 0) + 1
                vec = {}
                for t, count in tf.items():
                    sub_tf = 1.0 + math.log(count)
                    idf = math.log((1.0 + n_docs) / (1.0 + doc_freq.get(t, 1))) + 1.0
                    vec[t] = sub_tf * idf
                matrix.append(vec)
            return matrix

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
    a_words = a.split()
    b_words = b.split()
    expected_words = set(b_words)
    common_words = set(a_words) & expected_words
    if not expected_words or not a_words:
        return 0
    # Precision prevents word-stuffing (e.g. dictionary pasting)
    precision = len(common_words) / len(set(a_words))
    recall = len(common_words) / len(expected_words)
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
    return round(max(ratio, f1) * 100)
