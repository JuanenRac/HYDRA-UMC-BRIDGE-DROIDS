<!-- =============================================================================
HYDRA-UMC-BRIDGE-DROIDS - Ponte di coordinamento bidirezionale per droidi con gambe/umanoidi
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

<p align="center">
  <img src="images/HYDRA_UMC_BANNER.svg" alt="Banner HYDRA-UMC-BRIDGE-DROIDS" width="100%">
</p>

# 🤖 HYDRA-UMC-BRIDGE-DROIDS

<p align="center"><a href="README.md">🇺🇸 English</a> | <a href="README_spa.md">🇪🇸 Español</a> | <a href="README_fra.md">🇫🇷 Français</a> | 🇮🇹 <b>Italiano</b> | <a href="README_deu.md">🇩🇪 Deutsch</a> | <a href="README_zho.md">🇨🇳 简体中文</a> | <a href="README_jpn.md">🇯🇵 日本語</a></p>

### 🔗 Confine di coordinamento privo di dipendenze tra HYDRA-UMC e i droidi con gambe/umanoidi

<p align="left">
  <img src="https://img.shields.io/badge/Licencia-GPL%203.0-blue.svg" alt="GPL 3.0">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB.svg" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/Safety-Fails%20Closed-red.svg" alt="Fails Closed">
</p>

---

## 1. 🛠️ PANORAMICA TECNICA

**HYDRA-UMC-BRIDGE-DROIDS** è il confine di coordinamento bidirezionale e di alto livello tra HYDRA-UMC e una piattaforma droide con gambe o umanoide, raggiungibile via Wi-Fi, Bluetooth o un collegamento cellulare (4G/5G). Non calcola mai l'andatura, l'equilibrio o le traiettorie articolari: valida e inoltra un vocabolario ridotto e con nome di trigger di azione a corpo intero (`WALK_TO`, `PICK_OBJECT`, `PLACE_OBJECT`, `RETURN_HOME`, `HOLD_POSITION`), ciascuno con il proprio contratto reale di parametri obbligatori. Non è un nodo di controllo motore e non può aggirare HYDRA-UMC-SERVER, i limiti dell'MCU, i watchdog o l'E-STOP.

Appartiene alla famiglia **Mobile & Autonomous Bridges** insieme a `HYDRA-UMC-BRIDGE-AMR` e `HYDRA-UMC-BRIDGE-UAV`, e condivide lo stesso contratto di lavoro e sicurezza `HYDRA-UMC-SDK` degli **External Automation Bridges** stazionari (CNC, LASER, OPENPNP, PRINTER3D, ROS2) - così nessun ponte, mobile o stazionario, inventa una propria definizione di "sicuro per lavorare".

