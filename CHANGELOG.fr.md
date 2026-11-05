# Blue Connect Local - Journal des modifications

## 1.3.1

🐬🐬🐬🐬🐬🐬🐬🐬🐬🐬

### 🐛 Corrections
- **Blue Connect Plus : une clé d'accès de 8 caractères est désormais acceptée** ([#6](https://github.com/Adrien40/ha-blue-connect-local/issues/6)). La version 1.3.0 exigeait exactement 9 caractères. Sur un Plus, la clé est la *Clé d'accès* affichée dans l'application Blueriiot.

### ✨ Améliorations
- Longueur du code d'accès contrôlée selon la famille de sonde : 9 caractères pour ZODIAC, 8 ou 9 pour Blueriiot (Blue Connect Plus), l'une ou l'autre quand la famille est inconnue. S'applique aux formulaires d'installation, de ré-authentification, de reconfiguration et d'options.
- Aides de formulaire et messages d'erreur plus courts et plus précis, dans toutes les langues prises en charge.

### 📚 Documentation
- Nouvelle page d'**exemple de dashboard** ([EN](docs/dashboard_example.md) / [FR](docs/dashboard_example.fr.md)) : le YAML du dashboard présenté dans le README.

### 🧰 Maintenance
- Tests : 565 (514 auparavant), couverture de 100 %, exécutés sur Home Assistant 2026.10.2 avec Python 3.14.

