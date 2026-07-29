# SUNTEK Fridge BLE — Home Assistant integration

[![Validate](https://github.com/halpcomputar/suntek-fridge-ble/actions/workflows/validate.yml/badge.svg)](https://github.com/halpcomputar/suntek-fridge-ble/actions/workflows/validate.yml)
[![hacs](https://img.shields.io/badge/HACS-custom-41BDF5.svg)](https://hacs.xyz/)

Local Bluetooth monitoring for 12 V portable compressor fridges built on the **SUNTEK
`SC-BLE-1.0`** module — reverse-engineered on a **BougeRV CRD2 V2.0** dual-zone fridge.
No cloud, no vendor account, no ESP32.

These fridges are **not** the Alpicool lineage. Alpicool, Brass Monkey, Bodega and their
rebrands use GATT service `1234` with a binary `FE FE … sum16` protocol, and are already
served by [alpicool_ha_ble](https://github.com/Gruni22/alpicool_ha_ble) and
[refridge](https://github.com/LeanderM99/refridge). This hardware uses service `FFF0` and
speaks newline-framed **ASCII CSV**. Nothing published covered it, hence this project.

Because `SC-BLE-1.0` is a generic module, this likely works with a range of rebadged
fridges beyond BougeRV. [Report your model](../../issues/new?template=model-report.yml) —
compatible or not.

## Does my fridge work?

Brand names prove nothing. The test is the GATT service:

| What you see | Verdict |
|---|---|
| Service `FFF0`, write `FFF1`, notify `FFF4` | ✅ this project |
| Service `1234`, write `1235`, notify `1236` | ❌ use an Alpicool integration |
| Advertised name starting `SYZ-` | ✅ strong signal |
| Manufacturer string `SUNTEK`, model `SC-BLE-1.0` | ✅ strong signal |

Check with [nRF Connect](https://www.nordicsemi.com/Products/Development-tools/nRF-Connect-for-mobile)
on your phone, with the vendor app closed.

## Status

**Read-only.** Everything the fridge reports is exposed as entities. Control — setpoints,
power, Eco/Max — is not implemented yet: the command characteristic `FFF1` is write-only,
so its format has to be captured from the vendor app. See
[PROTOCOL.md](PROTOCOL.md#command-frame-fff1) for the method and the six-command checklist.

10 of the 12 status fields are confirmed against the vendor app and the fridge's own
display. The remaining two are documented as untestable on the reference unit rather than
guessed at.

**Confirmed working** on Home Assistant against a BougeRV CRD2 V2.0 43QT — auto-discovery,
all seven entities populating, values matching the fridge's own display. Tested on exactly
one unit, so reports from any other hardware are genuinely useful.

> **Setup gotcha:** the fridge allows a single BLE connection. If the vendor app (or a
> scanner like nRF Connect) is holding it, the fridge stops advertising, discovery finds
> nothing, and the config flow reports "No compatible fridge found". Force-quit anything
> else that connects, then retry.

## Entities

| Entity | Type | Notes |
|---|---|---|
| Zone 1 / Zone 2 temperature | sensor | On the reference unit zone 1 is the larger compartment |
| Zone 1 / Zone 2 setpoint | sensor | |
| Input voltage | sensor | diagnostic |
| Run mode | sensor | enum: Eco / Max |
| Battery protection | sensor | enum: Low / Medium / High, diagnostic |
| Power | binary_sensor | device class *running* |

Temperatures are normalised to °C internally, so Home Assistant renders them in your
preferred unit and long-term statistics survive you flipping the fridge between °F and °C.

`iot_class` is `local_push`: the integration subscribes and never polls. The fridge sends
a status frame every ~4 seconds, plus an immediate one on any change.

## Installation

### HACS

1. HACS → ⋮ → **Custom repositories**
2. Repository `https://github.com/halpcomputar/suntek-fridge-ble`, type **Integration**
3. Download, then **restart Home Assistant**

### Manual

Copy `custom_components/suntek_fridge_ble/` into your Home Assistant
`config/custom_components/` and restart.

### Setup

With the vendor app closed, the fridge should be auto-discovered under
**Settings → Devices & Services**. Otherwise add it manually via **Add Integration →
SUNTEK Fridge BLE**.

## Requirements and limitations

- A Bluetooth adapter in range, or an [ESPHome Bluetooth Proxy](https://esphome.io/components/bluetooth_proxy/).
  Range is roughly 10 m.
- **One BLE connection at a time.** While Home Assistant is connected the vendor app
  cannot connect, and vice versa. The integration treats being dropped as normal and
  reconnects with backoff.

## Development

The protocol layer has no Home Assistant dependency, so its tests run anywhere:

```bash
pip install pytest && python3 -m pytest tests/ -q
```

`tools/probe.py` is a standalone BLE probe that decodes frames live and highlights what
changed — including across reconnects, which is how the app-only settings were mapped.
See [PROTOCOL.md](PROTOCOL.md) for the full spec, what is confirmed, and what is not.

## Credit

The Alpicool projects — [Gruni22/alpicool_ha_ble](https://github.com/Gruni22/alpicool_ha_ble),
[LeanderM99/refridge](https://github.com/LeanderM99/refridge),
[klightspeed/BrassMonkeyFridgeMonitor](https://github.com/klightspeed/BrassMonkeyFridgeMonitor),
and [dandwhelan's compatibility notes](https://github.com/dandwhelan/Alpicool50l12vfridgefreezer) —
cover a different protocol, but their documentation is what made it quick to rule that
lineage out and start fresh.

## License

MIT — see [LICENSE](LICENSE).