### Caratteristiche principali:
* ✅ **Nucleo di coordinamento privo di dipendenze, reale:** `DroidCoordinator` in `coordinator.py` non ha alcun import di trasporto (né socket, né SDK del produttore) - è deliberatamente Python semplice, testabile su qualsiasi host senza un droide reale collegato. *(implementato, testato in `tests/test_coordinator.py`)*
* ✅ **Vocabolario reale di trigger di azione con nome:** `WALK_TO`, `PICK_OBJECT`, `PLACE_OBJECT`, `RETURN_HOME`, `HOLD_POSITION` - mai un comando articolare grezzo. L'andatura a corpo intero, l'equilibrio e il controllo a livello articolare restano autorità propria del computer di bordo del droide (di classe Jetson o equivalente). *(implementato)*
* ✅ **Validazione reale dei parametri per azione:** ogni trigger di azione ha il proprio contratto reale e minimo di parametri obbligatori (ad es. `WALK_TO` richiede `x`/`y`) verificato prima che un lavoro venga mai inoltrato - una richiesta a cui manca ciò che la propria azione richiede viene rifiutata localmente, non passata silenziosamente a valle. *(implementato, testato)*
* ✅ **Porta di sicurezza condivisa, reale:** ogni lavoro inviato tramite `DroidCoordinator.dispatch()` viene valutato da `evaluate_job()` del `bridge_contract` di `HYDRA-UMC-SDK`, la stessa porta usata da tutti i ponti fratelli e da HYDRA-UMC-SERVER; una fase produttiva richiede una macchina esterna `IDLE` e una cella HYDRA-UMC `READY`, mentre `HOLD_POSITION` (mappato da `ABORT`) resta richiedibile durante un guasto. *(implementato)*
* ✅ **Instradamento delle fasi chiuso ed evidenza statica:** una futura fase SDK sconosciuta viene negata anziché ipotizzata. `inspect_action_plan.py` emette il piano d'azione statico di schema `1.0` senza aprire alcun trasporto. *(implementato, testato)*
* ✅ **Trasporto Boston Dynamics Spot reale:** `SpotDroidControl` di `spot_transport.py` invia un dispatch già validato come un vero comando bosdyn-client (`synchro_stand_command`/`synchro_sit_command`/`synchro_trajectory_command_in_body_frame`, inviato tramite `RobotCommandClient.robot_command()`) - un dispatch rifiutato non raggiunge mai la rete. *(implementato, testato in `tests/test_spot_transport.py`)*
* ✅ **Build/test non mutante:** `build-test.bat`/`.sh` compilano il codice sorgente ed eseguono test unitari deterministici senza cambiare versione o CHANGELOG. *(implementato, vedi COMPILAZIONE ED ESECUZIONE più sotto)*
* 🔜 **Adattatore Wi-Fi/BT/4G-5G specifico per una piattaforma di droide non Spot** - introdotto solo dopo che quella piattaforma sarà selezionata e testata. *(pianificato)*

---

## 2. 🔄 FLUSSO DI COORDINAMENTO DEL DROIDE

```mermaid
flowchart LR
    DROID["Droide con gambe / umanoide<br/>(Wi-Fi / BT / 4G-5G)"] -- "trigger di azione" --> BRIDGE["BRIDGE-DROIDS<br/>DroidCoordinator.dispatch()"]
    BRIDGE -- BridgeJob --> SDK["HYDRA-UMC-SDK<br/>evaluate_job()"]
    SDK -- GateDecision --> SERVER["HYDRA-UMC-SERVER"]
    SERVER -- "lavoro / abort" --> MCU["Sicurezza MCU"]
```

---

## 3. 🧱 ARCHITETTURA E DECISIONI DI PROGETTAZIONE

* **Perché il nucleo non calcola mai l'andatura o l'equilibrio.** Il computer di bordo del droide (di classe Jetson o equivalente) esegue già un controller reale a corpo intero specifico per l'hardware - ricalcolarlo qui lo duplicherebbe male o entrerebbe in conflitto con esso. Inviare solo trigger di destinazione/azione con nome (`WALK_TO x y`, `PICK_OBJECT object_id`) mantiene il ruolo di HYDRA-UMC limitato al coordinamento, in linea con la nota di architettura incollata da cui è partito questo progetto: "non calcolare l'andatura del droide nel nucleo."
* **Perché ogni trigger di azione ha il proprio elenco esplicito di parametri obbligatori.** Un `WALK_TO` senza `x`/`y`, o un `PICK_OBJECT` senza `object_id`, è un errore reale e rilevabile nella forma della richiesta - rifiutarlo qui, prima di qualsiasi trasporto, è rigorosamente meglio che inoltrare un'istruzione incompleta sperando che anche il firmware del droide la rifiuti in modo sicuro.
* **Perché `DroidCoordinator.dispatch()` incanala comunque ogni lavoro attraverso la porta condivisa `evaluate_job()`.** Un droide è semplicemente un altro client dello stesso `bridge_contract` usato da CNC, LASER, OPENPNP, PRINTER3D e ROS2 - non ottiene alcun bypass speciale della logica IDLE/READY applicata da tutti gli altri ponti e da HYDRA-UMC-SERVER.
* **Perché `HOLD_POSITION` (da `ABORT`) resta richiedibile durante un guasto.** Il requisito di fase produttiva della porta (`IDLE` + `READY`) non viene deliberatamente applicato allo stesso modo a una richiesta di abort - un operatore deve sempre poter chiedere a un droide di bloccarsi sul posto, anche in pieno guasto, invece di continuare qualunque cosa stesse facendo.
* **Perché l'adattatore di trasporto e un'interfaccia di comandi concreta non sono ancora in questo repository.** Vincolarsi al protocollo di comandi reale Wi-Fi/BT/4G-5G di una specifica piattaforma droide prima che sia selezionata e testata rischierebbe di incorporare ipotesi che questo nucleo locale privo di dipendenze non può verificare.
* **Come si inserisce nel resto dell'ecosistema.** BRIDGE-DROIDS si trova tra un droide reale e `HYDRA-UMC-SDK` → `HYDRA-UMC-SERVER` → sicurezza MCU - è un confine di coordinamento, mai un nodo di controllo motore, e non può aggirare HYDRA-UMC-SERVER, i limiti dell'MCU, i watchdog o l'E-STOP.

