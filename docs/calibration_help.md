[![Français](https://img.shields.io/badge/Langue-Fran%C3%A7ais-blue)](calibration_help.fr.md) [![English](https://img.shields.io/badge/Language-English-red)](#)
[← Back to README](../README.md)

# 🎛️ Blue Connect Local - Calibration Guide

This document explains how to configure and fine-tune your Blue Connect probe calibration directly from the Home Assistant interface. 💡

---

## 1. ⚙️ Calibrating the pH

In the Configuration window (gear icon ⚙️ > *🧪 Probes Calibration*), there are two ways to calibrate the pH. Both use the same two buffer solutions (pH 4 and pH 7). Each method has its own fields, including the **target pH** of each solution, so everything you need is in one place. Typical values for pool buffer solutions are **pH 4.00** and **pH 7.02** (at about 20 °C): check your own bottle and enter its exact value.

### ⚡ Method A: in mV (recommended, needs an access code)

With an access code, the integration reads the electrode potential itself and can show the pH with **2 decimals** (high-resolution pH). Calibrating it in mV is the most accurate way.

1. Enable the **Raw pH (mV)** diagnostic sensor, which is **disabled by default**: *Settings > Devices & services > Blue Connect Local*, open the disabled entity and toggle **Enable**.
2. Dip the probe in the **pH 7** buffer solution. Trigger a **New Analysis** (button) and note the mV once the value is stable (run a second analysis to be sure).
3. Do the same in the **pH 4** buffer solution.
4. In *Options > 🧪 Probes Calibration*: enter the **mV measured** at each buffer and, next to each, the **target pH** of the solution (e.g. `7.02` and `4.00`). The two mV fields are empty by default: fill in both, or leave both empty to keep using the calibration stored in the probe.

Three rules are checked when you validate: both mV values are given (or none), they must be different, and the pH 4 buffer must read a **higher** mV than the pH 7 one (typically around +177 mV for pH 4 and 0 mV for pH 7).

As soon as both mV values are filled in, this calibration is used instead of the one stored in the probe, for the high-resolution pH only. The standard pH (0.1 resolution) and the probe itself are not modified.

> 💡 To see what the probe currently holds, enable the **Blue Connect pH calibration** diagnostic sensor (disabled by default). It shows both points, for example `pH 7.0 = 2.8 mV · pH 4.0 = 178.2 mV`, and the four numbers as attributes. The probe's registers are read on each analysis anyway for the high-resolution pH; with your own mV calibration, they are only read while this sensor is enabled.

#### 📤 Sending your calibration to the Blue Connect (optional)

Tick **Send the calibrations to the Blue Connect** (at the end of the calibration fields, shared with the ORP) and validate: at the next analysis, your two points are written into the probe's own registers, like the official app's calibration wizard would. It needs an access code and both mV values filled in, also updates the calibration date shown by the **Last pH Calibration** sensor (if the probe accepts it: otherwise a warning appears in the logs), is never stored (the box always shows unticked) and is not available on the Blue Connect Plus. The pH is only written if it changed since the last successful sending (see the ORP section below).

> ⚠️ This also changes the probe's own standard pH, the alert thresholds stored in the probe, and what the official app shows. Send it only with values you trust, then check the result with the **Blue Connect pH calibration** sensor.

### 🔢 Method B: by pH value (without access code)

Without an access code, there is no electrode potential to read. Open the collapsed section **pH calibration by value (without access code)**:

* **pH 7 measured value** (e.g. `7.10`): what the **Probe-Calibrated pH** sensor shows once stabilized in the pH 7 buffer solution.
* **pH 4 measured value** (e.g. `4.10`): same for the pH 4 buffer solution.

Next to each, enter the **target pH** of the solution (e.g. `7.02` and `4.00`). This calibration applies on top of the probe's own internal calibration: if that one changes, the pH shown changes too.

> ℹ️ **Why only 0.1 resolution?** Without an access code, the integration only receives the pH that the Blue Connect computed itself and broadcasts, already rounded to 0.1. The electrode potential (mV) that allows 2 decimals can only be read through the authenticated connection, which needs the access code. The calibration by value corrects that value (offset and slope), but cannot bring back the decimals that were rounded off before it was sent.

> ⚠️ The two points (pH 4 and pH 7) must be far enough apart, and the pH 4 value must not be higher than the pH 7 one. Otherwise the form refuses it (and a degenerate calibration is ignored rather than displaying a distorted value).

### 🔋 And ORP (Redox)?

ORP (oxidation-reduction potential, or Redox) is calibrated on the same principle as the pH in mV, with **a single point** (an offset, no slope). It needs an access code: the integration only knows the raw electrode potential through the authenticated connection.

1. Enable the **Raw ORP (mV)** diagnostic sensor (disabled by default).
2. Dip the probe in a **reference solution** (e.g. a 468 mV solution, see its bottle), trigger a **New Analysis** and note the mV once the value is stable.
3. In *Options > 🧪 Probes Calibration*, enter that value in **ORP (Redox): mV measured in the reference solution** and the potential of the solution in **ORP (Redox): reference solution**. Both, or none: **both fields are empty by default**.

The correction applied to the raw potential is *reference − measured*. Once both fields are filled in, it takes priority over the probe's own correction; clear both to go back to the probe's. The **ORP** sensor has a `calibration_source` attribute (`integration` or `probe`) telling which one is used.

> 💡 To see what the probe holds, enable **Blue Connect ORP calibration**: its state is the calibration stored in the probe: the reference solution's mV, then the mV the electrode read in it (e.g. `ORP 468 mV = 472 mV`), with `reference`, `measured`, `correction` (reference minus measured, e.g. `-4`) and `status_code` as attributes. The **Last ORP Calibration** sensor shows its date. The status code is shown as read: its meaning is not documented.

> ⚠️ **Raw ORP** replaces the former *Raw ORP* of previous versions, which was in fact the ORP already corrected by the probe: that value is now **Probe-Calibrated ORP** (your entity keeps its history). Your former ORP calibration was added on top of that already-corrected value and the fields were pre-filled with 650/650: they are **cleared on update**, and have to be entered again if you need them.

#### 📤 Sending the calibrations to the Blue Connect

The single **Send the calibrations to the Blue Connect** box sends what is filled in: the pH (both mV values) and/or the ORP (both values). It writes the two ORP registers and the ORP calibration date, and **only what changed since the last successful sending**: if you only changed the ORP, the pH registers (and the pH calibration date) are left alone, and the other way round. If a sending fails, nothing is remembered as sent: tick the box again to try again.

> ⚠️ Like the pH, it changes the ORP the probe itself computes, what the official app shows and its onboard thresholds. Check the result with **Blue Connect ORP calibration**.

#### 🚨 Abnormal calibration warning

A **warning** appears in *Settings > Repairs* (never blocking) when the calibration in use looks wrong:
* **ORP**: more than **100 mV** between the reference and the measured value. A real electrode is within a few tens of mV: a larger gap usually means the probe was not in the reference solution (e.g. in the pool water), or the solution is wrong, or the electrode is dirty or worn.
* **pH**: electrode slope outside **50-63 mV/pH** (59.16 in theory at 25 °C), or offset at pH 7 beyond **±60 mV**.

These limits are generic rules of thumb for electrodes, not a Blue Connect specification. The warning disappears by itself once the values look normal, and you can ignore it from the Repairs page.

---

## 2. 🌡️ Why the "Target" differs from the nominal value

Water chemistry is sensitive to temperature ☀️. The pH of a buffer solution varies slightly with its temperature at the moment you immerse the probe 💧.
* 📦 Check the back of your buffer solution bottle (for example, for pH 7.00).
* 📊 You will find a table giving the exact value according to the liquid temperature.
* 🎯 **Example:** at 20 °C, a pH 7 solution is actually **7.02** — this is the precise value to enter in the **Solution target** fields, not the nominal value printed on the label.

This rigor explains a slight difference between Home Assistant and the official app: a sign that the measurement is actually closer to your pool's true condition. 🔬

---

## 3. 🚨 Configuring alert thresholds

The integration automatically creates binary status sensors (pH, ORP, Temperature). You can define your own limits in the configuration:
* ⚖️ **pH Min / Max:** (Default: 6.90 - 7.40)
* 🛡️ **ORP Min / Max:** (Default: 650 - 750 mV)
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
