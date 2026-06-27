# 🏠 Mudah Property Scraper (CSV)

Scrapes Mudah.my property listings daily at **10:00 AM MYT** and saves results as CSV files directly in this repo. No Google account needed.

---

## 📁 File Structure

```
mudah-scraper/
├── .github/
│   └── workflows/
│       └── scrape.yml        ← GitHub Actions schedule
├── data/                     ← Auto-created by scraper
│   ├── mudah_all.csv         ← Master file (all listings ever)
│   └── mudah_2025-01-01.csv  ← Daily file (new listings only)
├── scraper.py
├── requirements.txt
└── README.md
```

---

## 🚀 Setup (5 minutes)

### Step 1 — Create a GitHub repo

1. Go to [github.com](https://github.com) → **New repository**
2. Name it `mudah-scraper`, set it to **Private** (recommended)
3. Click **Create repository**

### Step 2 — Push these files

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/mudah-scraper.git
git push -u origin main
```

### Step 3 — Enable Actions write permission

> GitHub Actions needs permission to commit the CSV back to the repo.

1. Go to your repo → **Settings**
2. Click **Actions → General** (left sidebar)
3. Scroll to **Workflow permissions**
4. Select **Read and write permissions**
5. Click **Save**

### Step 4 — Test it manually

1. Go to your repo → **Actions** tab
2. Click **Mudah Property Scraper**
3. Click **Run workflow → Run workflow**
4. Once done, check the `data/` folder in your repo — CSVs will be there!

---

## ⚙️ Customisation

Edit the top of `scraper.py`:

```python
# Scrape KL only
MUDAH_URL = "https://www.mudah.my/kuala-lumpur/properties-for-sale"

# Selangor rentals
MUDAH_URL = "https://www.mudah.my/selangor/properties-for-rent"

# More pages per run (slower but more data)
MAX_PAGES = 10
```

---

## 📊 CSV Columns

| Column | Description |
|---|---|
| `listing_id` | Unique ID (used for deduplication) |
| `title` | Property title |
| `price` | Listed price |
| `location` | Area/region |
| `beds` | Bedrooms |
| `baths` | Bathrooms |
| `size` | Floor area |
| `url` | Link to listing |
| `scraped_at` | Timestamp |

---

## 📂 Two Output Files

| File | What's in it |
|---|---|
| `data/mudah_YYYY-MM-DD.csv` | Only **new** listings found today |
| `data/mudah_all.csv` | Every listing ever scraped (master) |

The scraper deduplicates using `listing_id` so no row ever appears twice in the master file.
