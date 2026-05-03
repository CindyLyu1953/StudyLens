# StudyLens — User Guide

StudyLens helps you work with **social media effects** research: explore studies in the database, compare them side by side, and—when you have your own paper—**turn PDFs into structured tables** (design, measures, findings, context) using the included extraction notebooks.

---

## Get structured information from your PDF (fastest path)

The website **does not** extract fields from your PDF automatically. To go **from PDF → spreadsheet-style features on your computer**, use the Jupyter notebooks in this repository with a **Google Gemini API key**.

### 1. Prerequisites

- [Python 3](https://www.python.org/downloads/) and [Jupyter](https://jupyter.org/install) (or Google Colab)
- Your paper as a **PDF** (and any **appendix PDFs**, if the study uses them)

### 2. API key

1. Create a key with Google’s Gemini API: [Gemini API documentation](https://ai.google.dev/gemini-api/docs).
2. Set it as an environment variable **`GOOGLE_API_KEY`**, or paste it into the notebook where indicated (see the first setup cells).

**Do not commit your API key** to git or share it publicly.

### 3. Run the extraction notebook

1. Open **`Feature_Exraction/Non_Contextual_Features.ipynb`** in Jupyter (or upload it to Colab).
2. Install dependencies if prompted (the notebook installs `google-generativeai`; other imports are standard library unless your environment is minimal).
3. **Run all cells**. When asked, select your **main PDF**(s). If a paper has appendices, you can upload those when prompted.
4. When it finishes, you get a **CSV file** of extracted study features (condensed and verbatim fields where applicable).

### 4. Optional: contextual metadata

For extra **context** columns (e.g. country, year window, socio-political framing), run **`Feature_Exraction/Contextual_Metadata.ipynb`** with the same API setup. It will ask for inputs such as country and year range, then produce another CSV. You can **merge** that output with the first CSV for a fuller row set.

More detail on prompts and flow: **`Feature_Exraction/Feature_Extraction.md`**.

---

## Use the StudyLens website

The web app lets you **search**, **open article details**, and **compare** studies already in the database.

### Open the site

- **Local copy:** if you run the app yourself, it is typically at `http://localhost:5001` (see below).
- **Hosted instance:** use the URL provided by your team or institution.

### Search and filters

- Enter keywords (topic, author, journal, etc.).
- Narrow results with year, journal, and country/region filters where available.

### Article pages

- Open **View Details** for condensed summaries of each feature.
- Expand **full** or **verbatim** text when you need the original wording from the dataset.

### Compare studies

- Add papers to your comparison list from search (up to **five** at a time).
- Export a comparison as **CSV** if you need it offline.
- You can **save** comparisons in the browser (stored locally on your device).

### Profile

- Set **username** and **institution** (stored in your browser).
- See **favorites**, **saved comparisons**, and **activity** stats when using a connected instance.

---

## Ask to add your paper to the shared database

If you want **your study included** in the public StudyLens catalog (not just a CSV on your machine):

1. Open **Profile** → **Upload Papers**.
2. Fill in your contact details and **bibliographic information** (title, authors, DOI, etc.).
3. **Attach the PDF** if you are allowed to share it—this helps reviewers process your request.
4. Submit and track status under **My Requests**.

Requests are reviewed before data goes live. Timing depends on whoever runs that instance.

---

## What kind of information you get

Extracted and displayed fields are grouped roughly as:

- **Basics:** title, authors, journal, year, citation, abstract  
- **Design & sample:** sample size, region, recruitment, demographics, incentives  
- **Measurement & analysis:** treatments, outcomes, survey items, estimation approach  
- **Findings:** main effects, moderators, interactions  
- **Context:** social, political, platform, and time-related background  

Many columns have both a **short** version and a **verbatim** excerpt when the dataset provides both.

---

## Run the website on your computer (optional)

```bash
pip install -r requirements.txt
python app.py
```

Then open the address shown in the terminal (often port **5001**). You still need the **PDF extraction notebooks** above to generate structured rows from new PDFs.

---

## Privacy

- **Profile, favorites, and saved comparisons** in the browser are stored **locally** on your device unless your team has customized the app.
- **Upload requests** and usage tracking on a shared server are stored **on that server** according to the operator’s policy.
- Keep **API keys** on your machine or secret manager only.

---

## Getting help

- For **PDF extraction** issues, check `Feature_Exraction/Feature_Extraction.md` and your API quota or PDF permissions.
- For **database content** or **upload requests**, use the request form in the app or contact whoever operates your StudyLens instance.
