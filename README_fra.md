<!-- =============================================================================
HYDRA-UMC-BRIDGE-DROIDS - Pont de coordination bidirectionnel pour droïdes à pattes/humanoïdes
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

<p align="center">
  <img src="images/HYDRA_UMC_BANNER.svg" alt="Bannière HYDRA-UMC-BRIDGE-DROIDS" width="100%">
</p>

# 🤖 HYDRA-UMC-BRIDGE-DROIDS

<p align="center"><a href="README.md">🇺🇸 English</a> | <a href="README_spa.md">🇪🇸 Español</a> | 🇫🇷 <b>Français</b> | <a href="README_ita.md">🇮🇹 Italiano</a> | <a href="README_deu.md">🇩🇪 Deutsch</a> | <a href="README_zho.md">🇨🇳 简体中文</a> | <a href="README_jpn.md">🇯🇵 日本語</a></p>

### 🔗 Frontière de coordination sans dépendance entre HYDRA-UMC et les droïdes à pattes/humanoïdes

<p align="left">
  <img src="https://img.shields.io/badge/Licencia-GPL%203.0-blue.svg" alt="GPL 3.0">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB.svg" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/Safety-Fails%20Closed-red.svg" alt="Sécurité intrinsèque">
</p>

---

## 1. 🛠️ APERÇU TECHNIQUE

**HYDRA-UMC-BRIDGE-DROIDS** est la frontière de coordination bidirectionnelle et haut niveau entre HYDRA-UMC et une plateforme de droïde à pattes ou humanoïde, accessible par Wi-Fi, Bluetooth ou une liaison cellulaire (4G/5G). Elle ne calcule jamais la marche, l'équilibre ni les trajectoires articulaires : elle valide et transmet un vocabulaire réduit et nommé de déclencheurs d'action corps entier (`WALK_TO`, `PICK_OBJECT`, `PLACE_OBJECT`, `RETURN_HOME`, `HOLD_POSITION`), chacun avec son propre contrat réel de paramètres obligatoires. Ce n'est pas un nœud de contrôle moteur, et elle ne peut pas contourner HYDRA-UMC-SERVER, les limites du MCU, les watchdogs ou l'E-STOP.

Il appartient à la famille **Mobile & Autonomous Bridges**, aux côtés de `HYDRA-UMC-BRIDGE-AMR` et `HYDRA-UMC-BRIDGE-UAV`, et partage le même contrat de tâches et de sécurité `HYDRA-UMC-SDK` que les **External Automation Bridges** stationnaires (CNC, LASER, OPENPNP, PRINTER3D, ROS2) — ainsi, aucun pont, mobile ou stationnaire, n'invente sa propre définition du « sûr pour travailler ».

### Fonctionnalités clés :
* ✅ **Noyau de coordination sans dépendance, réel :** `DroidCoordinator` de `coordinator.py` n'importe aucun transport (ni socket, ni SDK constructeur) — c'est délibérément du Python pur, testable sur n'importe quel hôte sans droïde réel connecté. *(implémenté, testé dans `tests/test_coordinator.py`)*
* ✅ **Vocabulaire réel de déclencheurs d'action nommés :** `WALK_TO`, `PICK_OBJECT`, `PLACE_OBJECT`, `RETURN_HOME`, `HOLD_POSITION` — jamais une commande articulaire brute. La marche corps entier, l'équilibre et le contrôle articulaire restent l'autorité propre du contrôleur embarqué du droïde (classe Jetson ou équivalent). *(implémenté)*
* ✅ **Validation réelle des paramètres par action :** chaque déclencheur d'action a son propre contrat réel et minimal de paramètres obligatoires (par ex. `WALK_TO` nécessite `x`/`y`), vérifié avant qu'une tâche ne soit jamais transmise — une requête à laquelle il manque ce que sa propre action exige est rejetée localement, et non transmise en silence en aval. *(implémenté, testé)*
* ✅ **Portail de sécurité partagé, réel :** chaque tâche envoyée via `DroidCoordinator.dispatch()` est évaluée par `evaluate_job()` du `bridge_contract` de `HYDRA-UMC-SDK`, le même portail utilisé par tous les ponts frères et HYDRA-UMC-SERVER ; une phase productive nécessite une machine externe `IDLE` et une cellule HYDRA-UMC `READY`, tandis que `HOLD_POSITION` (mappé depuis `ABORT`) reste demandable pendant un défaut. *(implémenté)*
* ✅ **Routage de phases fermé et évidence statique :** une future phase SDK inconnue est refusée plutôt que devinée. `inspect_action_plan.py` émet le plan d'action statique de schéma `1.0` sans ouvrir aucun transport. *(implémenté, testé)*
* ✅ **Build/test non mutant :** `build-test.bat`/`.sh` compilent le code source et exécutent des tests unitaires déterministes sans changer la version ni le CHANGELOG. *(implémenté, voir COMPILATION ET EXÉCUTION ci-dessous)*
* 🔜 **Adaptateur de transport réel Wi-Fi/BT/4G-5G et une interface de commandes de droïde documentée** — introduits seulement après la sélection et le test d'une plateforme réelle. *(prévu)*

