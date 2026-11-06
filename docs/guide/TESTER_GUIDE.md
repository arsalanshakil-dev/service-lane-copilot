# Service Lane Copilot: tester and demo guide

Updated: 2026-11-06

## What it is

Service Lane Copilot is an assistant for car-dealership service advisors. An advisor enters a vehicle's serial number and sees:

- its mileage and service history
- which services are due or coming up, each with the record evidence behind it

A local AI model helps write customer messages, suggests extra checks and answers questions about the records.

The app and its AI models run on your own computer; the AI runs locally through Ollama, so prompts and answers are not sent to any AI service. Only the database is reached over the network. All 1,000 vehicle records are synthetic demo data, so no real customers or vehicles are involved.

| Part | What it does |
| --- | --- |
| Web app (port 3000) | The screens you use: Service lane, Vehicle records, Settings (from the ··· menu beside the advisor name) and the Ask Copilot chat |
| Backend API | Reads and updates vehicle records, and works out due and coming-up services from editable maintenance rules |
| Database | Supabase (Postgres) with 1,000 synthetic vehicles and 8 demo maintenance rules |
| Local AI | Ollama with two models: `qwen3.5:4b` (better answers) and `qwen3:1.7b` (faster) |

## Install and run

The app runs as two local servers, a Python API and a Next.js web app, plus Ollama for the AI.

### One-command install (recommended)

Run one line in a terminal. The script checks for Git, Python, Node.js and Ollama and offers to install any that are missing. It then downloads the project to `service-lane-copilot` in your home folder, sets everything up, downloads the two AI models (a few GB), starts the app and opens the browser. It asks once for the Supabase URL and secret key; ask the project owner for these privately.

**Windows** (PowerShell or Command Prompt):

```
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; & ([scriptblock]::Create((irm https://raw.githubusercontent.com/arsalanshakil-dev/service-lane-copilot/main/scripts/install-windows.ps1)))"
```

**macOS and Linux** (Terminal):

```
bash -c "$(curl -fsSL https://raw.githubusercontent.com/arsalanshakil-dev/service-lane-copilot/main/scripts/install.sh)"
```

To start the app again later, run the same line. It skips the finished steps.

After the first install, the script is in the project folder. Add an option to the command below to change what it does:

- Windows (PowerShell): `powershell -ExecutionPolicy Bypass -File $HOME\service-lane-copilot\scripts\install-windows.ps1 <option>`
- macOS / Linux: `bash ~/service-lane-copilot/scripts/install.sh <option>`

| To do this | Windows option | macOS / Linux option |
| --- | --- | --- |
| Stop the app | Close the two "Service Lane Copilot" windows | `--stop` |
| Get the latest version | `-Update` | `--update` |
| Enter new database keys | `-ResetKeys` | `--reset-keys` |
| Download only the smaller, faster model | `-SmallModelOnly` | `--small-model-only` |
| Use another web port | `-WebPort 3001` | `--web-port 3001` |

On macOS and Linux the server logs are in `~/service-lane-copilot/.run/`.

### Manual install

Full details are in the [README](../../README.md); this is the short version for Windows PowerShell.

**What you need:**

