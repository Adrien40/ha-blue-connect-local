[![Français](https://img.shields.io/badge/Langue-Fran%C3%A7ais-blue)](calibration_help.fr.md) [![English](https://img.shields.io/badge/Language-English-red)](#)
[← Back to README](README.md)

# 🎛️ Blue Connect Local - Calibration Guide

This document explains how to configure and fine-tune your Blue Connect probe calibration directly from the Home Assistant interface. 💡

---

## 1. ⚙️ Understanding pH calibration (high precision)

Unlike the official app, which uses fixed reference values (pH 7.00 / 4.00), **Blue Connect Local** lets you enter the exact value of your buffer solutions. In the Configuration window (gear icon ⚙️), four fields are available:

* **Measured pH 7 value** (`ph_calib_7`, e.g. `7.10`): what your probe actually measured once immersed and stabilized in the pH 7 buffer solution.
* **pH 7 solution target** (`ph_ref_7`, e.g. `7.02`): the exact value of your buffer solution.
* **Measured pH 4 value** (`ph_calib_4`, e.g. `4.10`) and **pH 4 solution target** (`ph_ref_4`, e.g. `4.00`): same thing for the second calibration point.

The integration exposes a diagnostic entity **`sensor.*_raw_ph`** that shows the raw pH reported by the probe, before any correction: this is the value to read, once stabilized, while the probe soaks in each buffer solution.

> ⚠️ The two points (pH 4 and pH 7) must be far enough apart. If the measured values are too close to each other, the calibration is considered degenerate: the integration ignores it and falls back to the uncalibrated raw pH rather than displaying a distorted value.

### 🔋 What about Redox (ORP)?
The principle is identical. The diagnostic entity **`sensor.*_raw_orp`** shows the raw value from the Redox probe, before any offset. Immerse the Blue Connect in a reference solution (e.g. 650 mV), wait for it to stabilize, then enter:
* **Measured ORP (Redox) value** (`orp_calib`, e.g. `650`)
* **ORP (Redox) solution target** (`orp_ref`, e.g. `650`)

The integration applies the difference between the two to all subsequent readings.

---

## 2. 🌡️ Why the "Target" differs from the nominal value

Water chemistry is sensitive to temperature ☀️. The pH of a buffer solution varies slightly with its temperature at the moment you immerse the probe 💧.
* 📦 Check the back of your buffer solution bottle (for example, for pH 7.00).
* 📊 You will find a table giving the exact value according to the liquid temperature.
* 🎯 **Example:** at 20 °C, a pH 7 solution is actually **7.02** — this is the precise value to enter in the **Solution target** fields, not the nominal value printed on the label.

This rigor explains a slight difference between Home Assistant and the official app: a sign that the measurement is actually closer to your pool's true condition. 🔬

---

## 3. 🚨 Configuring alert thresholds

The integration automatically creates binary status sensors (pH, Redox, Temperature). You can define your own limits in the configuration:
* ⚖️ **pH Min / Max:** (Default: 6.90 - 7.40)
* 🛡️ **Redox Min / Max:** (Default: 650 - 750 mV)
* ❄️ **Min Temperature:** useful to anticipate freezing risk in winter (Default: 6.0 °C)
* 🥵 **Max Temperature:** useful to prevent the water from turning if it gets too hot (Default: 32.0 °C)

If a reading exceeds these thresholds, the matching binary sensor switches to the "Problem" state ⚠️ — ideal to trigger your automations (notifications 📱, turning on filtration 🔄, etc.).

---

## 4. 🧪 Water balance (Langelier Index)

By entering TAC, TH and TDS in the options, Home Assistant continuously computes the **Langelier Saturation Index (LSI)** from the temperature read by the Blue Connect:
* **Corrosive water (LSI < -0.3)**: attacks seals, liner and metal parts.
* **Balanced water (LSI between -0.3 and +0.3)**: perfect water.
* **Scale-forming water (LSI > +0.3)**: risk of limescale deposits.

No manual pH entry is needed for this calculation: the integration continuously uses the already calibrated pH.