---

## 2. 🔄 FLUX DE COORDINATION DU DROÏDE

```mermaid
flowchart LR
    DROID["Droïde à pattes / humanoïde<br/>(Wi-Fi / BT / 4G-5G)"] -- "déclencheur d'action" --> BRIDGE["BRIDGE-DROIDS<br/>DroidCoordinator.dispatch()"]
    BRIDGE -- BridgeJob --> SDK["HYDRA-UMC-SDK<br/>evaluate_job()"]
    SDK -- GateDecision --> SERVER["HYDRA-UMC-SERVER"]
    SERVER -- "tâche / abandon" --> MCU["Sécurité MCU"]
```

---

## 3. 🧱 ARCHITECTURE ET CHOIX DE CONCEPTION

* **Pourquoi le noyau ne calcule jamais la marche ni l'équilibre.** Le calcul embarqué propre du droïde (classe Jetson ou équivalent) exécute déjà un contrôleur corps entier réel et spécifique au matériel — le recalculer ici le dupliquerait mal ou entrerait en conflit avec lui. N'envoyer que des déclencheurs de destination/action nommés (`WALK_TO x y`, `PICK_OBJECT object_id`) maintient le rôle de HYDRA-UMC à la coordination, conformément à la note d'architecture collée dont ce projet est parti : « ne pas calculer la marche du droïde dans le noyau ».
* **Pourquoi chaque déclencheur d'action a sa propre liste explicite de paramètres obligatoires.** Un `WALK_TO` sans `x`/`y`, ou un `PICK_OBJECT` sans `object_id`, est une véritable erreur de forme de requête, détectable — la rejeter ici, avant tout transport, est strictement préférable à transmettre une instruction incomplète en espérant que le firmware propre du droïde la rejette aussi de façon sûre.
* **Pourquoi `DroidCoordinator.dispatch()` fait quand même passer chaque tâche par le portail partagé `evaluate_job()`.** Un droïde n'est qu'un client de plus du même `bridge_contract` utilisé par CNC, LASER, OPENPNP, PRINTER3D et ROS2 — il ne bénéficie d'aucun contournement spécial de la logique IDLE/READY appliquée par tous les autres ponts et par HYDRA-UMC-SERVER.
* **Pourquoi `HOLD_POSITION` (depuis `ABORT`) reste demandable pendant un défaut.** L'exigence de phase productive du portail (`IDLE` + `READY`) n'est délibérément pas appliquée de la même manière à une demande d'abandon — un opérateur doit toujours pouvoir demander à un droïde de s'immobiliser sur place, même en plein défaut, plutôt que de continuer ce qu'il était en train de faire.
* **Pourquoi l'adaptateur de transport et une interface de commandes concrète ne sont pas encore dans ce dépôt.** S'engager sur le protocole de commandes réel Wi-Fi/BT/4G-5G d'une plateforme de droïde spécifique avant qu'elle ne soit sélectionnée et testée risquerait d'intégrer des hypothèses que ce noyau local sans dépendance ne peut pas vérifier.
* **Comment cela s'intègre dans le reste de l'écosystème.** BRIDGE-DROIDS se situe entre un droïde réel et `HYDRA-UMC-SDK` → `HYDRA-UMC-SERVER` → sécurité MCU : c'est une frontière de coordination, jamais un nœud de contrôle moteur, et elle ne peut pas contourner HYDRA-UMC-SERVER, les limites du MCU, les watchdogs ou l'E-STOP.

---

## 📂 STRUCTURE DES RÉPERTOIRES

```text
HYDRA-UMC-BRIDGE-DROIDS/
├── src/
│   └── hydra_umc_bridge_droids/
│       ├── __init__.py
│       └── coordinator.py       # DroidCoordinator : portail de déclencheurs d'action sans dépendance
├── tests/
│   └── test_coordinator.py      # Tests unitaires déterministes du noyau de coordination
├── tools/
│   ├── build_test.py            # Compilateur + lanceur de tests non mutant (build-test.bat/.sh)
│   ├── bump_version.py          # Synchronise pyproject.toml, manifeste et CHANGELOG.md
│   └── inspect_action_plan.py   # Affiche le plan d'action statique (aucun transport ouvert)
├── docs/
│   └── BRIDGE_GUIDE.md          # Portée, plateformes compatibles, scripts, portail d'acceptation matérielle
├── build-test.bat / build-test.sh  # Valide uniquement, ne modifie jamais le dépôt
├── build.bat / build.sh            # Valide puis, si succès, incrémente version + CHANGELOG
├── pyproject.toml               # Métadonnées du paquet ; dépend de HYDRA-UMC-SDK (git)
├── hydra-umc.project.json       # Manifeste de l'écosystème (version, maturité, famille)
├── CHANGELOG.md
├── CODE_OF_CONDUCT.md / CONTRIBUTING.md / SECURITY.md / SUPPORT.md
├── LICENSE / LICENSE.md
└── README.md / README_*.md      # Ce fichier et ses 6 traductions
```