### 🙏 Remerciements
- Merci à [@tomvleminckx-cmd](https://github.com/tomvleminckx-cmd) pour son rapport ([#6](https://github.com/Adrien40/ha-blue-connect-local/issues/6)) et ses tests sur son Blue Connect Plus.

🐬🐬🐬🐬🐬🐬🐬🐬🐬🐬

## 1.3.0

🐬🐬🐬🐬🐬🐬🐬🐬🐬🐬

### ✨ Nouveautés
- **Support Blueriiot (Blue Connect Plus)** : le profil est détecté à chaque connexion et la sonde est décodée comme une ZODIAC (température, pH, Redox, conductivité, salinité, batterie). Mode Actif uniquement (code d'accès requis).
- **Découverte Automatique** des sondes Blueriiot dont le nom Bluetooth commence par `B20`, affichées comme *Blue Connect Plus* de Blueriiot.
- **Versions matérielle et logicielle** dans la fiche de l'appareil, et **4 nouveaux capteurs de diagnostic** désactivés par défaut (ZODIAC) : *Numéro de série de la sonde*, *Première connexion*, *Date de remplacement de la sonde* et *Dernière calibration du pH*.
- Traductions dans toutes les langues prises en charge.

### 🛡️ Sécurité pour les ZODIAC
- Les sondes ZODIAC gardent la même séquence Bluetooth qu'en 1.2.0 jusqu'à la mesure. Ensuite, jusqu'à 7 lectures de diagnostic sont ajoutées (2 à chaque analyse, les autres une seule fois) : la connexion dure donc un peu plus longtemps. Les capteurs propres aux ZODIAC sont *indisponibles* sur les sondes Blueriiot.

### 🐛 Corrections
- Le capteur *Batterie ADC* n'affiche plus `0` après le recalcul des valeurs dérivées.

### ⚠️ Limites connues
- Je n'ai pas pu valider le support Blueriiot sur du vrai matériel (testé par un contributeur sur un Blue Connect Plus, firmware 2.3.0). Pas de numéro de série, de SKU ni d'état du flotteur, et un code d'accès erroné se termine par un délai d'attente dépassé.
- Derrière un **proxy Bluetooth ESPHome**, les nouveaux capteurs de diagnostic restent *inconnus* tant que le proxy n'est pas réglé (`CONFIG_BT_GATTC_MAX_CACHE_CHAR: "200"` et `cache_services: false`) : voir le README.

### 🧰 Maintenance
- Les diagnostics masquent aussi le numéro de série de la sonde, comme celui de l'appareil.
- Typage : `mypy --strict` repasse avec Home Assistant 2026.10 (formulaires désormais typés avec `probatio`), sans changement de comportement.
- La table GATT reçue de la sonde est loggée en debug. Tests ajoutés pour Blueriiot et pour les lectures de diagnostic.

### 🙏 Remerciements
- Merci à [@vinzgithub](https://github.com/vinzgithub), contributeur, pour sa pull request [#5](https://github.com/Adrien40/ha-blue-connect-local/pull/5) (pistes sur le protocole Blueriiot) et pour ses tests sur son Blue Connect Plus.

🐬🐬🐬🐬🐬🐬🐬🐬🐬🐬

## 1.2.0

🐬🐬🐬🐬🐬🐬🐬🐬🐬🐬

Cette version est entièrement consacrée à la robustesse : les problèmes de tentatives Bluetooth, de déchargement et de ré-authentification sont corrigés, un capteur de diagnostic **Redox Brut** rejoint le pH brut, et la suite de tests passe de 40 à ~400 tests.

### 🚨 Changements majeurs
- **Home Assistant 2026.3.0 ou plus récent** (`hacs.json`), première version livrée avec Python 3.14. Les tests passent sur 2026.3.0 et 2026.9.4.

### ✨ Nouveautés
- Capteur de diagnostic **Redox Brut** (mV), à côté du pH brut existant : la valeur de la sonde
  *avant* tout décalage, pour calibrer sur une solution étalon.

### 🧂 À propos du chlore
- Pas d'estimation du chlore, volontairement : l'ORP est un pouvoir oxydant, pas une concentration, donc une valeur de chlore qui en serait dérivée paraîtrait précise mais serait fausse. L'entité **CyA** et le **type de traitement** sont conservés, mais aucune valeur calculée n'en dépend pour l'instant.

### 🐛 Corrections
- **La ré-authentification et la reconfiguration ignoraient le nouveau code d'accès** : les options (prioritaires) et une copie dans le stockage local gardaient l'ancien, donc la notification de réparation revenait. Le nouveau code est désormais utilisé, n'est plus enregistré dans le stockage local, et la ré-authentification valide son format (9 caractères alphanumériques).
- Les entités **Intervalle d'Analyse** et **CyA (Stabilisant)** continuaient d'afficher leur ancienne valeur après une modification dans **Configurer**, alors que la nouvelle valeur était déjà utilisée ; elles suivent maintenant la valeur réellement utilisée.
- Des trames BLE invalides étaient relancées indéfiniment : le compteur de tentatives était remis à zéro avant le décodage, donc l'état « injoignable » n'était jamais atteint.
- Arrêt du coordinateur : `async_shutdown` appelle maintenant l'implémentation parente et est idempotent, et le minuteur de la première analyse (2 s après le démarrage) est annulé au déchargement.
- `validate_calibration` ne plante plus sur une valeur non numérique (ORP, décalage, CyA ou intervalle).
- Une calibration pH dégénérée (points trop proches) ne renvoie plus silencieusement une valeur fausse : le pH retombe sur le pH brut avec un avertissement journalisé.
- Un appareil vu uniquement par un scanner qui ne peut pas s'y connecter (`connectable=False`) n'est plus considéré comme absent.
- Le bouton **Nouvelle Analyse** gère proprement toute erreur inattendue au lieu de laisser une trace non gérée dans la tâche d'arrière-plan.
- Les notifications abandonnées (file pleine) sont maintenant journalisées au niveau debug.
- Les événements de signal BLE perdu / retrouvé sont journalisés une seule fois par transition, au niveau info (auparavant non journalisés), pour qu'une coupure soit visible dans le journal sans être répétée à chaque tentative.

### 🛡️ Renforcement
- Les **diagnostics** masquent maintenant aussi le numéro de série, le Cloud ID et le titre de l'entrée (construit à partir du nom BLE, qui peut contenir une partie de l'adresse MAC) : le fichier téléchargé peut être joint sans risque à une issue publique. Le SKU reste visible pour le support. Les options affichées sont maintenant les valeurs réellement utilisées (une valeur modifiée depuis une entité n'y figurait pas).
- Un pH calculé hors de 0–14 devient *inconnu* au lieu d'être affiché.
- L'indice de Langelier et le pH d'équilibre refusent NaN et l'infini.

### 🧰 Maintenance
- Descriptions de champs (`data_description`) ajoutées aux formulaires de ré-authentification, de reconfiguration, d'installation et d'options (adresse MAC, calibration, synchronisation, traitement, CyA), dans les 19 langues.
- Le coordinateur reçoit son `config_entry` explicitement ; les pauses BLE sont des constantes nommées ; une fonction de compatibilité remplace `device_registry.async_get_device` (obsolète), pour fonctionner sur 2026.3.0 comme sur 2026.9.4.
- Suite de tests passée de 40 à ~400 tests, avec 100 % de couverture : Bluetooth simulé, coordinateur, config/options flow, chaîne de migration 1.1 → 1.4, entités, cohérence des traductions, tests par propriétés.
- CI : workflow pytest + couverture (Python 3.14, 95 % minimum), `mypy --strict` dans son propre workflow *Typing*, configuration explicite de ruff / pytest dans `pyproject.toml`, `requirements_test.txt`.
- Style (ruff) et syntaxe Python 3.14 : `TimeoutError`, `except A, B:`.
- Le manifest déclare l'échelle de qualité `platinum`, avec des tests qui la gardent cohérente.

### 📚 Documentation
- `README.md` / `README.fr.md` : version minimale de Home Assistant, Redox brut, nouvelle section *Analyses planifiées*, entités manquantes dans le tableau, et badges de licence / CI / échelle de qualité.
- `calibration_help.md` / `calibration_help.fr.md` : vraie version anglaise du guide, liens entre les langues et lien depuis le README.

🐬🐬🐬🐬🐬🐬🐬🐬🐬🐬

## 1.1.1

🐬🐬🐬🐬🐬🐬🐬🐬🐬🐬

### ✨ Nouveautés
- **Détection instantanée d'un code d'accès invalide** : l'état d'authentification est lu directement sur la sonde, donc *Code d'accès invalide* est signalé en quelques secondes au lieu d'attendre le délai d'environ 2×60 s (avec une relecture de confirmation à 0,5 s pour éviter les faux positifs sur les proxys BLE à forte latence). Nouvel état `auth_failed` sur le capteur État Bluetooth.
- **Blue Connect Silver** : les entités Conductivité/Salinité sont désactivées automatiquement (une seule fois) dès que le modèle Silver est détecté, au lieu de rester actives avec la valeur *Inconnu*.
- Détection du modèle dès la découverte Bluetooth : la conductivité détectée pendant la découverte est conservée, donc les entités Conductivité/Salinité ont le bon état activé par défaut dès leur création.

### 🐛 Corrections
- Modifier un code d'accès existant dans le menu Options (par exemple pour corriger une faute de frappe) déclenche maintenant une analyse immédiate ; avant, seul le passage d'un champ vide à un code le faisait.
- L'ancien `hw_version` est explicitement supprimé du registre des appareils lors de la mise à jour depuis la 1.1.0, ce qui retire la ligne redondante « Hardware: WA000100 » de la page de l'appareil.

### 🧰 Maintenance
- Registre des appareils : le SKU est maintenant exposé comme `model_id` (*ID du modèle*) au lieu de `hw_version` ; le capteur de diagnostic `sw_version`, qui rapportait l'ID Cloud de l'appareil et non une version de firmware, est renommé `cloud_id` (une migration du registre conserve l'historique des entités).
- Les entités orphelines *Numéro de série* / *Modèle (SKU)* (déjà intégrées à l'en-tête de l'appareil en 1.1.0) sont nettoyées du registre des entités (migration de l'entrée 2 → 4).
- Chaînes anglaises harmonisées au singulier (*Automatic Analysis*, *Analysis paused*).
- Suppression de 3 constantes inutilisées et d'un import inutile.

### 🙏 Remerciements
- Merci à @alexdelprete pour son aide, ses suggestions et ses tests.

🐬🐬🐬🐬🐬🐬🐬🐬🐬🐬

## 1.1.0

🐬🐬🐬🐬🐬🐬🐬🐬🐬🐬

### ✨ Nouveautés
- Détection automatique du modèle (Blue Connect **Gold** ou **Silver**) : en mode actif via le SKU matériel et en mode entièrement passif en analysant la trame BLE. Le modèle détecté s'affiche dès l'écran de configuration, à la découverte Bluetooth.
- Les entités Conductivité et Salinité sont désactivées par défaut sur Blue Connect Silver.
- Informations enrichies dans l'en-tête de l'appareil : modèle détecté, numéro de modèle (SKU), numéro de série et adresse MAC Bluetooth.

### 🐛 Corrections
- Le numéro de série et le SKU restaurés depuis le stockage local sont injectés dès la création des entités, sans attendre la première lecture BLE.
- Le marqueur matériel `0xFFFF` est maintenant pris en compte au décodage des trames, ce qui supprime les valeurs de salinité erronées sur les appareils sans sonde de conductivité.

### 🧰 Maintenance
- Extraction centralisée de la trame BLE brute (`extract_raw_payload`), suppression des capteurs redondants *Modèle (SKU)* et *Numéro de série* et du code mort, et renforcement des tests unitaires.

### 📋 Notes de mise à jour
- Après la mise à jour depuis la 1.0.3, les anciens capteurs *Modèle (SKU)* et *Numéro de série* apparaissent comme indisponibles : ouvrez l'entité > icône engrenage > **Supprimer** (la 1.1.1 les nettoie automatiquement).
- Blue Connect Silver : une entité Conductivité déjà active reste visible avec la valeur *Inconnu* ; désactivez-la ou masquez-la dans **Paramètres** > **Appareils et services** > **Entités** (la 1.1.1 le fait automatiquement).

🐬🐬🐬🐬🐬🐬🐬🐬🐬🐬

## 1.0.3

🐬🐬🐬🐬🐬🐬🐬🐬🐬🐬

### ✨ Nouveautés
- Détection automatique du **Blue Connect Silver**, à partir du préfixe de nom BLE `BC3-QX25001952`.

🐬🐬🐬🐬🐬🐬🐬🐬🐬🐬

## 1.0.2

🐬🐬🐬🐬🐬🐬🐬🐬🐬🐬

### 🐛 Corrections
- Correctif : le numéro de version de `manifest.json` avait été oublié en 1.0.1 ; HACS et Home Assistant affichent maintenant la bonne version. Aucun autre changement de code.

🐬🐬🐬🐬🐬🐬🐬🐬🐬🐬

## 1.0.1

🐬🐬🐬🐬🐬🐬🐬🐬🐬🐬

### 🧰 Maintenance
- Version « sous le capot », sans nouveauté visible.
- Refactorisation de l'architecture : la logique pure est extraite du coordinateur vers des modules dédiés (`protocol.py`, `model.py`, `validation.py`).
- Ajout d'une suite pytest sans dépendance à Home Assistant : chimie de l'eau (LSI, pH d'équilibre), décodage des trames BLE (18 et 19 octets) et validation du config flow.
- CI : un workflow GitHub Actions (`tests.yaml`) lance les tests à chaque modification.
- Suppression du code mort (conditions inatteignables) dans la validation de calibration.

🐬🐬🐬🐬🐬🐬🐬🐬🐬🐬

## 1.0.0

🐬🐬🐬🐬🐬🐬🐬🐬🐬🐬

### ✨ Nouveautés
- Première version stable.

🐬🐬🐬🐬🐬🐬🐬🐬🐬🐬