- Python 3.11 or newer, Node.js 20.9 or newer, and Git
- [Ollama](https://ollama.com/download), with the two models pulled: `ollama pull qwen3.5:4b` and `ollama pull qwen3:1.7b`
- Access to a Supabase database that holds the demo data, as a `SUPABASE_URL` and `SUPABASE_SECRET_KEY`. Ask the project owner for these privately and never share them further.
- At least 8 GB of RAM (16 GB recommended)

**Steps:**

1. Get the project folder, for example `git clone https://github.com/arsalanshakil-dev/service-lane-copilot.git`.
2. Copy `backend/.env.example` to `backend/.env` and fill in `SUPABASE_URL` and `SUPABASE_SECRET_KEY`.
3. Terminal 1, the API:

   ```powershell
   cd backend
   py -3 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

4. Terminal 2, the web app:

   ```powershell
   cd frontend
   npm install
   npm run dev
   ```

5. Make sure the Ollama app is running, then open http://localhost:3000 in your browser.

If you are setting up your own database instead, follow "Supabase database setup" in the README, including the one-time maintenance-rules step, and load the demo data with `python seed_supabase.py` from `backend/`.

**Common situations:**

| Situation | What to do |
| --- | --- |
| Stop the app | Press Ctrl+C in both terminals. Changes stay in the database. |
| The page loads but shows "unavailable" | Check that Terminal 1 is running and `backend/.env` has the right Supabase values. http://127.0.0.1:8000/api/health shows the status. |
| Chat says Ollama is not available | Start the Ollama app and check `ollama list` shows the models |
| Port 3000 is already in use | Run `npm run dev -- -p 3001` and open http://localhost:3001 |
| AI answers are very slow | ··· menu beside the advisor name → Settings → AI model → `qwen3:1.7b` |

## Five-minute demo script

Present it as a customer arriving at the service lane. Before the demo, open the app and ask the chat one question so the AI model is already loaded. The first AI answer of a session is the slowest.

1. **Look up a vehicle (30 s).** On Service lane, click a sample serial under the search box. Point out:
   - the mileage
   - the Overview tab with its Due and Coming up items
   - that every item shows the record evidence and the rule behind it
2. **Show history and telemetry (45 s).**
   - Open the History tab, then the Telemetry tab.
   - Telemetry is a simulated 5-minute recording. Switch the window between 15 s and 5 min and drag the slider.
   - Say clearly that it is simulated and never used for recommendations.
3. **Record a completed service (45 s).** Back on Overview, click **Mark as done** on a recommendation, enter today's date and mileage, and save. The item turns Completed, and the Change log tab gets a new entry.
4. **Draft a customer message (45 s).** In Customer drafts, show the instant Explanation draft, then click **Generate with local AI**. Point out that drafts are never sent anywhere.
5. **Ask Copilot (60 s).** Open the chat and ask, "What does this vehicle need today and why?"
   - Then ask it to update the mileage to a higher number. It shows a change card, and nothing is saved until you click **Apply change**.
   - Ask something off-topic, such as "What's the weather?", to show that it refuses questions that aren't about service.
6. **Browse all records (30 s).** Open Vehicle records, search for a make, change the rows per page, and click **AI summary** on a row.
7. **Settings (30 s).** Open the **···** menu beside the advisor name at the bottom of the sidebar and choose **Settings**. Show the AI model choice, theme, time zone and the Maintenance rules. Changing a rule's miles changes which vehicles show as Due.

## Test checklist

Tick each item and note anything that looks wrong.

| # | Try this | Expected result |
| --- | --- | --- |
| 1 | Open http://localhost:3000 | The Service lane page loads with sample serials |
| 2 | Look up a sample serial | The vehicle opens with Overview, History, Telemetry and Change log tabs |
| 3 | Look up a serial that doesn't exist, such as `TEST-0000` | A clear "not found" message with an option to add the vehicle |
| 4 | Vehicle records: search, page through the list, change rows per page | 1,000 records in total; the paging and counts are correct |
| 5 | Add a vehicle (Vehicle records → + Add vehicle) | It saves and opens; the Change log shows "added" |
| 6 | Edit details, a history entry and a recommendation | Changes save and appear in the Change log; history cannot be deleted |
| 7 | Update mileage | The new mileage shows with its date and source |
| 8 | Mark a recommendation as done | It shows Completed, and a history entry is added |
| 9 | Generate with local AI (drafts), Suggest more with local AI, and AI summary | Each returns text within a few minutes; no prices appear |
| 10 | Chat: ask about a vehicle, then ask it to change something | It answers from the record; changes appear as cards and are saved only after Apply change |
| 11 | Chat: ask a general question (recipes, weather, coding) | A polite refusal |
| 12 | Settings (··· menu beside the advisor name; ⚙ in the top bar on a phone): switch the AI model, theme and time zone | Each applies across the app and is remembered after a reload |
| 13 | Settings: edit a maintenance rule's miles | Due and Coming up items change on affected vehicles |
| 14 | Stop both servers, start them again, then reload | Your earlier changes are still there |

**Reporting an issue:** send the serial number, the steps you took, what you expected, what happened, a screenshot, and the last 30 lines of the terminal that showed an error.

## Limits and things to know

- **AI speed:** the models run on the CPU. A first answer can take 1–3 minutes, and long chats take longer. `qwen3:1.7b` is faster but less accurate.
- **No login:** keep the app on your own machine and do not expose ports 3000 or 8000 to a network.
- **Demo data only:** the vehicles, history and maintenance rules are fictional. They are not real maintenance advice, and safety items are prompts for an advisor to check, not diagnoses.
- **Simulated telemetry:** no vehicle or OBD-II adapter is connected.
- **AI output must be reviewed:** AI suggestions and summaries are unverified. Drafts are text only and never sent.
