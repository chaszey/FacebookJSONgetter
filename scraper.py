import os
import requests
from apify_client import ApifyClient

# Haal de geheimen op uit de GitHub environment variables
APIFY_TOKEN = os.getenv("APIFY_TOKEN")
WP_USER = os.getenv("WP_USER")
WP_PASS = os.getenv("WP_PASS")

# WordPress configuratie (pas jouw website URL hier aan)
WP_URL_POSTS = "https://stichtingenpassant.nl/wp-json/wp/v2/posts"

# --- STAP 1: Haal al bestaande WordPress-berichten op om duplicaten te voorkomen ---
print("Bezig met ophalen van bestaande WordPress-berichten...")
existing_urls = set()
page = 1
while True:
  res = requests.get(
      WP_URL_POSTS,
      params={"per_page": 100, "page": page, "status": "publish,draft"},
  )
  if res.status_code != 200:
    break
  posts = res.json()
  if not posts:
    break
  for post in posts:
    # We slaan de inhoud op om te checken of de Facebook-link er al in staat
    existing_urls.add(post.get("content", {}).get("rendered", ""))
  page += 1

# --- STAP 2: Haal data op van Apify ---
print("Bezig met ophalen van Facebook-posts via Apify...")
apify_client = ApifyClient(APIFY_TOKEN)
run = apify_client.actor("whoareyouanas/facebook-group-scraper").call(
    run_input={
        "startUrls": [{"url": "https://www.facebook.com/groups/schaakhuis"}],
        "maxPosts": 5,
    }
)

# --- STAP 3: Loop door de posts en plaats ze als ze nieuw zijn ---
new_posts_count = 0
for item in apify_client.dataset(run["defaultDatasetId"]).iterate_items():
  post_text = item.get("text", "Geen tekst")
  post_url = item.get("url", "#")

  # Als de URL al ergens in een bestaande post content voorkomt, slaan we hem over
  if post_url in str(existing_urls):
    print(f"Bericht bestaat al, overgeslagen: {post_url}")
    continue

  # Bouw het WordPress bericht (je kunt 'status' op 'publish' zetten als je het direct live wilt)
  payload = {
      "title": (
          f"Schaakhuis Update: {post_text[:30]}..."
      ),  # Pakt de eerste 30 tekens als titel
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
