# MENA Signal

A minimalist front page of Middle East geopolitics, defence and naval news.
Every story links out to its original publisher.

- `build.py` fetches the RSS feeds, filters to the region, removes noise and duplicates, categorises, and writes `site/index.html`.
- `template.html` is the page design.
- `.github/workflows/build.yml` rebuilds and redeploys the site to GitHub Pages every hour.

Run locally: `python build.py`, then open `site/index.html`.

Edit the feed list, keywords or site name at the top of `build.py`.