---

## 📂 STRUTTURA DELLE DIRECTORY

```text
HYDRA-UMC-BRIDGE-DROIDS/
├── src/
│   └── hydra_umc_bridge_droids/
│       ├── __init__.py
│       └── coordinator.py       # DroidCoordinator: porta di trigger di azione priva di dipendenze
├── tests/
│   └── test_coordinator.py      # Test unitari deterministici del nucleo di coordinamento
├── tools/
│   ├── build_test.py            # Compilatore + esecutore di test non mutante (build-test.bat/.sh)
│   ├── bump_version.py          # Sincronizza pyproject.toml, manifesto e CHANGELOG.md
│   └── inspect_action_plan.py   # Stampa il piano d'azione statico (nessun trasporto aperto)
├── docs/
│   └── BRIDGE_GUIDE.md          # Ambito, piattaforme compatibili, script, porta di accettazione hardware
├── build-test.bat / build-test.sh  # Solo valida, non modifica mai il repository
├── build.bat / build.sh            # Valida e, solo in caso di successo, aggiorna versione + CHANGELOG
├── pyproject.toml               # Metadati del pacchetto; dipende da HYDRA-UMC-SDK (git)
├── hydra-umc.project.json       # Manifesto dell'ecosistema (versione, maturità, famiglia)
├── CHANGELOG.md
├── CODE_OF_CONDUCT.md / CONTRIBUTING.md / SECURITY.md / SUPPORT.md
├── LICENSE / LICENSE.md
└── README.md / README_*.md      # Questo file e le sue 6 traduzioni
```

---

## 4. ⚙️ COMPILAZIONE ED ESECUZIONE

Richiede Python 3.11+. `tools/build_test.py` si aspetta che `HYDRA-UMC-SDK` sia clonato come directory fratella (`../HYDRA-UMC-SDK`) o indicato tramite la variabile d'ambiente `HYDRA_UMC_SDK_ROOT`.

```bash
# Windows
build-test.bat      # solo validazione — nessun cambio di versione/CHANGELOG
build.bat            # valida e, se ha successo, aggiorna versione + CHANGELOG

# Linux/macOS
bash build-test.sh
bash build.sh
```

`build-test` compila ogni modulo sotto `src/` con `py_compile` ed esegue l'intera suite `unittest` (`tests/test_coordinator.py`) - in modo deterministico, senza connessione reale a un droide, senza rete e senza cambio di versione/CHANGELOG. `build` esegue prima quella stessa validazione e, solo in caso di successo, chiama `tools/bump_version.py` per sincronizzare la versione tra `pyproject.toml`, `hydra-umc.project.json` e `CHANGELOG.md`. Non esiste ancora un comando `run` con hardware reale - serve un adattatore di trasporto validato e una piattaforma droide reale.

---

## ✅ Stato attuale e prossimi passi

