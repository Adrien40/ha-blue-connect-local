[![Français](https://img.shields.io/badge/Langue-Fran%C3%A7ais-blue)](README.fr.md) [![English](https://img.shields.io/badge/Language-English-red)](#)

# Blue Connect Local for Home Assistant 🐬
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/Adrien40/ha-blue-connect-local)](https://github.com/Adrien40/ha-blue-connect-local/releases)

If this project is useful to you, you can support its development 🙏

<a href="https://www.buymeacoffee.com/adrien40"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" width="160"></a>

---

## ⚡ At a Glance
- 🔌 100% local operation via Bluetooth (BLE)
- 🏠 Compatible with Home Assistant (no cloud)
- 🌡️ Measurements: Temperature, pH, ORP Redox, Salinity, Conductivity, Battery
- 🎯 Manual Analysis: Force a new water analysis on demand, remotely
- ⚖️ Floating Status
- 🔋 Optimized to preserve battery life
- ⚙️ Installation via HACS in 2 minutes

---

## 📸 Examples in Home Assistant

### 📊 Visualization

<p align="center">
  <img src="docs/screenshots/dashboard_overview.png" width="600">
</p>

<p align="center">
  <em>📊 Overview of pool data in Home Assistant</em>
</p>

---

### 🔍 Technical Details

<p align="center">
  <img src="docs/screenshots/entities_overview.png" width="600">
</p>

<p align="center">
  <em>🔍 Entities exposed by the integration & ⚙️ Advanced configuration options</em>
</p>

---

A **100% local integration for Home Assistant** that turns your Blue Connect analyzer into a Bluetooth Low Energy (BLE) sensor, letting you control and monitor your pool with zero dependency on the Cloud. 🛡️

> ⚠️ **Warning**: This integration queries the Blue Connect directly over Bluetooth.

### 💡 Why This Integration?
This integration frees your Blue Connect from the Cloud by directly leveraging its BLE protocol, for uncompromising home automation:

* **🔒 100% local:** Works without internet. Your data goes straight from the pool to Home Assistant.
* **⏱️ No API limits:** Passive listening to regular data frames, plus the ability to force a measurement on demand, with no restrictions.
* **🛡️ Longevity:** Total independence from official servers, so your hardware keeps working for the long haul.

**Blue Connect Local** is the result of in-depth **reverse engineering** work to turn your analyzer into a true local, industrial-grade sensor capable of communicating directly with your Home Assistant instance.
Blue Connect Local replaces the cloud with a **local control** solution, while offering a reliable **pool monitoring** system built on a **BLE sensor**.

---

### ✅ Compatibility / Requirements
* 🏷️ **Supported models**: ZODIAC Blue Connect (Gold / Silver).
* 🏅 **Tested on**: Validated on the **ZODIAC Blue Connect Gold**.
* 🔑 **Access Code (Optional)**: Your device's 9-character access code. It isn't required for passive listening, but it is **essential** for on-demand analyses.
* 🛠️ **Required hardware**: Internal Bluetooth adapter, USB Bluetooth dongle, or an **ESPHome Bluetooth Proxy** (strongly recommended, [easy installation here](https://esphome.github.io/bluetooth-proxies/)).
* 📶 **Signal quality**: A stable RSSI signal (ideally **above -75 dBm**) is essential to guarantee a reliable connection to the Blue Connect. Testing shows that a signal below -90 dBm causes frequent read failures.
* ⏱️ **Real-time monitoring**: A `sensor.*_signal_bluetooth` entity uses Home Assistant's passive listening so you can watch signal strength live — all without draining the Blue Connect's battery!

> ❌ **Not compatible**: Blueriiot versions are not supported.

---

### ✨ Highlights
* 🏠 **100% Local (BLE)**: No Cloud dependency, no subscription, no latency.
* 🌡️ **Raw sensor readings**: Temperature, pH, ORP (Redox), Salinity, Conductivity, Battery (%).
* 🚀 **Real-time analysis**: Trigger a manual measurement whenever you want.
* 🧪 **Advanced Chemical Intelligence**:
  * Calculates the **Langelier Saturation Index** (LSI) to tell you whether your water is balanced, scale-forming, or corrosive.
* 🟤 **Multi-treatment support**: Works with **Bromine** (automatically disables the CYA entity, which isn't relevant for that treatment) and with stabilizer-free pools (CYA = 0).
* ⚙️ **100% UI Configuration**: Automatic Bluetooth discovery, probe calibration, and alert threshold settings, all directly from the Home Assistant interface (no YAML required).
* 🔄 **Sync Modes**: Passive Mode (silent, battery-saving listening) and Active Mode (on-demand Bluetooth analyses via the access code).
* 🌍 **Multi-language**: Developed in French 🇫🇷 and available in EN, ES, DE, IT, NL, PL, PT, PT-BR, SV, RU, ZH-HANS, ZH-HANT, CS, HU, EL, HR, DA, NB (AI-translated).
* 📡 Turns your Blue Connect into a true **BLE sensor** for Home Assistant

---

### 🚀 Installation

#### Via HACS (Recommended)
This repository isn't (yet) in the official default list, so you'll need to add it as a custom repository.

1. Open **HACS** in your Home Assistant.
2. Click the 3 dots in the top-right corner and select **Custom repositories**.
3. Under **Repository**, paste the URL: `https://github.com/Adrien40/ha-blue-connect-local`
4. Under **Type**, choose **Integration**, then click **Add**.
5. Once added, a window will pop up: click **Download** (select the latest version).
6. **Fully restart Home Assistant**.
7. Go to **Settings** > **Devices & Services** > **Add Integration** and search for "Blue Connect Local".

### Manual
Copy the `custom_components/blue_connect_local` folder into the `custom_components` folder of your Home Assistant configuration, then restart.

---

### 📊 Available Sensors and Controls
| Entity | Unit / Type | Description |
| :--- | :--- | :--- |
| 💧 **pH** | pH | Calculated pH (Nernst equation + thermal compensation). |
| ⚡ **Redox / ORP** | mV | Oxidation-reduction potential. |
| 🌡️ **Temperature** | °C | Precise water temperature. |
| ⚖️ **Langelier Saturation Index** | LSI | Water balance indicator (Corrosive, Balanced, or Scale-forming). |
| 🎯 **Equilibrium pH** | pH | Ideal pH target, calculated per the Taylor Balance. |
| 🔋 **Battery** | % and mV | Charge level (%) and raw battery voltage. |
| 📶 **RSSI Signal** | dBm | Real-time received Bluetooth signal strength. |
| 🔵 **Bluetooth State** | Status | Detailed connection state (Connected, Standby, Error...). |
| ⏱️ **Next Analysis** | Timestamp | Estimated time of the next data reading. |
| 🚀 **New Analysis** | Button | **Trigger an instant analysis (~60s).** |
| ⏸️ **Auto Analysis** | Switch | Turn automatic readings on/off (Pause Mode). |

> 🛠️ **Diagnostics**: The integration also exposes advanced sensors (original factory-formula pH, the full raw hex frame, and binary alert statuses).

---

### 🧪 Chemical Expertise: Professional-Grade Analysis

👉 No need to understand these calculations — Home Assistant automates everything.

<details>
<summary>🔬 See the scientific details</summary>

#### Water Balance: Langelier Saturation Index & Taylor Balance ⚖️
The Langelier Saturation Index (LSI) is the essential companion to the **Taylor Balance**. It tells you whether your water is:
* **Corrosive (LSI < -0.3)**: The water attacks your seals, liner, and metal parts.
* **Balanced (LSI between -0.3 and +0.3)**: Perfect water.
* **Scale-forming (LSI > +0.3)**: Risk of limescale buildup.

Enter your TAC (Total Alkalinity), TH (Total Hardness), and TDS in the options, and Home Assistant will calculate your balance live, based on the temperature read from the Blue Connect!

> **Diagnostics**: The integration also exposes the raw pH (mV), the factory-formula pH, the full hex frame, and the timestamp of the last measurement.

</details>


### 🎯 A Note on Measurement Accuracy
Values shown in Home Assistant may differ slightly from those in the official Blue Connect app.

Blue Connect Local supports "high-precision" calibration. Unlike the mobile app, which uses fixed values, our integration lets you enter the exact value of your buffer solution (pH 7.02, 4.01, etc.), adjusted for temperature during calibration. This scientific rigor is what can create a slight offset — a sign that the reading is actually closer to your pool's true conditions. 🔬

---

## 🚀 Configuration
1. Go to **Settings** > **Devices & Services**.
2. The integration should automatically detect your Blue Connect if your Bluetooth dongle/antenna is in range.
2. Click **Add Integration** and search for **Blue Connect Local**.
3. Follow the on-screen instructions to set your treatment type (Chlorine, Bromine) and your probe calibration/offset.

### ⚙️ Options, Calibration & Alerts
Once the device has been added, you can click **Configure** ⚙️ to:
* Adjust the values of your calibration solutions (pH 4, pH 7, Redox).
* Update your water parameters (TAC, TH, TDS, Stabilizer) from the dashboard.
* Set your own **custom alert thresholds** (pH Min/Max, ORP Min/Max, etc.) to drive your own automations.

---

### 🐛 Troubleshooting

<details>
<summary>⚠️ See common issues</summary>
  
* **Frequent Bluetooth errors**: The integration automatically handles connection retries. If the sensor shows `Signal Lost`, the Blue Connect is out of range. Move your antenna closer, or [install an ESPHome Bluetooth Proxy](https://esphome.github.io/bluetooth-proxies/) as close to the pool as possible (all you need is an ESP32 (~€10) and a USB charger).

</details>

---

### 🤝 Contributing & Support
For any bugs or feature requests, please open an [Issue](https://github.com/Adrien40/ha-blue-connect-local/issues) on this repository.

### ⚠️ Disclaimer
This integration is an independent project. It has no affiliation whatsoever with the Fluidra/Zodiac company. Use of this software is at your own risk.

### ⚖️ License
Project licensed under **GPLv3**. Independent of the Fluidra company. Use at your own risk.

---

**Built with ❤️ by @Adrien40**

<a href="https://www.buymeacoffee.com/adrien40"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" width="180"></a>

<!-- Keywords: Home Assistant custom integration, BLE sensor, pool monitoring, local control -->
