# Biizy — BI easy · lokální Streamlit POC

Lokální demonstrace propojených CRM a ERP dat. Data zůstávají v lokálních CSV a v paměťovém DuckDB:

- při prvním spuštění vytvoří deterministická fiktivní data do `data/`;
- při nastaveném `OPENAI_API_KEY` model vytváří SQL nad popsaným schématem, takže není omezený na pevný seznam analytických záměrů;
- aplikace povolí jen jeden příkaz `SELECT`, omezuje výsledek na 500 řádků a DuckDB má vypnutý přístup k externím souborům a sítím;
- Analytický chat ukazuje výsledek i skutečně vykonané SQL; při nejednoznačné otázce může model požádat o upřesnění;
- bez API klíče zůstává k dispozici omezený lokální parser pro několik běžných dotazů;
- v návaznosti lze výsledek upřesnit (například `Jen pro Enterprise, top 3`) a ze stejného kontextu vytvořit vizualizaci;
- dashboard ukládá vytvořené vizualizace, umožňuje jejich řazení a export do PDF.

## Ukázka aplikace

### Analytický chat

![Analytický chat](<screenshots/Snímek obrazovky 2026-11-03 174944.png>)

### Dashboard

![Dashboard](<screenshots/Snímek obrazovky 2026-11-03 175014.png>)

## Instalace a spuštění

```powershell
cd "C:\Users\marti\PROJEKTY\STREAMLIT TEST"
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Otevřete adresu, kterou Streamlit vypíše (obvykle `http://localhost:8501`).

## Rozhraní

- Vaše zprávy mají světle růžové pozadí, odpovědi AI světle zelené; avatary používají stejný odstín jako zpráva.
- Návod a úvodní tipy jsou pod ikonou „i“ vedle nadpisu chatu. Zobrazí se při najetí myší, zaměření klávesnicí nebo klepnutí.
- Dotaz odešlete klávesou Enter nebo tlačítkem „Zobrazit odpověď“. Pro graf použijte tlačítko „Vytvořit graf“.
- Vlevo klikněte na tlačítko **Dashboardy**, které má stejný vzhled jako **Analytický chat**. Zobrazí se existující dashboardy a volba **Vytvořit nový**. Teprve po této volbě zadejte název a klikněte na **Uložit**. Každý nový dashboard začíná stránkou **Přehled**.
- V analytickém chatu lze tlačítkem **Uložit chat** uložit celou konverzaci. V levém panelu ji otevřete v rozbalovací sekci **Uložené chaty**; název se vytvoří z prvního dotazu a po otevření jej lze upravit. Opakované uložení otevřeného uloženého chatu aktualizuje jeho obsah.
- Rozhraní používá písmo **Plus Jakarta Sans** načítané z Google Fonts. Sytě růžová zvýrazňuje hlavní akce, aktivní záložku, vybraný dashboard a detaily filtrů; zelená zůstává základní barvou navigace.
- Vybraný dashboard je v levém menu zvýrazněný stejným sytě růžovým pozadím jako vybrané hodnoty filtrů (například Praha). Jeho stránky jsou nahoře v hlavní části jako vodorovné záložky s růžově označenou aktivní stránkou. Vedle záložek otevřete tlačítkem **+ Nová stránka** formulář pro přidání stránky; nová stránka se rovnou aktivuje. Stránky, filtry a karty patří vždy pouze danému dashboardu.
- Rozhraní používá stavové záložky Streamlitu; vyžaduje Streamlit 1.66.1 nebo novější.
- Tabulkový výsledek i vytvořený graf lze tlačítkem **Přidat do dashboardu** uložit ve vyskakovacím dialogu: nejprve vyberte dashboard, potom stránku. Název vizuálu se předvyplní návrhem a lze jej upravit; nový dashboard dostane stránku **Přehled**.
- Ukládání v `storage/dashboard.json` používá verzi 3 se seznamem dashboardů. Starší seznam karet nebo stránek se při načtení převede do jednoho dashboardu **Můj dashboard** se zachováním všech stránek, karet, filtrů a jejich ID.
- Grafy na dashboardu využívají celou šířku karty, ovládací tlačítka jsou pod výsledkem.
- Filtry dashboardu se podle dostupné šířky skládají do dvou sloupců nebo pod sebe, aby byly čitelné vybrané hodnoty i celé období.
- Filtry období, segmentu a města se aplikují na zdrojové faktury a příležitosti před agregací, stejně pro karty i PDF. SQL parser zachovává aliasy a podporuje také poddotazy a větve `UNION ALL`; původní SQL uložených karet se nemění.
- Tlačítka na úzkých obrazovkách zalamují text místo jeho ořezávání; ovládání má viditelné zvýraznění při navigaci klávesnicí.
- Výchozí světlé téma a barvy nativních ovládacích prvků sjednocuje `.streamlit/config.toml`.

## Příklady promptů

### Analytický chat

- `How many overdue invoices do we have?`
- `Show overdue invoices for Enterprise.`
- `What is the total overdue amount?`
- `Show revenue by product for Enterprise.`
- `Show pipeline by stage.`
- `How many companies are in each city?`
- `Which sales stages have the highest average opportunity value?`

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

Otázka, krátký konverzační kontext a popis schématu se odešlou OpenAI. Model vrátí pouze SQL nebo žádost o upřesnění; výsledná data se modelu zpět neposílají. Aplikace před vykonáním ověří, že SQL obsahuje právě jeden příkaz `SELECT`, a vynutí limit výsledku. Data se načtou do paměti DuckDB a externí přístup DuckDB je vypnutý. CSV zdroje tak nejsou dostupné pro zápis přes SQL. Bez API klíče se použije pouze omezený lokální fallback.

U demo faktur mají stavy přesné hodnoty `Paid` a `Overdue`. Dotaz na faktury po splatnosti musí filtrovat stav `Overdue`; samotné datum splatnosti nestačí, protože i již zaplacená faktura může mít datum splatnosti v minulosti. Aplikace zároveň opraví velikost písmen u přímého porovnání `payment_status` s těmito známými hodnotami.

Toto je ochrana pro lokální POC, ne bezpečnostní hranice pro produkční data. Přidání nového zdroje nebo SQL enginu musí zachovat oprávnění pouze pro čtení i na úrovni samotného zdroje.

## Stručný návrh napojení na Fabric Lakehouse

1. Připojit backend aplikace k read-only **SQL analytics endpointu** příslušného Lakehouse.
2. Použít aplikační identitu Microsoft Entra s přístupem pouze ke schváleným analytickým pohledům/tabulkám; nedávat jí roli workspace s možností úprav.
3. Modelu předávat schéma a generovat T-SQL pro Fabric, nikoli DuckDB SQL. SQL kontrolovat parserem pro T-SQL, povolit pouze jeden `SELECT` nad povolenými objekty a nastavit timeout i limit výsledků.
4. Přihlašovací údaje zůstanou pouze v backendu. Model dostane otázku a schéma, nikoli databázové připojení. Výsledky se mu neposílají zpět, pokud pro to nebude samostatně schválené nakládání s daty.

Lakehouse SQL analytics endpoint poskytuje read-only SQL rozhraní nad daty Lakehouse. Více informací: [SQL analytics endpoint pro Lakehouse](https://learn.microsoft.com/en-us/fabric/data-engineering/lakehouse-sql-analytics-endpoint).