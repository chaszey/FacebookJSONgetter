import json
import os
import requests
from apify_client import ApifyClient

# Haal alle geheimen op uit de GitHub environment variables
APIFY_TOKEN = os.getenv("APIFY_TOKEN")
WP_USER = os.getenv("WP_USER")
WP_PASS = os.getenv("WP_PASS")
FB_COOKIES_RAW = os.getenv("FB_COOKIES")

# WordPress configuratie
WP_URL_POSTS = "https://stichtingenpassant.nl/wp-json/wp/v2/posts"

# Converteer de cookies naar het juiste formaat voor Apify
cookies_input = []
if FB_COOKIES_RAW:
  try:
    cookies_input = json.loads(FB_COOKIES_RAW)
  except Exception as e:
    print(f"Waarschuwing bij parsen van cookies: {e}")

# --- STAP 1: Haal al bestaande WordPress-berichten op ---
print("Bezig met ophalen van bestaande WordPress-berichten...")
existing_urls = set()
page = 1

while True:
  res = requests.get(
      WP_URL_POSTS,
      params={"per_page": 100, "page": page, "status": "publish"},
      auth=(WP_USER, WP_PASS),
  )

  print(f"WordPress API Status Code: {res.status_code}")

  if res.status_code != 200:
    print(f"Fout of einde bereikt. Server antwoordde met: {res.text[:300]}")
    break

  try:
    posts = res.json()
  except Exception as e:
    print(f"Kon JSON niet lezen. Ruwe serverrespons: {res.text[:300]}")
    break

  if not posts:
    break

  for post in posts:
    existing_urls.add(post.get("content", {}).get("rendered", ""))
  page += 1

# --- STAP 2: Haal data op van Apify (inclusief cookies om de loginmuur te omzeilen) ---
print("Bezig met ophalen van Facebook-posts via Apify...")
apify_client = ApifyClient(APIFY_TOKEN)

run_input = {
    "startUrls": [{"url": "https://www.facebook.com/groups/schaakhuis"}],
    "maxPosts": 5,
}

if cookies_input:
  run_input["cookies"] = cookies_input
  print("Facebook cookies succesvol geladen voor de scraper.")
else:
  print("Let op: Geen FB_COOKIES gevonden, kans op blokkade door Facebook is groot.")

run = apify_client.actor("whoareyouanas/facebook-group-scraper").call(
    run_input=run_input
)

# --- STAP 3: Loop door de posts en plaats ze als ze nieuw zijn ---
new_posts_count = 0
for item in apify_client.dataset(run["defaultDatasetId"]).iterate_items():
  post_text = item.get("text", "Geen tekst")
  post_url = item.get("url", "#")

  if post_url in str(existing_urls):
    print(f"Bericht bestaat al, overgeslagen: {post_url}")
    continue

  payload = {
      "title": f"Schaakhuis Update: {post_text[:30]}...",
      "content": (
          f"<p>{post_text}</p><p><a href='{post_url}' target='_blank'>Bekijk"
          " origineel bericht op Facebook</a></p>"
      ),
      "status": "publish",
  }

  response = requests.post(
      WP_URL_POSTS, json=payload, auth=(WP_USER, WP_PASS)
  )

  if response.status_code == 201:
    print(f"Succesvol geplaatst: {post_url}")
    new_posts_count += 1
  else:
    print(f"Fout bij plaatsen ({response.status_code}): {response.text}")

print(f"Klaar! {new_posts_count} nieuwe berichten toegevoegd aan WordPress.")
