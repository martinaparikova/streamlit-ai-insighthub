# Semantický model a ontologie – plán realizace

Tento dokument eviduje plán rozvoje semantického modelu v aplikaci Biizy a skutečně dokončené části.

## Cíl

Rozšířit analytický chat o odpovědi nad business znalostmi a definicemi, ne jen o generování SQL. Semantický model je editovatelný zdroj pravdy pro tabulky, vztahy, metriky, termíny a business pravidla.

## Etapa 1 – Semantický model pro vestavěná demo data

**Stav: dokončeno v této implementaci.**

- [x] Perzistentní semantický model ve workspace.
- [x] Výchozí demo katalog pro `companies`, `invoices` a `opportunities`.
- [x] Schválené vztahy přes `company_id`.
- [x] Editovatelné metriky: Revenue, objem po splatnosti, počet faktur po splatnosti a hodnota pipeline.
- [x] Editovatelný slovník pojmů a business pravidla.
- [x] Obrazovka **Semantický model** s přehledem a formuláři pro úpravu/vytvoření položek.
- [x] Analytický chat odpovídá bez SQL na otázky k tabulkám, vztahům, metrikám, pojmům a pravidlu overdue.
- [x] Placeholder/preview budoucího AI draftu.
- [x] Migrace starších workspace dokumentů na verzi 5 bez ztráty dashboardů a chatů.

Limity etapy 1:

- model používá vestavěná demo data;
- AI draft ještě neanalyzuje nový externě připojený zdroj;
- editace je formulářová, bez drag-and-drop ER diagramu;
- znalostní chat používá bezpečný deterministický router, nikoliv volné generování definic modelem.

## Etapa 2 – AI draft a AI editor

**Stav: plánováno.**

- [ ] Tlačítko **Vytvořit AI draft** nad aktivním zdrojem metadat.
- [ ] Návrh entit, tabulek, kandidátních vztahů, metrik, synonym a prázdných šablon popisů.
- [ ] U každého návrhu confidence a evidence (např. shoda klíčů / datových typů).
- [ ] AI editor s instrukcemi typu „vytvoř metriku“, „přejmenuj entitu“ nebo „přidej vztah“.
- [ ] Strukturovaný diff, explicitní potvrzení a zahazování návrhu.
- [ ] Historie změn, undo a status `draft` / `approved`.

## Etapa 3 – Připojení vlastních zdrojů a semantické SQL

**Stav: plánováno.**

- [ ] Připojovací wizard pro read-only zdroje (nejdříve Fabric SQL endpoint / SQL databáze).
- [ ] Bezpečné uložení credentials mimo zdrojový kód.
- [ ] Introspekce schématu, klíčů a základního profilu dat.
- [ ] Obnovení metadat a zobrazení dopadu změn ve zdroji.
- [ ] SQL generované pouze přes schválené metriky, vztahy, povolené entity a dimenze.
- [ ] Validace SQL, limitů, timeoutů a oprávnění zůstává povinná.

## Etapa 4 – Governance a produkční provoz

**Stav: plánováno.**

- [ ] Role viewer/editor/reviewer/owner.
- [ ] Schvalovací workflow, vlastník metriky a auditní historie.
- [ ] Verze metrik a možnost porovnání/obnovení verzí.
- [ ] Dokumenty, procesy, FAQ a vazby na entity/metriky.
- [ ] Export/import modelu (JSON/YAML) a API.
- [ ] Multi-workspace/multi-tenant izolace.

## Principy implementace

1. AI nikdy bez potvrzení uživatele nemění schválený model.
2. Neznámé business definice se nevymýšlejí: AI si vyžádá upřesnění nebo vytvoří označený draft.
3. Externí zdroje budou vždy připojené read-only identitou s omezením na schválené objekty.
4. Odpověď chatu uvádí, zda čerpá z modelu nebo z vykonaného SQL dotazu.
5. Business význam (ontologie) a vykonatelná analytická pravidla (semantický model) jsou uložené společně, ale mají samostatné typy objektů.