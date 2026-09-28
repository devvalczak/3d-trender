# 3D Trender

Lokalna aplikacja webowa do przygotowania sprzedaży wydruków 3D.

## Asystent: jeden lejek zamiast skakania po zakładkach

Zakładka **Asystent** (domyślna) przeprowadza produkty przez cztery etapy jednym kliknięciem:

1. **Trendy**: ocena obserwowanych fraz (popyt, konkurencja, sezon, marża). Top N przechodzi dalej. Frazy z wysokim ryzykiem IP są pomijane.
2. **Modele**: ile modeli jest dostępnych i ile nadaje się do sprzedaży, najlepsi kandydaci. Z Thingiverse aplikacja pobiera plik i czyta wymiary, wagę i czas. Dla innych serwisów bierze typowe wymiary frazy albo plik wgrany ręcznie.
3. **Stół**: ile sztuk mieści się na płycie (obrys prostokątny, obrót 0°/90°, odstęp i margines, strefy wykluczenia X1C/P1S) z podglądem układu.
4. **Zysk**: druk w AMS (płukanie i czas zmian koloru dzielone na sztuki na płycie) porównany z drukiem jednokolorowym i malowaniem, plus **optymalny harmonogram doby**. Optymalizator dobiera, ile płyt i po ile sztuk drukować w godzinach obsługi i czy dodać jedną dłuższą płytę na noc.

Na końcu: **plan produkcji** na N dni (z limitem realnego zbytu), **szkic aukcji** (tytuł ≤ 75 znaków, cena, opis z atrybucją autora) i **porównanie z poprzednim przebiegiem**.

Na każdym etapie możesz wykluczyć pozycję, wybrać innego kandydata, poprawić wymiary, wagę, czas, kolory lub cenę albo wgrać własny `.3mf`. Przeliczają się wtedy tylko etapy 3-4, bez ponownego odpytywania serwisów. Pocięty projekt z Bambu Studio z kilkoma obiektami na płycie jest przeliczany na jedną sztukę.

Pozostałe zakładki służą do ręcznego sprawdzania:

- **Okazje**: co warto teraz drukować, posortowane od najbardziej opłacalnych, z oceną *Dobre / Bardzo dobre / Najlepsze* i listą powodów.
- **Modele 3D**: wyszukiwarkę modeli z filtrem „tylko do sprzedaży”, kosztem licencji komercyjnej i wyliczonym zyskiem dla każdego modelu.
- **Konkurencję**: oferty i ceny z Allegro, OLX, Etsy i eBay (mediana, kwartyle, sprzedaż).
- **Kalkulator**: filament, prąd, amortyzację drukarki, serwis, nieudane wydruki, pracę, opakowanie, licencję i prowizję. Wagę i czas czyta z pociętego **.3mf z Bambu Studio**, z **G-code** albo szacuje z **STL**.
- **Trendy i sezony**: Google Trends, rosnące frazy do obserwowania i kalendarz okazji (Halloween, Święta, Dzień Matki…).

## Uruchomienie w Dockerze (macOS, Windows, Linux)

