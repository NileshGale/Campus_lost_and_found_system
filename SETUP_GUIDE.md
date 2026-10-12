# Setup Guide: Campus Lost & Found

This guide takes you from a fresh Windows laptop to the app running in your browser. No prior setup is assumed. Each step ends with a **✅ Check** so you know it worked before moving on.

Budget about **45–60 minutes** the first time, mostly waiting for downloads.

> **On a Mac or Linux?** The steps are the same; only a few commands differ. See [Mac / Linux differences](#mac--linux-differences) at the end.

---

## Contents

0. [What you are setting up](#0-what-you-are-setting-up)
1. [Install Python](#1-install-python)
2. [Install MongoDB (the database)](#2-install-mongodb-the-database)
3. [Install VS Code (optional, recommended)](#3-install-vs-code-optional-recommended)
4. [Get the project code](#4-get-the-project-code)
5. [Open a terminal in the project folder](#5-open-a-terminal-in-the-project-folder)
6. [Create a virtual environment](#6-create-a-virtual-environment)
7. [Install the Python libraries](#7-install-the-python-libraries)
8. [Create your `.env` file (settings and secrets)](#8-create-your-env-file-settings-and-secrets)
9. [Set up Gmail for sending emails](#9-set-up-gmail-for-sending-emails)
10. [Create the admin account](#10-create-the-admin-account)
11. [Start the app](#11-start-the-app)
12. [Try the whole flow once](#12-try-the-whole-flow-once)
13. [Look inside the database (for the viva)](#13-look-inside-the-database-for-the-viva)
14. [Run the automated tests](#14-run-the-automated-tests)
15. [Everyday use: starting and stopping](#15-everyday-use-starting-and-stopping)
16. [Putting the code on GitHub safely](#16-putting-the-code-on-github-safely)
17. [Checklist before the final submission](#17-checklist-before-the-final-submission)
18. [Troubleshooting](#18-troubleshooting)
19. [Mac / Linux differences](#mac--linux-differences)
20. [Optional: putting it online](#optional-putting-it-online)

---

## 0. What you are setting up

| Piece | What it is | Where it runs |
|---|---|---|
| **Python** | The programming language the app is written in | Your laptop |
| **Flask app** (this project) | The website itself | Your laptop, at `http://127.0.0.1:5000` |
| **MongoDB** | The database that stores users, items and claims | Your laptop (or free in the cloud with Atlas) |
| **Gmail SMTP** | Sends the OTP and alert emails | Google's servers, using your Gmail account |

The browser talks to the Flask app; the Flask app talks to MongoDB and Gmail.

**A note on the terminal.** You'll type commands into a terminal (PowerShell). Type or paste each command exactly as shown and press **Enter**. Lines starting with `#` are comments; don't type those.

---

## 1. Install Python

1. Go to **https://www.python.org/downloads/windows/** and download the latest **Python 3.12** or **3.13** "Windows installer (64-bit)". (The app is tested on 3.12. Versions older than 3.12 will **not** work.)
2. Run the installer. On the **first screen**, tick **"Add python.exe to PATH"** at the bottom. This is the most commonly missed step.
3. Click **Install Now** and wait for it to finish.

**✅ Check:** open a *new* PowerShell window (press the Windows key, type `powershell`, press Enter) and run:

```powershell
python --version
```

You should see `Python 3.12.x` or `Python 3.13.x`.
If you see "not recognized" or the Microsoft Store opens, see [Troubleshooting](#18-troubleshooting) → *"python is not recognized"*.

---

## 2. Install MongoDB (the database)

Pick **one** option. **Option A** is simplest for a college demo.

### Option A: MongoDB on your laptop (recommended)

1. Go to **https://www.mongodb.com/try/download/community**.
2. Choose: Version = the latest **8.0.x**, Platform = **Windows x64**, Package = **msi**. Click **Download**.
3. Run the installer:
   - Choose **Complete**.
   - On the "Service Configuration" screen, keep **"Install MongoD as a Service"** ticked (with the default settings). MongoDB then starts automatically with Windows.
   - Keep **"Install MongoDB Compass"** ticked. Compass is a visual tool to look at your data.
4. Finish the installation.

**✅ Check:** open **MongoDB Compass** from the Start menu, leave the connection string as `mongodb://localhost:27017` and click **Connect**. If you see a list of databases (`admin`, `config`, `local`), MongoDB is running.

Your `MONGO_URI` (needed in step 8) is:

```
mongodb://localhost:27017/lostfound
```

### Option B: MongoDB Atlas (free, in the cloud)

Use this if you can't install software, or want to share one database between laptops.

1. Sign up at **https://www.mongodb.com/cloud/atlas/register** and create a **free (M0)** cluster.
2. **Database Access** → *Add New Database User* → choose a username and password (avoid `@ : / ?` in the password). Save both.
3. **Network Access** → *Add IP Address* → *Add Current IP Address*. (For a demo on different Wi-Fi networks you can use `0.0.0.0/0`, which allows any IP. That's less safe, so remove it afterwards.)
4. **Database** → *Connect* → *Drivers* → copy the connection string. It looks like:
   `mongodb+srv://myuser:<db_password>@cluster0.abcde.mongodb.net/?retryWrites=true&w=majority`
5. Replace `<db_password>` with your password and add the database name **`lostfound`** right after `.net/`:

```
mongodb+srv://myuser:MyPassword123@cluster0.abcde.mongodb.net/lostfound?retryWrites=true&w=majority
```

That full line is your `MONGO_URI` for step 8.

---

## 3. Install VS Code (optional, recommended)

A good editor makes it easier to edit `.env` and read the code.

1. Download from **https://code.visualstudio.com/** and install (tick "Add to PATH" and "Open with Code").
2. Open VS Code → Extensions (left sidebar, the four-squares icon) → install **Python** (by Microsoft).

---

## 4. Get the project code

Use whichever matches how the code was shared with you.

**If you got a ZIP file:** right-click it → **Extract All...** → choose a simple location such as `C:\Projects\`. You should end up with a folder like `C:\Projects\lost-found\` that directly contains `app.py`, `requirements.txt`, `README.md`, etc.

**If it's on GitHub:** install Git from **https://git-scm.com/download/win** (all defaults are fine), then in PowerShell:

```powershell
cd C:\Projects
git clone https://github.com/<username>/<repo-name>.git lost-found
```

> If the folder you received contains a `.venv` folder, **delete it**. A virtual environment only works on the computer it was created on. You'll create your own in step 6.

**✅ Check:** the folder contains `app.py`, `config.py`, `requirements.txt`, `.env.example` and the folders `routes`, `templates`, `static`, `utils`.
(Files starting with a dot can be hidden. In File Explorer: **View → Show → File name extensions** and **Hidden items**.)

---

## 5. Open a terminal in the project folder

Every command from now on must run **inside the project folder**.

- **Easiest (Windows 11):** open the `lost-found` folder in File Explorer, right-click an empty area → **Open in Terminal**.
- **Or in VS Code:** File → Open Folder → pick `lost-found` → Terminal → New Terminal.
- **Or manually:** `cd C:\Projects\lost-found`

**✅ Check:** run `dir app.py`. It should list the file, not say "Cannot find path".

---

## 6. Create a virtual environment

A virtual environment (`.venv`) is a private folder of libraries just for this project, so it doesn't clash with anything else on your computer.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell says *"running scripts is disabled on this system"*, run this **once**, answer `Y`, then run the activate command again:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.venv\Scripts\Activate.ps1
```

(In the old Command Prompt instead of PowerShell, the activate command is `.venv\Scripts\activate.bat`.)

**✅ Check:** your prompt now starts with `(.venv)`, like:
`(.venv) PS C:\Projects\lost-found>`

> **Remember:** every time you open a new terminal to work on the project, run `.venv\Scripts\Activate.ps1` first. If `(.venv)` isn't shown, the commands below won't find the libraries.

---

## 7. Install the Python libraries

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

This downloads Flask, PyMongo, scikit-learn, Pillow and the rest. It can take **3–10 minutes**. scikit-learn is large.

**✅ Check:** the last line says `Successfully installed ...` with no red `ERROR`. Then:

```powershell
python -c "import flask, pymongo, sklearn, PIL; print('All libraries OK')"
```

prints `All libraries OK`.

---

## 8. Create your `.env` file (settings and secrets)

The `.env` file holds passwords and college-specific settings. It **stays on your computer**. It's listed in `.gitignore`, so Git never uploads it to GitHub.

1. Make your own copy from the template. (If a `.env` already exists in the folder, skip this and edit that one instead.)

   ```powershell
   Copy-Item .env.example .env
   ```

2. Generate a secret key (a long random string that protects logins and OTPs):

   ```powershell
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

   Copy the 64-character output.

3. Open the file: `notepad .env` (or open it in VS Code) and fill it in:

   | Setting | What to put |
   |---|---|
   | `SECRET_KEY` | The 64-character string from step 2. Never share it. |
   | `MONGO_URI` | `mongodb://localhost:27017/lostfound` (Option A) or your Atlas string (Option B) |
   | `FLASK_DEBUG` | `1` while setting up and testing. `0` for the final demo. |
   | `MAIL_USERNAME` | Your Gmail address (step 9). **Can stay empty for now.** |
   | `MAIL_PASSWORD` | Your Gmail **App Password** (step 9). **Can stay empty for now.** |
   | `COLLEGE_NAME` | e.g. `ABC Institute of Technology` |
   | `ALLOWED_EMAIL_DOMAINS` | The part after `@` in college emails, e.g. `abcit.edu.in`. Several? Separate with commas: `abcit.edu.in,staff.abcit.edu.in` |
   | `CONTACT_EMAIL`, `CONTACT_PHONE` | Shown in the footer |
   | `SECURITY_DESK_LOCATION`, `SECURITY_DESK_HOURS` | Where and when items are collected |
   | `CAMPUS_LOCATIONS` | Suggestions for the location box, comma separated |
   | `COOKIE_SECURE`, `BEHIND_PROXY` | Leave at `0` on your laptop |

4. Save the file. In Notepad, make sure it's saved as `.env`, **not** `.env.txt`. Choose *Save as type: All files* if needed.

> **Testing without Gmail:** if `MAIL_USERNAME` / `MAIL_PASSWORD` are empty and `FLASK_DEBUG=1`, the app **prints every email (including the OTP codes) in the terminal** instead of sending it. You can test everything now and set up Gmail later.

**✅ Check:**

```powershell
python -c "from app import app; print('Config OK, database:', app.config['MONGO_URI'])"
```

This should print `Config OK ...`. If it mentions `SECRET_KEY` or MongoDB, see [Troubleshooting](#18-troubleshooting).

---

## 9. Set up Gmail for sending emails

Gmail requires an **App Password**, a separate 16-letter password just for this app. **Your normal Gmail password will not work** (Google rejects it).

> ⚠️ **Security note:** an app password was shared over chat earlier. Treat that one as exposed: **delete it** (step 5 below) and create a new one. Put the new one **only** in `.env`, never in code, chats or GitHub.

1. Use a **personal Gmail account**. College / Google Workspace accounts often have app passwords turned off by the college.
2. Turn on 2-Step Verification: **https://myaccount.google.com/signinoptions/two-step-verification**. App passwords only appear after this is on.
3. Open **https://myaccount.google.com/apppasswords**.
4. Type a name such as `Lost and Found` and click **Create**. Google shows a 16-letter password like `abcd efgh ijkl mnop`. Copy it now; Google shows it only once.
5. On the same page, **delete any old app password** that was shared before (trash icon next to it).
6. In `.env`:

   ```
   MAIL_USERNAME=yourname@gmail.com
   MAIL_PASSWORD=abcdefghijklmnop
   ```

   (Spaces in the password are fine; the app removes them.)
7. Send yourself a test email:

   ```powershell
   flask --app app send-test-email yourname@gmail.com
   ```

**✅ Check:** the terminal prints `Sent!` and the email arrives. **Check the Spam folder** the first time and mark it "Not spam".

The app uses Gmail SMTP: server `smtp.gmail.com`, port `587`, TLS on. These are already set in `config.py`.

---

## 10. Create the admin account

Admins review disputed claims, run the security desk, and can remove posts and ban users.

```powershell
flask --app app create-admin
```

It asks for a full name, an email and a password (twice). **While you type the password nothing appears on screen.** That's normal; just type and press Enter. The password must have 8+ characters, an uppercase letter, a number and a special character.

**✅ Check:** it prints `Admin ... created.`

Optional: add demo data for a quick presentation (3 students and 5 items, all with password `Demo@1234`):

```powershell
flask --app app seed-demo
```

Remove it later with `flask --app app seed-demo --clear`.

---

## 11. Start the app

```powershell
python app.py
```

You'll see something like:

```
 * Running on http://127.0.0.1:5000
```

Open **http://127.0.0.1:5000** in Chrome or Edge.

**✅ Check:** the landing page "Lost something on campus? Let's bring it back." appears.

- **Keep this terminal open** while you use the site. Closing it stops the website.
- **To stop:** click in the terminal and press **Ctrl + C**.
- **After editing `.env`**, stop and start the app again for the change to apply.

---

## 12. Try the whole flow once

Use **two browser windows** so you can be two people: a normal window and an **InPrivate/Incognito** window (Ctrl + Shift + N). You'll need two email addresses on your college domain. If you used `seed-demo`, the demo accounts work too.

| # | Who | Do this | You should see |
|---|---|---|---|
| 1 | Person A (finder) | **Register** with a college email | "We've emailed a 6-digit code" |
| 2 | Person A | Enter the code from the email (or the terminal, in dev mode) | "Email verified" → log in |
| 3 | Person A | **Report → I found something**. Fill it in, add private details and a question like *"What colour is the inside?" → "Brown"* | The post page shows your private details in a yellow box |
| 4 | Person B (owner) | Register, verify, log in, then **Report → I lost something** with a similar description | "We found 1 possible match". Both people get a notification (bell) and an email |
| 5 | Person B | Open the match → **This is mine** → answer the question, describe the item, tick the box → Submit | Claim status **Pending** |
| 6 | Person A | Dashboard → **Claims waiting for your review** → Review | Answers side by side with the expected answers → **Approve** |
| 7 | Person B | Check email | "Your claim was approved: handover code inside" with a 6-digit code |
| 8 | Admin | Log in → **Admin → Security desk** → *Hand over* → enter Person B's code, tick "I checked the ID" | "Handover complete." The item shows **Returned** |

Also try the safety features:

- Register with a `@gmail.com` address → rejected.
- Enter the wrong password 5 times → account locked for 15 minutes.
- **Forgot password** with an email that doesn't exist → same message as one that does.
- Claim three items with wrong answers and have them rejected → that account can't claim any more.

---

## 13. Look inside the database (for the viva)

Open **MongoDB Compass** → connect → database **`lostfound`**. You'll see:

| Collection | Things worth showing |
|---|---|
| `users` | `password_hash` starts with `$2b$`: bcrypt, never the real password. `is_verified`, `trust_score`, `failed_login_attempts`, `lock_until`. |
| `otps` | `otp_hash` is a long hex string (the code itself is never stored), `purpose`, `attempts`, `expires_at`. The document disappears by itself after 10 minutes (TTL index; MongoDB checks about once a minute). |
| `items` | `type`, `status`, `hidden_details`, `verification_questions` |
| `claims` | `answers`, `proof_files`, `status`, `history` (who did what and when) |
| `notifications` | One per bell message |

Click the **Indexes** tab on `otps` to show the TTL index on `expires_at`.

If someone gets locked out during a demo, you can edit their user document in Compass and set `lock_until` to `null`.

---

## 14. Run the automated tests

There are 28 tests covering the security rules (OTP limits, lockout, CSRF, rate limiting, uploads, the full claim and handover flow). They use a **separate** database called `lostfound_test`, so your real data is safe. MongoDB must be running.

```powershell
pip install -r requirements-dev.txt
pytest
```

**✅ Check:** the last line says `28 passed`.

---

## 15. Everyday use: starting and stopping

Each time you want to run the project:

```powershell
cd C:\Projects\lost-found        # or "Open in Terminal" in the folder
.venv\Scripts\Activate.ps1
python app.py
```

Then open http://127.0.0.1:5000. Stop with **Ctrl + C**. MongoDB (Option A) starts with Windows, so there's nothing else to start.

---

## 16. Putting the code on GitHub safely

The `.gitignore` file already keeps `.env`, `.venv`, uploads and caches out of Git. Always double-check before the first push.

```powershell
git init                       # skip if the folder already has a .git folder
git add .
git status
```

In the `git status` list, **`.env` must NOT appear** (`.env.example` is fine). To be sure:

```powershell
git check-ignore .env
```

This should print `.env`, which means it's ignored. Then:

```powershell
git commit -m "Campus Lost & Found project"
```

Create an **empty private repository** on https://github.com/new (don't add a README there), then run the lines GitHub shows you, which look like:

```powershell
git branch -M main
git remote add origin https://github.com/<username>/<repo-name>.git
git push -u origin main
```

> **If `.env` ever gets pushed by mistake:** deleting the file afterwards is not enough, because it stays in the Git history. Immediately delete that Gmail app password and create a new one (step 9), and generate a new `SECRET_KEY` (step 8).

---

## 17. Checklist before the final submission

- [ ] Created a **new** Gmail app password and **deleted** the one that was shared over chat (step 9).
- [ ] `.env` is **not** on GitHub: on the repository page you should see `.env.example` but no `.env`.
- [ ] `COLLEGE_NAME`, `ALLOWED_EMAIL_DOMAINS`, `SECURITY_DESK_LOCATION`, `SECURITY_DESK_HOURS` are set to the real values.
- [ ] `flask --app app send-test-email ...` works.
- [ ] An admin account exists.
- [ ] `FLASK_DEBUG=0` for the final demo. With `0`, emails are only sent through Gmail, never printed, so Gmail must be set up.
- [ ] Demo data removed if you don't want it: `flask --app app seed-demo --clear`.
- [ ] `pytest` shows `28 passed`.

---

## 18. Troubleshooting

| What you see | Why | Fix |
|---|---|---|
| `python is not recognized...` or the Microsoft Store opens | Python isn't on PATH | Re-run the Python installer → *Modify* → tick *Add Python to environment variables*. Or use `py` instead of `python` (`py -m venv .venv`). Also: Settings → Apps → Advanced app settings → App execution aliases → turn off the two "python" entries. |
| `Activate.ps1 cannot be loaded because running scripts is disabled` | PowerShell's safety setting | `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`, answer `Y` |
| `No matching distribution found for numpy==...` or scikit-learn fails to install | Python is older than 3.12 | Install Python 3.12/3.13, delete `.venv`, redo steps 6–7 |
| `ModuleNotFoundError: No module named 'flask'` | The virtual environment isn't active | Run `.venv\Scripts\Activate.ps1` (look for `(.venv)`) |
| `RuntimeError: SECRET_KEY is missing or too short` | `.env` missing, in the wrong folder, or saved as `.env.txt` | `.env` must sit next to `app.py`. Turn on file extensions in Explorer and rename `.env.txt` → `.env` |
| `Could not connect to MongoDB` in the terminal, or a "Database unavailable" page | MongoDB isn't running, or the URI is wrong | Option A: Win + R → `services.msc` → **MongoDB Server** → *Start*. Option B (Atlas): check the password in `MONGO_URI` and allow your IP under *Network Access* |
| `SMTPAuthenticationError: (535, 'Username and Password not accepted')` | Normal Gmail password used, 2-Step Verification off, or a typo | Create an App Password (step 9) and paste it into `MAIL_PASSWORD`. Restart the app |
| Emails don't arrive | Spam folder, or mail not configured | Check Spam. If `MAIL_*` is empty and `FLASK_DEBUG=1`, the email is printed in the terminal instead |
| "Use your college email address" for a valid college email | `ALLOWED_EMAIL_DOMAINS` doesn't match | Put the exact part after `@` (no `@`) in `.env`, then restart the app |
| "This form expired" | The page was open more than 2 hours, or cookies are blocked | Refresh the page and submit again |
| "Slow down: too many attempts" | Rate limit (for example 10 logins a minute) | Wait a minute. Restarting the app also resets the limits |
| "Too many failed attempts. Try again in N minutes" | Account lock after 5 wrong passwords | Wait 15 minutes, use **Forgot password**, or set `lock_until` to `null` in Compass |
| `Address already in use` / port 5000 busy | Another program uses port 5000 | `$env:PORT=5001; python app.py`, then open http://127.0.0.1:5001 |
| Changes in `.env` don't apply | The app reads `.env` only when it starts | Ctrl + C, then `python app.py` again |
| `flask: command not found` / `not recognized` | venv not active | Activate it (step 6) |

---

## Mac / Linux differences

| Step | Windows | Mac / Linux |
|---|---|---|
| Python | python.org installer | Mac: python.org installer or `brew install python@3.12`; Linux: your package manager |
| MongoDB | MSI installer | Mac: `brew tap mongodb/brew && brew install mongodb-community && brew services start mongodb-community`; Linux: follow mongodb.com's guide for your distro (or use Atlas) |
| Python command | `python` | `python3` |
| Create venv | `python -m venv .venv` | `python3 -m venv .venv` |
| Activate venv | `.venv\Scripts\Activate.ps1` | `source .venv/bin/activate` |
| Copy `.env` | `Copy-Item .env.example .env` | `cp .env.example .env` |
| Different port | `$env:PORT=5001; python app.py` | `PORT=5001 python app.py` (on a Mac, port 5000 is often used by AirPlay, so 5001 is a good idea) |

---

## Optional: putting it online

Not needed for a college demo. If you do deploy (Render, Railway, a VPS...):

- Use **MongoDB Atlas** for the database.
- Set the same variables from `.env` in the hosting dashboard (never upload `.env` itself), with `FLASK_DEBUG=0`, `COOKIE_SECURE=1` (the site must use HTTPS) and `BEHIND_PROXY=1`.
- Use a production server instead of `python app.py`, e.g. `gunicorn app:app` on Linux, or `waitress-serve --port=8000 app:app` on Windows (`pip install gunicorn` / `waitress`).
- With more than one worker process, point `RATELIMIT_STORAGE_URI` at shared storage (e.g. a Redis URL), so rate limits apply across all workers.
- Uploaded photos are saved on disk. Many free hosts wipe the disk on each deploy, so use a host with a persistent disk if photos must survive.