**Reale oggi:** versione `0.0.1`, funzionale come nucleo di coordinamento privo di dipendenze (`DroidCoordinator`) con validazione reale dei parametri per azione, instradamento delle fasi chiuso, uno schema di azione statico `plan-only`, e script build-test non mutanti collegati alla CI con un checkout dell'SDK.

**Confine di integrazione:** questo ponte è solo un confine di coordinamento - non è un nodo di controllo motore, e non può aggirare HYDRA-UMC-SERVER, i limiti dell'MCU, i watchdog o l'E-STOP; ogni lavoro inviato passa comunque attraverso la stessa porta condivisa usata da tutti i ponti fratelli.

**Ancora da fare:** nessun trasporto reale (Wi-Fi/BT/4G-5G) né un droide fisico è ancora stato validato - un adattatore di trasporto reale e un'interfaccia di comandi per droidi documentata saranno introdotti solo dopo che una piattaforma specifica sarà selezionata e testata.

---

## 🔗 Progetti correlati

Questo progetto fa parte di un ecosistema robotico più ampio dello stesso autore (JuanenRac / Electro Hobby 3D), che copre firmware, software di controllo, nodi IA e strumenti di flotta. Vale la pena saperlo, perché una richiesta potrebbe in realtà riguardare uno di questi progetti anziché questo repository.

### Direttamente correlati

- **[HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK)** — il contratto condiviso di lavoro e sicurezza attraverso cui ogni ponte (incluso questo) valuta i propri lavori.
- **[HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER)** — il confine autenticato dell'ecosistema a cui questo ponte riporta.
- **[HYDRA-UMC-BRIDGE-AMR](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-AMR)** — ponte mobile fratello per flotte AGV/AMR.
- **[HYDRA-UMC-BRIDGE-UAV](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-UAV)** — ponte mobile fratello per droni.

### Resto dell'ecosistema

**Piattaforma HYDRA-UMC** — la micro-fabbrica multi-robot per cui questo ponte coordina gli ausiliari
- **[HYDRA-UMC](https://github.com/JuanenRac/HYDRA-UMC)** — la scheda madre CM5 + STM32H745 che orchestra fino a 8 bracci robotici.
- **[HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER)** — il backend Express/WebSocket con cui parlano tutti i client di controllo e i ponti.
- **[HYDRA-UMC-STUDIO](https://github.com/JuanenRac/HYDRA-UMC-STUDIO)** — dashboard di controllo web, visualizzazione 3D multi-robot.

**External Automation Bridges** — repository fratelli che condividono questa stessa porta di lavoro `HYDRA-UMC-SDK`
- **[HYDRA-UMC-BRIDGE-CNC](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-CNC)** — ponte di coordinamento cella CNC.
- **[HYDRA-UMC-BRIDGE-LASER](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-LASER)** — ponte di coordinamento celle laser.
- **[HYDRA-UMC-BRIDGE-OPENPNP](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-OPENPNP)** — ponte di flusso schede per OpenPnP.
- **[HYDRA-UMC-BRIDGE-PRINTER3D](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-PRINTER3D)** — ponte di coordinamento per software di stampa 3D open.
- **[HYDRA-UMC-BRIDGE-ROS2](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-ROS2)** — ponte di coordinamento generico per qualsiasi piattaforma ROS 2.

**Evidenze di sicurezza e integrazione**
- **[HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES)** — evidenze di sicurezza delle zone di cella usate in tutta la famiglia di ponti.
- **[HYDRA-UMC-HIL-BRIDGE](https://github.com/JuanenRac/HYDRA-UMC-HIL-BRIDGE)** — evidenze di test hardware-in-the-loop.

## 👤 AUTORE
**JuanenRac** (Electro Hobby 3D)
📧 electrohobby3d@gmail.com
📺 [youtube.com/@electrohobby3d](https://youtube.com/@electrohobby3d)

## 📜 LICENZA
GPL-3.0 - Vedi LICENSE per i dettagli.
