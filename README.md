# StudyLens — User Guide

StudyLens helps you work with **social media effects** research: explore studies in the database, compare them side by side, and contribute new papers for review. Step-by-step guidance for extracting structured fields from your own PDFs will be added here once that workflow is published in this repository.

---

## Get structured information from your PDF


---

## Use the StudyLens website

The web app lets you **search**, **open article details**, and **compare** studies already in the database.

### Open the site

- **Local copy:** if you run the app yourself, it is typically at `http://localhost:5001` (see below).
- **Hosted instance:** use the URL provided by your team or institution.

### Search and filters

- Enter keywords (topic, author, journal, US, high income, etc.).
- Narrow results with year, journal, and country/region filters where available.

### Article pages

- Open **View Details** for condensed summaries of each feature.
- Expand **full** or **verbatim** text when you need the original wording from the dataset.

### Compare studies

- Add papers to your comparison list from search (up to **five** at a time).
- Click **Create Your Own Comparison** to enter custom mode. You can turn **44 indicators** on or off across the bibliographic, design, measurement, findings, context, and platform-usage groupings—so you build a **personalized** table with only the rows you need, then read or **export** it. This is often more practical than scrolling an all-fields view. Use **Back to standard view** when you want the full layout again.
- **Export** your table as **CSV** with **Download Comparison**.
- **Save** comparisons in the browser (stored locally on your device) when you want to return to the same setup.

### Profile

- Set **username** and **institution** (stored in your browser).
- See **favorites**, **saved comparisons**, and **activity** stats when using a connected instance.

---

## Ask to add your paper to the shared database

If you want **your interested studies included** in the public StudyLens catalog (not just a CSV on your machine):

1. Open **Profile** -> **Upload Papers**.
2. Fill in your contact details and the URL of the paper.
3. **Attach the PDF** if you are allowed to share it—this helps reviewers process your request.
4. Submit and check back within one week to confirm your papers have been added to the database.

Requests are reviewed before data goes live. We usually process requests within about a week.

---

## What kind of information you get

On the **Compare** page, the table and **Create Your Own Comparison** indicator list use the same **six sections** and **44 rows** as in the app:

- **Bibliographic:** Authors, Title, Journal, Year, Citation, Abstract  
- **Research Design & Sample:** Sample Size, Country / Region, Recruitment Source, Demographics, Incentive  
- **Measurement & Analysis:** Treatment / Independent Variable(s), Outcome / Dependent Variable(s), Survey Questions, Analysis Equations  
- **Findings:** Main Effects, Moderators, Moderation Results  
- **Context:** AI Context Summary, Temporal Context, GDP Per Capita (USD), Gini Coefficient, World Bank Income Group, Study Language, Platform Language / Locale Optimization, Traditional Media Strength, Electoral Proximity, Liberal Democracy Index, Press Freedom Index, Internet Freedom Score, Internet Penetration, Political Stability Score  
- **Internet And Social Media Usage:** Population (Million), Internet Users (Million), Social Media Users (Million), YouTube Users (Million), Facebook Users (Million), Instagram Users (Million), X Users (Million), TikTok Users (Million), LinkedIn Users (Million), Messenger Users (Million), Snapchat Users (Million), Pinterest Users (Million)  

Many indicators include both a **condensed** summary and a **verbatim** excerpt from the source when the dataset provides both (AI Context Summary is condensed-only in the comparison view).

---

## Run the website on your computer (optional)

Set **`GROQ_API_KEY`** before starting the server: the app configures a **Groq** client at startup (`app.py`) so that backend code can send prompts to **Groq’s hosted language models** when those endpoints run (without a key, that client is created without credentials and any Groq-backed call can fail).

```bash
pip install -r requirements.txt
export GROQ_API_KEY="your-groq-api-key"
python app.py
```

Then open the address shown in the terminal (often port **5001**).

---

## Privacy

- **Profile, favorites, and saved comparisons** in the browser are stored **locally** on your device unless your team has customized the app.
- **Upload requests** and usage tracking on a shared server are stored **on that server** according to the operator’s policy.
- Keep **API keys** on your machine or secret manager only.

