# Campus Lost & Found

A web app where students and staff report lost and found items, get matched automatically, prove ownership, and collect items from the college security desk.

Built with **Flask + MongoDB**. Authentication, OTP email verification, a TF-IDF matching engine and a layered ownership-verification system make it more than a basic CRUD app.

> **Setting it up on a new computer?** Follow **[SETUP_GUIDE.md](SETUP_GUIDE.md)**. It starts from zero (installing Python) and ends with the app running.

---

## Contents

1. [Features](#1-features)
2. [Tech stack](#2-tech-stack)
3. [How the system works](#3-how-the-system-works)
4. [Trusting the claimant: the verification layers](#4-trusting-the-claimant-the-verification-layers)
5. [Security features](#5-security-features)
6. [Matching engine](#6-matching-engine)
7. [Database collections](#7-database-collections)
8. [Folder structure](#8-folder-structure)
9. [Pages](#9-pages)
10. [Design decisions worth explaining in the viva](#10-design-decisions-worth-explaining-in-the-viva)
11. [Commands](#11-commands)

---

## 1. Features

| Module | What it does |
|---|---|
| **Authentication** | Register with a college email only, verify with a 6-digit email OTP, log in, reset a forgotten password. |
| **Report lost item** | Title, category, description, last-seen location, date, optional photo. |
| **Report found item** | Same fields, plus private details and verification questions only the finder and admin can see. The public photo is blurred. |
| **Search & filter** | Keywords, type, category, location, date range, open/all. |
| **Matching engine** | Every new post is compared with posts of the opposite type. Both people get an in-app notification and an email. |
| **Claims** | The owner answers the finder's questions, describes the item and uploads proof (bill, old photo, box, IMEI). |
| **Review** | The finder reviews a claim. If two or more people claim the same item, it's *disputed* and only an admin decides. |
| **Security desk handover** | Approved owners get a one-time handover code by email. The desk checks their college ID, enters the code, and the item is marked *returned*. |
| **Trust score** | Each rejected claim costs 20 points; after 3 rejections the account can't claim any more. A successful pickup adds 5. |
| **Admin panel** | Overview, claims queue (pending / disputed / approved...), security desk queue, remove or restore posts, ban or unban users. |
| **Notifications** | Bell icon with unread count, plus emails for OTPs, matches, claim decisions and handover codes. |

## 2. Tech stack

| Layer | Used |
|---|---|
| Backend | Python 3.12+, Flask 3, PyMongo |
| Database | MongoDB (local Community Server or the free MongoDB Atlas tier) |
| Frontend | Jinja templates, hand-written CSS (light theme, Inter font), plain JavaScript with `fetch` |
| Auth | Flask-Login (session in an HttpOnly cookie), bcrypt, Flask-WTF (CSRF), Flask-Limiter |
| Email | Flask-Mail through Gmail SMTP (`smtp.gmail.com:587`, TLS) |
| Images | Pillow: checks that the file is a real image, strips metadata, makes blurred public copies |
| Matching | scikit-learn: TF-IDF vectors + cosine similarity |

## 3. How the system works

```
  Browser ──HTTPS/HTTP──►  Flask app (app.py)
                             │  routes/      auth, items, claims, admin, main
                             │  utils/       otp, mailer, matcher, uploads, claims ...
                             │
                             ├──► MongoDB    users, otps, items, claims, notifications
                             ├──► Gmail SMTP OTP and alert emails
                             └──► Disk       static/uploads/ (public, blurred)
                                             private_uploads/ (originals + proofs)
```

**Claim flow (the main story):**

```
Owner sees a match ─► raises a claim ─► answers questions + uploads proof
   ─► finder (or admin, if disputed) reviews ─► approved?
   ─► owner gets a handover code by email ─► goes to the security desk with ID + code
   ─► admin checks the ID, enters the code ─► item marked "returned", full log saved
```

**Item status:** `open` → `claimed` (a claim was approved) → `returned`. Admins can also set `removed`.
**Claim status:** `pending` → `approved` → `completed`, or `rejected`. When another claim wins, the rest become `closed`, with no penalty.

## 4. Trusting the claimant: the verification layers

No single check is enough, so the app stacks several:

1. **Hidden identifying details.** The public post says only "Black leather wallet, Library". The finder privately records details like the brand, contents or a scratch, and writes questions about them. The public photo is blurred (Pillow Gaussian blur on a small copy), and the original is served only to the finder, admins and the approved owner.
2. **Verification questions.** The claimant answers the finder's questions without ever seeing the expected answers. Reviewers see both side by side, with a rough similarity hint.
3. **Proof upload.** Up to 3 images (bill, box, old photo, IMEI). These are stored privately and only the claimant, the finder and admins can open them.
4. **Accountability through login.** Only verified college emails can claim, so every claim is tied to a real person.
5. **Handover at the security desk.** Items never change hands between students directly. The desk checks the college ID, and the admin must tick "I checked the ID" before confirming.
6. **OTP confirmation.** On approval, a 6-digit handover code (stored hashed, valid 7 days, 5 attempts) is emailed to the owner. Only the real email owner can give it to the desk. Completing the handover records who did it and when.
7. **Fake-claim penalties.** Each rejected claim lowers the trust score by 20. After 3 rejections the account is blocked from claiming; admins can lift the block or ban the account.
8. **Multiple claimants.** Two or more pending claims make an item *disputed*. The finder can no longer decide; an admin compares all claims (there's a "Compare" link between them).

## 5. Security features

| Requirement | Where it's implemented |
|---|---|
| College email only, checked on the backend | `utils/validators.py` → `is_college_email()`; used by `RegisterForm` in `forms.py` |
| Password rules (8+ chars, uppercase, number, special) | `utils/validators.py` → `password_problems()`; the live checklist in JS is only a convenience |
| bcrypt password hashing | `routes/auth.py` → `hash_password()` / `check_password()` |
| Account starts `is_verified: false`, login only after OTP | `routes/auth.py` → `register()`, `login()`, `verify_otp()` |
| OTP from `secrets`, stored hashed | `utils/otp.py` → `generate_otp()` uses `secrets.randbelow`; only an HMAC-SHA256 hash is saved |
| 10-minute expiry with a TTL index | `extensions.py` → `otps.expires_at` TTL index; expiry is also checked in code |
| 5 wrong attempts, then a new OTP is needed | `utils/otp.py` → `check_code()`: atomic attempt counter |
| Resend with 60 s cooldown | `utils/otp.py` → `issue_otp()` (server side) + countdown in `static/js/main.js` |
| `purpose` field (register / reset) | The OTP lookup *and* the hash include the purpose, so a registration code can't reset a password |
| 5 failed logins → 15-minute lock | `routes/auth.py` → `login()`: `failed_login_attempts`, `lock_until` |
| Rate limiting on login and OTP routes | Flask-Limiter decorators in `routes/auth.py` (for example `10 per minute` on login) |
| Session in an HttpOnly cookie | Flask-Login + `SESSION_COOKIE_HTTPONLY`, `SameSite=Lax`, `Secure` when on HTTPS (`config.py`) |
| Forgot password doesn't reveal which emails exist | Same message and page either way. Registering an existing email also looks identical; the real owner gets an "you already have an account" email instead |
| Reset logs out all old sessions | Each user has a `session_token` inside the login cookie. A reset replaces it, so every old cookie stops working |
| CSRF protection | `CSRFProtect` on every form; the `fetch` calls send the `X-CSRFToken` header |
| Admin routes protected on the backend | `utils/decorators.py` → `@admin_required` (returns 403) |
| Input validation & sanitisation | WTForms validators and filters (`clean_text`, `clean_line`); Jinja auto-escapes all output; search input is regex-escaped; IDs are parsed as ObjectIds |
| Uploads: images only (jpg/png/webp), max 5 MB | `utils/uploads.py`: extension check, size check, Pillow actually opens the image, re-saved as a fresh JPEG (removes GPS metadata and hidden payloads) |
| Extra hardening | Content-Security-Policy, X-Frame-Options, nosniff and `no-store` on private pages (`app.py`); open-redirect protection on `?next=`; unverified sign-ups auto-delete after 24 h |

## 6. Matching engine

File: `utils/matcher.py`. It runs when a post is created, and again whenever the owner opens their post or dashboard.

1. Take open posts of the **opposite type** (lost ↔ found), excluding your own, whose dates make sense (found on or after the day it was lost, ±1 day).
2. Build a text for each post: title (counted twice) + category + description + location.
3. Turn the texts into **TF-IDF vectors**. Rare, specific words like "metro" or "bi-fold" count more than common ones.
4. **Cosine similarity** between the new post and each candidate gives a 0–1 text score.
5. Final score = `0.75 × text score + 0.20 (same category) + 0.05 (shared location word)`.
6. Anything ≥ 30% is a likely match. The top 3 trigger notifications and emails to *both* posters.

## 7. Database collections

| Collection | Fields |
|---|---|
| `users` | name, email, password_hash, role (`user`/`admin`), is_verified, trust_score, rejected_claims, failed_login_attempts, lock_until, created_at, *plus* is_banned, session_token, unverified_expires_at (TTL) |
| `otps` | email, otp_hash, purpose (`register`/`reset`), attempts, expires_at (TTL index), last_sent_at |
| `items` | type (`lost`/`found`), title, category, description, location, date, image_id, hidden_details, verification_questions (`[{question, answer}]`), status, posted_by, *plus* held_at, created_at, returned_at, returned_to |
| `claims` | item_id, claimant_id, answers, proof_files, status, handover_otp_hash, reviewed_by, *plus* details, review_note, handover_expires_at, handover_attempts, history (a full timeline of who did what, when) |
| `notifications` | user_id, message, type, is_read, created_at, *plus* link |

Indexes are created automatically when the app starts (`ensure_indexes()` in `extensions.py`).

## 8. Folder structure

```
lost-found/
├── app.py               Creates the app; security headers, error pages, CLI commands
├── config.py            All settings, read from .env
├── extensions.py        Mongo, mail, CSRF, login manager, rate limiter + DB indexes
├── models.py            User class for Flask-Login (with the session-token check)
├── forms.py             Every form and its server-side validation
├── .env                 Your secrets (NOT committed; see .gitignore)
├── .env.example         Template for .env (committed, no real secrets)
├── requirements.txt     Exact library versions
├── routes/
│   ├── auth.py          Register, verify OTP, login, logout, forgot/reset password
│   ├── items.py         Report lost/found, browse & search, item details, photos
│   ├── claims.py        Claim form, my claims, review, proof images
│   ├── admin.py         Admin panel, security desk, posts, users
│   └── main.py          Landing, dashboard, notifications, profile
├── utils/
│   ├── otp.py           Generate / hash / verify OTPs, resend cooldown
│   ├── mailer.py        Sends every email (prints to the terminal in dev mode)
│   ├── matcher.py       TF-IDF matching + answer similarity hint
│   ├── validators.py    College email, password rules, input cleaning
│   ├── claims.py        Approve / reject / handover logic, trust score
│   ├── uploads.py       Image checks, blurring, private storage
│   └── notifications.py, decorators.py, helpers.py, icons.py
├── templates/           Pages (auth/, items/, claims/, admin/, main/) + emails/
├── static/              css/style.css, js/main.js, images/, uploads/ (public blurred copies)
├── private_uploads/     Original photos and claim proofs (never served directly)
└── tests/               28 automated tests (pytest)
```

## 9. Pages

Landing · Register · Verify OTP · Login · Forgot Password · Reset Password · Dashboard · Report Lost Item · Report Found Item · Browse & Search · Item Details · Claim Form · My Claims (+ claim detail/review page) · Notifications · Profile · Admin Panel (Overview, Claims, Security desk, Posts, Users).

## 10. Design decisions worth explaining in the viva

- **Why HMAC-SHA256 for OTPs instead of bcrypt?** A 6-digit code has only a million possibilities, so any plain hash can be reversed by trying them all. HMAC mixes in the server's `SECRET_KEY`, so a stolen database alone is useless. The 5-attempt limit stops online guessing.
- **Why private uploads live outside `static/`?** Anything in `static/` can be downloaded by anyone who knows the URL. Original photos and proofs (bills, IMEI numbers) are personal, so they're served by a route that checks permissions first. Only the blurred copies sit in `static/uploads/`.
- **Why a `session_token` on each user?** Flask's login cookie is signed, not stored on the server, so it can't simply be deleted. Putting a random token in the cookie and in the database means changing the token (password reset, ban) instantly invalidates every old cookie.
- **Why registration looks the same for existing emails?** Otherwise an attacker could type emails into the register form to learn who has an account. The real owner gets an email explaining what happened.
- **Why a finder can't decide disputed items?** With two claimants, a finder might favour a friend. An admin compares both sets of answers and proof.
- **Why is proof optional?** Many items (a water bottle, keys) have no bill. The answers and the ID check at the desk still apply.

## 11. Commands

Run these inside the project folder with the virtual environment activated (see the setup guide).

| Command | What it does |
|---|---|
| `python app.py` | Start the website at http://127.0.0.1:5000 |
| `flask --app app create-admin` | Create an admin account (asks for name, email, password) |
| `flask --app app promote-admin someone@college.edu.in` | Make an existing user an admin |
| `flask --app app send-test-email you@gmail.com` | Check the Gmail settings |
| `flask --app app seed-demo` | Add 3 demo users and 5 demo items (password `Demo@1234`) |
| `flask --app app seed-demo --clear` | Remove the demo data |
| `pytest` | Run the 28 automated tests (needs MongoDB running) |
