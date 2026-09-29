import base64
import json
import os
import re
import requests
from apify_client import ApifyClient

# Haal alle geheimen op uit de GitHub environment variables
APIFY_TOKEN = os.getenv("APIFY_TOKEN")
WP_USER = os.getenv("WP_USER")
WP_PASS = os.getenv("WP_PASS")
FB_COOKIES_RAW = os.getenv("FB_COOKIES")
FB_PROXY_URL = os.getenv("FB_PROXY_URL")

# WordPress configuratie
WP_URL_POSTS = "https://www.stichtingenpassant.nl/wp-json/wp/v2/posts"

# Bekende pinned/welkomst-post(s) die je nooit wilt plaatsen (vul aan indien nodig)
IGNORED_POST_IDS = {
    "24144350838513621",  # "Welkom op de Facebookpagina..." pinned post
}

IGNORED_TEXT_SNIPPETS = {
    "Iedereen kan zien wie lid is van deze groep",
    "Wie kan deze groep zien",
    "Zichtbaarheid",
    # voeg hier gerust meer vaste Facebook-zinnetjes aan toe als je ze tegenkomt
}

# Namen van groepsbeheerders wiens posts wél geplaatst mogen worden.
# Vul dit aan met de exacte Facebook-weergavenamen van je beheerders.
ADMIN_NAMES = {
    "Han Nicolaas",
    "Evert Roeleveld",
    "Gerard Milord",
    "Raymond Liem",
    "Maciej Guliński",
    "Norbert Harmanus",
    # "Naam Van Andere Beheerder",
}


def is_valid_post(item, seen_texts):
  """Filtert rommelposts eruit: lege tekst, ontbrekende timestamp,
  onleesbare tracking-data, groepsinfo-items, duplicaten binnen deze
  run, en posts van niet-beheerders."""
  post_id = item.get("postId", "")
  text = item.get("text", "").strip()
  timestamp = item.get("timestamp", "").strip()
  author = item.get("authorName", "").strip()
  post_url = item.get("url") or item.get("postUrl", "")

  if post_id in IGNORED_POST_IDS:
    return False, "staat op de negeerlijst (pinned/welkomstpost)"

  # Een echte post heeft altijd /posts/<id>/ in de URL. Groepsinfo-,
  # about- of privacyblokken hebben dat niet en zijn dus geen echte post.
  if "/posts/" not in post_url:
    return False, "geen echte post-URL (waarschijnlijk groepsinfo/about-blok)"

  if not timestamp:
    return False, "geen geldige timestamp"

  if not text or text == "Geen tekst":
    return False, "lege tekst"

  # Herken base64-achtige tracking-strings: lang, geen spaties.
  looks_like_base64 = bool(re.fullmatch(r"[A-Za-z0-9+/=]{20,}", text))
  if looks_like_base64:
    return False, "tekst lijkt op onleesbare tracking-data (base64)"

  # Extra vangnet: bekende vaste Facebook-teksten die geen echte post zijn.
  lowered = text.lower()
  for snippet in IGNORED_TEXT_SNIPPETS:
    if snippet.lower() in lowered:
      return False, "tekst bevat een bekende Facebook-standaardtekst (geen echte post)"

  if author not in ADMIN_NAMES:
    return False, f"auteur '{author or '(onbekend)'}' staat niet op de beheerderslijst"

  if text in seen_texts:
    return False, "duplicaat van een andere post in deze run"

  return True, ""


# Bouw handmatig de Base64 authenticatie-header op (dit omzeilt server-stripping)
credentials = f"{WP_USER}:{WP_PASS}"
encoded_credentials = base64.b64encode(credentials.encode("utf-8")).decode(
    "utf-8"
)
wp_headers = {
    "Authorization": f"Basic {encoded_credentials}",
    "Content-Type": "application/json",
}

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
      headers=wp_headers,
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

# --- STAP 2: Haal data op van Apify ---
print("Bezig met ophalen van Facebook-posts via Apify...")
apify_client = ApifyClient(APIFY_TOKEN)

run_input = {
    "startUrls": [{"url": "https://www.facebook.com/groups/schaakhuis"}],
    "maxPosts": 5,
    "proxyUrl": FB_PROXY_URL,
}

if cookies_input:
  run_input["cookies"] = cookies_input
  print("Facebook cookies succesvol geladen voor de scraper.")
else:
  print("Let op: Geen FB_COOKIES gevonden, kans op blokkade door Facebook is groot.")

run = apify_client.actor("whoareyouanas/facebook-group-scraper").call(
    run_input=run_input
)

# --- STAP 3: Loop door de posts, filter rommel/niet-admins/duplicaten eruit ---
new_posts_count = 0
skipped_count = 0
seen_texts = set()

for item in apify_client.dataset(run["defaultDatasetId"]).iterate_items():
  valid, reason = is_valid_post(item, seen_texts)
  if not valid:
    print(f"Overgeslagen (reden: {reason}): {item.get('postUrl', '#')}")
    skipped_count += 1
    continue

  post_text = item.get("text", "Geen tekst")
  post_url = item.get("url") or item.get("postUrl", "#")
  seen_texts.add(post_text.strip())

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

  response = requests.post(WP_URL_POSTS, json=payload, headers=wp_headers)

  if response.status_code == 201:
    print(f"Succesvol geplaatst: {post_url}")
    new_posts_count += 1
  else:
    print(f"Fout bij plaatsen ({response.status_code}): {response.text}")

print(
    f"Klaar! {new_posts_count} nieuwe berichten toegevoegd, "
    f"{skipped_count} overgeslagen als rommel/niet-beheerder/duplicaat."
)