---

## 4. ⚙️ COMPILATION ET EXÉCUTION

Nécessite Python 3.11+. `tools/build_test.py` attend que `HYDRA-UMC-SDK` soit cloné en tant que répertoire frère (`../HYDRA-UMC-SDK`) ou indiqué via la variable d'environnement `HYDRA_UMC_SDK_ROOT`.

```bash
# Windows
build-test.bat      # validation uniquement — pas de changement de version/CHANGELOG
build.bat            # valide puis, si succès, incrémente version + CHANGELOG

# Linux/macOS
bash build-test.sh
bash build.sh
```

`build-test` compile chaque module sous `src/` avec `py_compile` et exécute la suite complète `unittest` (`tests/test_coordinator.py`) — de manière déterministe, sans connexion réelle à un droïde, sans réseau et sans changement de version/CHANGELOG. `build` exécute d'abord cette même validation et, seulement en cas de succès, appelle `tools/bump_version.py` pour synchroniser la version dans `pyproject.toml`, `hydra-umc.project.json` et `CHANGELOG.md`. Il n'existe pas encore de commande `run` avec matériel réel — cela nécessite un adaptateur de transport validé et une plateforme de droïde réelle.

---

## ✅ État actuel et prochaines étapes

**Réel aujourd'hui :** version `0.0.1`, fonctionnel en tant que noyau de coordination sans dépendance (`DroidCoordinator`) avec validation réelle des paramètres par action, routage de phases fermé, un schéma d'action statique `plan-only`, et des scripts build-test non mutants intégrés en CI avec un checkout du SDK.

**Frontière d'intégration :** ce pont n'est qu'une frontière de coordination — ce n'est pas un nœud de contrôle moteur, et il ne peut pas contourner HYDRA-UMC-SERVER, les limites du MCU, les watchdogs ou l'E-STOP ; chaque tâche envoyée passe toujours par le même portail partagé utilisé par tous les ponts frères.

**Encore à venir :** aucun transport réel (Wi-Fi/BT/4G-5G) ni droïde physique n'a encore été validé — un adaptateur de transport réel et une interface de commandes de droïde documentée seront introduits seulement après la sélection et le test d'une plateforme spécifique.

---

## 🔗 Projets liés

Ce projet fait partie d'un écosystème robotique plus large du même auteur (JuanenRac / Electro Hobby 3D), couvrant firmware, logiciel de contrôle, nœuds d'IA et outillage de flotte. Cela vaut la peine de le savoir, car une demande pourrait en réalité concerner l'un de ces projets plutôt que ce dépôt.

### Directement liés

- **[HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK)** — le contrat partagé de tâches et de sécurité par lequel chaque pont (y compris celui-ci) évalue ses tâches.
- **[HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER)** — la frontière authentifiée de l'écosystème à laquelle ce pont rend compte.
- **[HYDRA-UMC-BRIDGE-AMR](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-AMR)** — pont mobile frère pour les flottes AGV/AMR.
- **[HYDRA-UMC-BRIDGE-UAV](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-UAV)** — pont mobile frère pour les drones.

### Reste de l'écosystème

**Plateforme HYDRA-UMC** — la micro-usine multi-robot pour laquelle ce pont coordonne les auxiliaires
- **[HYDRA-UMC](https://github.com/JuanenRac/HYDRA-UMC)** — la carte mère CM5 + STM32H745 orchestrant jusqu'à 8 bras robotiques.
- **[HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER)** — le backend Express/WebSocket auquel parlent tous les clients de contrôle et ponts.
- **[HYDRA-UMC-STUDIO](https://github.com/JuanenRac/HYDRA-UMC-STUDIO)** — tableau de bord web, visualisation 3D multi-robot.

**External Automation Bridges** — dépôts frères partageant ce même portail de tâches `HYDRA-UMC-SDK`
- **[HYDRA-UMC-BRIDGE-CNC](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-CNC)** — pont de coordination de cellule CNC.
- **[HYDRA-UMC-BRIDGE-LASER](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-LASER)** — pont de coordination de cellules laser.
- **[HYDRA-UMC-BRIDGE-OPENPNP](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-OPENPNP)** — pont de flux de cartes pour OpenPnP.
- **[HYDRA-UMC-BRIDGE-PRINTER3D](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-PRINTER3D)** — pont de coordination pour logiciels d'impression 3D ouverts.
- **[HYDRA-UMC-BRIDGE-ROS2](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-ROS2)** — pont de coordination générique pour toute plateforme ROS 2.

**Preuves de sécurité et d'intégration**
- **[HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES)** — preuves de sécurité des zones de cellule utilisées dans toute la famille de ponts.
- **[HYDRA-UMC-HIL-BRIDGE](https://github.com/JuanenRac/HYDRA-UMC-HIL-BRIDGE)** — preuves de tests hardware-in-the-loop.

## 👤 AUTEUR
**JuanenRac** (Electro Hobby 3D)
📧 electrohobby3d@gmail.com

## 📜 LICENCE
GPL-3.0 - Voir LICENSE pour les détails.
