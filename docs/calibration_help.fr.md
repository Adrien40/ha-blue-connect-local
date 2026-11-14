[![English](https://img.shields.io/badge/Language-English-red)](calibration_help.md) [![Français](https://img.shields.io/badge/Langue-Fran%C3%A7ais-blue)](#)
[← Retour au README](../README.fr.md)

# 🎛️ Blue Connect Local - Guide de Calibration

Ce document explique comment configurer et affiner la calibration de votre sonde Blue Connect directement depuis l'interface de Home Assistant. 💡

---

## 1. ⚙️ Calibrer le pH

Dans la fenêtre de Configuration (icône engrenage ⚙️ > *🧪 Calibration des Sondes*), il y a deux façons de calibrer le pH. Les deux utilisent les mêmes solutions tampon (pH 4 et pH 7). Chaque méthode a ses propres champs, y compris le **pH cible** de chaque solution : tout ce dont vous avez besoin est au même endroit. Les valeurs courantes des solutions tampon de piscine sont **pH 4,00** et **pH 7,02** (à environ 20 °C) : vérifiez votre flacon et saisissez sa valeur exacte.

### ⚡ Méthode A : en mV (recommandée, nécessite un code d'accès)

Avec un code d'accès, l'intégration lit elle-même le potentiel de l'électrode et peut afficher le pH avec **2 décimales** (pH haute résolution). La calibrer en mV est la façon la plus précise.

1. Activez le capteur de diagnostic **pH Brut (mV)**, **désactivé par défaut** : *Paramètres > Appareils et services > Blue Connect Local*, ouvrez l'entité désactivée et activez-la avec **Activer**.
2. Plongez la sonde dans la solution tampon **pH 7**. Lancez une **Nouvelle Analyse** (bouton) et notez les mV une fois la valeur stable (faites une seconde analyse pour en être sûr).
3. Faites de même dans la solution tampon **pH 4**.
4. Dans *Options > 🧪 Calibration des Sondes* : saisissez les **mV mesurés** pour chaque solution tampon et, à côté, le **pH cible** de la solution (par exemple `7,02` et `4,00`). Les deux champs mV sont vides par défaut : renseignez les deux, ou laissez les deux vides pour continuer à utiliser la calibration enregistrée dans la sonde.

Trois règles sont vérifiées à la validation : les deux valeurs en mV sont renseignées (ou aucune), elles doivent être différentes, et la solution tampon pH 4 doit donner des mV **plus élevés** que la solution pH 7 (typiquement autour de +177 mV pour pH 4 et 0 mV pour pH 7).

Dès que les deux valeurs en mV sont renseignées, cette calibration est utilisée à la place de celle enregistrée dans la sonde, pour le pH haute résolution uniquement. Le pH standard (résolution 0,1) et la sonde elle-même ne sont pas modifiés.

> 💡 Pour voir ce que la sonde contient actuellement, activez le capteur de diagnostic **Calibration pH du Blue Connect** (désactivé par défaut). Il affiche les deux points, par exemple `pH 7.0 = 2.8 mV · pH 4.0 = 178.2 mV`, et les quatre nombres en attributs. Les registres de la sonde sont de toute façon lus à chaque analyse pour le pH haute résolution ; avec votre propre calibration en mV, ils ne sont lus que tant que ce capteur est activé.

#### 📤 Envoyer votre calibration au Blue Connect (facultatif)

Cochez **Envoyer les calibrations au Blue Connect** (à la fin des champs de calibration, commune avec l'ORP) et validez : à la prochaine analyse, vos deux points sont écrits dans les propres registres de la sonde, comme le ferait l'assistant de calibration de l'application officielle. Il faut un code d'accès et les deux valeurs en mV renseignées ; la date de calibration affichée par le capteur **Dernière calibration du pH** est aussi mise à jour (si la sonde l'accepte, sinon un avertissement apparaît dans les journaux) ; la case n'est jamais enregistrée (elle s'affiche toujours décochée) et n'existe pas pour le Blue Connect Plus. Le pH n'est écrit que s'il a changé depuis le dernier envoi réussi (voir la section ORP ci-dessous).

> ⚠️ Cela change aussi le pH standard de la sonde, les seuils d'alerte enregistrés dans la sonde et ce qu'affiche l'application officielle. Ne l'envoyez qu'avec des valeurs auxquelles vous faites confiance, puis vérifiez le résultat avec le capteur **Calibration pH du Blue Connect**.

### 🔢 Méthode B : par valeur de pH (sans code d'accès)

Sans code d'accès, il n'y a pas de potentiel d'électrode à lire. Ouvrez la section repliée **Calibration par valeur de pH (sans code d'accès)** :

* **Valeur pH 7 mesurée** (ex : `7.10`) : ce qu'affiche le capteur **pH calibré sonde** une fois stabilisé dans la solution tampon pH 7.
* **Valeur pH 4 mesurée** (ex : `4.10`) : de même pour la solution tampon pH 4.

À côté de chacune, saisissez le **pH cible** de la solution (par exemple `7,02` et `4,00`). Cette calibration s'applique par-dessus la calibration interne de la sonde : si celle-ci change, le pH affiché change aussi.

> ℹ️ **Pourquoi seulement 0,1 de résolution ?** Sans code d'accès, l'intégration ne reçoit que le pH que le Blue Connect a calculé lui-même et diffuse, déjà arrondi à 0,1. Le potentiel de l'électrode (mV), qui permet d'avoir 2 décimales, n'est lisible que par la connexion authentifiée, donc avec le code d'accès. La calibration par valeur corrige cette valeur (décalage et pente), mais ne peut pas redonner les décimales supprimées avant l'envoi.

> ⚠️ Les deux points (pH 4 et pH 7) doivent être suffisamment éloignés, et la valeur pH 4 ne doit pas dépasser la valeur pH 7. Sinon le formulaire la refuse (et une calibration dégénérée est ignorée plutôt que d'afficher une valeur faussée).

### 🔋 Et l'ORP (Redox) ?

L'ORP (potentiel d'oxydoréduction, ou Redox) se calibre sur le principe du pH en mV, avec **un seul point** (un décalage, sans pente). Il faut un code d'accès : l'intégration ne connaît le potentiel brut de l'électrode que par la connexion authentifiée.

1. Activez le capteur de diagnostic **ORP Brut (mV)** (désactivé par défaut).
2. Plongez la sonde dans une **solution étalon** (ex : une solution à 468 mV, voir son flacon), lancez une **Nouvelle Analyse** et notez les mV une fois la valeur stable.
3. Dans *Options > 🧪 Calibration des Sondes*, saisissez cette valeur dans **ORP (Redox) : mV mesurés dans la solution étalon** et le potentiel de la solution dans **ORP (Redox) : solution étalon**. Les deux, ou aucun : **les deux champs sont vides par défaut**.

La correction appliquée au potentiel brut est *référence − mesure*. Une fois les deux champs renseignés, elle est prioritaire sur celle de la sonde ; videz-les pour revenir à celle de la sonde. Le capteur **ORP** a un attribut `calibration_source` (`integration` ou `probe`) qui indique laquelle est utilisée.

> 💡 Pour voir ce que contient la sonde, activez **Calibration ORP du Blue Connect** : son état est la calibration enregistrée dans la sonde : les mV de la solution étalon, puis les mV lus par l'électrode dans cette solution (ex : `ORP 468 mV = 472 mV`), avec `reference`, `measured`, `correction` (référence moins mesure, ex : `-4`) et `status_code` en attributs. Le capteur **Dernière calibration de l'ORP** affiche sa date. Le code de statut est affiché tel que lu : sa signification n'est pas documentée.

> ⚠️ **ORP Brut** remplace l'ancien *Redox Brut* des versions précédentes, qui était en réalité l'ORP déjà corrigé par la sonde : cette valeur est désormais **ORP calibré sonde** (votre entité garde son historique). Votre ancienne calibration ORP s'ajoutait à cette valeur déjà corrigée et les champs étaient préremplis à 650/650 : ils sont **vidés à la mise à jour**, et sont à ressaisir si vous en avez besoin.

#### 📤 Envoyer les calibrations au Blue Connect

La case unique **Envoyer les calibrations au Blue Connect** envoie ce qui est renseigné : le pH (les deux valeurs en mV) et/ou l'ORP (les deux valeurs). Elle écrit les deux registres ORP et la date de calibration ORP, et **uniquement ce qui a changé depuis le dernier envoi réussi** : si vous n'avez changé que l'ORP, les registres pH (et la date de calibration pH) ne sont pas touchés, et inversement. Si un envoi échoue, rien n'est retenu comme envoyé : cochez à nouveau la case pour réessayer.

> ⚠️ Comme pour le pH, cela change l'ORP calculé par la sonde elle-même, ce qu'affiche l'application officielle et ses seuils internes. Vérifiez le résultat avec **Calibration ORP du Blue Connect**.

#### 🚨 Avertissement de calibration anormale

Un **avertissement** apparaît dans *Paramètres > Réparations* (jamais bloquant) quand la calibration utilisée semble anormale :
* **ORP** : plus de **100 mV** entre la référence et la valeur mesurée. Une électrode en bon état est à quelques dizaines de mV : un écart plus grand signifie en général que la sonde n'était pas dans la solution étalon (par exemple dans l'eau de la piscine), que la solution est erronée, ou que l'électrode est encrassée ou usée.
* **pH** : pente de l'électrode hors de **50-63 mV/pH** (59,16 en théorie à 25 °C), ou offset à pH 7 au-delà de **±60 mV**.

Ces limites sont des repères génériques pour les électrodes, pas une spécification Blue Connect. L'avertissement disparaît tout seul quand les valeurs redeviennent normales, et vous pouvez l'ignorer depuis la page Réparations.

---

## 2. 🌡️ Pourquoi la "Cible" diffère de la valeur nominale

La chimie de l'eau est sensible à la température ☀️. Le pH d'une solution tampon varie légèrement selon sa température au moment où vous y trempez la sonde 💧.
* 📦 Regardez au dos de votre flacon de solution tampon (par exemple, pour le pH 7.00).
* 📊 Vous y trouverez un tableau donnant la valeur exacte selon la température du liquide.
* 🎯 **Exemple :** à 20 °C, une solution pH 7 vaut en réalité **7.02** — c'est cette valeur précise qu'il faut saisir dans les champs **Cible de la solution**, pas la valeur nominale imprimée sur l'étiquette.

C'est cette rigueur qui explique un léger écart entre Home Assistant et l'application officielle : le signe que la mesure est en réalité plus proche de l'état réel de votre bassin. 🔬

---

## 3. 🚨 Configurer les seuils d'alerte

L'intégration crée automatiquement des capteurs binaires de statut (pH, ORP, Température). Vous pouvez définir vos propres limites dans la configuration :
* ⚖️ **pH Min / Max :** (Défaut : 6.90 - 7.40)
* 🛡️ **ORP Min / Max :** (Défaut : 650 - 750 mV)
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
