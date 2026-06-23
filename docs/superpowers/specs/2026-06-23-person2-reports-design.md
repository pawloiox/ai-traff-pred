# Osoba 2: Raporty (PDF), Powody i Powiadomienia - Design Spec

## Cel

Celem jest rozbudowa systemu raportowania i powiadomień zgodnie z planem podziału pracy dla Osoby 2. Moduł ma dostarczyć raporty opóźnień w formacie PDF, wzbogacić opisy przyczyn o nowe dane oraz przygotować fundament pod system powiadomień Push, unikając konfliktów z pracą Osoby 1 i 3.

## 1. Raporty Opóźnień (PDF)

*   **Narzędzie:** Biblioteka `fpdf2` (nie wymaga binarnych zależności systemowych, jest czysto pythonowa).
*   **Struktura:**
    *   Nagłówek: Nazwa portu, Punkt, Data wygenerowania.
    *   Sekcja Analityczna: Poziom ryzyka, obecna kongestia (np. 80%), trend.
    *   Sekcja Przyczyny i Rekomendacji: Opis sytuacji wygenerowany przez LLM (lub fallback).
*   **Architektura:**
    *   Nowy plik: `backend/services/reports/pdf_generator.py`.
    *   Nowy endpoint API (np. `GET /api/reports/{point_id}/pdf`) rejestrowany w `app/main.py`.

## 2. Rozbudowa przyczyny (cause) o nowe dane

*   **Zasada kontraktu:** Osoba 3 odpowiedzialna za dane pogodowe i czasowe dostarczy je w słowniku sytuacji (klucze `weather` i `temporal`), z którego my skorzystamy.
*   **Zmiany w `app/reports.py`:**
    *   Rozszerzenie funkcji `_cause_text()` (fallback) o obsługę złej pogody (np. ulewa) i specyfiki czasu (np. godziny szczytu).
    *   Rozszerzenie funkcji `_situation_signature()`, aby odświeżała cache narracji gdy zmieni się pogoda.
*   **Zmiany w `app/groq_client.py`:**
    *   Wzbogacenie promptu wysyłanego do LLM, tak aby wplatał on w generowane komunikaty kontekst pogodowy i czasowy.

## 3. Szkielet systemu powiadomień (Push Notifications)

*   **Zasada:** Wdrażamy architekturę backendową (Mock/Szkielet). Prawdziwa integracja z Firebase Admin SDK nastąpi w etapie 11.
*   **Baza Danych (`app/storage.py`):**
    *   Dodanie tabeli `push_subscriptions` (przechowującej tokeny FCM powiązane z portem/rolą użytkownika).
*   **Endpointy:**
    *   Dodanie `POST /api/notifications/subscribe` (do zapisywania tokenów).
*   **Serwis Powiadomień (`backend/services/notifications/push.py`):**
    *   Utworzenie funkcji mockującej wysyłkę.
    *   Wpięcie funkcji wyzwalającej "wysyłkę" do cyklu generowania raportów w `app/reports.py` (tylko dla sytuacji poziomu `critical`).

## 4. Ograniczenia i Unikanie Konfliktów

*   Nie modyfikujemy plików frontendu przypisanych do Osoby 1 (`src/features/...`).
*   Nie modyfikujemy głównej pętli analizy i silnika punktacji (`app/analysis.py`), co należy do Osoby 3.
*   Ewentualne modyfikacje w współdzielonych plikach (`app/storage.py`, `app/main.py`) będą minimalne i dobrze wyizolowane.