Wymagany jest [Docker Desktop](https://www.docker.com/products/docker-desktop/) (macOS/Windows) albo Docker Engine z wtyczką Compose (Linux). Obraz działa na procesorach Intel/AMD i Apple Silicon.

```bash
git clone -b claude/3d-print-prep-automation-6o5g6z https://github.com/devvalczak/3d-trender
cd 3d-trender
docker compose up -d --build
```

Otwórz http://localhost:8000. Bez pliku `.env` aplikacja startuje w trybie DEMO.

| Co | Jak |
|---|---|
| Klucze API | skopiuj `.env.example` do `.env` (Windows: `copy .env.example .env`), uzupełnij i uruchom `docker compose up -d` |
| Logi | `docker compose logs -f` |
| Zatrzymanie | `docker compose down` (dane zostają) |
| Aktualizacja | `git pull` i `docker compose up -d --build` |
| Inny port | `TRENDER_PORT=9000` w `.env` |
| Dostęp z telefonu w sieci domowej | `TRENDER_BIND=0.0.0.0` w `.env`, potem `http://<IP komputera>:8000` |
| Google Trends bez SerpApi | `WITH_PYTRENDS=true` w `.env` i `docker compose up -d --build` |
| Kopia bazy | `docker compose cp trender:/app/data/trender.db ./trender-backup.db` |
| Usunięcie wszystkiego z danymi | `docker compose down -v` |

Baza SQLite leży w wolumenie Dockera `trender-data`, więc przetrwa restart i przebudowę obrazu. Aplikacja w kontenerze działa jako zwykły użytkownik (nie root). Domyślnie jest dostępna tylko z tego komputera.

## Uruchomienie bez Dockera

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .                 # opcjonalnie: pip install -e ".[pytrends]"
cp .env.example .env             # uzupełnij klucze API
3d-trender                       # albo: python -m trender.main
```

Otwórz http://127.0.0.1:8000 i kliknij **Skanuj**. Dane zapisują się w `data/trender.db`. Skan powtarza się automatycznie co `REFRESH_INTERVAL_HOURS` i z każdym dniem buduje historię rynku (liczba ofert, mediana, sprzedaż).

Bez kluczy aplikacja działa w **trybie DEMO**: pokazuje przykładowe, wyraźnie oznaczone dane, żeby dało się przetestować cały przepływ.

## Źródła danych i klucze

| Źródło | Do czego | Klucz |
|---|---|---|
| Allegro REST API | oferty, ceny, sprzedaż 30 dni | [apps.developer.allegro.pl](https://apps.developer.allegro.pl/): `client_credentials`. **Endpoint `/offers/listing` wymaga zweryfikowania aplikacji przez Allegro.** |
| OLX | oferty i ceny | bez klucza (publiczny endpoint strony, nieoficjalny) |
| eBay Browse API | oferty, ceny (domyślnie eBay.de) | [developer.ebay.com](https://developer.ebay.com/my/keys) |
| Etsy Open API v3 | oferty, ceny, ulubione | [etsy.com/developers](https://www.etsy.com/developers/your-apps) (keystring + shared secret) |
| Google Trends | trend wyszukiwań, rosnące frazy | [SerpApi](https://serpapi.com/) (stabilne) lub pytrends (bez klucza, często limitowane) |
| Thingiverse | modele + licencje | App Token |
| Cults3D | modele, ceny plików, licencje | nazwa użytkownika + klucz API |
| MyMiniFactory | modele | klucz API |
| Printables | modele + licencje | bez klucza (nieoficjalne GraphQL) |
| NBP | kursy EUR/USD → PLN | bez klucza |

MakerWorld, Thangs, Amazon i Vinted nie mają publicznego API, więc aplikacja pokazuje dla nich tylko linki do wyszukiwania.

> Integracje napisano według dokumentacji API i przetestowano na zamockowanych odpowiedziach. Nieoficjalne źródła (OLX, Printables) mogą przestać działać po zmianie strony. Błąd jednego źródła nie blokuje pozostałych i widać go w interfejsie.

## Jak liczona jest opłacalność

Wynik 0-100 to średnia ważona (wagi zmienisz w Ustawieniach):

- **Marża (35%)**: zysk na godzinę pracy drukarki przy medianie cen w głównym kanale (domyślnie Allegro). Czas drukarki to wąskie gardło, więc liczy się zysk/h, a nie tylko zysk/szt.
- **Popyt (30%)**: sprzedaż konkurencji z 30 dni, momentum Google Trends (ostatnie 4 tygodnie vs 12 poprzednich), ulubione na Etsy.
- **Konkurencja (20%)**: liczba ofert (skala logarytmiczna).
- **Sezon (15%)**: czy trwa okno sprzedaży okazji, do której pasuje produkt.

Kary: ryzyko naruszenia IP (np. Pokémon, Disney, Labubu) mnoży wynik przez 0.3. Ujemny zysk ogranicza wynik do 30.

Dla modeli 3D: 45% zysk/h, 25% popularność, 30% „czystość” licencji (CC0/CC-BY najwyżej, NC najniżej). Koszt płatnego pliku lub licencji rozkładany jest na `expected_units_per_model` sztuk.

**Klasyfikacja licencji to heurystyka, nie porada prawna.** Przed sprzedażą sprawdź licencję na stronie modelu.

## Testy

```bash
pip install -e ".[dev]" && pytest
```
