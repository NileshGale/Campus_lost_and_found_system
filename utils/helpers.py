"""Small shared helpers: time and pagination."""
import math
from datetime import datetime, timezone


def utcnow():
    return datetime.now(timezone.utc)


def as_utc(value):
    """Treat naive datetimes as UTC so comparisons never crash."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def paginate(collection, query, page, per_page, sort=("created_at", -1)):
    total = collection.count_documents(query)
    pages = max(1, math.ceil(total / per_page))
    page = min(max(1, page), pages)
    docs = list(collection.find(query).sort(*sort).skip((page - 1) * per_page).limit(per_page))
    return {
        "docs": docs,
        "page": page,
        "pages": pages,
        "total": total,
        "has_prev": page > 1,
        "has_next": page < pages,
    }


def page_arg(request):
    try:
        return max(1, int(request.args.get("page", 1)))
    except ValueError:
        return 1
