[![English](https://img.shields.io/badge/Language-English-red)](calibration_help.md) [![Français](https://img.shields.io/badge/Langue-Fran%C3%A7ais-blue)](#)
[← Retour au README](README.fr.md)

# 🎛️ Blue Connect Local - Guide de Calibration

Ce document explique comment configurer et affiner la calibration de votre sonde Blue Connect directement depuis l'interface de Home Assistant. 💡

---

## 1. ⚙️ Comprendre la calibration pH (haute précision)

Contrairement à l'application officielle, qui utilise des valeurs de référence fixes (pH 7.00 / 4.00), **Blue Connect Local** vous permet de saisir la valeur exacte de vos solutions tampon. Dans la fenêtre de Configuration (icône de la roue crantée ⚙️), quatre champs sont disponibles :

* **Valeur pH 7 mesurée** (`ph_calib_7`, ex : `7.10`) : ce que votre sonde a réellement mesuré une fois plongée et stabilisée dans la solution tampon pH 7.
* **Cible de la solution pH 7** (`ph_ref_7`, ex : `7.02`) : la valeur exacte de votre solution tampon.
* **Valeur pH 4 mesurée** (`ph_calib_4`, ex : `4.10`) et **Cible de la solution pH 4** (`ph_ref_4`, ex : `4.00`) : idem pour le second point de calibration.

L'intégration expose une entité diagnostic **`sensor.*_raw_ph`** qui affiche le pH brut remonté par la sonde, avant toute correction : c'est cette valeur qu'il faut relever, stabilisée, pendant que la sonde trempe dans chaque solution tampon.

> ⚠️ Les deux points (pH 4 et pH 7) doivent être suffisamment distincts. Si les valeurs mesurées sont trop proches l'une de l'autre, la calibration est jugée dégénérée : l'intégration l'ignore et retombe sur le pH brut non calibré plutôt que d'afficher une valeur faussée.

### 🔋 Et le Redox (ORP) ?
Le principe est identique. L'entité diagnostic **`sensor.*_raw_orp`** affiche la valeur brute de la sonde Redox, avant tout décalage. Plongez le Blue Connect dans une solution étalon (ex : 650 mV), attendez la stabilisation, puis saisissez :
* **Valeur ORP (Redox) mesurée** (`orp_calib`, ex : `650`)
* **Cible de la solution ORP (Redox)** (`orp_ref`, ex : `650`)

L'intégration applique l'écart entre les deux à toutes les mesures suivantes.

---

## 2. 🌡️ Pourquoi la "Cible" diffère de la valeur nominale

La chimie de l'eau est sensible à la température ☀️. Le pH d'une solution tampon varie légèrement selon sa température au moment où vous y trempez la sonde 💧.
* 📦 Regardez au dos de votre flacon de solution tampon (par exemple, pour le pH 7.00).
* 📊 Vous y trouverez un tableau donnant la valeur exacte selon la température du liquide.
* 🎯 **Exemple :** à 20 °C, une solution pH 7 vaut en réalité **7.02** — c'est cette valeur précise qu'il faut saisir dans les champs **Cible de la solution**, pas la valeur nominale imprimée sur l'étiquette.

C'est cette rigueur qui explique un léger écart entre Home Assistant et l'application officielle : le signe que la mesure est en réalité plus proche de l'état réel de votre bassin. 🔬

---

## 3. 🚨 Configurer les seuils d'alerte

L'intégration crée automatiquement des capteurs binaires de statut (pH, Redox, Température). Vous pouvez définir vos propres limites dans la configuration :
* ⚖️ **pH Min / Max :** (Défaut : 6.90 - 7.40)
* 🛡️ **Redox Min / Max :** (Défaut : 650 - 750 mV)
* ❄️ **Température Min :** utile pour anticiper le risque de gel l'hiver (Défaut : 6.0 °C)
* 🥵 **Température Max :** pratique pour éviter que l'eau ne tourne si elle chauffe trop (Défaut : 32.0 °C)

Si une mesure dépasse ces seuils, le capteur binaire correspondant passe à l'état "Problème" ⚠️ — idéal pour déclencher vos automatisations (notifications 📱, mise en route de la filtration 🔄, etc.).

---

## 4. 🧪 Équilibre de l'eau (Indice de Langelier)

En renseignant TAC, TH et TDS dans les options, Home Assistant calcule en continu l'**Indice de Langelier (LSI)**, à partir de la température lue sur le Blue Connect :
* **Eau corrosive (LSI < -0.3)** : attaque joints, liner et pièces métalliques.
* **Eau équilibrée (LSI entre -0.3 et +0.3)** : eau parfaite.
* **Eau entartrante (LSI > +0.3)** : risque de dépôt de calcaire.

Aucune saisie manuelle du pH n'est nécessaire pour ce calcul : l'intégration utilise en continu le pH calibré déjà calculé.
