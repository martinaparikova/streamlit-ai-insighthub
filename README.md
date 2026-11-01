# Insight Hub — lokální Streamlit POC

Lokální demonstrace propojených CRM a ERP dat. Data zůstávají lokálně v CSV a DuckDB; je-li nastavený `OPENAI_API_KEY`, chat používá LLM jen pro výběr bezpečného analytického plánu:

- při prvním spuštění vytvoří deterministická fiktivní data do `data/`;
- DuckDB nad CSV soubory skutečně vykonává SQL dotazy;
- Analytický chat rozumí přirozeným anglickým dotazům, ukazuje odpověď, tabulku nebo graf a skutečně vykonané SQL;
- v návaznosti lze výsledek upřesnit (například `Jen pro Enterprise, top 3`) a ze stejného kontextu vytvořit vizualizaci;
- dashboard ukládá vytvořené vizualizace, umožňuje jejich řazení a export do PDF.

## Instalace a spuštění

```powershell
cd "C:\Users\marti\PROJEKTY\STREAMLIT TEST"
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Otevřete adresu, kterou Streamlit vypíše (obvykle `http://localhost:8501`).

## Příklady promptů

### Analytický chat

- `How many overdue invoices do we have?`
- `Show overdue invoices for Enterprise.`
- `What is the total overdue amount?`
- `Show revenue by product for Enterprise.`
- `Show pipeline by stage.`

### Vytvořit vizual

- Nejprve se zeptejte na data nebo výsledek upřesněte. Poté napište například:
  `Udělej růžový graf, maximum modře, Roboto větší a nahoru.`
- Klikněte na **Vytvořit vizual**. Aplikace použije aktuální kontext i SQL předchozí otázky.

## LLM režim a bezpečnost

Nainstalujte závislosti a nastavte API key pouze jako proměnnou prostředí (nikdy ne do zdrojového kódu):

```powershell
python -m pip install -r requirements.txt
setx OPENAI_API_KEY "your-api-key"
```

Po `setx` restartujte terminál nebo VS Code. Volitelně lze nastavit `OPENAI_MODEL`; výchozí model je `gpt-4.1-mini`.

LLM negeneruje SQL, které by aplikace přímo vykonala. Vrací pouze whitelisted intent, segment, město a limit. Aplikace tyto hodnoty validuje a sestaví read-only SQL sama. Pokud API není dostupné, zůstane použitelný původní pravidlový parser jako fallback.